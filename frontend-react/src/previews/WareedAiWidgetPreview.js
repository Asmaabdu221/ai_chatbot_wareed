import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
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

const WIDGET_USER_ID_STORAGE_KEY = 'wareed_preview_widget_user_id';
const WIDGET_CONVERSATION_ID_STORAGE_KEY = 'wareed_preview_widget_conversation_id';
const UUID_V4_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function generateWidgetUserId() {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

  // Fallback UUID v4 generator for older browsers.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function getOrCreateWidgetUserId() {
  if (typeof window === 'undefined') return null;

  const existing = window.localStorage.getItem(WIDGET_USER_ID_STORAGE_KEY);
  if (existing && UUID_V4_REGEX.test(existing)) {
    return existing;
  }

  const generated = generateWidgetUserId();
  window.localStorage.setItem(WIDGET_USER_ID_STORAGE_KEY, generated);
  return generated;
}

function getStoredConversationId() {
  if (typeof window === 'undefined') return null;

  const existing = window.localStorage.getItem(WIDGET_CONVERSATION_ID_STORAGE_KEY);
  if (existing && UUID_V4_REGEX.test(existing)) {
    return existing;
  }

  return null;
}

function setStoredConversationId(conversationId) {
  if (typeof window === 'undefined') return;

  if (conversationId && UUID_V4_REGEX.test(conversationId)) {
    window.localStorage.setItem(WIDGET_CONVERSATION_ID_STORAGE_KEY, conversationId);
    return;
  }

  window.localStorage.removeItem(WIDGET_CONVERSATION_ID_STORAGE_KEY);
}

export default function WareedAiWidgetPreview() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sessionUserId, setSessionUserId] = useState(() => getOrCreateWidgetUserId());
  const [sessionConversationId, setSessionConversationId] = useState(() => getStoredConversationId());
  const [messages, setMessages] = useState(() => [
    { id: 'welcome', role: 'assistant', text: WELCOME_MESSAGE },
  ]);
  const messageCounterRef = useRef(1);
  const messagesContainerRef = useRef(null);

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

    const typingId = `typing_${messageCounterRef.current++}`;
    setMessages((prev) => [
      ...prev,
      { id: typingId, role: 'assistant', text: TYPING_MESSAGE, isTyping: true },
    ]);
    setIsSending(true);

    try {
      // Always read continuity IDs from storage at send time (state is only a UI mirror).
      const stableUserId = getOrCreateWidgetUserId();
      const stableConversationId = getStoredConversationId();

      if (stableUserId && stableUserId !== sessionUserId) {
        setSessionUserId(stableUserId);
      }
      if (stableConversationId && stableConversationId !== sessionConversationId) {
        setSessionConversationId(stableConversationId);
      }

      console.info('[Widget continuity] /api/chat payload IDs', {
        user_id: stableUserId || null,
        conversation_id: stableConversationId || null,
      });

      const { data } = await api.post('/api/chat', {
        message: text,
        include_knowledge: true,
        ...(stableUserId ? { user_id: stableUserId } : {}),
        ...(stableConversationId ? { conversation_id: stableConversationId } : {}),
      });

      const assistantText =
        (data?.reply || data?.response || '').trim() || CONNECTIVITY_ERROR_MESSAGE;
      const assistantId = data?.message_id || `msg_${messageCounterRef.current++}`;

      // Pin and persist conversation_id so continuity survives refresh/re-render.
      if (data?.conversation_id && UUID_V4_REGEX.test(data.conversation_id)) {
        setStoredConversationId(data.conversation_id);
        setSessionConversationId(data.conversation_id);
      }

      setMessages((prev) =>
        prev.map((m) =>
          m.id === typingId ? { id: assistantId, role: 'assistant', text: assistantText } : m
        )
      );
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
