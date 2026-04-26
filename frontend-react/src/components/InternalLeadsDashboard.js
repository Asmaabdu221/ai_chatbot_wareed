/**
 * InternalLeadsDashboard — V1.5 (Realtime)
 *
 * Staff dashboard for reviewing and actioning captured leads.
 * Accessible at /internal/leads — protected by X-Internal-Api-Key.
 *
 * Realtime layer:
 *   - EventSource connects to GET /api/internal/leads/stream?api_key=...
 *   - Events are merged into the leads list by lead_id (no duplicates)
 *   - Toast notifications for new leads and delivery failures
 *   - Unread badge counts leads that arrived since last refresh
 *   - 30-second polling stays active as authoritative fallback
 *   - If SSE fails, dashboard continues working via polling
 *
 * API key resolution:
 *   1. REACT_APP_INTERNAL_API_KEY env var (set at deployment)
 *   2. sessionStorage 'wareed_internal_api_key' (cleared on tab close)
 *   3. On-screen entry form → saved to sessionStorage
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { getInternalLeads, closeInternalLead, retryInternalLeadCrm, getMe, API_BASE_URL } from '../services/api';
import { getAccessToken } from '../services/auth';
import './InternalLeadsDashboardV2.css';

const ENV_API_KEY = process.env.REACT_APP_INTERNAL_API_KEY || '';
const SESSION_KEY = 'wareed_internal_api_key';
const REFRESH_INTERVAL_MS = 30000;
const TOAST_DURATION_MS = 5000;
const SSE_MAX_ERRORS = 6; // after this many consecutive errors → declare offline

// Roles that may access the internal dashboard
const INTERNAL_ROLES = new Set(['admin', 'supervisor', 'staff']);

// Permissions derived from role (all roles equal for now; structure ready for differentiation)
function rolePermissions(role) {
  if (!INTERNAL_ROLES.has(role)) return { canView: false, canClose: false };
  return { canView: true, canClose: true };
}

const STATUS_LABELS = {
  new: 'جديد',
  delivered: 'مُسلَّم',
  failed: 'فاشل',
  closed: 'مغلق',
};

const CRM_STATUS_LABELS = {
  pending: 'قيد المزامنة',
  synced: 'متزامن',
  failed: 'فشل المزامنة',
  disabled: 'معطّل',
};

const INTENT_LABELS = {
  TRANSFER_TO_HUMAN: 'تحويل لموظف',
  CLARIFY: 'طلب استفسار',
  BOOKING: 'طلب حجز',
  ask_phone: 'طلب حجز',
  transfer_to_human: 'تحويل لموظف',
  offer_human_help: 'مساعدة بشرية',
};

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat('ar-SA', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function formatIntent(intent) {
  const raw = (intent || '').toString().trim();
  if (!raw) return 'غير محدد';

  const key = raw.toUpperCase();
  if (key === 'TRANSFER_TO_HUMAN') return 'تحويل لموظف';
  if (key === 'CLARIFY') return 'طلب استفسار';
  if (key === 'BOOKING' || key.includes('BOOK') || key.includes('ASK_PHONE')) return 'طلب حجز';

  return INTENT_LABELS[raw] || 'غير محدد';
}

function normalizeIntentKey(intent) {
  const raw = (intent || '').toString().trim();
  if (!raw) return '';
  const upper = raw.toUpperCase();
  if (upper === 'TRANSFER_TO_HUMAN') return 'TRANSFER_TO_HUMAN';
  if (upper === 'CLARIFY') return 'CLARIFY';
  if (upper === 'BOOKING' || upper.includes('BOOK') || upper.includes('ASK_PHONE')) return 'BOOKING';
  if (raw === 'transfer_to_human') return 'TRANSFER_TO_HUMAN';
  if (raw === 'ask_phone') return 'BOOKING';
  return '';
}

function renderSource(source) {
  if ((source || '').toLowerCase() === 'chatbot') {
    return (
      <span className="ild-source-icon" title="chatbot" aria-label="chatbot">
        <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect x="4" y="5" width="16" height="12" rx="4" />
          <path d="M9 17v3l3-2h4" />
          <circle cx="9.5" cy="11" r="1" />
          <circle cx="14.5" cy="11" r="1" />
        </svg>
      </span>
    );
  }
  return source || '—';
}

function toOneLineSummary(text, maxWords = 10) {
  const raw = (text || '').toString().replace(/\s+/g, ' ').trim();
  if (!raw) return 'استفسار عام';
  const words = raw.split(' ');
  if (words.length <= maxWords) return raw;
  return `${words.slice(0, maxWords).join(' ')}...`;
}

function getTableSummary(lead) {
  // Table must stay scan-friendly: short headline only.
  const source = lead?.summary_hint || lead?.summary_text || '';
  return toOneLineSummary(source, 10);
}

function normalizeEventToLead(event) {
  return {
    id: event.lead_id,
    conversation_id: event.conversation_id,
    phone: event.phone,
    latest_intent: event.latest_intent,
    latest_action: event.latest_action,
    summary_hint: event.summary_hint,
    summary_text: event.summary_text,
    source: event.source,
    status: event.status,
    created_at: event.created_at,
    delivered_at: event.delivered_at,
    delivery_error: event.delivery_error,
    crm_status: event.crm_status,
    crm_provider: event.crm_provider,
    crm_external_id: event.crm_external_id,
    crm_last_attempt_at: event.crm_last_attempt_at,
    crm_error_message: event.crm_error_message,
    crm_retry_count: event.crm_retry_count,
  };
}

function SummaryModal({ text, onClose }) {
  if (!text) return null;
  return (
    <div
      className="ild-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-label="تفاصيل المحادثة"
      onClick={onClose}
    >
      <div className="ild-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ild-modal__header">
          <h3 className="ild-modal__title">تفاصيل المحادثة</h3>
          <button type="button" className="ild-modal__close" onClick={onClose} aria-label="إغلاق">✕</button>
        </div>
        <div className="ild-modal__body">{text || 'لا توجد تفاصيل متاحة.'}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  return (
    <span className={`ild-badge ild-badge--${status}`}>
      {STATUS_LABELS[status] || status}
    </span>
  );
}

function CrmStatusBadge({ status }) {
  const effective = status || 'pending';
  return (
    <span className={`ild-badge ild-badge--${effective}`}>
      {CRM_STATUS_LABELS[effective] || effective}
    </span>
  );
}

function ConnectionStatus({ status }) {
  const labels = {
    connecting: 'جارٍ الاتصال',
    live: 'مباشر',
    reconnecting: 'إعادة اتصال',
    offline: 'بدون بث مباشر',
  };
  return (
    <span className={`ild-conn-status ild-conn-status--${status}`} title={labels[status]}>
      <span className="ild-conn-status__dot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}

function ToastNotifications({ toasts, onDismiss }) {
  if (toasts.length === 0) return null;
  return (
    <div className="ild-toasts" aria-live="polite" aria-label="إشعارات">
      {toasts.map((toast) => (
        <div key={toast.id} className={`ild-toast ild-toast--${toast.type}`} role="alert">
          <span className="ild-toast__icon" aria-hidden="true">
            {toast.type === 'new' ? '📞' : toast.type === 'error' ? '⚠️' : 'ℹ️'}
          </span>
          <span className="ild-toast__message">{toast.message}</span>
          <button
            type="button"
            className="ild-toast__close"
            onClick={() => onDismiss(toast.id)}
            aria-label="إغلاق الإشعار"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

function ApiKeyForm({ onSubmit }) {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');

  function handleSubmit(e) {
    e.preventDefault();
    const trimmed = key.trim();
    if (!trimmed) { setError('أدخل مفتاح الوصول'); return; }
    setError('');
    onSubmit(trimmed);
  }

  return (
    <div className="ild-keyform-wrap" dir="rtl">
      <div className="ild-keyform">
        <img src="/images/wareed-logo.png" alt="وريد" className="ild-keyform__logo" />
        <h1 className="ild-keyform__title">لوحة إدارة الطلبات</h1>
        <p className="ild-keyform__sub">أدخل مفتاح الوصول للمتابعة</p>
        <form onSubmit={handleSubmit} noValidate>
          <input
            type="password"
            className="ild-keyform__input"
            placeholder="X-Internal-Api-Key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoFocus
            autoComplete="current-password"
          />
          {error && <p className="ild-keyform__error">{error}</p>}
          <button type="submit" className="ild-keyform__btn">دخول</button>
        </form>
      </div>
    </div>
  );
}

function AccessDenied({ onSwitchToApiKey }) {
  return (
    <div className="ild-keyform-wrap" dir="rtl">
      <div className="ild-keyform">
        <img src="/images/wareed-logo.png" alt="وريد" className="ild-keyform__logo" />
        <h1 className="ild-keyform__title">غير مصرح بالوصول</h1>
        <p className="ild-keyform__sub">حسابك الحالي لا يمتلك صلاحية الوصول للوحة إدارة الطلبات.</p>
        <p className="ild-keyform__sub" style={{ fontSize: '12px', marginTop: '-4px' }}>
          تواصل مع مدير النظام لإضافة الصلاحية، أو استخدم مفتاح وصول مباشر.
        </p>
        <button type="button" className="ild-keyform__btn" onClick={onSwitchToApiKey}>
          استخدام مفتاح وصول مباشر
        </button>
      </div>
    </div>
  );
}

function LeadDetailPanel({
  lead,
  onClose,
  onSaveAndClose,
  onRetryCrm,
  closing,
  retryingCrm,
  canClose,
  actionNote,
  onActionNoteChange,
}) {
  if (!lead) return null;
  const normalizedPhone = (lead.phone || '').toString().replace(/[^\d]/g, '');
  const whatsappHref = normalizedPhone ? `https://wa.me/${normalizedPhone}` : null;
  const intentLabel = formatIntent(lead.latest_intent);
  const actionLabel = formatIntent(lead.latest_action);
  const requestType = !intentLabel || intentLabel === 'غير محدد'
    ? actionLabel
    : (!actionLabel || actionLabel === 'غير محدد' || actionLabel === intentLabel)
      ? intentLabel
      : `${intentLabel} / ${actionLabel}`;

  return (
    <div className="ild-panel" dir="rtl" role="complementary" aria-label="تفاصيل الـ Lead">
      <div className="ild-panel__header">
        <h2 className="ild-panel__title">تفاصيل الـ Lead</h2>
        <button type="button" className="ild-panel__close-btn" onClick={onClose} aria-label="إغلاق">✕</button>
      </div>
      <div className="ild-panel__body">
        {[
          ['الحالة', <StatusBadge status={lead.status} />],
          ['رقم الهاتف', (
            <span className="ild-panel__value--phone-wrap">
              <a href={`tel:${lead.phone}`} className="ild-panel__phone-link">
                <span className="ild-panel__value--phone">{lead.phone}</span>
              </a>
              {whatsappHref && (
                <a
                  href={whatsappHref}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="ild-panel__whatsapp-link"
                  aria-label="فتح واتساب"
                  title="فتح واتساب"
                >
                  <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M12 4a8 8 0 0 0-6.8 12.2L4 20l4-1.1A8 8 0 1 0 12 4Z" />
                    <path d="M9.5 9.2c.2-.5.4-.5.7-.5h.6c.2 0 .4 0 .5.4l.7 1.7c.1.2.1.4 0 .5l-.3.5c-.1.1-.2.3-.1.5.2.3.7 1.1 1.6 1.8 1 .8 1.8 1 2.2 1.1.2.1.4 0 .5-.1l.5-.6c.2-.2.4-.2.6-.1l1.6.8c.2.1.3.2.3.4v.5c-.2.6-.9 1.1-1.5 1.2-.4.1-1 .1-2.2-.4-1.6-.7-3.5-2.3-4.5-3.8-1-1.6-1.1-2.9-.6-3.9Z" />
                  </svg>
                </a>
              )}
            </span>
          )],
          ['نوع الطلب', requestType || 'غير محدد'],
          ['ملخص الطلب', lead.summary_hint || '—'],
          ['وقت الاستلام', formatDate(lead.created_at)],
          lead.delivery_error && ['خطأ التسليم', <span className="ild-panel__value--error">{lead.delivery_error}</span>],
        ].filter(Boolean).map(([label, value]) => (
          <div key={label} className="ild-panel__row">
            <span className="ild-panel__label">{label}</span>
            <span className="ild-panel__value">{value}</span>
          </div>
        ))}
      </div>
      {canClose && (
        <div className="ild-panel__footer">
          <div className="ild-panel__note">
            <label className="ild-panel__note-label" htmlFor={`lead-note-${lead.id}`}>
              ملاحظات الإجراء
            </label>
            <textarea
              id={`lead-note-${lead.id}`}
              className="ild-panel__note-input"
              value={actionNote}
              onChange={(e) => onActionNoteChange(e.target.value)}
              placeholder="اكتب الملاحظة هنا..."
              rows={2}
            />
          </div>
          <div className="ild-panel__actions">
            <button
              type="button"
              className="ild-panel__cancel-link"
              onClick={onClose}
            >
              إلغاء
            </button>
            {lead.status !== 'closed' && (
              <button
                type="button"
                className="ild-btn ild-btn--close-lead"
                onClick={() => onSaveAndClose(lead.id, actionNote)}
                disabled={closing}
              >
                {closing ? 'جارٍ الحفظ والإغلاق...' : 'حفظ وإغلاق الطلب'}
              </button>
            )}
          </div>
        </div>
      )}
      {lead.crm_status === 'failed' && canClose && (
        <div className="ild-panel__footer">
          <button
            type="button"
            className="ild-btn ild-btn--refresh"
            onClick={() => onRetryCrm(lead.id)}
            disabled={retryingCrm}
          >
            {retryingCrm ? '...' : 'Retry CRM'}
          </button>
        </div>
      )}
      <div className="ild-panel__id-bottom">
        <span className="ild-panel__id-label">Lead ID</span>
        <span className="ild-panel__value ild-panel__value--mono">{lead.id}</span>
      </div>
    </div>
  );
}

function FilterBar({ filters, onChange, onClear, statsTabs, activeStatus, onStatusChange }) {
  const hasActive = !!(filters.q || filters.intent || filters.action || filters.dateFrom || filters.dateTo);
  return (
    <div className="ild-filter-bar">
      <div className="ild-filter-bar__controls">
        <div className="ild-filter-bar__search-wrap">
          <span className="ild-filter-bar__search-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20L17 17" />
            </svg>
          </span>
          <input
            type="search"
            className="ild-filter-bar__search"
            placeholder="بحث بالهاتف أو الملخص..."
            value={filters.q}
            onChange={(e) => onChange({ ...filters, q: e.target.value })}
          />
        </div>
        <select
          className="ild-filter-bar__select"
          value={filters.intent}
          onChange={(e) => onChange({ ...filters, intent: e.target.value })}
        >
          <option value="">كل النوايا</option>
          <option value="BOOKING">طلب حجز</option>
          <option value="TRANSFER_TO_HUMAN">تحويل لموظف</option>
          <option value="CLARIFY">طلب استفسار</option>
        </select>
        <div className="ild-filter-bar__dates">
          <input
            type="date"
            className="ild-filter-bar__date"
            value={filters.dateFrom}
            onChange={(e) => onChange({ ...filters, dateFrom: e.target.value })}
            title="من تاريخ"
          />
          <span className="ild-filter-bar__date-sep">—</span>
          <input
            type="date"
            className="ild-filter-bar__date"
            value={filters.dateTo}
            onChange={(e) => onChange({ ...filters, dateTo: e.target.value })}
            title="إلى تاريخ"
          />
        </div>
        {hasActive && (
          <button type="button" className="ild-filter-bar__clear" onClick={onClear}>
            مسح الفلاتر ✕
          </button>
        )}
      </div>

      <div className="ild-filter-bar__stats" aria-label="إحصاءات الحالة">
        {statsTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={`ild-mini-stat ild-mini-stat--${tab.key}${activeStatus === tab.key ? ' ild-mini-stat--active' : ''}`}
            onClick={() => onStatusChange(tab.key)}
          >
            <span className="ild-mini-stat__label">{tab.label}</span>
            <span className="ild-mini-stat__count">{tab.count}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

export default function InternalLeadsDashboard() {
  const navigate = useNavigate();

  useEffect(() => {
    document.title = 'لوحة إدارة الطلبات';
  }, []);

  // --- Auth mode ---
  // 'checking'  → resolving whether user has an internal role
  // 'bearer'    → authenticated via JWT Bearer (role-based)
  // 'apikey'    → authenticated via X-Internal-Api-Key
  // 'denied'    → logged in but no internal role (prompt to switch to API key)
  const [authMode, setAuthMode] = useState('checking');
  const [currentUser, setCurrentUser] = useState(null);   // User from /auth/me (bearer path)
  const [forceApiKey, setForceApiKey] = useState(false);  // user chose API key despite having no role

  // --- API key (apikey auth mode) ---
  const [apiKey, setApiKey] = useState(() =>
    ENV_API_KEY || sessionStorage.getItem(SESSION_KEY) || ''
  );
  const [keyRejected, setKeyRejected] = useState(false);

  // --- Data ---
  const [leads, setLeads] = useState([]);
  const [stats, setStats] = useState({ all: 0, new: 0, delivered: 0, failed: 0, closed: 0 });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [selectedLead, setSelectedLead] = useState(null);
  const [closingIds, setClosingIds] = useState(new Set());
  const [retryingCrmIds, setRetryingCrmIds] = useState(new Set());
  const [filters, setFilters] = useState({ q: '', intent: '', action: '', dateFrom: '', dateTo: '' });
  const [debouncedQ, setDebouncedQ] = useState('');
  const [summaryModalText, setSummaryModalText] = useState(null);
  const [leadActionNotes, setLeadActionNotes] = useState({});

  // --- Realtime ---
  const [connectionStatus, setConnectionStatus] = useState('connecting');
  const [toasts, setToasts] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const refreshTimerRef = useRef(null);
  const apiKeyRef = useRef(apiKey);
  const statusFilterRef = useRef(statusFilter);
  const effectiveFiltersRef = useRef(filters);

  // --- Resolve auth mode on mount ---
  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      // Not logged in → fall back to API key path
      setAuthMode('apikey');
      return;
    }
    getMe()
      .then((user) => {
        if (user && INTERNAL_ROLES.has(user.role)) {
          setCurrentUser(user);
          setAuthMode('bearer');
        } else if (user) {
          // Logged in but no internal role
          setAuthMode('denied');
        } else {
          setAuthMode('apikey');
        }
      })
      .catch(() => setAuthMode('apikey'));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Derive permissions from current auth mode
  const permissions = useMemo(() => {
    if (authMode === 'bearer' && currentUser) return rolePermissions(currentUser.role);
    if (authMode === 'apikey' && (apiKey || !ENV_API_KEY)) return { canView: true, canClose: true };
    return { canView: false, canClose: false };
  }, [authMode, currentUser, apiKey]);

  // Debounce search query
  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(filters.q), 300);
    return () => clearTimeout(t);
  }, [filters.q]);

  // Effective filters: use debounced q but immediate values for dropdowns/dates
  const effectiveFilters = useMemo(
    () => ({ ...filters, q: debouncedQ }),
    [filters, debouncedQ]
  );

  // Keep refs up-to-date so callbacks always read current values
  // apiKeyRef holds '' when using bearer auth (effectiveKey)
  useEffect(() => { apiKeyRef.current = authMode === 'bearer' ? '' : apiKey; }, [authMode, apiKey]);
  useEffect(() => { statusFilterRef.current = statusFilter; }, [statusFilter]);
  useEffect(() => { effectiveFiltersRef.current = effectiveFilters; }, [effectiveFilters]);

  // ---------------------------------------------------------------------------
  // Toast system
  // ---------------------------------------------------------------------------

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((toast) => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, ...toast }]);
    setTimeout(() => removeToast(id), TOAST_DURATION_MS);
  }, [removeToast]);

  // ---------------------------------------------------------------------------
  // REST fetch (initial load + 30s authoritative sync)
  // ---------------------------------------------------------------------------

  const fetchLeads = useCallback(async (key, filter, { resetUnread = false } = {}) => {
    // key is empty string when using bearer auth (axios interceptor injects the Bearer header)
    const af = effectiveFiltersRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await getInternalLeads(key, {
        status: null,
        pageSize: 100,
        // Intent/status filtering is handled client-side to keep pills and dropdown fully synced.
        intent: null,
        action: null,
        q: af.q || null,
        dateFrom: af.dateFrom || null,
        dateTo: af.dateTo || null,
      });
      setLeads(res.items || []);
      setKeyRejected(false);
      if (resetUnread) setUnreadCount(0);

      // status_counts comes from backend regardless of active status tab
      const counts = res.status_counts || {};
      setStats({
        all: Object.values(counts).reduce((a, b) => a + b, 0),
        new: counts.new || 0,
        delivered: counts.delivered || 0,
        failed: counts.failed || 0,
        closed: counts.closed || 0,
      });
    } catch (err) {
      if (err.response?.status === 403) {
        setKeyRejected(true);
        setError('مفتاح الوصول غير صحيح');
      } else {
        setError('تعذّر تحميل الـ Leads. تحقق من الاتصال بالخادم.');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  // ---------------------------------------------------------------------------
  // Lead event handler (SSE)
  // ---------------------------------------------------------------------------

  const handleLeadEvent = useCallback((event) => {
    const { event_type } = event;
    if (!event_type || event_type === 'ping' || event_type === 'connected') return;

    // Refetch from REST so active filters are respected (safer than local state mutation)
    // apiKeyRef holds '' when using bearer auth
    fetchLeads(apiKeyRef.current, statusFilterRef.current);

    const leadData = normalizeEventToLead(event);

    // Sync open detail panel immediately (no need to wait for refetch)
    setSelectedLead((prev) =>
      prev && prev.id === leadData.id ? { ...prev, ...leadData } : prev
    );

    // Notifications and unread count
    if (event_type === 'lead.created') {
      setUnreadCount((c) => c + 1);
      addToast({ type: 'new', message: `Lead جديد — ${leadData.phone}` });
    } else if (event_type === 'lead.delivery_failed') {
      addToast({ type: 'error', message: `فشل تسليم Lead — ${leadData.phone}` });
    } else if (event_type === 'lead.closed') {
      addToast({ type: 'info', message: `تم إغلاق Lead — ${leadData.phone}` });
    }
  }, [addToast, fetchLeads]);

  // Stable ref so the EventSource effect doesn't need handleLeadEvent in its deps
  const handleLeadEventRef = useRef(handleLeadEvent);
  useEffect(() => { handleLeadEventRef.current = handleLeadEvent; }, [handleLeadEvent]);

  // Effective key: empty when using bearer (axios interceptor handles auth)
  const effectiveKey = authMode === 'bearer' ? '' : apiKey;

  // Initial fetch + when auth mode, status tab, or any filter changes
  useEffect(() => {
    if (authMode === 'checking' || authMode === 'denied') return;
    if (authMode === 'apikey' && !apiKey) return;
    fetchLeads(effectiveKey, statusFilter, { resetUnread: true });
  }, [authMode, effectiveKey, statusFilter, fetchLeads, effectiveFilters]); // eslint-disable-line react-hooks/exhaustive-deps

  // 30-second authoritative polling (fallback even when SSE is live)
  useEffect(() => {
    if (authMode === 'checking' || authMode === 'denied') return;
    if (authMode === 'apikey' && !apiKey) return;
    refreshTimerRef.current = setInterval(
      () => fetchLeads(effectiveKey, statusFilter),
      REFRESH_INTERVAL_MS
    );
    return () => clearInterval(refreshTimerRef.current);
  }, [authMode, effectiveKey, statusFilter, fetchLeads]);

  // Sync selected lead when polling updates the list
  useEffect(() => {
    if (selectedLead) {
      const updated = leads.find((l) => l.id === selectedLead.id);
      if (updated) setSelectedLead(updated);
    }
  }, [leads]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // EventSource — realtime layer
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (authMode === 'checking' || authMode === 'denied') return;
    if (authMode === 'apikey' && !apiKey) return;

    // Bearer path: pass JWT via ?token= (EventSource cannot send Authorization header)
    const sseUrl = authMode === 'bearer'
      ? `${API_BASE_URL}/api/internal/leads/stream?token=${encodeURIComponent(getAccessToken() || '')}`
      : `${API_BASE_URL}/api/internal/leads/stream?api_key=${encodeURIComponent(apiKey)}`;

    let es = null;
    let errorCount = 0;

    function connect() {
      es = new window.EventSource(sseUrl);

      es.onopen = () => {
        setConnectionStatus('live');
        errorCount = 0;
      };

      es.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data);
          if (handleLeadEventRef.current) handleLeadEventRef.current(event);
        } catch {
          // malformed event — ignore
        }
      };

      es.onerror = () => {
        errorCount += 1;
        if (errorCount >= SSE_MAX_ERRORS) {
          setConnectionStatus('offline');
          es.close(); // stop retrying — 30s poll covers it
        } else {
          setConnectionStatus('reconnecting');
          // EventSource auto-reconnects; we just track state
        }
      };
    }

    connect();
    return () => { if (es) es.close(); };
  }, [authMode, apiKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  function handleSaveApiKey(key) {
    sessionStorage.setItem(SESSION_KEY, key);
    setApiKey(key);
    setKeyRejected(false);
    setConnectionStatus('connecting');
  }

  function handleClearApiKey() {
    sessionStorage.removeItem(SESSION_KEY);
    setApiKey('');
    setLeads([]);
    setSelectedLead(null);
    setError(null);
    setUnreadCount(0);
    setConnectionStatus('connecting');
  }

  function handleFilterChange(key) {
    setStatusFilter(key);
    setSelectedLead(null);
    if (key === 'new') setUnreadCount(0);
  }

  function handleFiltersChange(newFilters) {
    setFilters(newFilters);
    setSelectedLead(null);
  }

  function handleClearFilters() {
    setFilters({ q: '', intent: '', action: '', dateFrom: '', dateTo: '' });
    setSelectedLead(null);
  }

  function handleManualRefresh() {
    setUnreadCount(0);
    fetchLeads(effectiveKey, statusFilter, { resetUnread: true });
  }

  async function handleCloseLead(leadId) {
    setClosingIds((prev) => new Set([...prev, leadId]));
    try {
      const updated = await closeInternalLead(effectiveKey, leadId);
      setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
      if (selectedLead?.id === updated.id) setSelectedLead(updated);
    } catch {
      setError('تعذّر إغلاق الـ Lead. حاول مجدداً.');
    } finally {
      setClosingIds((prev) => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  async function handleSaveAndCloseLead(leadId, note) {
    const safeNote = (note || '').trim();
    if (safeNote) {
      setLeadActionNotes((prev) => ({ ...prev, [leadId]: safeNote }));
    }
    await handleCloseLead(leadId);
  }

  async function handleRetryCrm(leadId) {
    setRetryingCrmIds((prev) => new Set([...prev, leadId]));
    try {
      const updated = await retryInternalLeadCrm(effectiveKey, leadId);
      setLeads((prev) => prev.map((l) => (l.id === updated.id ? updated : l)));
      if (selectedLead?.id === updated.id) setSelectedLead(updated);
    } catch {
      setError('تعذّرت إعادة محاولة مزامنة CRM.');
    } finally {
      setRetryingCrmIds((prev) => {
        const next = new Set(prev);
        next.delete(leadId);
        return next;
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  // Auth-state gates
  if (authMode === 'checking') {
    return <div className="ild-keyform-wrap" dir="rtl"><div className="ild-keyform"><p>جاري التحقق من الصلاحيات...</p></div></div>;
  }
  if (authMode === 'denied' && !forceApiKey) {
    return <AccessDenied onSwitchToApiKey={() => setForceApiKey(true)} />;
  }
  // forceApiKey=true falls through to API key form below
  if ((authMode === 'apikey' || forceApiKey) && (!apiKey || keyRejected)) {
    return <ApiKeyForm onSubmit={handleSaveApiKey} />;
  }

  const hasActiveFilters = !!(
    effectiveFilters.q || effectiveFilters.intent || effectiveFilters.action ||
    effectiveFilters.dateFrom || effectiveFilters.dateTo
  );

  const selectedStatus = statusFilter;
  const filteredLeads = leads.filter((lead) => {
    const statusMatch = statusFilter === 'all' || lead.status === statusFilter;
    const intentMatch = !filters.intent || normalizeIntentKey(lead.latest_intent) === filters.intent;
    return statusMatch && intentMatch;
  });
  const statTabs = [
    { key: 'all', label: 'الكل', count: stats.all },
    { key: 'new', label: 'جديد', count: stats.new },
    { key: 'delivered', label: 'مسلّم', count: stats.delivered },
    { key: 'failed', label: 'فاشل', count: stats.failed },
    { key: 'closed', label: 'مغلق', count: stats.closed },
  ];
  const intentLabels = {
    TRANSFER_TO_HUMAN: 'تحويل لموظف',
    CLARIFY: 'طلب استفسار',
    BOOKING: 'طلب حجز',
  };

  return (
    <div className="ild-layout" dir="rtl" lang="ar">
      <SummaryModal text={summaryModalText} onClose={() => setSummaryModalText(null)} />

      {/* Toast notifications — fixed overlay */}
      <ToastNotifications toasts={toasts} onDismiss={removeToast} />

      {/* Header */}
      <header className="ild-header">
        <div className="ild-header__brand">
          <img src="/images/wareed-logo.png" alt="وريد" className="ild-header__logo" />
          <span className="ild-header__title">لوحة إدارة الطلبات</span>
          {unreadCount > 0 && (
            <span className="ild-unread-badge" title={`${unreadCount} Lead جديد غير مقروء`}>
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </div>
        <div className="ild-header__actions">
          {authMode !== 'bearer' && !ENV_API_KEY && (
            <button type="button" className="ild-btn ild-btn--logout" onClick={handleClearApiKey}>
              <span className="ild-btn__icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                  <path d="M16 17l5-5-5-5" />
                  <path d="M21 12H9" />
                </svg>
              </span>
              خروج
            </button>
          )}
          <button
            type="button"
            className="ild-btn ild-btn--analytics"
            onClick={() => navigate('/internal/analytics')}
            title="لوحة التحليلات"
          >
            <span className="ild-btn__icon" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M4 20V10" />
                <path d="M10 20V4" />
                <path d="M16 20V13" />
                <path d="M22 20V7" />
              </svg>
            </span>
            تحليلات
          </button>
          <button
            type="button"
            className="ild-btn ild-btn--refresh"
            onClick={handleManualRefresh}
            disabled={loading}
            title="تحديث يدوي"
            aria-label="تحديث"
          >
            <svg
              className={`ild-btn__icon${loading ? ' ild-btn__icon--spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path d="M21 2v6h-6" />
              <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
              <path d="M3 22v-6h6" />
              <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
            </svg>
          </button>
          <ConnectionStatus status={connectionStatus} />
        </div>
      </header>

      <FilterBar
        filters={filters}
        onChange={handleFiltersChange}
        onClear={handleClearFilters}
        statsTabs={statTabs}
        activeStatus={selectedStatus}
        onStatusChange={handleFilterChange}
      />

      {/* Error banner */}
      {error && (
        <div className="ild-error-banner" role="alert">
          {error}
          <button type="button" onClick={() => setError(null)} className="ild-error-banner__dismiss">✕</button>
        </div>
      )}

      {/* Main: table + detail panel */}
      <div className={`ild-main${selectedLead ? ' ild-main--split' : ''}`}>
        <div className="ild-table-wrap">
          {loading && filteredLeads.length === 0 ? (
            <div className="ild-empty">
              <span className="ild-empty__spinner" aria-hidden="true" />
              <p>جارٍ التحميل...</p>
            </div>
          ) : filteredLeads.length === 0 ? (
            <div className="ild-empty">
              <p className="ild-empty__icon">{hasActiveFilters ? '🔍' : '📭'}</p>
              <p>{hasActiveFilters ? 'لا توجد نتائج تطابق الفلاتر المحددة' : 'لا توجد Leads بعد'}</p>
              {hasActiveFilters && (
                <button type="button" className="ild-btn ild-btn--link" onClick={handleClearFilters}>
                  مسح الفلاتر
                </button>
              )}
            </div>
          ) : (
            <table className="ild-table" data-testid="leads-table">
              <thead>
                <tr>
                  <th>رقم الهاتف</th>
                  <th>نية التواصل</th>
                  <th>ملخص الطلب</th>
                  <th>المصدر</th>
                  <th>وقت الاستلام</th>
                  <th>الحالة</th>
                  <th>CRM</th>
                  <th>تفاصيل</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredLeads.map((lead) => (
                  <tr
                    key={lead.id}
                    className={[
                      'ild-table__row',
                      selectedLead?.id === lead.id ? 'ild-table__row--selected' : '',
                      lead.status === 'new' ? 'ild-table__row--new' : '',
                    ].filter(Boolean).join(' ')}
                    onClick={() => setSelectedLead(lead)}
                    tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedLead(lead)}
                    role="button"
                    aria-label={`Lead ${lead.phone}`}
                  >
                    <td className="ild-table__phone">{lead.phone}</td>
                    <td className="ild-table__intent">{intentLabels[(lead.latest_intent || '').toUpperCase()] || 'غير محدد'}</td>
                    <td className="ild-table__hint">{getTableSummary(lead)}</td>
                    <td>{renderSource(lead.source)}</td>
                    <td className="ild-table__date">{formatDate(lead.created_at)}</td>
                    <td><StatusBadge status={lead.status} /></td>
                    <td><CrmStatusBadge status={lead.crm_status} /></td>
                    <td>
                      <button
                        type="button"
                        className="ild-btn ild-btn--summary"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSummaryModalText(lead.summary_text || 'لا توجد تفاصيل متاحة.');
                        }}
                        aria-label="عرض تفاصيل المحادثة"
                        title="عرض التفاصيل"
                      >
                        <svg className="ild-btn__icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                          <path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12z" />
                          <circle cx="12" cy="12" r="3" />
                        </svg>
                      </button>
                    </td>
                    <td>
                      {lead.status !== 'closed' && permissions.canClose && (
                        <button
                          type="button"
                          className="ild-btn ild-btn--inline-close"
                          onClick={(e) => { e.stopPropagation(); handleCloseLead(lead.id); }}
                          disabled={closingIds.has(lead.id)}
                          aria-label={`إغلاق ${lead.phone}`}
                          title="إغلاق"
                        >
                          {closingIds.has(lead.id) ? '...' : (
                            <svg className="ild-btn__icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                              <circle cx="12" cy="12" r="9" />
                              <path d="M9 9l6 6" />
                              <path d="M15 9l-6 6" />
                            </svg>
                          )}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {selectedLead && (
          <LeadDetailPanel
            lead={selectedLead}
            onClose={() => setSelectedLead(null)}
            onSaveAndClose={handleSaveAndCloseLead}
            onRetryCrm={handleRetryCrm}
            closing={closingIds.has(selectedLead.id)}
            retryingCrm={retryingCrmIds.has(selectedLead.id)}
            canClose={permissions.canClose}
            actionNote={leadActionNotes[selectedLead.id] || ''}
            onActionNoteChange={(value) =>
              setLeadActionNotes((prev) => ({ ...prev, [selectedLead.id]: value }))
            }
          />
        )}
      </div>

      <div className="ild-footer">
        {connectionStatus === 'live'
          ? 'بث مباشر نشط — يتحدث فوراً عند كل Lead جديد'
          : 'يتجدد تلقائياً كل 30 ثانية'}
      </div>
    </div>
  );
}

