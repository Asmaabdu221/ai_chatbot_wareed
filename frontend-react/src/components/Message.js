import React, { useEffect, useRef, useState } from 'react';
import { formatArabicDate, formatArabicNumber } from '../utils/arabicFormatters';
import './Message.css';

import MessageContextMenu from './MessageContextMenu';

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

const TRAILING_PUNCTUATION_REGEX = /[).,!?؛:،]+$/;

const renderInlineElements = (text, keyPrefix) => {
  // Regex matches Markdown links, raw URLs, bold, italic, and code blocks in order.
  // Matching URLs first prevents inline formatting characters (like underscores in URLs) from breaking the link.
  const tokens = String(text || '').split(/(\[.*?\]\(https?:\/\/[^\s)]+\)|https?:\/\/[^\s]+|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|`[^`]+`)/g);
  
  return tokens.map((token, idx) => {
    if (!token) return null;
    const key = `${keyPrefix}-inline-${idx}`;

    // 1. Markdown Link: [text](url)
    const mdLinkMatch = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
    if (mdLinkMatch) {
      return (
        <a key={key} href={mdLinkMatch[2]} target="_blank" rel="noopener noreferrer">
          {mdLinkMatch[1]}
        </a>
      );
    }

    // 2. Raw URL
    if (/^https?:\/\//i.test(token)) {
      const trimmed = token.replace(TRAILING_PUNCTUATION_REGEX, '');
      const trailing = token.slice(trimmed.length);
      return (
        <React.Fragment key={key}>
          <a href={trimmed} target="_blank" rel="noopener noreferrer">
            {trimmed}
          </a>
          {trailing}
        </React.Fragment>
      );
    }

    // 3. Bold
    if ((token.startsWith('**') && token.endsWith('**')) || (token.startsWith('__') && token.endsWith('__'))) {
      return <strong key={key}>{renderInlineElements(token.slice(2, -2), `${key}-strong`)}</strong>;
    }

    // 4. Italic
    if ((token.startsWith('*') && token.endsWith('*')) || (token.startsWith('_') && token.endsWith('_'))) {
      return <em key={key}>{renderInlineElements(token.slice(1, -1), `${key}-em`)}</em>;
    }

    // 5. Code
    if (token.startsWith('`') && token.endsWith('`')) {
      return <code key={key}>{token.slice(1, -1)}</code>;
    }

    // 6. Plain text
    return <React.Fragment key={key}>{token}</React.Fragment>;
  });
};

const renderAssistantTextBlock = (text, keyPrefix) => {
  const lines = String(text || '').split('\n');
  return lines.map((line, idx) => {
    const key = `${keyPrefix}-line-${idx}`;
    const heading = line.match(/^\s{0,3}#{1,6}\s+(.*)$/);
    const unordered = line.match(/^\s*[-*+]\s+(.*)$/);
    const ordered = line.match(/^\s*(\d+)\.\s+(.*)$/);

    if (!line.trim()) {
      return <br key={key} />;
    }
    if (heading) {
      return <div key={key} className="text-block"><strong>{renderInlineElements(heading[1], key)}</strong></div>;
    }
    if (unordered) {
      return <div key={key} className="text-block">• {renderInlineElements(unordered[1], key)}</div>;
    }
    if (ordered) {
      return <div key={key} className="text-block">{ordered[1]}. {renderInlineElements(ordered[2], key)}</div>;
    }
    return <div key={key} className="text-block">{renderInlineElements(line, key)}</div>;
  });
};

const stripAttachmentMeta = (text) => {
  const raw = String(text || '');
  const lines = raw.split('\n');
  const filtered = lines.filter((line) => !/^\s*📎\s+\S+/.test(line.trim()));
  return filtered.join('\n').trimEnd();
};

const CodeBlock = ({ code, lang }) => {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
    } catch (_) { }
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
  isPinned = false,
  onAction,
}) => {
  const { role, content, timestamp, created_at, id } = message;
  const isUser = role === 'user';
  const isSpeaking = !isUser && id && speakingId === id;
  const ts = created_at || timestamp;
  const displayContent = stripAttachmentMeta(content);
  const blocks = parseContent(displayContent);

  const [menuData, setMenuData] = useState(null);
  const [copyFeedback, setCopyFeedback] = useState(false);
  const lastTapRef = useRef(0);

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
      if (id && speakingId === id && typeof window !== 'undefined' && window.speechSynthesis) {
        window.speechSynthesis.cancel();
        onSpeak?.(null);
      }
    };
  }, [id, speakingId, onSpeak]);

  const handleCopy = async () => {
    const textToCopy = String(displayContent || '').trim();
    if (!textToCopy) return;

    try {
      // Direct approach for modern environments
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(textToCopy);
      } else {
        // Fallback for non-secure contexts or compatibility issues
        const textArea = document.createElement("textarea");
        textArea.value = textToCopy;
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
      }
      setCopyFeedback(true);
      setTimeout(() => setCopyFeedback(false), 2000);
    } catch (err) {
      console.error('Copy failed:', err);
    }
  };

  const handleInteraction = (e) => {
    const isMobile = window.matchMedia('(max-width: 640px)').matches;
    const x = e.clientX || (e.touches && e.touches[0].clientX);
    const y = e.clientY || (e.touches && e.touches[0].clientY);

    setMenuData({ x, y, isMobile });
  };

  const handleDoubleClick = (e) => {
    e.preventDefault();
    handleInteraction(e);
  };

  const handleTouchStart = (e) => {
    const now = Date.now();
    if (now - lastTapRef.current < 300) {
      handleInteraction(e);
    }
    lastTapRef.current = now;
  };

  const handleMenuAction = (actionId) => {
    setMenuData(null);
    switch (actionId) {
      case 'copy':
        handleCopy();
        break;
      case 'share':
        if (navigator.share) {
          navigator.share({ text: displayContent }).catch(() => { });
        } else {
          handleCopy();
        }
        break;
      default:
        if (onAction) onAction(actionId);
        break;
    }
  };

  const replyTo = message.replyTo;

  return (
    <div
      className={`message-wrapper ${isUser ? 'user' : 'assistant'} ${isGrouped ? 'grouped' : ''} ${isAltGroup ? 'alt' : ''} ${isPinned ? 'pinned' : ''}`}
      onDoubleClick={handleDoubleClick}
      onTouchStart={handleTouchStart}
    >
      <div className="message-container">
        <div className="message-content">
          {replyTo && (
            <div className="message-reply-ref">
              <span className="reply-ref-label">الرد على:</span>
              <span className="reply-ref-text">{replyTo.content.slice(0, 50)}...</span>
            </div>
          )}
          <div className="message-text arabic-text" dir="auto">
            {isPinned && <span className="pin-hint">📌</span>}
            {blocks.map((b, i) => (
              b.type === 'code'
                ? <CodeBlock key={i} code={b.content} lang={b.lang} />
                : (
                  isUser
                    ? <span key={i} className="text-block">{renderInlineElements(b.content, `user-${i}`)}</span>
                    : <React.Fragment key={i}>{renderAssistantTextBlock(b.content, `assistant-${i}`)}</React.Fragment>
                )
            ))}
            {copyFeedback && <div className="copy-toast">تم النسخ</div>}
          </div>

          {(showTimestamp || (!isUser && displayContent?.trim())) && (
            <div className="message-footer">
              {showTimestamp && timestampLabel && (
                <span className="message-timestamp arabic-text" dir="auto">
                  {timestampLabel}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {menuData && (
        <MessageContextMenu
          x={menuData.x}
          y={menuData.y}
          isMobile={menuData.isMobile}
          onClose={() => setMenuData(null)}
          onAction={handleMenuAction}
        />
      )}
    </div>
  );
};

export default Message;
