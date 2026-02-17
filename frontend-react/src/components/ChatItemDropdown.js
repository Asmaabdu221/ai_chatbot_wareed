/**
 * ChatItemDropdown - Three-dots menu for sidebar chat items.
 * Share, Rename, Pin, Archive, Delete.
 */

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './ChatItemDropdown.css';

const ShareIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" />
    <polyline points="16 6 12 2 8 6" />
    <line x1="12" y1="2" x2="12" y2="15" />
  </svg>
);

const RenameIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
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

const DeleteIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
    <polyline points="3 6 5 6 21 6" />
    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <line x1="10" y1="11" x2="10" y2="17" />
    <line x1="14" y1="11" x2="14" y2="17" />
  </svg>
);

const ThreeDotsIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <circle cx="12" cy="6" r="1.5" />
    <circle cx="12" cy="12" r="1.5" />
    <circle cx="12" cy="18" r="1.5" />
  </svg>
);

const ChatItemDropdown = ({
  isOpen,
  onClose,
  anchorRef,
  conversation,
  onShare,
  onRename,
  onPin,
  onArchive,
  onDelete,
}) => {
  const menuRef = useRef(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!isOpen || !anchorRef?.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const isRtl = document.documentElement.dir === 'rtl';
    const menuWidth = 180;
    setPosition({
      top: rect.bottom + 4,
      left: isRtl ? rect.right - menuWidth : rect.left,
    });
  }, [isOpen, anchorRef]);

  useEffect(() => {
    if (!isOpen) return;
    const handleClickOutside = (e) => {
      if (
        menuRef.current && !menuRef.current.contains(e.target) &&
        anchorRef?.current && !anchorRef.current.contains(e.target)
      ) {
        onClose();
      }
    };
    const handleEscape = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen, onClose, anchorRef]);

  if (!isOpen) return null;

  const menuContent = (
    <div
      ref={menuRef}
      className="chat-item-dropdown"
      role="menu"
      aria-label="خيارات المحادثة"
      style={{
        position: 'fixed',
        top: position.top,
        left: position.left,
        zIndex: 1500,
      }}
    >
      <button type="button" className="chat-item-dropdown-opt" role="menuitem" onClick={() => { onShare?.(conversation); onClose(); }}>
        <ShareIcon />
        <span>مشاركة</span>
      </button>
      <button type="button" className="chat-item-dropdown-opt" role="menuitem" onClick={() => { onRename?.(conversation); onClose(); }}>
        <RenameIcon />
        <span>إعادة تسمية</span>
      </button>
      <button type="button" className="chat-item-dropdown-opt" role="menuitem" onClick={() => { onPin?.(conversation); onClose(); }}>
        <PinIcon />
        <span>تثبيت المحادثة</span>
      </button>
      <button type="button" className="chat-item-dropdown-opt" role="menuitem" onClick={() => { onArchive?.(conversation); onClose(); }}>
        <ArchiveIcon />
        <span>أرشفة</span>
      </button>
      <button type="button" className="chat-item-dropdown-opt chat-item-dropdown-opt-danger" role="menuitem" onClick={() => { onDelete?.(conversation); onClose(); }}>
        <DeleteIcon />
        <span>حذف</span>
      </button>
    </div>
  );

  return createPortal(menuContent, document.body);
};

export { ThreeDotsIcon };
export default ChatItemDropdown;
