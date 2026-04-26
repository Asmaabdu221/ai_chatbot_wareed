import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import './DashboardChatWidgetV2.css';

const WELCOME_TEXT = 'مرحبًا بك في تجربة البوت الذكي. اكتب سؤالك وسأقوم بالرد مباشرة.';
const TYPING_TEXT = 'جاري الكتابة...';
const ERROR_TEXT = 'تعذر الاتصال حاليًا، حاول مرة أخرى بعد قليل.';

const USER_ID_KEY = 'wareed_dashboard_widget_user_id';
const CONVERSATION_ID_KEY = 'wareed_dashboard_widget_conversation_id';
const UUID_REGEX =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function createUuid() {
  if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
    return window.crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const random = Math.floor(Math.random() * 16);
    const value = char === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function getOrCreateUserId() {
  if (typeof window === 'undefined') return null;
  const current = window.localStorage.getItem(USER_ID_KEY);
  if (current && UUID_REGEX.test(current)) return current;
  const generated = createUuid();
  window.localStorage.setItem(USER_ID_KEY, generated);
  return generated;
}

function getConversationId() {
  if (typeof window === 'undefined') return null;
  const current = window.localStorage.getItem(CONVERSATION_ID_KEY);
  return current && UUID_REGEX.test(current) ? current : null;
}

function setConversationId(conversationId) {
  if (typeof window === 'undefined') return;
  if (conversationId && UUID_REGEX.test(conversationId)) {
    window.localStorage.setItem(CONVERSATION_ID_KEY, conversationId);
  } else {
    window.localStorage.removeItem(CONVERSATION_ID_KEY);
  }
}

function renderText(text) {
  const value = String(text || '');
  const lines = value.split('\n');
  return lines.map((line, index) => (
    <React.Fragment key={`line-${index}`}>
      {line}
      {index < lines.length - 1 ? <br /> : null}
    </React.Fragment>
  ));
}

export default function DashboardChatWidgetV2() {
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [sessionUserId, setSessionUserId] = useState(() => getOrCreateUserId());
  const [sessionConversationId, setSessionConversationId] = useState(() => getConversationId());
  const [messages, setMessages] = useState([
    { id: 'welcome', role: 'assistant', text: WELCOME_TEXT },
  ]);
  const counterRef = useRef(1);
  const listRef = useRef(null);

  useEffect(() => {
    const node = listRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [messages, isOpen]);

  const sendMessage = async (raw) => {
    const text = String(raw || '').trim();
    if (!text || isSending) return;

    const userMessageId = `u_${counterRef.current++}`;
    const typingId = `t_${counterRef.current++}`;

    setMessages((prev) => [...prev, { id: userMessageId, role: 'user', text }]);
    setMessages((prev) => [...prev, { id: typingId, role: 'assistant', text: TYPING_TEXT, typing: true }]);
    setInput('');
    setIsSending(true);

    try {
      const userId = getOrCreateUserId();
      const conversationId = getConversationId();

      if (userId && userId !== sessionUserId) setSessionUserId(userId);
      if (conversationId && conversationId !== sessionConversationId) {
        setSessionConversationId(conversationId);
      }

      const { data } = await api.post('/api/chat', {
        message: text,
        include_knowledge: true,
        ...(userId ? { user_id: userId } : {}),
        ...(conversationId ? { conversation_id: conversationId } : {}),
      });

      if (data?.user_id && UUID_REGEX.test(data.user_id)) {
        window.localStorage.setItem(USER_ID_KEY, data.user_id);
        setSessionUserId(data.user_id);
      }

      if (data?.conversation_id && UUID_REGEX.test(data.conversation_id)) {
        setConversationId(data.conversation_id);
        setSessionConversationId(data.conversation_id);
      }

      const reply = String(data?.reply || data?.response || '').trim() || ERROR_TEXT;
      const assistantId = data?.message_id || `a_${counterRef.current++}`;

      setMessages((prev) =>
        prev.map((message) =>
          message.id === typingId ? { id: assistantId, role: 'assistant', text: reply } : message
        )
      );
    } catch (error) {
      setMessages((prev) =>
        prev.map((message) =>
          message.id === typingId
            ? { id: `e_${counterRef.current++}`, role: 'assistant', text: ERROR_TEXT }
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
    <div className="dashboard-chat-widget-v2" dir="rtl" lang="ar">
      <button
        type="button"
        className="dashboard-chat-widget-v2__trigger"
        aria-expanded={isOpen}
        onClick={() => setIsOpen((prev) => !prev)}
        title="Wareed AI"
      >
        <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M12 3l1.3 2.9L16 7.2l-2.7 1.3L12 11.5l-1.3-3L8 7.2l2.7-1.3L12 3Z" />
          <path d="M18.5 11.2l.8 1.8 1.7.8-1.7.8-.8 1.8-.8-1.8-1.8-.8 1.8-.8.8-1.8Z" />
          <path d="M6 12.5l1 2.1 2 .9-2 .9-1 2.1-.9-2.1-2-.9 2-.9.9-2.1Z" />
        </svg>
      </button>

      {isOpen && (
        <aside className="dashboard-chat-widget-v2__panel" aria-label="تجربة البوت الذكي">
          <header className="dashboard-chat-widget-v2__header">
            <h3>Wareed AI</h3>
            <button
              type="button"
              className="dashboard-chat-widget-v2__close"
              onClick={() => setIsOpen(false)}
              aria-label="إغلاق"
            >
              ×
            </button>
          </header>

          <div ref={listRef} className="dashboard-chat-widget-v2__messages">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`dashboard-chat-widget-v2__bubble dashboard-chat-widget-v2__bubble--${message.role} dashboard-chat-widget-v2__bubble--enter`}
              >
                {renderText(message.text)}
              </div>
            ))}
          </div>

          <form className="dashboard-chat-widget-v2__form" onSubmit={onSubmit}>
            <div className="dashboard-chat-widget-v2__input-wrap">
              <input
                type="text"
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="اكتب رسالتك..."
                disabled={isSending}
              />
              <button type="submit" disabled={isSending || !input.trim()} aria-label="إرسال">
                <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
                  <path d="M4 12h14" />
                  <path d="M13 5l7 7-7 7" />
                </svg>
              </button>
            </div>
          </form>
        </aside>
      )}
    </div>
  );
}
