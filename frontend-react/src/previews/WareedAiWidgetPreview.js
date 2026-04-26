import React, { useEffect, useRef, useState } from 'react';
import api from '../services/api';
import './WareedAiWidgetPreview.css';

const WELCOME_MESSAGE = `Ø­ÙŠØ§Ùƒ Ø§Ù„Ù„Ù‡ ÙÙŠ Ù…Ø®ØªØ¨Ø±Ø§Øª ÙˆØ±ÙŠØ¯ Ø§Ù„Ø·Ø¨ÙŠØ©
Ø£Ù†Ø§ Wareed AIØŒ Ù…Ø³Ø§Ø¹Ø¯Ùƒ Ø§Ù„Ø°ÙƒÙŠ.
Ø£Ù‚Ø¯Ø± Ø£Ø³Ø§Ø¹Ø¯Ùƒ ÙÙŠ Ø§Ù„Ø§Ø³ØªÙØ³Ø§Ø± Ø¹Ù† Ø§Ù„ØªØ­Ø§Ù„ÙŠÙ„ØŒ Ø§Ù„Ù†ØªØ§Ø¦Ø¬ØŒ Ø§Ù„ÙØ±ÙˆØ¹ØŒ ÙˆØ§Ù„Ø®Ø¯Ù…Ø§Øª.
ØªÙØ¶Ù„ ÙƒÙŠÙ Ø£Ù‚Ø¯Ø± Ø£Ø®Ø¯Ù…ÙƒØŸ`;

const QUICK_ACTIONS = [
  { label: 'Ø§Ø³Ø£Ù„ Ø¹Ù† ØªØ­Ù„ÙŠÙ„', text: 'Ø£Ø¨ØºÙ‰ Ø£Ø³Ø£Ù„ Ø¹Ù† ØªØ­Ù„ÙŠÙ„' },
  { label: 'Ø§Ø¹Ø±Ù Ø§Ù„ÙØ±ÙˆØ¹', text: 'Ø£Ø¨ØºÙ‰ Ø£Ø¹Ø±Ù Ø§Ù„ÙØ±ÙˆØ¹' },
  { label: 'ØªÙØ³ÙŠØ± Ù†ØªÙŠØ¬Ø©', text: 'Ø¹Ù†Ø¯ÙŠ Ù†ØªÙŠØ¬Ø© ÙˆØ£Ø¨ØºÙ‰ ØªÙØ³ÙŠØ±' },
  { label: 'ØªÙˆØ§ØµÙ„ Ù…Ø¹Ù†Ø§', text: 'Ø£Ø¨ØºÙ‰ Ø£ØªÙˆØ§ØµÙ„ Ù…Ø¹ Ø®Ø¯Ù…Ø© Ø§Ù„Ø¹Ù…Ù„Ø§Ø¡' },
];

const CONNECTIVITY_ERROR_MESSAGE = 'Ø­ØµÙ„Øª Ù…Ø´ÙƒÙ„Ø© Ù…Ø¤Ù‚ØªØ© ÙÙŠ Ø§Ù„Ø§ØªØµØ§Ù„ØŒ Ø­Ø§ÙˆÙ„ Ù…Ø±Ø© Ø£Ø®Ø±Ù‰ Ø¨Ø¹Ø¯ Ù‚Ù„ÙŠÙ„.';
const TYPING_MESSAGE = 'Ø¬Ø§Ø±ÙŠ Ø§Ù„ÙƒØªØ§Ø¨Ø©...';

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
            {part}
          </a>
        );
      }
      URL_REGEX.lastIndex = 0;
      return <React.Fragment key={`text-${lineIndex}-${partIndex}`}>{part}</React.Fragment>;
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
        <span className="wareed-widget-preview__ai-dot" />
        <span>Wareed AI</span>
      </button>

      {isOpen && (
        <aside
          id="wareed-ai-chat-panel"
          className="wareed-widget-preview__chat-panel"
          aria-label="Ù†Ø§ÙØ°Ø© Ø¯Ø±Ø¯Ø´Ø© ÙˆØ±ÙŠØ¯ AI"
        >
          <header className="wareed-widget-preview__chat-header">
            <div className="wareed-widget-preview__brand-text">
              <h3>Wareed AI</h3>
              <p>Ø§Ù„Ù…Ø³Ø§Ø¹Ø¯ Ø§Ù„Ø°ÙƒÙŠ</p>
            </div>
            <button
              type="button"
              className="wareed-widget-preview__header-close"
              onClick={() => setIsOpen(false)}
              aria-label="Ø¥ØºÙ„Ø§Ù‚"
            >
              Ø¥ØºÙ„Ø§Ù‚
            </button>
          </header>

          <div className="wareed-widget-preview__quick-actions" role="list" aria-label="Ø¥Ø¬Ø±Ø§Ø¡Ø§Øª Ø³Ø±ÙŠØ¹Ø©">
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
              placeholder="Ø§ÙƒØªØ¨ Ø³Ø¤Ø§Ù„Ùƒ Ù‡Ù†Ø§..."
              aria-label="Ø§ÙƒØªØ¨ Ø³Ø¤Ø§Ù„Ùƒ Ù‡Ù†Ø§"
              disabled={isSending}
            />
            <button
              type="submit"
              className="wareed-widget-preview__send-button"
              disabled={isSending}
              aria-label="Ø¥Ø±Ø³Ø§Ù„"
            >
              {isSending ? '...' : 'âž¤'}
            </button>
          </form>
        </aside>
      )}
    </div>
  );
}
