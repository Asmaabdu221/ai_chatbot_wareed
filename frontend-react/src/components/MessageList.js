import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import Message from './Message';
import TypingIndicator from './TypingIndicator';
import { formatArabicDate, formatArabicText } from '../utils/arabicFormatters';
import './MessageList.css';

const SUGGESTED_PROMPTS = [
  'ما هي خدمات وريد الصحية؟',
  'كم سعر تحليل فيتامين د؟',
  'ما هو رقم التواصل؟',
  'ما هي التحاليل الجينية المتوفرة؟',
];

const WELCOME_PRIMARY_ACTIONS = [
  { key: 'booking', label: '\u0627\u062d\u062c\u0632 \u062a\u062d\u0644\u064a\u0644 \u0623\u0648 \u0628\u0627\u0642\u0629' },
  { key: 'specific_test', label: '\u0627\u0633\u0623\u0644 \u0639\u0646 \u062a\u062d\u0644\u064a\u0644 \u0645\u0639\u064a\u0651\u0646' },
  { key: 'explain_results', label: '\u0634\u0631\u062d \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0644\u064a\u0644' },
  { key: 'services', label: '\u0627\u0644\u062e\u062f\u0645\u0627\u062a \u0648\u0627\u0644\u0641\u0631\u0648\u0639 \u0648\u0627\u0644\u0633\u062d\u0628 \u0627\u0644\u0645\u0646\u0632\u0644\u064a' },
];

const WELCOME_SECONDARY_ACTIONS = {
  booking: [
    {
      label: '\u0627\u0628\u062f\u0623 \u0627\u0644\u0637\u0644\u0628',
      message: '\u0623\u0628\u063a\u0649 \u0623\u062d\u062c\u0632 \u062a\u062d\u0644\u064a\u0644 \u0623\u0648 \u0628\u0627\u0642\u0629.',
    },
    {
      label: '\u0627\u0637\u0644\u0628 \u062e\u062f\u0645\u0629 \u0633\u062d\u0628 \u0645\u0646\u0632\u0644\u064a',
      message: '\u0623\u0628\u063a\u0649 \u062e\u062f\u0645\u0629 \u0633\u062d\u0628 \u0645\u0646\u0632\u0644\u064a (\u0648\u0631\u064a\u062f \u0643\u064a\u0631).',
    },
    { label: '\u0643\u064a\u0641 \u0623\u062d\u062c\u0632 \u0645\u0648\u0639\u062f\u061f', message: '\u0643\u064a\u0641 \u0623\u062d\u062c\u0632 \u0645\u0648\u0639\u062f\u061f' },
  ],
  specific_test: [
    {
      label: '\u0627\u0628\u062f\u0623 \u0627\u0644\u0633\u0624\u0627\u0644',
      message: '\u0623\u0628\u063a\u0649 \u0623\u0633\u0623\u0644 \u0639\u0646 \u062a\u062d\u0644\u064a\u0644 \u0645\u0639\u064a\u0651\u0646.',
    },
    {
      label: '\u0627\u0644\u062a\u062d\u0636\u064a\u0631 \u0642\u0628\u0644 \u0627\u0644\u062a\u062d\u0644\u064a\u0644',
      message: '\u0627\u064a\u0634 \u0644\u0627\u0632\u0645 \u0623\u0633\u0648\u064a \u0642\u0628\u0644 \u062a\u062d\u0644\u064a\u0644 \u0641\u064a\u062a\u0627\u0645\u064a\u0646 \u062f\u061f',
    },
  ],
  explain_results: [
    {
      label: '\u0627\u0628\u062f\u0623 \u0627\u0644\u0634\u0631\u062d',
      message: '\u0623\u0628\u063a\u0649 \u0634\u0631\u062d \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0644\u064a\u0644. \u0648\u0634 \u0627\u0644\u0645\u0637\u0644\u0648\u0628 \u0623\u0631\u0641\u0642\u061f',
    },
  ],
  services: [
    {
      label: '\u0627\u0628\u062f\u0623 \u0627\u0644\u0637\u0644\u0628',
      message: '\u0623\u0628\u063a\u0649 \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0639\u0646 \u0627\u0644\u0641\u0631\u0648\u0639 \u0648\u0627\u0644\u062e\u062f\u0645\u0627\u062a \u0648\u0627\u0644\u0633\u062d\u0628 \u0627\u0644\u0645\u0646\u0632\u0644\u064a.',
    },
    { label: '\u0645\u062a\u0649 \u0633\u0627\u0639\u0627\u062a \u0627\u0644\u062f\u0648\u0627\u0645\u061f', message: '\u0645\u062a\u0649 \u0633\u0627\u0639\u0627\u062a \u0627\u0644\u062f\u0648\u0627\u0645\u061f' },
    { label: '\u0637\u0631\u0642 \u0627\u0644\u062f\u0641\u0639', message: '\u0648\u0634 \u0637\u0631\u0642 \u0627\u0644\u062f\u0641\u0639 \u0627\u0644\u0645\u062a\u0627\u062d\u0629\u061f' },
  ],
};

const MessageList = ({
  messages,
  isSending,
  isFetching,
  error,
  hasConversation,
  onSuggestedPromptClick,
  userName = 'مستخدم',
  onReply,
  onDelete,
  onPin,
  pinnedMessageIds = [],
}) => {
  const messagesEndRef = useRef(null);
  const [speakingId, setSpeakingId] = useState(null);
  const listRef = useRef(null);
  const nearBottomRef = useRef(true);
  const prevLengthRef = useRef(0);
  const prevFirstIdRef = useRef(null);
  const prevScrollHeightRef = useRef(0);
  const [showNewMessages, setShowNewMessages] = useState(false);
  const [selectedWelcomeSection, setSelectedWelcomeSection] = useState(null);

  const scrollToBottom = (behavior = 'smooth') => {
    messagesEndRef.current?.scrollIntoView({ behavior });
  };

  const updateNearBottom = () => {
    const list = listRef.current;
    if (!list) return;
    const threshold = 140;
    const distance = list.scrollHeight - list.scrollTop - list.clientHeight;
    const isNearBottom = distance < threshold;
    nearBottomRef.current = isNearBottom;
    if (isNearBottom) setShowNewMessages(false);
  };

  useEffect(() => {
    if (isSending && nearBottomRef.current) {
      scrollToBottom();
      return;
    }
    const hadMore = messages.length > prevLengthRef.current;
    if (hadMore && !nearBottomRef.current) {
      setShowNewMessages(true);
    } else if (nearBottomRef.current) {
      scrollToBottom();
    }
    prevLengthRef.current = messages.length;
  }, [messages, isSending]);

  useEffect(() => {
    updateNearBottom();
  }, []);

  useEffect(() => {
    return () => {
      if (typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  useEffect(() => {
    if (messages.length > 0 && selectedWelcomeSection !== null) {
      setSelectedWelcomeSection(null);
    }
  }, [messages.length, selectedWelcomeSection]);

  useLayoutEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const prevFirstId = prevFirstIdRef.current;
    const nextFirstId = messages[0]?.id ?? null;
    if (prevFirstId && nextFirstId && prevFirstId !== nextFirstId && !nearBottomRef.current) {
      const heightDiff = list.scrollHeight - prevScrollHeightRef.current;
      if (heightDiff > 0) list.scrollTop += heightDiff;
    }
    prevScrollHeightRef.current = list.scrollHeight;
    prevFirstIdRef.current = nextFirstId;
  }, [messages]);

  const dayKey = (ts) => {
    if (!ts) return '';
    const d = new Date(ts);
    return d.toDateString();
  };

  const formatDay = (ts) => formatArabicDate(ts);

  const handleMessageAction = (action, message) => {
    if (action === 'reply') onReply(message);
    if (action === 'delete') onDelete(message.id);
    if (action === 'pin') onPin(message.id);
  };

  return (
    <div
      className={`message-list ${isFetching ? 'is-fetching' : ''}`}
      ref={listRef}
      onScroll={updateNearBottom}
    >
      {/* Ramadan Watermark */}
      <div
        className="ramadan-watermark"
        style={{ backgroundColor: '#f8fafc' }}
        aria-hidden="true"
      />
      {messages.length === 0 && !isSending && !isFetching && (
        <div className="welcome-screen arabic-text" dir="auto">
          <div className="welcome-card">
            <img src="/images/chat-welcome-icon.png" alt="" className="welcome-icon-img" aria-hidden="true" />
            <h3 className="welcome-greeting">{formatArabicText('\u0645\u0631\u062d\u0628\u064b\u0627 \u0628\u0643 \u0641\u064a \u0645\u062e\u062a\u0628\u0631\u0627\u062a \u0648\u0631\u064a\u062f \u0627\u0644\u0637\u0628\u064a\u0629')}</h3>
            <p className="welcome-trust-line">{formatArabicText('\u0645\u0639\u062a\u0645\u062f\u064a\u0646 \u0645\u0646 \u0633\u0628\u0627\u0647\u064a \u00b7 10M+ \u062a\u062d\u0644\u064a\u0644 \u00b7 \u0633\u062d\u0628 \u0645\u0646\u0632\u0644\u064a')}</p>
            <p className="welcome-subtitle">{formatArabicText('\u0643\u064a\u0641 \u0646\u0642\u062f\u0631 \u0646\u062e\u062f\u0645\u0643 \u0627\u0644\u064a\u0648\u0645\u061f')}</p>

            <div className="welcome-primary-actions">
              {WELCOME_PRIMARY_ACTIONS.map((action) => (
                <button
                  key={`welcome-primary-${action.key}`}
                  type="button"
                  className={`welcome-primary-button ${selectedWelcomeSection === action.key ? 'is-active' : ''}`}
                  dir="auto"
                  onClick={() => setSelectedWelcomeSection(action.key)}
                >
                  {formatArabicText(action.label)}
                </button>
              ))}
            </div>

            {selectedWelcomeSection && (
              <div className="welcome-secondary-actions">
                {WELCOME_SECONDARY_ACTIONS[selectedWelcomeSection].map((action, index) => (
                  <button
                    key={`welcome-secondary-${selectedWelcomeSection}-${index}`}
                    type="button"
                    className="welcome-chip"
                    dir="auto"
                    onClick={() => onSuggestedPromptClick?.(action.message)}
                    disabled={!onSuggestedPromptClick}
                  >
                    {formatArabicText(action.label)}
                  </button>
                ))}
                <button
                  type="button"
                  className="welcome-collapse-button"
                  onClick={() => setSelectedWelcomeSection(null)}
                >
                  {formatArabicText('\u0631\u062c\u0648\u0639')}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
      {false && messages.length === 0 && !isSending && !isFetching && !hasConversation && (
        <div className="welcome-screen arabic-text" dir="auto">
          <img src="/images/chat-welcome-icon.png" alt="" className="welcome-icon-img" aria-hidden="true" />
          <h3 className="welcome-greeting">
            {formatArabicText(`مرحباً ${userName} ! يمكنك كتابة استفسارك هنا :`)}
          </h3>
          <div className="suggested-prompts">
            {SUGGESTED_PROMPTS.map((text, index) => (
              <button
                key={`suggest-${index}`}
                type="button"
                className="prompt-card"
                dir="auto"
                onClick={() => onSuggestedPromptClick?.(text)}
                disabled={!onSuggestedPromptClick}
                aria-label={formatArabicText(text)}
              >
                {formatArabicText(text)}
              </button>
            ))}
          </div>
        </div>
      )}

      {false && messages.length === 0 && !isSending && !isFetching && hasConversation && (
        <div className="welcome-screen arabic-text" dir="auto">
          <img src="/images/chat-welcome-icon.png" alt="" className="welcome-icon-img" aria-hidden="true" />
          <h3>{formatArabicText('لا توجد رسائل بعد')}</h3>
          <p className="welcome-hint">
            {formatArabicText('ابدأ بكتابة رسالتك وسيظهر الرد هنا.')}
          </p>
          <div className="suggested-prompts">
            {SUGGESTED_PROMPTS.map((text, index) => (
              <button
                key={`suggest-new-${index}`}
                type="button"
                className="prompt-card"
                dir="auto"
                onClick={() => onSuggestedPromptClick?.(text)}
                disabled={!onSuggestedPromptClick}
                aria-label={formatArabicText(text)}
              >
                {formatArabicText(text)}
              </button>
            ))}
          </div>
        </div>
      )}

      {messages.length === 0 && (isFetching || isSending) && (
        <div className="skeleton-list">
          <div className="skeleton-bubble"></div>
          <div className="skeleton-bubble short"></div>
          <div className="skeleton-bubble"></div>
        </div>
      )}

      {(() => {
        let groupIndex = 0;
        return messages.map((message, index) => {
          const prev = messages[index - 1];
          const next = messages[index + 1];
          const currentTs = message.created_at || message.timestamp;
          const prevTs = prev ? (prev.created_at || prev.timestamp) : null;
          const showSeparator = !prev || dayKey(currentTs) !== dayKey(prevTs);
          const prevRole = prev?.role;
          const nextRole = next?.role;
          const isGrouped = prevRole === message.role;
          const isGroupEnd = nextRole !== message.role;
          if (!prev || prev.role !== message.role) groupIndex += 1;
          const isAltGroup = groupIndex % 2 === 0;
          return (
            <React.Fragment key={`${message.id || index}-${index}`}>
              {showSeparator && currentTs && (
                <div className="date-separator arabic-text" dir="auto">
                  {formatDay(currentTs)}
                </div>
              )}
              <Message
                message={message}
                showAvatar={isGroupEnd}
                showTimestamp={isGroupEnd}
                isGrouped={isGrouped}
                isAltGroup={isAltGroup}
                speakingId={speakingId}
                onSpeak={setSpeakingId}
                isPinned={pinnedMessageIds.includes(message.id)}
                onAction={(action) => handleMessageAction(action, message)}
              />
            </React.Fragment>
          );
        });
      })()}

      {error && (
        <div className="error-bubble arabic-text" dir="auto">
          ⚠️ {formatArabicText(error)}
        </div>
      )}

      {isSending && <TypingIndicator />}

      {isFetching && messages.length > 0 && (
        <div className="loading-overlay" aria-hidden="true">
          <div className="skeleton-bubble"></div>
          <div className="skeleton-bubble short"></div>
          <div className="skeleton-bubble"></div>
        </div>
      )}

      {showNewMessages && (
        <button
          type="button"
          className="new-messages-pill arabic-text"
          onClick={() => {
            setShowNewMessages(false);
            scrollToBottom('smooth');
          }}
        >
          ⬇ رسائل جديدة
        </button>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
};

export default MessageList;
