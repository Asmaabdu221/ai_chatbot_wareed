import React, { useEffect, useRef, useState } from 'react';
import api from './services/api';
import './WareedAiWidgetPreview.css';

const WELCOME_MESSAGE = `حياك الله في مختبرات وريد الطبية
أنا Wareed AI، مساعدك الذكي.
أقدر أساعدك في الاستفسار عن التحاليل، النتائج، الفروع، والخدمات.
تفضل كيف أقدر أخدمك؟`;

const QUICK_ACTIONS = [
  { icon: '🧪', label: 'اسأل عن تحليل', text: 'أبغى أسأل عن تحليل' },
  { icon: '📍', label: 'اعرف الفروع', text: 'أبغى أعرف الفروع' },
  { icon: '🧾', label: 'تفسير نتيجة', text: 'عندي نتيجة وأبغى تفسير' },
  { icon: '🎧', label: 'تواصل معنا', text: 'أبغى أتواصل مع خدمة العملاء' },
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

      console.info('[Widget continuity] /api/chat response IDs', {
        user_id: data?.user_id || null,
        conversation_id: data?.conversation_id || null,
      });

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
      <button
        type="button"
        className="wareed-widget-preview__ai-button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-controls="wareed-ai-chat-panel"
      >
        <span className="wareed-widget-preview__ai-dot" />
        <span>Wareed AI</span>
      </button>

      {isOpen && (
        <aside
          id="wareed-ai-chat-panel"
          className="wareed-widget-preview__chat-panel"
          aria-label="نافذة دردشة وريد AI"
        >
          <header className="wareed-widget-preview__chat-header">
            <div className="wareed-widget-preview__brand-wrap">
              <div className="wareed-widget-preview__avatar" aria-hidden="true">W</div>
              <div className="wareed-widget-preview__brand-text">
                <h3>Wareed AI</h3>
                <p>المساعد الذكي</p>
                <div className="wareed-widget-preview__status">
                  <span className="wareed-widget-preview__status-dot" />
                  <span>متصل الآن</span>
                </div>
              </div>
            </div>
            <button type="button" onClick={() => setIsOpen(false)} aria-label="إغلاق">
              إغلاق
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
                <span className="wareed-widget-preview__quick-icon" aria-hidden="true">
                  {action.icon}
                </span>
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
                  <p>{message.text}</p>
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
            <button type="submit" disabled={isSending} aria-label="إرسال">
              {isSending ? '...' : '➤'}
            </button>
          </form>
        </aside>
      )}
    </div>
  );
}
