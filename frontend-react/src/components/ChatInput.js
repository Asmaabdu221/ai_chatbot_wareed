import React, { useState, useRef, useEffect } from 'react';
import { getErrorMessage } from '../utils/errorUtils';
import AttachmentMenu from './AttachmentMenu';
import './ChatInput.css';

const ACCEPT_IMAGE = 'image/jpeg,image/jpg,image/png';

const formatDuration = (totalSeconds) => {
  const s = Math.max(0, Math.floor(totalSeconds || 0));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toString().padStart(2, '0')}`;
};

const pickAudioExtension = (mimeType) => {
  const mt = (mimeType || '').toLowerCase();
  if (mt.includes('wav')) return 'wav';
  if (mt.includes('mp4') || mt.includes('m4a')) return 'm4a';
  if (mt.includes('ogg')) return 'ogg';
  if (mt.includes('mpeg') || mt.includes('mp3')) return 'mp3';
  return 'webm';
};

const MicrophoneIcon = ({ className }) => (
  <svg className={className} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
    <line x1="12" y1="19" x2="12" y2="23" />
    <line x1="8" y1="23" x2="16" y2="23" />
  </svg>
);

const SendIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 12L21 3L13 21L10 14L3 12Z" />
    <path d="M10 14L21 3" />
  </svg>
);

const PlusIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

const ChatInput = ({
  conversationId,
  onSend,
  onTyping,
  onVoiceMessage,
  showFileUpload = false,
  disabled,
}) => {
  const [message, setMessage] = useState('');
  const [pendingAttachment, setPendingAttachment] = useState(null);
  const [pendingAudio, setPendingAudio] = useState(null);
  const [recordingState, setRecordingState] = useState('idle');
  const [recordingDuration, setRecordingDuration] = useState(0);
  const [isListening, setIsListening] = useState(false);
  const [voiceError, setVoiceError] = useState(null);
  const [ocrError, setOcrError] = useState(null);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const textareaRef = useRef(null);

  useEffect(() => {
    if (conversationId === null) {
      setMessage('');
      setPendingAttachment(null);
      clearPendingAudio();
      if (textareaRef.current) {
        textareaRef.current.focus();
        textareaRef.current.style.height = 'auto';
      }
    }
  }, [conversationId]);

  useEffect(() => {
    const focusComposer = () => {
      if (textareaRef.current) {
        textareaRef.current.focus();
      }
    };
    window.addEventListener('wareed:focus-composer', focusComposer);
    return () => window.removeEventListener('wareed:focus-composer', focusComposer);
  }, []);

  useEffect(() => {
    return () => {
      clearRecordingTimer();
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stop();
      }
      releaseStream();
      setPendingAudio((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return prev;
      });
    };
  }, []);

  const imageInputRef = useRef(null);
  const fileInputRef = useRef(null);
  const attachButtonRef = useRef(null);
  const mediaRecorderRef = useRef(null);
  const recordedChunksRef = useRef([]);
  const recordingStartRef = useRef(0);
  const recordingTimerRef = useRef(null);
  const streamRef = useRef(null);
  const recognitionRef = useRef(null);
  const gotResultRef = useRef(false);
  const hasSpeechRecognition = false;

  const clearRecordingTimer = () => {
    if (recordingTimerRef.current) {
      window.clearInterval(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
  };

  const releaseStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  };

  const clearPendingAudio = () => {
    setPendingAudio((prev) => {
      if (prev?.url) URL.revokeObjectURL(prev.url);
      return null;
    });
    setRecordingState('idle');
    setRecordingDuration(0);
  };

  useEffect(() => {
    if (!hasSpeechRecognition) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'ar-SA';
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

  const startRecording = async () => {
    if (disabled) return;
    if (typeof window === 'undefined' || !navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      setVoiceError('Voice recording is not supported in this browser.');
      return;
    }

    try {
      setVoiceError(null);
      clearPendingAudio();
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const mimeCandidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'];
      const mimeType = mimeCandidates.find((mt) => window.MediaRecorder.isTypeSupported?.(mt));
      const recorder = mimeType ? new window.MediaRecorder(stream, { mimeType }) : new window.MediaRecorder(stream);

      recordedChunksRef.current = [];
      recordingStartRef.current = Date.now();
      setRecordingDuration(0);

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          recordedChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = () => {
        clearRecordingTimer();
        setIsListening(false);
        const total = Math.max(1, Math.round((Date.now() - recordingStartRef.current) / 1000));
        const blobType = recorder.mimeType || 'audio/webm';
        const blob = new Blob(recordedChunksRef.current, { type: blobType });
        if (!blob.size) {
          setVoiceError('No audio was captured. Please try again.');
          setRecordingState('idle');
          releaseStream();
          return;
        }
        const url = URL.createObjectURL(blob);
        setPendingAudio({ blob, url, duration: total });
        setRecordingDuration(total);
        setRecordingState('preview');
        releaseStream();
      };

      recorder.onerror = () => {
        clearRecordingTimer();
        setIsListening(false);
        setRecordingState('idle');
        setVoiceError('Recording failed. Please try again.');
        releaseStream();
      };

      mediaRecorderRef.current = recorder;
      recorder.start();
      setRecordingState('recording');
      setIsListening(true);
      recordingTimerRef.current = window.setInterval(() => {
        setRecordingDuration(Math.max(0, Math.round((Date.now() - recordingStartRef.current) / 1000)));
      }, 500);
    } catch (err) {
      setRecordingState('idle');
      setIsListening(false);
      setVoiceError(getErrorMessage(err, 'Unable to access microphone.'));
      releaseStream();
    }
  };

  const stopRecording = () => {
    const rec = mediaRecorderRef.current;
    if (rec && rec.state !== 'inactive') {
      rec.stop();
    }
  };

  const sendPendingAudio = async () => {
    if (!pendingAudio || disabled) return;

    const text = message.trim();
    const ext = pickAudioExtension(pendingAudio.blob.type);
    const file = new File([pendingAudio.blob], `voice-message-${Date.now()}.${ext}`, {
      type: pendingAudio.blob.type || 'audio/webm',
    });

    try {
      await onSend(text, file, 'audio');
      clearPendingAudio();
      setMessage('');
      if (textareaRef.current) {
        textareaRef.current.style.height = 'auto';
      }
    } catch (err) {
      setVoiceError(getErrorMessage(err, 'Failed to send voice message.'));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (pendingAudio) {
      await sendPendingAudio();
      return;
    }

    const content = message.trim();

    if (!content && !pendingAttachment) {
      setOcrError('محتوى الرسالة مطلوب.');
      return;
    }

    if (pendingAttachment && !content) {
      setOcrError('يرجى كتابة سؤالك حول المرفق قبل الإرسال.');
      return;
    }

    if (content && !disabled) {
      try {
        await onSend(content, pendingAttachment?.file, pendingAttachment?.type);
        setMessage('');
        setPendingAttachment(null);
        if (textareaRef.current) {
          textareaRef.current.style.height = 'auto';
        }
      } catch (err) {
        setOcrError(getErrorMessage(err, 'Failed to send message.'));
      }
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void handleSubmit(e);
    }
  };

  const handleChange = (e) => {
    setMessage(e.target.value);
    setVoiceError(null);
    setOcrError(null);
    if (onTyping) onTyping();
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
    }
  };

  const toggleVoiceInput = () => {
    if (disabled) return;
    setVoiceError(null);
    if (recordingState === 'recording') {
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

  const handleVoiceRecordingToggle = () => {
    if (disabled) return;
    setVoiceError(null);
    if (recordingState === 'recording') {
      stopRecording();
      return;
    }
    void startRecording();
  };

  const handleAttachClick = () => {
    if (disabled) return;
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
    if (!file) return;
    const ext = '.' + (file.name?.split('.').pop() || '').toLowerCase();
    if (!['.jpg', '.jpeg', '.png'].includes(ext)) {
      setOcrError('يرجى اختيار صورة بصيغة JPEG أو PNG');
      return;
    }

    setOcrError(null);
    const reader = new FileReader();
    reader.onload = (event) => {
      setPendingAttachment({
        file,
        name: file.name,
        type: 'image',
        preview: event.target.result
      });
    };
    reader.readAsDataURL(file);
    e.target.value = '';
    setAttachmentMenuOpen(false);
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = '.' + (file.name?.split('.').pop() || '').toLowerCase();

    // Convert extension for backend mapping
    let attachmentType = 'pdf';
    if (ext === '.doc' || ext === '.docx') attachmentType = 'doc';
    else if (ext === '.txt') attachmentType = 'txt';

    if (!['.pdf', '.doc', '.docx', '.txt'].includes(ext)) {
      setOcrError('يرجى اختيار ملف بصيغة PDF أو DOC أو DOCX أو TXT');
      e.target.value = '';
      return;
    }

    setOcrError(null);
    setPendingAttachment({
      file,
      name: file.name,
      type: attachmentType,
      preview: null
    });
    e.target.value = '';
    setAttachmentMenuOpen(false);
  };

  const removeAttachment = () => {
    setPendingAttachment(null);
    setOcrError(null);
  };

  const hasAttachmentOption = true;
  const hasText = message.trim().length > 0;

  return (
    <div className="chat-input-container">
      {pendingAttachment && (
        <div className="chat-input-attachment-preview">
          {pendingAttachment.preview ? (
            <div className="attachment-thumbnail">
              <img src={pendingAttachment.preview} alt="preview" />
              <button type="button" className="remove-attachment" onClick={removeAttachment} aria-label="إزالة المرفق">✕</button>
            </div>
          ) : (
            <div className="attachment-chip">
              <span className="attachment-icon">📄</span>
              <span className="attachment-name">{pendingAttachment.name}</span>
              <button type="button" className="remove-attachment" onClick={removeAttachment} aria-label="إزالة المرفق">✕</button>
            </div>
          )}
        </div>
      )}

      {pendingAudio && (
        <div className="chat-input-audio-preview" role="group" aria-label="Voice message preview">
          <span className="audio-preview-icon" aria-hidden="true">🎙️</span>
          <audio className="audio-preview-player" controls src={pendingAudio.url} />
          <span className="audio-preview-duration">{formatDuration(pendingAudio.duration)}</span>
          <button type="button" className="audio-preview-action" onClick={clearPendingAudio} aria-label="Cancel voice message">✕</button>
          <button type="button" className="audio-preview-action audio-preview-send" onClick={() => void sendPendingAudio()} aria-label="Send voice message">✓</button>
        </div>
      )}

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
              disabled={disabled}
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
              isImageLoading={false}
              isFileLoading={false}
              disabled={disabled}
            />
          </div>
        )}

        {recordingState === 'recording' && (
          <span className="chat-input-recording-indicator" aria-live="polite">
            <span className="chat-input-recording-dot" aria-hidden="true" />
            Recording... {formatDuration(recordingDuration)}
          </span>
        )}

        <textarea
          ref={textareaRef}
          className="chat-input-textarea"
          placeholder="اكتب رسالتك..."
          value={message}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          disabled={disabled || recordingState === 'recording'}
          rows={1}
        />

        <button
          type="button"
          className={`chat-input-mic-btn ${recordingState === 'recording' ? 'listening' : ''}`}
          onClick={handleVoiceRecordingToggle}
          disabled={disabled}
          title={recordingState === 'recording' ? 'Stop recording' : 'Start recording'}
        >
          <MicrophoneIcon />
        </button>
        <button
          type="submit"
          className="chat-input-send-btn"
          disabled={disabled || (!message.trim() && !pendingAttachment && !pendingAudio)}
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
        {recordingState === 'recording'
          ? 'جاري الاستماع... تحدث الآن'
          : pendingAudio
            ? 'Review your voice message then send with ✓'
            : pendingAttachment
            ? 'اكتب سؤالك حول المرفق واضغط Enter'
            : hasText
              ? 'اضغط Enter للإرسال'
              : 'اضغط على الميكروفون للتحدث أو اكتب رسالتك'}
      </div>
    </div>
  );
};

export default ChatInput;
