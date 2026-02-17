import React, { useState } from 'react';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
import { getApiUrlForDisplay, extractTextFromImage, extractTextFromDocument } from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';
import './ChatWindow.css';

/**
 * When onSendMessage is provided (authenticated flow), it is used for text messages.
 * Otherwise legacy sendChatMessage is used (demo mode).
 */
const ChatWindow = ({
  conversationId,
  conversationTitle,
  messages,
  userId,
  userEmail,
  userName,
  onNewMessage,
  onSendMessage,
  onPrescriptionResponse,
  isFetchingMessages,
  onToggleSidebar,
  onArchiveConversation,
  onDeleteConversation,
  onPinConversation,
  pinnedConversationIds = [],
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSendMessage = async (message) => {
    if (!message.trim() || isLoading) return;
    console.info("[Chat] Sending payload:", {
      message: message.trim(),
      conversationId,
    });
    setIsLoading(true);
    setError(null);
    try {
      if (onSendMessage) {
        await onSendMessage(message);
      } else if (onNewMessage) {
        const { sendChatMessage } = await import('../services/api');
        const response = await sendChatMessage(message, userId, conversationId, true);
        if (response.success) await onNewMessage(response, message);
        else setError(response.error || 'حدث خطأ في معالجة الرسالة');
      }
    } catch (err) {
      const msg = err.message || '';
      if (err.code === 'ECONNABORTED' || msg.includes('timeout')) {
        setError('انتهت مهلة الانتظار. يرجى المحاولة مرة أخرى.');
      } else if (msg.includes('Network Error') || !err.response) {
        setError(`لا يمكن الاتصال بالخادم. تأكد من تشغيل الخادم على ${getApiUrlForDisplay()}`);
      } else {
        setError(getErrorMessage(err, 'فشل الاتصال بالخادم. يرجى المحاولة مرة أخرى.'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleVoiceMessage = () => {};

  const handleImageUpload = async (file) => {
    const data = await extractTextFromImage(file);
    const responseMessage = data?.response_message || data?.extracted_text || '';
    if (!responseMessage.trim()) {
      throw new Error('لم يتم التعرف على تحاليل واضحة في الصورة. يرجى رفع صورة أوضح.');
    }
    if (onPrescriptionResponse) {
      await onPrescriptionResponse('صورة وصفة طبية', responseMessage);
    } else {
      await handleSendMessage(responseMessage);
    }
  };

  const handleFileUpload = async (file) => {
    const data = await extractTextFromDocument(file);
    const extractedText = data?.extracted_text || data?.response_message || '';
    if (!extractedText.trim()) {
      throw new Error('لم يتم استخراج نص من الملف. تأكد من أن الملف يحتوي على نص.');
    }
    const prompt = `هذه محتويات ملف (وصفة/تحاليل):\n\n${extractedText}\n\nقم بتحليل التحاليل المذكورة واخبرني أيها متوفر لدى مختبرات وريد وأيها غير متوفر. إذا احتجت توضيحاً إضافياً اسأل.`;
    await handleSendMessage(prompt);
  };

  return (
    <div className="chat-window">
      <div className="chat-header">
        <button
          type="button"
          className="chat-header-profile-btn"
          onClick={onToggleSidebar}
          title="فتح القائمة"
          aria-label="فتح القائمة"
        >
          <div className="chat-header-avatar">
            {userEmail
              ? (userEmail.split('@')[0] || '?').slice(0, 2).toUpperCase() || '?'
              : '?'}
          </div>
        </button>
        <div className="chat-header-spacer" aria-hidden="true" />
        <div className="chat-header-brand">
          <span className="chat-header-brand-text" dir="auto">مختبرات وريد الطبية </span>
        </div>
      </div>

      <MessageList
        messages={messages}
        isSending={isLoading}
        isFetching={isFetchingMessages}
        error={error}
        hasConversation={!!conversationId}
        onSuggestedPromptClick={handleSendMessage}
        userName={userName || (userEmail?.split('@')[0]) || 'مستخدم'}
      />

      <ChatInput
        onSend={handleSendMessage}
        onVoiceMessage={handleVoiceMessage}
        onImageUpload={handleImageUpload}
        onFileUpload={handleFileUpload}
        showFileUpload={true}
        disabled={isLoading}
      />
    </div>
  );
};

export default ChatWindow;
