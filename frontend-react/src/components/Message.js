import React, { useEffect, useRef, useState } from 'react';
import { formatArabicDate, formatArabicNumber } from '../utils/arabicFormatters';
import './Message.css';

/** Extract plain text for TTS (strip code blocks) */
const getTextForSpeech = (text) => {
  const parts = String(text || '').split('```');
  return parts
    .filter((_, i) => i % 2 === 0)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
};

const parseContent = (text) => {
  const parts = String(text || '').split('```');
  return parts.map((part, index) => {
    if (index % 2 === 1) {
      const [firstLine, ...rest] = part.split('\n');
      const lang = firstLine.trim().length <= 20 ? firstLine.trim() : '';
      const code = lang ? rest.join('\n') : part;
      return { type: 'code', content: code, lang };
    }
    return { type: 'text', content: part };
  });
};

const CodeBlock = ({ code, lang }) => {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch (_) {}
  };
  return (
    <div className="code-block">
      <div className="code-header">
        <span className="code-lang">{lang || 'code'}</span>
        <button className="code-copy" onClick={handleCopy}>
          نسخ
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
};

const Message = ({
  message,
  showAvatar = true,
  showTimestamp = true,
  isGrouped = false,
  isAltGroup = false,
  speakingId = null,
  onSpeak,
}) => {
  const { role, content, timestamp, created_at, id } = message;
  const isUser = role === 'user';
  const isSpeaking = !isUser && id && speakingId === id;
  const ts = created_at || timestamp;
  const blocks = parseContent(content);
  const [isTouchMetaVisible, setIsTouchMetaVisible] = useState(false);
  const touchTimerRef = useRef(null);
  const hintTimerRef = useRef(null);
  const [copyHint, setCopyHint] = useState(false);
  const timestampLabel = (() => {
    if (!ts) return '';
    const dateLabel = formatArabicDate(ts);
    const timeLabel = formatArabicNumber(
      new Intl.DateTimeFormat('ar', {
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(ts))
    );
    if (!dateLabel) return timeLabel;
    return timeLabel ? `${dateLabel} ${timeLabel}` : dateLabel;
  })();

  useEffect(() => {
    return () => {
      if (touchTimerRef.current) clearTimeout(touchTimerRef.current);
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
      if (id && speakingId === id && typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        onSpeak?.(null);
      }
    };
  }, [id, speakingId, onSpeak]);

  const handleTouchStart = () => {
    if (touchTimerRef.current) clearTimeout(touchTimerRef.current);
    touchTimerRef.current = setTimeout(() => {
      setIsTouchMetaVisible(true);
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
      hintTimerRef.current = setTimeout(() => setIsTouchMetaVisible(false), 2000);
    }, 400);
  };

  const handleTouchEnd = () => {
    if (touchTimerRef.current) clearTimeout(touchTimerRef.current);
  };

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(String(content || ''));
      setCopyHint(true);
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
      hintTimerRef.current = setTimeout(() => setCopyHint(false), 1600);
    } catch (_) {}
  };

  const handleSpeak = () => {
    if (isUser || !content?.trim()) return;
    if (typeof window === 'undefined' || !window.speechSynthesis) return;

    if (isSpeaking) {
      window.speechSynthesis.cancel();
      onSpeak?.(null);
      return;
    }

    window.speechSynthesis.cancel();
    const text = getTextForSpeech(content);
    if (!text) return;

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'ar-SA';
    utterance.rate = 0.95;
    utterance.onend = () => onSpeak?.(null);
    utterance.onerror = () => onSpeak?.(null);
    window.speechSynthesis.speak(utterance);
    onSpeak?.(id);
  };

  return (
    <div
      className={`message-wrapper ${isUser ? 'user' : 'assistant'} ${isGrouped ? 'grouped' : ''} ${isAltGroup ? 'alt' : ''} ${isTouchMetaVisible ? 'show-meta' : ''}`}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <div className="message-container">
        <div className={`message-avatar ${showAvatar ? '' : 'hidden'}`} aria-hidden={!showAvatar}>
          {isUser ? '👤' : '🤖'}
        </div>
        <div className="message-content">
          <div className="message-text arabic-text" dir="auto">
            {blocks.map((b, i) => (
              b.type === 'code'
                ? <CodeBlock key={i} code={b.content} lang={b.lang} />
                : <span key={i} className="text-block">{b.content}</span>
            ))}
          </div>
          <div className="message-actions" aria-hidden="true">
            <button type="button" className="message-action-btn" onClick={handleCopy}>
              نسخ
            </button>
            {copyHint && <span className="message-copy-hint">تم النسخ</span>}
          </div>
          {(showTimestamp || (!isUser && content?.trim())) && (
            <div className="message-footer">
              {showTimestamp && timestampLabel && (
                <span className="message-timestamp arabic-text" dir="auto">
                  {timestampLabel}
                </span>
              )}
              {!isUser && content?.trim() && (
                <button
                  type="button"
                  className={`message-tts-btn ${isSpeaking ? 'speaking' : ''}`}
                  onClick={handleSpeak}
                  title={isSpeaking ? 'إيقاف القراءة' : 'قراءة النص'}
                  aria-label={isSpeaking ? 'إيقاف القراءة' : 'قراءة النص'}
                >
                  {isSpeaking ? '⏹' : '🔊'}
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default Message;
