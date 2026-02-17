/**
 * ShareModal - Share conversation to WhatsApp, Telegram, copy link.
 */

import React, { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import './ShareModal.css';

const getShareUrl = (conversation) => {
  const base = typeof window !== 'undefined' ? window.location.origin + window.location.pathname : '';
  return conversation?.id ? `${base}?c=${conversation.id}` : base;
};

const getShareText = (title) => {
  return title ? `محادثة: ${title}` : 'محادثة من وريد';
};

const ShareModal = ({ isOpen, onClose, conversation, onCopied }) => {
  const inputRef = useRef(null);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const url = getShareUrl(conversation);
  const text = getShareText(conversation?.title);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      onCopied?.();
    } catch (_) {}
  };

  const handleWhatsApp = () => {
    const u = `https://wa.me/?text=${encodeURIComponent(text + '\n' + url)}`;
    window.open(u, '_blank', 'noopener,noreferrer');
  };

  const handleTelegram = () => {
    const u = `https://t.me/share/url?url=${encodeURIComponent(url)}&text=${encodeURIComponent(text)}`;
    window.open(u, '_blank', 'noopener,noreferrer');
  };

  const modalContent = (
    <div className="share-modal-overlay" onClick={onClose} role="dialog" aria-modal="true" aria-label="مشاركة المحادثة">
      <div className="share-modal" onClick={(e) => e.stopPropagation()}>
        <div className="share-modal-header">
          <h3>مشاركة المحادثة</h3>
          <button type="button" className="share-modal-close" onClick={onClose} aria-label="إغلاق">×</button>
        </div>
        <div className="share-modal-body">
          <div className="share-modal-url">
            <input ref={inputRef} type="text" readOnly value={url} aria-label="رابط المشاركة" />
          </div>
          <div className="share-modal-actions">
            <button type="button" className="share-modal-btn" onClick={handleCopy}>
              نسخ الرابط
            </button>
            <button type="button" className="share-modal-btn share-modal-btn-whatsapp" onClick={handleWhatsApp}>
              واتساب
            </button>
            <button type="button" className="share-modal-btn share-modal-btn-telegram" onClick={handleTelegram}>
              تيليجرام
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(modalContent, document.body);
};

export default ShareModal;
