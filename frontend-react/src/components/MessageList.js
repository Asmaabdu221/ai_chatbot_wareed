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

const MessageList = ({
  messages,
  isSending,
  isFetching,
  error,
  hasConversation,
  onSuggestedPromptClick,
  userName = 'مستخدم',
}) => {
  const messagesEndRef = useRef(null);
  const [speakingId, setSpeakingId] = useState(null);
  const listRef = useRef(null);
  const nearBottomRef = useRef(true);
  const prevLengthRef = useRef(0);
  const prevFirstIdRef = useRef(null);
  const prevScrollHeightRef = useRef(0);
  const [showNewMessages, setShowNewMessages] = useState(false);

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

  return (
    <div
      className={`message-list ${isFetching ? 'is-fetching' : ''}`}
      ref={listRef}
      onScroll={updateNearBottom}
    >
      {messages.length === 0 && !isSending && !isFetching && !hasConversation && (
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

      {messages.length === 0 && !isSending && !isFetching && hasConversation && (
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
