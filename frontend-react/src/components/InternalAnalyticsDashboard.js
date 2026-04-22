import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getLeadAnalytics, getMe } from '../services/api';
import { getAccessToken } from '../services/auth';
import './InternalAnalyticsDashboard.css';

const INTERNAL_ROLES = new Set(['admin', 'supervisor', 'staff']);

// ---------------------------------------------------------------------------
// Pure SVG trend chart (no external charting library)
// ---------------------------------------------------------------------------
function TrendChart({ trend }) {
  if (!trend || trend.length === 0) {
    return <div className="iad-chart__empty">لا توجد بيانات للرسم البياني</div>;
  }

  const W = 700;
  const H = 160;
  const PAD = { top: 16, right: 16, bottom: 36, left: 36 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const maxCount = Math.max(...trend.map((p) => p.count), 1);
  const minCount = 0;

  const xScale = (i) => PAD.left + (i / Math.max(trend.length - 1, 1)) * chartW;
  const yScale = (v) => PAD.top + chartH - ((v - minCount) / (maxCount - minCount)) * chartH;

  const points = trend.map((p, i) => [xScale(i), yScale(p.count)]);

  const polyline = points.map((p) => p.join(',')).join(' ');
  const areaPath = [
    `M ${points[0][0]},${PAD.top + chartH}`,
    ...points.map((p) => `L ${p[0]},${p[1]}`),
    `L ${points[points.length - 1][0]},${PAD.top + chartH}`,
    'Z',
  ].join(' ');

  // Y gridlines
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((r) => Math.round(minCount + r * (maxCount - minCount)));
  const uniqueYTicks = [...new Set(yTicks)];

  // X labels: show at most 8 evenly spaced dates
  const labelStep = Math.max(1, Math.ceil(trend.length / 8));
  const xLabels = trend
    .map((p, i) => ({ ...p, i }))
    .filter((_, i) => i % labelStep === 0 || i === trend.length - 1);

  return (
    <div className="iad-chart-wrap">
      <svg className="iad-chart" viewBox={`0 0 ${W} ${H}`} aria-label="رسم بياني للأيام">
        {/* Y gridlines */}
        {uniqueYTicks.map((v) => (
          <g key={v}>
            <line
              className="iad-chart__gridline"
              x1={PAD.left}
              y1={yScale(v)}
              x2={W - PAD.right}
              y2={yScale(v)}
            />
            <text className="iad-chart__y-label" x={PAD.left - 4} y={yScale(v) + 4}>
              {v}
            </text>
          </g>
        ))}

        {/* Area fill */}
        <path className="iad-chart__area" d={areaPath} />

        {/* Line */}
        <polyline className="iad-chart__line" points={polyline} />

        {/* Dots + X labels */}
        {trend.map((p, i) => (
          <g key={p.date}>
            <circle className="iad-chart__dot" cx={xScale(i)} cy={yScale(p.count)} r={3} />
          </g>
        ))}
        {xLabels.map(({ date, i }) => (
          <text key={date} className="iad-chart__label" x={xScale(i)} y={H - 8}>
            {date.slice(5)} {/* MM-DD */}
          </text>
        ))}
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Distribution bar list
// ---------------------------------------------------------------------------
function DistributionList({ items, labelKey, valueKey, barColor }) {
  if (!items || items.length === 0) {
    return <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', textAlign: 'right' }}>لا توجد بيانات</p>;
  }
  const max = Math.max(...items.map((it) => it[valueKey]), 1);
  return (
    <div className="iad-dist-list">
      {items.map((it) => (
        <div key={it[labelKey]} className="iad-dist-row">
          <span className="iad-dist-row__label" title={it[labelKey]}>{it[labelKey]}</span>
          <div className="iad-dist-row__bar-wrap">
            <div
              className="iad-dist-row__bar"
              style={{ width: `${(it[valueKey] / max) * 100}%`, background: barColor || undefined }}
            />
          </div>
          <span className="iad-dist-row__count">{it[valueKey]}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// API key form
// ---------------------------------------------------------------------------
function ApiKeyForm({ onSubmit, error, loading }) {
  const [val, setVal] = useState('');
  return (
    <div className="iad-keyform-wrap">
      <div className="iad-keyform">
        <div className="iad-keyform__title">لوحة التحليلات — الوصول الداخلي</div>
        <p className="iad-keyform__sub">أدخل مفتاح API الداخلي للمتابعة</p>
        <form onSubmit={(e) => { e.preventDefault(); onSubmit(val.trim()); }}>
          <input
            className="iad-keyform__input"
            type="password"
            placeholder="X-Internal-Api-Key"
            value={val}
            onChange={(e) => setVal(e.target.value)}
            autoFocus
          />
          {error && <div className="iad-keyform__error">{error}</div>}
          <button className="iad-keyform__btn" type="submit" disabled={loading || !val}>
            {loading ? 'جارٍ التحقق...' : 'دخول'}
          </button>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Access denied
// ---------------------------------------------------------------------------
function AccessDenied({ onUseApiKey }) {
  return (
    <div className="iad-denied">
      <div className="iad-denied__icon">🔒</div>
      <div className="iad-denied__title">غير مصرح بالوصول</div>
      <p className="iad-denied__sub">حسابك لا يملك صلاحية عرض التحليلات الداخلية.</p>
      <button className="iad-btn iad-btn--fetch" style={{ marginTop: 8 }} onClick={onUseApiKey}>
        استخدام مفتاح API
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function InternalAnalyticsDashboard() {
  const navigate = useNavigate();

  // Auth state
  const [authMode, setAuthMode] = useState('checking'); // checking | bearer | apikey | denied
  const [currentUser, setCurrentUser] = useState(null);
  const [apiKey, setApiKey] = useState('');
  const [forceApiKey, setForceApiKey] = useState(false);
  const [keyError, setKeyError] = useState('');
  const [keyRejected, setKeyRejected] = useState(false);

  // Date filters
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // Data state
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [lastRefresh, setLastRefresh] = useState(null);

  const apiKeyRef = useRef('');

  // Resolve auth on mount
  useEffect(() => {
    const token = getAccessToken();
    if (!token) {
      setAuthMode('apikey');
      return;
    }
    getMe()
      .then((me) => {
        setCurrentUser(me);
        const role = me?.role;
        if (INTERNAL_ROLES.has(role)) {
          setAuthMode('bearer');
        } else {
          setAuthMode('denied');
        }
      })
      .catch(() => setAuthMode('apikey'));
  }, []);

  const effectiveKey = authMode === 'bearer' ? '' : apiKey;

  const fetchData = useCallback(async (key) => {
    setLoading(true);
    setError('');
    try {
      const result = await getLeadAnalytics(key, {
        dateFrom: dateFrom || null,
        dateTo: dateTo || null,
      });
      setData(result);
      setLastRefresh(new Date());
      setKeyRejected(false);
      if (authMode === 'apikey' || forceApiKey) {
        setApiKey(key);
        apiKeyRef.current = key;
      }
    } catch (err) {
      if (err?.response?.status === 403) {
        setKeyRejected(true);
        setKeyError('مفتاح API غير صحيح أو منتهي الصلاحية.');
      } else {
        setError('تعذر تحميل البيانات. تحقق من الاتصال وحاول مجدداً.');
      }
    } finally {
      setLoading(false);
    }
  }, [authMode, forceApiKey, dateFrom, dateTo]);

  // Auto-fetch when auth is resolved (bearer) or key is set
  useEffect(() => {
    if (authMode === 'bearer') {
      fetchData('');
    }
  }, [authMode]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleKeySubmit = (key) => {
    setKeyError('');
    fetchData(key);
  };

  const handleApplyFilters = () => {
    fetchData(effectiveKey);
  };

  const handleClearFilters = () => {
    setDateFrom('');
    setDateTo('');
    // fetch with cleared filters immediately
    setTimeout(() => fetchData(effectiveKey), 0);
  };

  // --- Auth gate ---
  if (authMode === 'checking') {
    return (
      <div className="iad-layout">
        <div className="iad-loading"><div className="iad-spinner" /><span>جارٍ التحقق من الصلاحيات...</span></div>
      </div>
    );
  }

  if (authMode === 'denied' && !forceApiKey) {
    return (
      <div className="iad-layout">
        <div className="iad-header">
          <div className="iad-header__left"><span className="iad-header__title">تحليلات الليدز</span></div>
          <div className="iad-header__right">
            <button className="iad-btn iad-btn--back" onClick={() => navigate('/internal/leads')}>← قائمة الليدز</button>
          </div>
        </div>
        <AccessDenied onUseApiKey={() => setForceApiKey(true)} />
      </div>
    );
  }

  if ((authMode === 'apikey' || forceApiKey) && (!apiKey || keyRejected)) {
    return (
      <ApiKeyForm
        onSubmit={handleKeySubmit}
        error={keyError}
        loading={loading}
      />
    );
  }

  // --- Compute display values ---
  const summary = data?.summary;
  const rates = data?.rates;
  const avgHours = data?.avg_delivery_time_hours;

  const fmtRate = (r) => r != null ? `${(r * 100).toFixed(1)}%` : '—';
  const fmtHours = (h) => {
    if (h == null) return '—';
    if (h < 1) return `${Math.round(h * 60)} دقيقة`;
    return `${h.toFixed(1)} ساعة`;
  };

  const lastRefreshStr = lastRefresh
    ? lastRefresh.toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <div className="iad-layout">
      {/* Header */}
      <header className="iad-header">
        <div className="iad-header__left">
          <span className="iad-header__title">تحليلات الليدز</span>
          {authMode === 'bearer' && currentUser?.role && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              {currentUser.display_name || currentUser.email} · {currentUser.role}
            </span>
          )}
        </div>
        <div className="iad-header__right">
          {lastRefreshStr && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              آخر تحديث: {lastRefreshStr}
            </span>
          )}
          <button className="iad-btn iad-btn--back" onClick={() => navigate('/internal/leads')}>
            ← قائمة الليدز
          </button>
        </div>
      </header>

      {/* Content */}
      <div className="iad-content">
        {/* Date controls */}
        <div className="iad-controls">
          <span className="iad-controls__label">النطاق الزمني:</span>
          <input
            type="date"
            className="iad-controls__date"
            value={dateFrom}
            onChange={(e) => setDateFrom(e.target.value)}
            max={dateTo || undefined}
          />
          <span className="iad-controls__sep">إلى</span>
          <input
            type="date"
            className="iad-controls__date"
            value={dateTo}
            onChange={(e) => setDateTo(e.target.value)}
            min={dateFrom || undefined}
          />
          <button className="iad-btn iad-btn--fetch" onClick={handleApplyFilters} disabled={loading}>
            {loading ? 'جارٍ التحميل...' : 'تطبيق'}
          </button>
          {(dateFrom || dateTo) && (
            <button className="iad-btn iad-btn--clear" onClick={handleClearFilters} disabled={loading}>
              مسح الفلتر
            </button>
          )}
        </div>

        {/* Error */}
        {error && (
          <div className="iad-error">
            <span>{error}</span>
            <button className="iad-error__dismiss" onClick={() => setError('')}>✕</button>
          </div>
        )}

        {/* Loading (first load) */}
        {loading && !data && (
          <div className="iad-loading"><div className="iad-spinner" /><span>جارٍ التحميل...</span></div>
        )}

        {/* Data */}
        {data && (
          <>
            {/* Summary cards */}
            <div className="iad-summary-grid">
              <div className="iad-summary-card iad-summary-card--total">
                <span className="iad-summary-card__count">{summary.total_leads}</span>
                <span className="iad-summary-card__label">إجمالي الليدز</span>
              </div>
              <div className="iad-summary-card iad-summary-card--new">
                <span className="iad-summary-card__count">{summary.new_leads}</span>
                <span className="iad-summary-card__label">جديد</span>
              </div>
              <div className="iad-summary-card iad-summary-card--delivered">
                <span className="iad-summary-card__count">{summary.delivered_leads}</span>
                <span className="iad-summary-card__label">تم التسليم</span>
              </div>
              <div className="iad-summary-card iad-summary-card--failed">
                <span className="iad-summary-card__count">{summary.failed_leads}</span>
                <span className="iad-summary-card__label">فشل التسليم</span>
              </div>
              <div className="iad-summary-card iad-summary-card--closed">
                <span className="iad-summary-card__count">{summary.closed_leads}</span>
                <span className="iad-summary-card__label">مغلق</span>
              </div>
            </div>

            {/* Rate cards */}
            <div className="iad-rates-row">
              <div className="iad-rate-card">
                <span className="iad-rate-card__value">{fmtRate(rates?.delivery_failure_rate)}</span>
                <span className="iad-rate-card__label">معدل فشل التسليم</span>
              </div>
              <div className="iad-rate-card">
                <span className="iad-rate-card__value">{fmtRate(rates?.close_rate)}</span>
                <span className="iad-rate-card__label">معدل الإغلاق</span>
              </div>
              <div className="iad-rate-card">
                <span className="iad-rate-card__value">{fmtHours(avgHours)}</span>
                <span className="iad-rate-card__label">متوسط وقت التسليم</span>
              </div>
            </div>

            {/* Trend chart */}
            <div className="iad-section">
              <div className="iad-section__title">الليدز بالأيام</div>
              <TrendChart trend={data.trend} />
            </div>

            {/* Distributions */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 'var(--space-md)' }}>
              <div className="iad-section">
                <div className="iad-section__title">توزيع حسب النية</div>
                <DistributionList items={data.by_intent} labelKey="intent" valueKey="count" />
              </div>
              <div className="iad-section">
                <div className="iad-section__title">توزيع حسب الإجراء</div>
                <DistributionList items={data.by_action} labelKey="action" valueKey="count" />
              </div>
              <div className="iad-section">
                <div className="iad-section__title">توزيع حسب الحالة</div>
                <DistributionList
                  items={data.by_status}
                  labelKey="status"
                  valueKey="count"
                  barColor="var(--brand-300)"
                />
              </div>
            </div>
          </>
        )}
      </div>

      {/* Footer */}
      <footer className="iad-footer">
        لوحة التحليلات الداخلية · وريد AI · {new Date().getFullYear()}
      </footer>
    </div>
  );
}
