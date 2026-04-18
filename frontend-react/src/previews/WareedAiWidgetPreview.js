import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import { usePreviewLeads } from '../contexts/PreviewLeadsContext';
import './WareedAiWidgetPreview.css';

const WELCOME_MESSAGE = `حياك الله في مختبرات وريد الطبية
أنا وريد AI، مساعدك الذكي.
أقدر أساعدك في الاستفسار عن التحاليل، النتائج، الفروع، والخدمات.
تفضل كيف أقدر أخدمك؟`;

const QUICK_CHIPS = [
  'أبغى أسأل عن تحليل',
  'أبغى أعرف الفروع',
  'عندي نتيجة وأبغى تفسير',
  'أبغى أتواصل مع خدمة العملاء',
];

const CONNECTIVITY_ERROR_MESSAGE = 'حصلت مشكلة مؤقتة في الاتصال، حاول مرة أخرى بعد قليل.';
const TYPING_MESSAGE = 'جاري الكتابة...';
const LEAD_CONFIRMATION_MESSAGE = 'تم استلام طلبك، وسيتم التواصل معك قريبًا من الفريق المختص.';
const LEAD_PHONE_INVALID_MESSAGE =
  'الرقم غير واضح. فضلاً اكتب رقم جوال صحيح بصيغة مثل 05XXXXXXXX أو +9665XXXXXXXX.';

const LEAD_TYPES = {
  SALES: 'SALES',
  BOOKING: 'BOOKING',
  RESULTS: 'RESULTS',
  CUSTOMER_SERVICE: 'CUSTOMER_SERVICE',
  DOCTOR_CALLBACK: 'DOCTOR_CALLBACK',
};

// Per-type escalation messages — each tailored to the context
const LEAD_PHONE_REQUEST_MESSAGES = {
  [LEAD_TYPES.SALES]: 'من فضلك زودني برقم جوالك ليتواصل معك أحد المختصين.',
  [LEAD_TYPES.BOOKING]: 'من فضلك زودني برقم جوالك لتأكيد الحجز ومتابعة الموعد.',
  [LEAD_TYPES.RESULTS]: 'لاستفسار عن نتيجتك، زودني برقم جوالك وسنتواصل معك في أقرب وقت.',
  [LEAD_TYPES.CUSTOMER_SERVICE]: 'يسعدنا مساعدتك، زودني برقم جوالك ليتواصل معك أحد فريق خدمة العملاء.',
  [LEAD_TYPES.DOCTOR_CALLBACK]: 'إذا حابب يتواصل معك أحد المختصين أو طبيب، زودني برقم جوالك.',
};

function getLeadPhoneMessage(leadType) {
  return (
    LEAD_PHONE_REQUEST_MESSAGES[leadType] ||
    LEAD_PHONE_REQUEST_MESSAGES[LEAD_TYPES.CUSTOMER_SERVICE]
  );
}

const EASTERN_DIGIT_MAP = {
  '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
  '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
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

// Detects lead routing intent from free text.
// Returns a LEAD_TYPE or null (no lead needed).
// "تفسير" alone is intentionally excluded — test-explanation questions should not trigger lead capture.
function detectLeadTypeFromText(rawText) {
  const text = (rawText || '').toLowerCase();
  if (!text.trim()) return null;

  if (/(حجز|موعد|booking|appointment|book)/i.test(text)) return LEAD_TYPES.BOOKING;
  if (/(نتيجة|نتائج|result|results|تأخرت نتيجتي)/i.test(text)) return LEAD_TYPES.RESULTS;
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
  const [isSending, setIsSending] = useState(false);
  const [sessionConversationId, setSessionConversationId] = useState(null);
  const [awaitingPhone, setAwaitingPhone] = useState(false);
  // Prevents asking for phone more than once per session after a lead is captured
  const [leadCaptured, setLeadCaptured] = useState(false);
  const [pendingLeadType, setPendingLeadType] = useState(null);
  const [leadContext, setLeadContext] = useState({
    latestUserQuestion: '',
    latestAssistantReply: '',
    lastConversationId: null,
  });
  const [messages, setMessages] = useState(() => [
    { id: 'welcome', role: 'assistant', text: WELCOME_MESSAGE },
  ]);
  const messageCounterRef = useRef(1);
  const messagesContainerRef = useRef(null);
  const { addLead, newLeadsCount } = usePreviewLeads();

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [messages, isOpen]);

  const sendMessage = async (rawText) => {
    const text = (rawText || '').trim();
    if (!text || isSending) return;

    const userId = `msg_${messageCounterRef.current++}`;
    setMessages((prev) => [...prev, { id: userId, role: 'user', text }]);
    setInput('');
    setIsOpen(true);

    // Phone number capture mode
    if (awaitingPhone) {
      if (!isLikelyPhone(text)) {
        const invalidId = `msg_${messageCounterRef.current++}`;
        setMessages((prev) => [
          ...prev,
          { id: invalidId, role: 'assistant', text: LEAD_PHONE_INVALID_MESSAGE },
        ]);
        return;
      }

      const capturedLead = {
        phone: normalizePhone(text),
        leadType: pendingLeadType || LEAD_TYPES.CUSTOMER_SERVICE,
        latestUserQuestion: leadContext.latestUserQuestion || text,
        latestAssistantReply: leadContext.latestAssistantReply || '',
        conversationId: leadContext.lastConversationId || null,
        createdAt: new Date().toISOString(),
      };
      addLead(capturedLead);
      setLeadCaptured(true);
      setAwaitingPhone(false);
      setPendingLeadType(null);

      const confirmId = `msg_${messageCounterRef.current++}`;
      setMessages((prev) => [
        ...prev,
        { id: confirmId, role: 'assistant', text: LEAD_CONFIRMATION_MESSAGE },
      ]);
      return;
    }

    // Normal message — send to backend
    const typingId = `typing_${messageCounterRef.current++}`;
    setMessages((prev) => [
      ...prev,
      { id: typingId, role: 'assistant', text: TYPING_MESSAGE, isTyping: true },
    ]);
    setIsSending(true);

    try {
      const { data } = await api.post('/api/chat', {
        message: text,
        include_knowledge: true,
        ...(sessionConversationId ? { conversation_id: sessionConversationId } : {}),
      });

      const assistantText =
        (data?.reply || data?.response || '').trim() || CONNECTIVITY_ERROR_MESSAGE;
      const assistantId = data?.message_id || `msg_${messageCounterRef.current++}`;
      const responseConversationId = data?.conversation_id || null;

      // Pin the conversation_id for the rest of this session so the backend
      // can maintain conversation state (phone capture, CTA suppression, etc.).
      if (responseConversationId && !sessionConversationId) {
        setSessionConversationId(responseConversationId);
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === typingId ? { id: assistantId, role: 'assistant', text: assistantText } : m
        )
      );

      // Lead routing: detect intent from user text first, then fall back to assistant reply.
      // Only ask for phone once per session (!leadCaptured) and not while already awaiting.
      const leadTypeFromFlow =
        detectLeadTypeFromText(text) || detectLeadTypeFromText(assistantText);

      if (leadTypeFromFlow && !awaitingPhone && !leadCaptured) {
        setPendingLeadType(leadTypeFromFlow);
        setAwaitingPhone(true);
        setLeadContext({
          latestUserQuestion: text,
          latestAssistantReply: assistantText,
          lastConversationId: responseConversationId,
        });
        const askPhoneId = `msg_${messageCounterRef.current++}`;
        setMessages((prev) => [
          ...prev,
          { id: askPhoneId, role: 'assistant', text: getLeadPhoneMessage(leadTypeFromFlow) },
        ]);
      }
    } catch (error) {
      console.error('Preview widget message send failed:', error);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === typingId
            ? { id: `err_${messageCounterRef.current++}`, role: 'assistant', text: CONNECTIVITY_ERROR_MESSAGE }
            : m
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
      {/*
        ================================================================
        FILLER SECTIONS — kept as comments for reference / internal demos.
        Do NOT restore these for the customer-facing widget page.
        ================================================================

        <main className="wareed-widget-preview__hero">
          <div className="wareed-widget-preview__hero-content">
            <p className="wareed-widget-preview__eyebrow">Wareed Labs Preview</p>
            <h1>معاينة ويدجت وريد AI</h1>
            <p>
              نموذج واجهة محلي لتجربة زر المساعد الذكي والشات العائم،
              بدون أي تعديل على التكامل الإنتاجي الحالي.
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
          <article className="wareed-widget-preview__card">
            <h2>معاينة داخلية</h2>
            <p>هذه الصفحة مخصصة لاختبار شكل و سلوك ويدجت وريد AI قبل ربطه بالموقع الإنتاجي.</p>
          </article>
          <article className="wareed-widget-preview__card">
            <h2>تجربة تفاعل عربية</h2>
            <p>الواجهة هنا RTL بالكامل مع رسائل تجريبية فقط لتأكيد تجربة الاستخدام.</p>
          </article>
          <article className="wareed-widget-preview__card">
            <h2>قابلية الدمج لاحقاً</h2>
            <p>بعد اعتماد الشكل النهائي، نقدر ننقل نفس المكون لواجهة الموقع الفعلية بشكل آمن.</p>
          </article>
        </section>

        <section className="wareed-widget-preview__lead-debug">
          <h2>آخر Lead (Preview Only)</h2>
          ...lead debug grid...
        </section>

        — Ghost multi-channel icons (placeholder; restore when channel stack is ready) —
        <div className="wareed-widget-preview__floating-stack" aria-hidden="true">
          <button type="button" className="wareed-widget-preview__ghost-icon">تطبيق وريد</button>
          <button type="button" className="wareed-widget-preview__ghost-icon">واتساب</button>
          <button type="button" className="wareed-widget-preview__ghost-icon">اتصال</button>
        </div>
        ================================================================
      */}

      {/* Floating AI toggle button */}
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

      {/* Chat panel */}
      {isOpen && (
        <aside
          id="wareed-ai-chat-panel"
          className="wareed-widget-preview__chat-panel"
          aria-label="نافذة دردشة وريد AI"
        >
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
