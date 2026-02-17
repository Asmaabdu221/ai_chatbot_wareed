import React from 'react';
import { formatArabicNumber, formatArabicText } from '../utils/arabicFormatters';
import './Dashboard.css';

const mock = {
  totals: [
    { label: 'إجمالي المستخدمين', value: '12,450' },
    { label: 'المستخدمون النشطون', value: '4,280' },
    { label: 'إجمالي المحادثات', value: '38,920' },
    { label: 'الرسائل (هذا الأسبوع)', value: '112,400' },
  ],
  messagesTrend: [
    { day: 'سبت', value: 1200 },
    { day: 'أحد', value: 1800 },
    { day: 'اثنين', value: 2400 },
    { day: 'ثلاثاء', value: 1900 },
    { day: 'أربعاء', value: 2600 },
    { day: 'خميس', value: 3200 },
    { day: 'جمعة', value: 2800 },
  ],
  popularPrompts: [
    { label: 'أسعار التحاليل', value: 32 },
    { label: 'مواعيد الفروع', value: 21 },
    { label: 'التحاليل الجينية', value: 18 },
    { label: 'تحضير قبل التحاليل', value: 15 },
  ],
  topHormones: [
    { label: 'TSH', value: 28 },
    { label: 'Vitamin D', value: 22 },
    { label: 'Ferritin', value: 16 },
    { label: 'HbA1c', value: 14 },
  ],
  alerts: [
    { type: 'warning', text: 'ارتفاع الطلب على استفسارات الأسعار هذا الأسبوع' },
    { type: 'info', text: 'تحسين وقت الاستجابة بنسبة 8% مقارنة بالأسبوع الماضي' },
  ],
};

const Dashboard = () => {
  const maxTrend = Math.max(...mock.messagesTrend.map((d) => d.value));
  const maxPopular = Math.max(...mock.popularPrompts.map((d) => d.value));
  const maxHormones = Math.max(...mock.topHormones.map((d) => d.value));
  const isLoading =
    mock.totals.length === 0 &&
    mock.messagesTrend.length === 0 &&
    mock.popularPrompts.length === 0 &&
    mock.topHormones.length === 0 &&
    mock.alerts.length === 0;

  return (
    <div className="dashboard-page arabic-text" dir="auto">
      <div className="dashboard-header">
        <div>
          <h2>{formatArabicText('لوحة التحكم')}</h2>
          <p>{formatArabicText('نظرة عامة على أداء الشات — بيانات تجريبية')}</p>
        </div>
        <div className="dashboard-actions">
          <button className="dash-btn" title="Coming soon" disabled>
            {formatArabicText('تصدير')}
          </button>
          <button className="dash-btn" title="Coming soon" disabled>
            {formatArabicText('مشاركة')}
          </button>
        </div>
      </div>

      <div className="stats-grid">
        {isLoading && (
          <>
            <div className="stat-card skeleton-card"></div>
            <div className="stat-card skeleton-card"></div>
            <div className="stat-card skeleton-card"></div>
            <div className="stat-card skeleton-card"></div>
          </>
        )}
        {!isLoading && mock.totals.length === 0 && (
          <div className="empty-section">
            {formatArabicText('لا توجد بيانات إحصائية حالياً.')}
          </div>
        )}
        {!isLoading && mock.totals.map((card) => (
          <div className="stat-card" key={card.label}>
            <div className="stat-label" dir="auto">
              {formatArabicText(card.label)}
            </div>
            <div className="stat-value" dir="auto">
              {formatArabicNumber(card.value)}
            </div>
          </div>
        ))}
      </div>

      <div className="dashboard-grid">
        <div className={`panel ${isLoading ? 'skeleton-panel' : ''}`}>
          <div className="panel-title" dir="auto">
            {formatArabicText('الرسائل اليومية (7 أيام)')}
          </div>
          {isLoading ? (
            <div className="panel-skeleton-body"></div>
          ) : mock.messagesTrend.length === 0 ? (
            <div className="empty-section">
              {formatArabicText('لا توجد بيانات متاحة لهذه الفترة.')}
            </div>
          ) : (
            <div className="bar-chart">
              {mock.messagesTrend.map((d) => (
                <div className="bar-item" key={d.day}>
                  <div
                    className="bar"
                    style={{ height: `${(d.value / maxTrend) * 100}%` }}
                    title={`${d.value} رسالة`}
                  />
                  <div className="bar-label" dir="auto">
                    {formatArabicText(d.day)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className={`panel ${isLoading ? 'skeleton-panel' : ''}`}>
          <div className="panel-title" dir="auto">
            {formatArabicText('أكثر الاستفسارات شيوعاً')}
          </div>
          {isLoading ? (
            <div className="panel-skeleton-body"></div>
          ) : mock.popularPrompts.length === 0 ? (
            <div className="empty-section">
              {formatArabicText('لا توجد بيانات شائعة حالياً.')}
            </div>
          ) : (
            <div className="list-chart">
              {mock.popularPrompts.map((d) => (
                <div className="list-row" key={d.label}>
                  <span dir="auto">{formatArabicText(d.label)}</span>
                  <div className="list-bar">
                    <span style={{ width: `${(d.value / maxPopular) * 100}%` }} />
                  </div>
                  <span className="list-value" dir="auto">
                    {formatArabicNumber(d.value)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className={`panel ${isLoading ? 'skeleton-panel' : ''}`}>
          <div className="panel-title" dir="auto">
            {formatArabicText('أكثر التحاليل طلباً (هرمونات)')}
          </div>
          {isLoading ? (
            <div className="panel-skeleton-body"></div>
          ) : mock.topHormones.length === 0 ? (
            <div className="empty-section">
              {formatArabicText('لا توجد بيانات متاحة حالياً.')}
            </div>
          ) : (
            <div className="list-chart">
              {mock.topHormones.map((d) => (
                <div className="list-row" key={d.label}>
                  <span dir="auto">{formatArabicText(d.label)}</span>
                  <div className="list-bar">
                    <span style={{ width: `${(d.value / maxHormones) * 100}%` }} />
                  </div>
                  <span className="list-value" dir="auto">
                    {formatArabicNumber(d.value)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className={`panel ${isLoading ? 'skeleton-panel' : ''}`}>
          <div className="panel-title" dir="auto">
            {formatArabicText('تنبيهات')}
          </div>
          <div className="alerts">
            {isLoading ? (
              <div className="panel-skeleton-body"></div>
            ) : mock.alerts.length === 0 ? (
              <div className="empty-section">
                {formatArabicText('لا توجد تنبيهات حالياً.')}
              </div>
            ) : (
              mock.alerts.map((a, i) => (
                <div className={`alert ${a.type}`} key={i}>
                  {formatArabicText(a.text)}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
