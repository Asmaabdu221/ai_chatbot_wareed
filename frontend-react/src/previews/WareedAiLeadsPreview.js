import React from 'react';
import { Link } from 'react-router-dom';
import { usePreviewLeads } from '../contexts/PreviewLeadsContext';
import './WareedAiLeadsPreview.css';

const LEAD_STATUSES = ['NEW', 'CONTACTED', 'CLOSED'];

export default function WareedAiLeadsPreview() {
  const { leads, newLeadsCount, updateLeadStatus, clearLeads } = usePreviewLeads();

  return (
    <div className="wareed-leads-preview" dir="rtl" lang="ar">
      <header className="wareed-leads-preview__header">
        <div>
          <p className="wareed-leads-preview__eyebrow">Internal Preview Panel</p>
          <h1>لوحة متابعة طلبات التواصل</h1>
          <p>هذه لوحة داخلية تجريبية فقط لعرض الطلبات الملتقطة من ويدجت المعاينة.</p>
        </div>
        <div className="wareed-leads-preview__header-actions">
          <span className="wareed-leads-preview__new-badge">NEW: {newLeadsCount}</span>
          <Link to="/wareed-ai-preview" className="wareed-leads-preview__back-link">
            الرجوع إلى معاينة الودجت
          </Link>
          <button type="button" onClick={clearLeads} className="wareed-leads-preview__clear-btn">
            مسح كل الطلبات
          </button>
        </div>
      </header>

      <section className="wareed-leads-preview__content">
        {leads.length === 0 ? (
          <article className="wareed-leads-preview__empty">
            <h2>لا توجد طلبات حالياً</h2>
            <p>ارسل طلباً من صفحة `/wareed-ai-preview` وسيظهر هنا مباشرة.</p>
          </article>
        ) : (
          <div className="wareed-leads-preview__grid">
            {leads.map((lead) => (
              <article key={lead.id} className="wareed-leads-preview__card">
                <div className="wareed-leads-preview__row">
                  <strong>الحالة</strong>
                  <select value={lead.status || 'NEW'} onChange={(e) => updateLeadStatus(lead.id, e.target.value)}>
                    {LEAD_STATUSES.map((status) => (
                      <option key={status} value={status}>
                        {status}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>Lead Type</strong>
                  <span>{lead.leadType}</span>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>رقم الجوال</strong>
                  <span>{lead.phone}</span>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>Conversation ID</strong>
                  <span>{lead.conversationId || '-'}</span>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>وقت الإنشاء</strong>
                  <span>{lead.createdAt}</span>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>آخر سؤال من المستخدم</strong>
                  <p>{lead.latestUserQuestion || '-'}</p>
                </div>
                <div className="wareed-leads-preview__row">
                  <strong>آخر رد من المساعد</strong>
                  <p>{lead.latestAssistantReply || '-'}</p>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
