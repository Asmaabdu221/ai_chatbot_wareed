/**
 * RenameModal - Rename a conversation.
 */

import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import './RenameModal.css';

const RenameModal = ({ conversation, onClose, onSave }) => {
  const [value, setValue] = useState(conversation?.title || '');
  const inputRef = useRef(null);

  useEffect(() => {
    setValue(conversation?.title || '');
  }, [conversation]);

  useEffect(() => {
    if (conversation) {
      inputRef.current?.focus();
    }
  }, [conversation]);

  useEffect(() => {
    if (!conversation) return;
    const handleEscape = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [conversation, onClose]);

  if (!conversation) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (value.trim()) onSave(value.trim());
  };

  const modalContent = (
    <div className="rename-modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="إعادة تسمية المحادثة">
      <div className="rename-modal" onClick={(e) => e.stopPropagation()}>
        <div className="rename-modal-header">
          <h3>إعادة تسمية المحادثة</h3>
          <button type="button" className="rename-modal-close" onClick={onClose} aria-label="إغلاق">×</button>
        </div>
        <form className="rename-modal-body" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="اسم المحادثة"
            maxLength={255}
            aria-label="اسم المحادثة"
          />
          <div className="rename-modal-actions">
            <button type="button" className="rename-modal-btn" onClick={onClose}>إلغاء</button>
            <button type="submit" className="rename-modal-btn rename-modal-btn-primary" disabled={!value.trim()}>
              حفظ
            </button>
          </div>
        </form>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
};

export default RenameModal;
