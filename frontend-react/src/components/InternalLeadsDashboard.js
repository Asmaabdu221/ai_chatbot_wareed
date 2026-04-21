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

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { getInternalLeads, closeInternalLead, API_BASE_URL } from '../services/api';
import './InternalLeadsDashboard.css';

const ENV_API_KEY = process.env.REACT_APP_INTERNAL_API_KEY || '';
const SESSION_KEY = 'wareed_internal_api_key';
const REFRESH_INTERVAL_MS = 30000;
const TOAST_DURATION_MS = 5000;
const SSE_MAX_ERRORS = 6; // after this many consecutive errors → declare offline

const STATUS_LABELS = {
  new: 'جديد',
  delivered: 'مُسلَّم',
  failed: 'فاشل',
  closed: 'مغلق',
};

const INTENT_LABELS = {
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
  return INTENT_LABELS[intent] || intent || '—';
}

function normalizeEventToLead(event) {
  return {
    id: event.lead_id,
    conversation_id: event.conversation_id,
    phone: event.phone,
    latest_intent: event.latest_intent,
    latest_action: event.latest_action,
    summary_hint: event.summary_hint,
    source: event.source,
    status: event.status,
    created_at: event.created_at,
    delivered_at: event.delivered_at,
    delivery_error: event.delivery_error,
  };
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

function StatCard({ label, count, active, onClick }) {
  return (
    <button
      type="button"
      className={`ild-stat-card${active ? ' ild-stat-card--active' : ''}`}
      onClick={onClick}
    >
      <span className="ild-stat-card__count">{count}</span>
      <span className="ild-stat-card__label">{label}</span>
    </button>
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
        <h1 className="ild-keyform__title">لوحة الـ Leads الداخلية</h1>
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

function LeadDetailPanel({ lead, onClose, onCloseLead, closing }) {
  if (!lead) return null;
  return (
    <div className="ild-panel" dir="rtl" role="complementary" aria-label="تفاصيل الـ Lead">
      <div className="ild-panel__header">
        <h2 className="ild-panel__title">تفاصيل الـ Lead</h2>
        <button type="button" className="ild-panel__close-btn" onClick={onClose} aria-label="إغلاق">✕</button>
      </div>
      <div className="ild-panel__body">
        {[
          ['الحالة', <StatusBadge status={lead.status} />],
          ['رقم الهاتف', <span className="ild-panel__value--phone">{lead.phone}</span>],
          ['نية التواصل', formatIntent(lead.latest_intent)],
          ['الإجراء', formatIntent(lead.latest_action)],
          ['ملخص الطلب', lead.summary_hint || '—'],
          ['المصدر', lead.source],
          ['وقت الاستلام', formatDate(lead.created_at)],
          lead.delivered_at && ['وقت التسليم', formatDate(lead.delivered_at)],
          lead.delivery_error && ['خطأ التسليم', <span className="ild-panel__value--error">{lead.delivery_error}</span>],
        ].filter(Boolean).map(([label, value]) => (
          <div key={label} className="ild-panel__row">
            <span className="ild-panel__label">{label}</span>
            <span className="ild-panel__value">{value}</span>
          </div>
        ))}
        <div className="ild-panel__row ild-panel__row--id">
          <span className="ild-panel__label">Lead ID</span>
          <span className="ild-panel__value ild-panel__value--mono">{lead.id}</span>
        </div>
      </div>
      {lead.status !== 'closed' && (
        <div className="ild-panel__footer">
          <button
            type="button"
            className="ild-btn ild-btn--close-lead"
            onClick={() => onCloseLead(lead.id)}
            disabled={closing}
          >
            {closing ? 'جارٍ الإغلاق...' : 'إغلاق الـ Lead ✓'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main dashboard
// ---------------------------------------------------------------------------

export default function InternalLeadsDashboard() {
  // --- API key ---
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
  const [lastRefreshed, setLastRefreshed] = useState(null);

  // --- Realtime ---
  const [connectionStatus, setConnectionStatus] = useState('connecting');
  const [toasts, setToasts] = useState([]);
  const [unreadCount, setUnreadCount] = useState(0);

  const refreshTimerRef = useRef(null);

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
  // Lead event handler (SSE)
  // ---------------------------------------------------------------------------

  const handleLeadEvent = useCallback((event) => {
    const { event_type } = event;
    if (!event_type || event_type === 'ping' || event_type === 'connected') return;

    const leadData = normalizeEventToLead(event);

    // Merge into leads list (upsert by id — no duplicates)
    setLeads((prev) => {
      const idx = prev.findIndex((l) => l.id === leadData.id);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = { ...next[idx], ...leadData };
        return next;
      }
      if (event_type === 'lead.created') {
        return [leadData, ...prev];
      }
      return prev;
    });

    // Sync open detail panel
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
  }, [addToast]);

  // Stable ref so the EventSource effect doesn't need handleLeadEvent in its deps
  const handleLeadEventRef = useRef(handleLeadEvent);
  useEffect(() => { handleLeadEventRef.current = handleLeadEvent; }, [handleLeadEvent]);

  // ---------------------------------------------------------------------------
  // REST fetch (initial load + 30s authoritative sync)
  // ---------------------------------------------------------------------------

  const fetchLeads = useCallback(async (key, filter, { resetUnread = false } = {}) => {
    if (!key) return;
    setLoading(true);
    setError(null);
    try {
      const res = await getInternalLeads(key, {
        status: filter === 'all' ? null : filter,
        pageSize: 100,
      });
      setLeads(res.items || []);
      setLastRefreshed(new Date());
      setKeyRejected(false);
      if (resetUnread) setUnreadCount(0);

      // Recompute stats from full result (authoritative)
      if (filter === 'all') {
        const s = { all: res.total || (res.items || []).length, new: 0, delivered: 0, failed: 0, closed: 0 };
        (res.items || []).forEach((l) => { if (s[l.status] !== undefined) s[l.status]++; });
        setStats(s);
      }
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

  // Initial fetch + when filter changes
  useEffect(() => {
    if (!apiKey) return;
    fetchLeads(apiKey, statusFilter, { resetUnread: true });
  }, [apiKey, statusFilter, fetchLeads]);

  // 30-second authoritative polling (fallback even when SSE is live)
  useEffect(() => {
    if (!apiKey) return;
    refreshTimerRef.current = setInterval(
      () => fetchLeads(apiKey, statusFilter),
      REFRESH_INTERVAL_MS
    );
    return () => clearInterval(refreshTimerRef.current);
  }, [apiKey, statusFilter, fetchLeads]);

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
    if (!apiKey) return;

    const url = `${API_BASE_URL}/api/internal/leads/stream?api_key=${encodeURIComponent(apiKey)}`;
    let es = null;
    let errorCount = 0;

    function connect() {
      es = new window.EventSource(url);

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
  }, [apiKey]); // eslint-disable-line react-hooks/exhaustive-deps

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
    if (key === 'new') setUnreadCount(0); // mark as seen
  }

  function handleManualRefresh() {
    setUnreadCount(0);
    fetchLeads(apiKey, statusFilter, { resetUnread: true });
  }

  async function handleCloseLead(leadId) {
    setClosingIds((prev) => new Set([...prev, leadId]));
    try {
      const updated = await closeInternalLead(apiKey, leadId);
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

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (!apiKey || keyRejected) {
    return <ApiKeyForm onSubmit={handleSaveApiKey} />;
  }

  const statTabs = [
    { key: 'all', label: 'الكل', count: stats.all },
    { key: 'new', label: STATUS_LABELS.new, count: stats.new },
    { key: 'delivered', label: STATUS_LABELS.delivered, count: stats.delivered },
    { key: 'failed', label: STATUS_LABELS.failed, count: stats.failed },
    { key: 'closed', label: STATUS_LABELS.closed, count: stats.closed },
  ];

  return (
    <div className="ild-layout" dir="rtl" lang="ar">
      {/* Toast notifications — fixed overlay */}
      <ToastNotifications toasts={toasts} onDismiss={removeToast} />

      {/* Header */}
      <header className="ild-header">
        <div className="ild-header__left">
          <img src="/images/wareed-logo.png" alt="وريد" className="ild-header__logo" />
          <span className="ild-header__title">لوحة الـ Leads</span>
          {unreadCount > 0 && (
            <span className="ild-unread-badge" title={`${unreadCount} Lead جديد غير مقروء`}>
              {unreadCount > 99 ? '99+' : unreadCount}
            </span>
          )}
        </div>
        <div className="ild-header__right">
          <ConnectionStatus status={connectionStatus} />
          {lastRefreshed && (
            <span className="ild-header__last-refresh">
              {lastRefreshed.toLocaleTimeString('ar-SA')}
            </span>
          )}
          <button
            type="button"
            className="ild-btn ild-btn--refresh"
            onClick={handleManualRefresh}
            disabled={loading}
            title="تحديث يدوي"
          >
            {loading ? '...' : '↺ تحديث'}
          </button>
          {!ENV_API_KEY && (
            <button type="button" className="ild-btn ild-btn--signout" onClick={handleClearApiKey}>
              خروج
            </button>
          )}
        </div>
      </header>

      {/* Stats / filter bar */}
      <div className="ild-stats-bar">
        {statTabs.map((tab) => (
          <StatCard
            key={tab.key}
            label={tab.label}
            count={tab.count}
            active={statusFilter === tab.key}
            onClick={() => handleFilterChange(tab.key)}
          />
        ))}
      </div>

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
          {loading && leads.length === 0 ? (
            <div className="ild-empty">
              <span className="ild-empty__spinner" aria-hidden="true" />
              <p>جارٍ التحميل...</p>
            </div>
          ) : leads.length === 0 ? (
            <div className="ild-empty">
              <p className="ild-empty__icon">📭</p>
              <p>لا توجد نتائج</p>
            </div>
          ) : (
            <table className="ild-table" data-testid="leads-table">
              <thead>
                <tr>
                  <th>رقم الهاتف</th>
                  <th>نية التواصل</th>
                  <th>ملخص الطلب</th>
                  <th>المصدر</th>
                  <th>الحالة</th>
                  <th>وقت الاستلام</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {leads.map((lead) => (
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
                    <td>{formatIntent(lead.latest_intent)}</td>
                    <td className="ild-table__hint">{lead.summary_hint || '—'}</td>
                    <td>{lead.source}</td>
                    <td><StatusBadge status={lead.status} /></td>
                    <td className="ild-table__date">{formatDate(lead.created_at)}</td>
                    <td>
                      {lead.status !== 'closed' && (
                        <button
                          type="button"
                          className="ild-btn ild-btn--inline-close"
                          onClick={(e) => { e.stopPropagation(); handleCloseLead(lead.id); }}
                          disabled={closingIds.has(lead.id)}
                          aria-label={`إغلاق ${lead.phone}`}
                        >
                          {closingIds.has(lead.id) ? '...' : 'إغلاق'}
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
            onCloseLead={handleCloseLead}
            closing={closingIds.has(selectedLead.id)}
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
