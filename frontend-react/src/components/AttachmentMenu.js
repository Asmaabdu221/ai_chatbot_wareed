/**
 * AttachmentMenu - Dropdown for attachment options (image, file).
 * Uses Portal to avoid clipping by parent overflow.
 */

import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import './AttachmentMenu.css';

const AttachmentMenu = ({
  isOpen,
  onClose,
  anchorRef,
  id,
  onImageUpload,
  onFileUpload,
  showFileUpload = false,
  isImageLoading = false,
  isFileLoading = false,
  disabled = false,
}) => {
  const menuRef = useRef(null);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!isOpen || !anchorRef?.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const isRtl = document.documentElement.dir === 'rtl';
    const menuWidth = 200;
    setPosition({
      top: rect.top,
      left: isRtl ? rect.right - menuWidth : rect.left,
    });
  }, [isOpen, anchorRef]);

  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (e) => {
      if (
        menuRef.current &&
        !menuRef.current.contains(e.target) &&
        anchorRef?.current &&
        !anchorRef.current.contains(e.target)
      ) {
        onClose();
      }
    };

    const handleEscape = (e) => {
      if (e.key === 'Escape') onClose();
    };

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
      id={id}
      className="attachment-menu"
      role="menu"
      aria-label="خيارات المرفقات"
      aria-orientation="vertical"
      style={{
        position: 'fixed',
        top: position.top - 8,
        left: position.left,
        transform: 'translateY(-100%)',
      }}
    >
      <button
        type="button"
        className="attachment-menu-item"
        role="menuitem"
        onClick={() => {
          if (!disabled && onImageUpload && !isImageLoading && !isFileLoading) {
            onImageUpload();
            onClose();
          }
        }}
        disabled={disabled || !onImageUpload || isImageLoading || isFileLoading}
        aria-label="رفع صورة وتحليل التحاليل"
      >
        <span className="attachment-menu-icon" aria-hidden="true">
          {isImageLoading ? '⏳' : '🖼️'}
        </span>
        <span className="attachment-menu-label">
          {isImageLoading ? 'جاري المعالجة...' : 'رفع صورة وتحليل التحاليل'}
        </span>
      </button>

      {showFileUpload && (
        <button
          type="button"
          className="attachment-menu-item"
          role="menuitem"
          onClick={() => {
            if (!disabled && onFileUpload && !isImageLoading && !isFileLoading) {
              onFileUpload();
              onClose();
            }
          }}
          disabled={disabled || !onFileUpload || isImageLoading || isFileLoading}
          aria-label="رفع ملف وتحليل الوصفة"
        >
          <span className="attachment-menu-icon" aria-hidden="true">
            {isFileLoading ? '⏳' : '📎'}
          </span>
          <span className="attachment-menu-label">
            {isFileLoading ? 'جاري المعالجة...' : 'رفع ملف (PDF, DOC, TXT)'}
          </span>
        </button>
      )}
    </div>
  );

  return createPortal(menuContent, document.body);
};

export default AttachmentMenu;
