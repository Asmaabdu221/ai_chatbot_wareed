/**
 * ChatHeaderActions - Share + three-dots menu for chat window header.
 * Pin chat, Archive, Report, Delete.
 */

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import ShareModal from './ShareModal';
import './ChatHeaderActions.css';

const ShareIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
    <polyline points="16 6 12 2 8 6" />
    <line x1="12" y1="2" x2="12" y2="15" />
  </svg>
);

const ThreeDotsIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
    <circle cx="12" cy="6" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="12" cy="18" r="1.5" />
  </svg>
);

const PinIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M12 17v5" />
    <path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16h1v2H2v-2h1v-4a2 2 0 0 1 1.11-1.79l1.78-.9A2 2 0 0 0 6 10.24V6h12v4.24a2 2 0 0 0 1.11 1.79l1.78.9A2 2 0 0 1 21 15.24V16h1v2h-3v-2h1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.24V8H9v2.76z" />
  </svg>
);

const ArchiveIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M21 8v13H3V8" />
    <path d="M1 3h22v5H1z" />
    <path d="M10 12h4" />
  </svg>
);

const ReportIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z" />
    <line x1="4" y1="22" x2="4" y2="15" />
  </svg>
);

const DeleteIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </svg>
);

const ChatHeaderActions = ({
  conversationId,
  conversationTitle,
  onArchive,
  onDelete,
  onPin,
  isPinned = false,
}) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const menuBtnRef = useRef(null);
  const menuRef = useRef(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!menuOpen || !menuBtnRef?.current) return;
    const rect = menuBtnRef.current.getBoundingClientRect();
    const isRtl = document.documentElement.dir === 'rtl';
    const menuWidth = 200;
    const padding = 12;
    let left = isRtl ? rect.right - menuWidth : rect.left;
    left = Math.max(padding, Math.min(left, window.innerWidth - menuWidth - padding));
    setPosition({
      top: rect.bottom + 4,
      left,
    });
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return;
    const handleClickOutside = (e) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target) &&
        menuBtnRef.current && !menuBtnRef.current.contains(e.target)
      ) {
        setMenuOpen(false);
      }
    };
    const handleEscape = (e) => { if (e.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [menuOpen]);

  const conversation = conversationId ? { id: conversationId, title: conversationTitle } : null;

  const handleShare = () => {
    setShareOpen(true);
    setMenuOpen(false);
  };

  const handleArchive = () => {
    if (conversationId && window.confirm('هل تريد أرشفة هذه المحادثة؟')) {
      onArchive?.(conversationId);
    }
    setMenuOpen(false);
  };

  const handleDelete = () => {
    if (conversationId && window.confirm('هل تريد حذف هذه المحادثة؟')) {
      onDelete?.(conversationId);
    }
    setMenuOpen(false);
  };

  return (
    <>
      <div className="chat-header-actions">
        <button
          type="button"
          className="chat-header-action-btn"
          onClick={handleShare}
          title="مشاركة"
          aria-label="مشاركة المحادثة"
        >
          <ShareIcon />
          <span>مشاركة</span>
        </button>
        <button
          ref={menuBtnRef}
          type="button"
          className="chat-header-action-btn"
          onClick={() => setMenuOpen((v) => !v)}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          aria-label="المزيد من الخيارات"
        >
          <ThreeDotsIcon />
        </button>
      </div>

      {menuOpen &&
        createPortal(
          <div
            ref={menuRef}
            className="chat-header-dropdown"
            role="menu"
            style={{
              position: 'fixed',
              top: position.top,
              left: position.left,
              zIndex: 1500,
            }}
          >
            <button
              type="button"
              className="chat-header-dropdown-opt"
              role="menuitem"
              onClick={() => {
                if (conversationId) onPin?.(conversationId);
                setMenuOpen(false);
              }}
            >
              <PinIcon />
              <span>{isPinned ? 'إلغاء تثبيت المحادثة' : 'تثبيت المحادثة'}</span>
            </button>
            <button type="button" className="chat-header-dropdown-opt" role="menuitem" onClick={handleArchive}>
              <ArchiveIcon />
              <span>أرشفة</span>
            </button>
            <button type="button" className="chat-header-dropdown-opt" role="menuitem" onClick={() => {}}>
              <ReportIcon />
              <span>إبلاغ</span>
            </button>
            <button type="button" className="chat-header-dropdown-opt chat-header-dropdown-opt-danger" role="menuitem" onClick={handleDelete}>
              <DeleteIcon />
              <span>حذف</span>
            </button>
          </div>,
          document.body
        )}

      {shareOpen && (
        <ShareModal
          isOpen={!!shareOpen}
          onClose={() => setShareOpen(false)}
          conversation={conversation}
        />
      )}
    </>
  );
};

export default ChatHeaderActions;
