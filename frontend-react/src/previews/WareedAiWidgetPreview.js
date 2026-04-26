import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import './WareedAiWidgetPreview.css';

const WELCOME_MESSAGE = `حياك الله في مختبرات وريد الطبية
أنا Wareed AI، مساعدك الذكي.
• الاستفسار عن التحاليل ونتائج التقارير وفروعنا ومواعيدنا
تفضل، كيف أقدر أخدمك اليوم؟`;

const QUICK_ACTIONS = [
  { label: 'اسأل عن تحليل', text: 'أبغى أسأل عن تحليل' },
  { label: 'اعرف الفروع', text: 'أبغى أعرف الفروع' },
  { label: 'تفسير نتيجة', text: 'عندي نتيجة وأبغى تفسير' },
  { label: 'تواصل معنا', text: 'أبغى أتواصل مع خدمة العملاء' },
];

const CONNECTIVITY_ERROR_MESSAGE = 'حصلت مشكلة مؤقتة في الاتصال، حاول مرة أخرى بعد قليل.';
const TYPING_MESSAGE = 'جاري الكتابة...';

const WIDGET_USER_ID_STORAGE_KEY = 'wareed_preview_widget_user_id';
const WIDGET_CONVERSATION_ID_STORAGE_KEY = 'wareed_preview_widget_conversation_id';
const UUID_V4_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const URL_REGEX = /(https?:\/\/[^\s]+|www\.[^\s]+)/gi;

function generateWidgetUserId() {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }

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

function setStoredUserId(userId) {
  if (typeof window === 'undefined') return;
  if (userId && UUID_V4_REGEX.test(userId)) {
    window.localStorage.setItem(WIDGET_USER_ID_STORAGE_KEY, userId);
  }
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

function normalizeUrl(url) {
  if (!url) return '';
  return /^https?:\/\//i.test(url) ? url : `https://${url}`;
}

function renderMessageTextWithLinks(text) {
  const raw = String(text || '');
  const lines = raw.split('\n');
  const branchRegex = /(\u0641\u0631\u0639\s+[^\n،,.]+)/g;

  return lines.map((line, lineIndex) => {
    const parts = line.split(URL_REGEX);
    const content = parts.map((part, partIndex) => {
      if (!part) return null;
      if (URL_REGEX.test(part)) {
        URL_REGEX.lastIndex = 0;
        const href = normalizeUrl(part);
        return (
          <a
            key={`link-${lineIndex}-${partIndex}`}
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="wareed-widget-preview__message-link"
          >
            فتح الموقع
          </a>
        );
      }
      URL_REGEX.lastIndex = 0;
      const branchParts = part.split(branchRegex);
      return (
        <React.Fragment key={`text-${lineIndex}-${partIndex}`}>
          {branchParts.map((chunk, chunkIndex) =>
            chunk.match(/^\u0641\u0631\u0639\s+/) ? (
              <strong key={`branch-${lineIndex}-${partIndex}-${chunkIndex}`} className="wareed-widget-preview__branch-name">
                {chunk}
              </strong>
            ) : (
              <React.Fragment key={`chunk-${lineIndex}-${partIndex}-${chunkIndex}`}>{chunk}</React.Fragment>
            )
          )}
        </React.Fragment>
      );
    });

    return (
      <React.Fragment key={`line-${lineIndex}`}>
        {content}
        {lineIndex < lines.length - 1 ? <br /> : null}
      </React.Fragment>
    );
  });
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

      if (data?.user_id && UUID_V4_REGEX.test(data.user_id)) {
        setStoredUserId(data.user_id);
        setSessionUserId(data.user_id);
      }

      if (data?.conversation_id && UUID_V4_REGEX.test(data.conversation_id)) {
        setStoredConversationId(data.conversation_id);
        setSessionConversationId(data.conversation_id);
      }

      const leadCaptured = Boolean(data?.lead_captured || data?.conversation_closed);
      if (leadCaptured) {
        console.info('[Widget session] lead captured, clearing conversation_id', {
          conversation_id: data?.conversation_id || null,
          lead_id: data?.lead_id || null,
        });
        setStoredConversationId(null);
        setSessionConversationId(null);
      }

      console.info('[Widget continuity] /api/chat response IDs', {
        user_id: data?.user_id || null,
        conversation_id: data?.conversation_id || null,
        lead_captured: Boolean(data?.lead_captured),
      });

      setMessages((prev) => {
        const next = prev.map((m) =>
          m.id === typingId ? { id: assistantId, role: 'assistant', text: assistantText } : m
        );

        const last = next[next.length - 1];
        const beforeLast = next[next.length - 2];

        if (
          last &&
          beforeLast &&
          last.role === 'assistant' &&
          beforeLast.role === 'assistant' &&
          String(last.text || '').trim() === String(beforeLast.text || '').trim()
        ) {
          console.log('[Widget] duplicate assistant message prevented');
          return next.slice(0, -1);
        }

        return next;
      });
    } catch (error) {
      console.error('Preview widget message send failed:', error);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === typingId
            ? {
                id: `err_${messageCounterRef.current++}`,
                role: 'assistant',
                text: CONNECTIVITY_ERROR_MESSAGE,
              }
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
      <div className="wareed-widget-preview__surface" />

      <button
        type="button"
        className="wareed-widget-preview__ai-button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-controls="wareed-ai-chat-panel"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className="wareed-widget-preview__ai-icon">
          <path d="M12 3l1.3 2.9L16 7.2l-2.7 1.3L12 11.5l-1.3-3L8 7.2l2.7-1.3L12 3Z" />
          <path d="M18.5 11.2l.8 1.8 1.7.8-1.7.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8.8-1.8Z" />
          <path d="M6 12.5l1 2.1 2 .9-2 .9-1 2.1-.9-2.1-2-.9 2-.9.9-2.1Z" />
        </svg>
        <span>Wareed AI</span>
      </button>

      <aside
        id="wareed-ai-chat-panel"
        className={`wareed-widget-preview__chat-panel ${isOpen ? 'wareed-widget-preview__chat-panel--open' : 'wareed-widget-preview__chat-panel--closed'}`}
        aria-label="نافذة دردشة وريد AI"
        aria-hidden={!isOpen}
      >
          <header className="wareed-widget-preview__chat-header">
            <div className="wareed-widget-preview__brand-text">
              <h3>Wareed AI</h3>
              <p>المساعد الذكي</p>
            </div>
            <button
              type="button"
              className="wareed-widget-preview__header-close"
              onClick={() => setIsOpen(false)}
              aria-label="إغلاق"
            >
              ×
            </button>
          </header>

          <div className="wareed-widget-preview__quick-actions" role="list" aria-label="إجراءات سريعة">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.text}
                type="button"
                onClick={() => sendMessage(action.text)}
                role="listitem"
                disabled={isSending}
                className="wareed-widget-preview__quick-card"
              >
                <span className="wareed-widget-preview__quick-label">{action.label}</span>
              </button>
            ))}
          </div>

          <div ref={messagesContainerRef} className="wareed-widget-preview__messages">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`wareed-widget-preview__message-row wareed-widget-preview__message-row--${message.role}`}
              >
                <div
                  className={`wareed-widget-preview__message wareed-widget-preview__message--${message.role}${
                    message.isTyping ? ' wareed-widget-preview__message--typing' : ''
                  }`}
                >
                  <p>{renderMessageTextWithLinks(message.text)}</p>
                </div>
              </div>
            ))}
          </div>

          <form className="wareed-widget-preview__composer" onSubmit={onSubmit}>
            <input
              type="text"
              value={input}
              onChange={(event) => setInput(event.target.value)}
              placeholder="اكتب سؤالك هنا..."
              aria-label="اكتب سؤالك هنا"
              disabled={isSending}
            />
            <button
              type="submit"
              className="wareed-widget-preview__send-button"
              disabled={isSending}
              aria-label="إرسال"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M4 12h14" />
                <path d="M13 5l7 7-7 7" />
              </svg>
            </button>
          </form>
      </aside>
    </div>
  );
}
