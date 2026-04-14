import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { createConversation, sendConversationMessage } from '../services/api';
import { usePreviewLeads } from '../contexts/PreviewLeadsContext';
import './WareedAiWidgetPreview.css';

const WELCOME_MESSAGE = `حياك الله في مختبرات وريد الطبية
أنا وريد AI، مساعدك الذكي.
أقدر أساعدك في الاستفسار عن التحاليل، النتائج، الفروع، والخدمات.
تفضل كيف أقدر أخدمك؟`;

const QUICK_CHIPS = ['أبغى أسأل عن تحليل', 'أبغى أعرف الفروع', 'عندي نتيجة وأبغى تفسير', 'أبغى أتواصل مع خدمة العملاء'];
const CONNECTIVITY_ERROR_MESSAGE = 'حصلت مشكلة مؤقتة في الاتصال، حاول مرة أخرى بعد قليل.';
const TYPING_MESSAGE = 'جاري الكتابة...';
const LEAD_PHONE_REQUEST_MESSAGE = 'من فضلك زودني برقم جوالك ليتواصل معك أحد المختصين.';
const LEAD_CONFIRMATION_MESSAGE = 'تم استلام طلبك، وسيتم التواصل معك قريبًا من الفريق المختص.';
const LEAD_PHONE_INVALID_MESSAGE = 'الرقم غير واضح. فضلاً اكتب رقم جوال صحيح بصيغة مثل 05XXXXXXXX أو +9665XXXXXXXX.';

const EASTERN_DIGIT_MAP = {
  '٠': '0',
  '١': '1',
  '٢': '2',
  '٣': '3',
  '٤': '4',
  '٥': '5',
  '٦': '6',
  '٧': '7',
  '٨': '8',
  '٩': '9',
};

const LEAD_TYPES = {
  SALES: 'SALES',
  BOOKING: 'BOOKING',
  RESULTS: 'RESULTS',
  CUSTOMER_SERVICE: 'CUSTOMER_SERVICE',
  DOCTOR_CALLBACK: 'DOCTOR_CALLBACK',
};

function normalizeDigits(value) {
  return (value || '').replace(/[٠-٩]/g, (digit) => EASTERN_DIGIT_MAP[digit] || digit);
}

function normalizePhone(value) {
  const normalized = normalizeDigits(value);
  return normalized.replace(/[^\d+]/g, '');
}

function isLikelyPhone(value) {
  const normalized = normalizePhone(value);
  if (!normalized) return false;
  if (!/^\+?\d+$/.test(normalized)) return false;
  const digitsOnly = normalized.replace(/\D/g, '');
  return digitsOnly.length >= 9 && digitsOnly.length <= 14;
}

function detectLeadTypeFromText(rawText) {
  const text = (rawText || '').toLowerCase();
  if (!text.trim()) return null;

  if (/(حجز|موعد|booking|appointment|book)/i.test(text)) return LEAD_TYPES.BOOKING;
  if (/(نتيجة|نتائج|result|results|تأخرت نتيجتي|تفسير)/i.test(text)) return LEAD_TYPES.RESULTS;
  if (/(خدمة العملاء|موظف|تواصل|support|customer service|شكوى)/i.test(text)) return LEAD_TYPES.CUSTOMER_SERVICE;
  if (/(سعر|أسعار|اسعار|تكلفة|price|pricing|cost|عرض)/i.test(text)) return LEAD_TYPES.SALES;
  if (/(أعراض|اعراض|ألم|الم|صداع|دوخة|حمى|حرارة|ضيق تنفس|doctor|طبيب)/i.test(text)) {
    return LEAD_TYPES.DOCTOR_CALLBACK;
  }

  return null;
}

export default function WareedAiWidgetPreview() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [conversationId, setConversationId] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [awaitingPhone, setAwaitingPhone] = useState(false);
  const [pendingLeadType, setPendingLeadType] = useState(null);
  const [leadContext, setLeadContext] = useState({ latestUserQuestion: '', latestAssistantReply: '' });
  const [latestLead, setLatestLead] = useState(null);
  const [messages, setMessages] = useState(() => [{ id: 'welcome', role: 'assistant', text: WELCOME_MESSAGE }]);
  const messageCounterRef = useRef(1);
  const messagesContainerRef = useRef(null);
  const { addLead, newLeadsCount } = usePreviewLeads();

  const pageCards = useMemo(
    () => [
      {
        title: 'معاينة داخلية',
        body: 'هذه الصفحة مخصصة لاختبار شكل و سلوك ويدجت وريد AI قبل ربطه بالموقع الإنتاجي.',
      },
      {
        title: 'تجربة تفاعل عربية',
        body: 'الواجهة هنا RTL بالكامل مع رسائل تجريبية فقط لتأكيد تجربة الاستخدام.',
      },
      {
        title: 'قابلية الدمج لاحقاً',
        body: 'بعد اعتماد الشكل النهائي، نقدر ننقل نفس المكون لواجهة الموقع الفعلية بشكل آمن.',
      },
    ],
    []
  );

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, isOpen]);

  const sendMessage = async (rawText) => {
    const text = (rawText || '').trim();
    if (!text || isSending) return;

    const userId = `msg_${messageCounterRef.current++}`;
    const userMessage = { id: userId, role: 'user', text };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setIsOpen(true);

    if (awaitingPhone) {
      if (!isLikelyPhone(text)) {
        const invalidPhoneId = `msg_${messageCounterRef.current++}`;
        setMessages((prev) => [...prev, { id: invalidPhoneId, role: 'assistant', text: LEAD_PHONE_INVALID_MESSAGE }]);
        return;
      }

      const capturedLead = {
        phone: normalizePhone(text),
        leadType: pendingLeadType || LEAD_TYPES.CUSTOMER_SERVICE,
        latestUserQuestion: leadContext.latestUserQuestion || text,
        latestAssistantReply: leadContext.latestAssistantReply || '',
        conversationId,
        createdAt: new Date().toISOString(),
      };
      const savedLead = addLead(capturedLead);
      setLatestLead(savedLead);
      setAwaitingPhone(false);
      setPendingLeadType(null);

      const confirmId = `msg_${messageCounterRef.current++}`;
      setMessages((prev) => [...prev, { id: confirmId, role: 'assistant', text: LEAD_CONFIRMATION_MESSAGE }]);
      return;
    }

    const typingId = `typing_${messageCounterRef.current++}`;
    const typingMessage = { id: typingId, role: 'assistant', text: TYPING_MESSAGE, isTyping: true };
    setMessages((prev) => [...prev, typingMessage]);
    setIsSending(true);

    try {
      let currentConversationId = conversationId;
      if (!currentConversationId) {
        const newConversation = await createConversation();
        currentConversationId = newConversation?.id;
        if (!currentConversationId) {
          throw new Error('Missing conversation id');
        }
        setConversationId(currentConversationId);
      }

      const data = await sendConversationMessage(currentConversationId, text);
      const assistantText = (data?.assistant_message?.content || '').trim() || CONNECTIVITY_ERROR_MESSAGE;
      const assistantId = data?.assistant_message?.id || `msg_${messageCounterRef.current++}`;
      const leadTypeFromFlow = detectLeadTypeFromText(text) || detectLeadTypeFromText(assistantText);

      setMessages((prev) =>
        prev.map((message) =>
          message.id === typingId
            ? {
                id: assistantId,
                role: 'assistant',
                text: assistantText,
              }
            : message
        )
      );

      if (leadTypeFromFlow && !awaitingPhone) {
        setPendingLeadType(leadTypeFromFlow);
        setAwaitingPhone(true);
        setLeadContext({
          latestUserQuestion: text,
          latestAssistantReply: assistantText,
        });
        const askPhoneId = `msg_${messageCounterRef.current++}`;
        setMessages((prev) => [...prev, { id: askPhoneId, role: 'assistant', text: LEAD_PHONE_REQUEST_MESSAGE }]);
      }
    } catch (error) {
      console.error('Preview widget message send failed:', error);
      setMessages((prev) =>
        prev.map((message) =>
          message.id === typingId
            ? {
                id: `err_${messageCounterRef.current++}`,
                role: 'assistant',
                text: CONNECTIVITY_ERROR_MESSAGE,
              }
            : message
        )
      );
    } finally {
      setIsSending(false);
    }
  };

  const onSubmit = (event) => {
    event.preventDefault();
    sendMessage(input);
  };

  return (
    <div className="wareed-widget-preview" dir="rtl" lang="ar">
      <main className="wareed-widget-preview__hero">
        <div className="wareed-widget-preview__hero-content">
          <p className="wareed-widget-preview__eyebrow">Wareed Labs Preview</p>
          <h1>معاينة ويدجت وريد AI</h1>
          <p>
            نموذج واجهة محلي لتجربة زر المساعد الذكي والشات العائم، بدون أي تعديل على التكامل الإنتاجي الحالي.
          </p>
          <div className="wareed-widget-preview__header-actions">
            <Link to="/wareed-ai-leads-preview" className="wareed-widget-preview__leads-link">
              لوحة المتابعة الداخلية
            </Link>
            <span className="wareed-widget-preview__new-badge">NEW: {newLeadsCount}</span>
          </div>
        </div>
      </main>

      <section className="wareed-widget-preview__cards">
        {pageCards.map((card) => (
          <article key={card.title} className="wareed-widget-preview__card">
            <h2>{card.title}</h2>
            <p>{card.body}</p>
          </article>
        ))}
      </section>

      <section className="wareed-widget-preview__lead-debug">
        <h2>آخر Lead (Preview Only)</h2>
        {!latestLead ? (
          <p>لا يوجد Lead ملتقط حتى الآن.</p>
        ) : (
          <div className="wareed-widget-preview__lead-grid">
            <div>
              <strong>Lead Type</strong>
              <span>{latestLead.leadType}</span>
            </div>
            <div>
              <strong>Status</strong>
              <span>{latestLead.status || 'NEW'}</span>
            </div>
            <div>
              <strong>Phone</strong>
              <span>{latestLead.phone}</span>
            </div>
            <div>
              <strong>Conversation ID</strong>
              <span>{latestLead.conversationId || '-'}</span>
            </div>
            <div>
              <strong>Created At</strong>
              <span>{latestLead.createdAt}</span>
            </div>
            <div>
              <strong>Latest User Question</strong>
              <span>{latestLead.latestUserQuestion}</span>
            </div>
            <div>
              <strong>Latest Assistant Reply</strong>
              <span>{latestLead.latestAssistantReply}</span>
            </div>
          </div>
        )}
      </section>

      <div className="wareed-widget-preview__floating-stack" aria-hidden="true">
        <button type="button" className="wareed-widget-preview__ghost-icon">
          تطبيق وريد
        </button>
        <button type="button" className="wareed-widget-preview__ghost-icon">
          واتساب
        </button>
        <button type="button" className="wareed-widget-preview__ghost-icon">
          اتصال
        </button>
      </div>

      <button
        type="button"
        className="wareed-widget-preview__ai-button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-controls="wareed-ai-chat-panel"
      >
        <span className="wareed-widget-preview__ai-dot" />
        Wareed AI
      </button>

      {isOpen && (
        <aside id="wareed-ai-chat-panel" className="wareed-widget-preview__chat-panel" aria-label="نافذة دردشة وريد AI">
          <header className="wareed-widget-preview__chat-header">
            <div>
              <h3>Wareed AI</h3>
              <p>المساعد الذكي</p>
            </div>
            <button type="button" onClick={() => setIsOpen(false)} aria-label="إغلاق">
              اغلاق
            </button>
          </header>

          <div className="wareed-widget-preview__chips" role="list">
            {QUICK_CHIPS.map((chip) => (
              <button
                key={chip}
                type="button"
                onClick={() => sendMessage(chip)}
                role="listitem"
                disabled={isSending}
              >
                {chip}
              </button>
            ))}
          </div>

          <div ref={messagesContainerRef} className="wareed-widget-preview__messages">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`wareed-widget-preview__message wareed-widget-preview__message--${message.role}${
                  message.isTyping ? ' wareed-widget-preview__message--typing' : ''
                }`}
              >
                <p>{message.text}</p>
              </div>
            ))}
          </div>

          <form className="wareed-widget-preview__composer" onSubmit={onSubmit}>
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="اكتب رسالتك هنا"
              aria-label="اكتب رسالتك"
              disabled={isSending}
            />
            <button type="submit" disabled={isSending}>
              {isSending ? 'جارٍ الإرسال...' : 'إرسال'}
            </button>
          </form>
        </aside>
      )}
    </div>
  );
}
