import React, { useState, useRef, useEffect } from 'react';
import { getErrorMessage } from '../utils/errorUtils';
import AttachmentMenu from './AttachmentMenu';
import './ChatInput.css';

const ACCEPT_IMAGE = 'image/jpeg,image/jpg,image/png';

const MicrophoneIcon = ({ className }) => (
  <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);

const SendIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

const PlusIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

const ChatInput = ({
  onSend,
  onVoiceMessage,
  onImageUpload,
  onFileUpload,
  showFileUpload = false,
  disabled,
}) => {
  const [message, setMessage] = useState('');
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState(null);
  const [ocrError, setOcrError] = useState(null);
  const [isOcrLoading, setIsOcrLoading] = useState(false);
  const [isFileLoading, setIsFileLoading] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const textareaRef = useRef(null);
  const imageInputRef = useRef(null);
  const fileInputRef = useRef(null);
  const attachButtonRef = useRef(null);
  const recognitionRef = useRef(null);

  const hasSpeechRecognition = typeof window !== 'undefined' &&
    (window.SpeechRecognition || window.webkitSpeechRecognition);

  const gotResultRef = useRef(false);

  useEffect(() => {
    if (!hasSpeechRecognition) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = document.documentElement.lang === 'ar' ? 'ar-SA' : 'ar-SA';
    recognitionRef.current = recognition;

    recognition.onresult = (event) => {
      gotResultRef.current = true;
      const transcript = event.results[0][0].transcript;
      if (transcript?.trim()) {
        onSend(transcript.trim());
      }
      setIsListening(false);
    };

    recognition.onend = () => setIsListening(false);

    recognition.onerror = (event) => {
      setIsListening(false);
      if (gotResultRef.current || event.error === 'aborted') {
        gotResultRef.current = false;
        return;
      }
      if (event.error === 'not-allowed') {
        setVoiceError('يرجى السماح بالوصول إلى الميكروفون');
      } else if (event.error === 'no-speech') {
        setVoiceError('لم يتم اكتشاف صوت. حاول مرة أخرى');
      } else {
        setVoiceError('حدث خطأ في التعرف على الصوت');
      }
    };

    return () => {
      if (recognitionRef.current) recognitionRef.current.abort();
    };
  }, [hasSpeechRecognition, onSend]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (message.trim() && !disabled) {
      onSend(message);
      setMessage('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const handleChange = (e) => {
    setMessage(e.target.value);
    setVoiceError(null);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  };

  const toggleVoiceInput = () => {
    if (disabled) return;
    setVoiceError(null);
    if (!hasSpeechRecognition) {
      setVoiceError('المتصفح لا يدعم التعرف على الصوت. استخدم Chrome أو Edge');
      return;
    }
    if (isListening) {
      recognitionRef.current?.abort();
      setIsListening(false);
    } else {
      gotResultRef.current = false;
      try {
        recognitionRef.current?.start();
        setIsListening(true);
      } catch (err) {
        setVoiceError('فشل بدء التسجيل الصوتي');
        setIsListening(false);
      }
    }
  };

  const handleAttachClick = () => {
    if (disabled || isOcrLoading) return;
    setAttachmentMenuOpen((prev) => !prev);
  };

  const handleImageSelect = () => {
    imageInputRef.current?.click();
  };

  const handleFileSelect = () => {
    fileInputRef.current?.click();
  };

  const handleImageChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !onImageUpload) return;
    const ext = '.' + (file.name?.split('.').pop() || '').toLowerCase();
    if (!['.jpg', '.jpeg', '.png'].includes(ext)) {
      setOcrError('يرجى اختيار صورة بصيغة JPEG أو PNG');
      return;
    }
    setOcrError(null);
    setIsOcrLoading(true);
    try {
      await onImageUpload(file);
    } catch (err) {
      setOcrError(getErrorMessage(err, 'فشل استخراج النص من الصورة'));
    } finally {
      setIsOcrLoading(false);
      e.target.value = '';
    }
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !onFileUpload) return;
    const ext = '.' + (file.name?.split('.').pop() || '').toLowerCase();
    if (!['.pdf', '.doc', '.docx', '.txt'].includes(ext)) {
      setOcrError('يرجى اختيار ملف بصيغة PDF أو DOC أو DOCX أو TXT');
      e.target.value = '';
      return;
    }
    setOcrError(null);
    setIsFileLoading(true);
    try {
      await onFileUpload(file);
    } catch (err) {
      setOcrError(getErrorMessage(err, 'فشل استخراج النص من الملف'));
    } finally {
      setIsFileLoading(false);
      e.target.value = '';
    }
  };

  const hasAttachmentOption = onImageUpload || (showFileUpload && onFileUpload);
  const hasText = message.trim().length > 0;

  return (
    <div className="chat-input-container">
      <form className="chat-input-form chat-input-pill" onSubmit={handleSubmit}>
        <input
          ref={imageInputRef}
          type="file"
          accept={ACCEPT_IMAGE}
          onChange={handleImageChange}
          style={{ display: 'none' }}
          aria-hidden="true"
        />
        {showFileUpload && (
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.doc,.docx,.txt"
            onChange={handleFileChange}
            style={{ display: 'none' }}
            aria-hidden="true"
          />
        )}

        {hasAttachmentOption && (
          <div className="chat-input-attach-wrap">
            <button
              ref={attachButtonRef}
              type="button"
              className="chat-input-icon-btn chat-input-plus-btn"
              disabled={disabled || isOcrLoading || isFileLoading}
              onClick={handleAttachClick}
              aria-label="إضافة مرفق"
              aria-haspopup="menu"
              aria-expanded={attachmentMenuOpen}
            >
              <PlusIcon />
            </button>
            <AttachmentMenu
              id="attachment-menu"
              isOpen={attachmentMenuOpen}
              onClose={() => setAttachmentMenuOpen(false)}
              anchorRef={attachButtonRef}
              onImageUpload={handleImageSelect}
              onFileUpload={showFileUpload ? handleFileSelect : undefined}
              showFileUpload={showFileUpload}
              isImageLoading={isOcrLoading}
              isFileLoading={isFileLoading}
              disabled={disabled}
            />
          </div>
        )}

        <textarea
          ref={textareaRef}
          className="chat-input-textarea"
          placeholder="اكتب رسالتك..."
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={disabled || isListening}
          rows={1}
        />

        <button
          type="button"
          className={`chat-input-mic-btn ${isListening ? 'listening' : ''}`}
          onClick={toggleVoiceInput}
          disabled={disabled}
          title={isListening ? 'جاري الاستماع...' : 'اضغط للتحدث'}
        >
          <MicrophoneIcon />
        </button>
        <button
          type="submit"
          className="chat-input-send-btn"
          disabled={disabled || !message.trim()}
          title="إرسال"
        >
          <SendIcon />
        </button>
      </form>

      {(voiceError || ocrError) && (
        <div className="chat-input-error" role="alert">
          ⚠️ {voiceError || ocrError}
          <button
            type="button"
            className="chat-input-error-close"
            onClick={() => { setVoiceError(null); setOcrError(null); }}
            aria-label="إغلاق"
          >
            ✕
          </button>
        </div>
      )}

      <div className="chat-input-hint">
        {isListening
          ? 'جاري الاستماع... تحدث الآن'
          : isOcrLoading
          ? 'جاري استخراج النص من الصورة...'
          : isFileLoading
          ? 'جاري استخراج النص من الملف...'
          : hasText
          ? 'اضغط Enter للإرسال'
          : 'اضغط على الميكروفون للتحدث أو اكتب رسالتك'}
      </div>
    </div>
  );
};

export default ChatInput;
