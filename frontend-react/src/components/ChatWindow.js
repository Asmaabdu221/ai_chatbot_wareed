import React, { useState } from 'react';
import MessageList from './MessageList';
import ChatInput from './ChatInput';
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
  onSendMessage,
  onNewChat,
  onPrescriptionResponse,
  onReplyToMessage,
  onDeleteMessage,
  onPinMessage,
  pinnedMessageIds = [],
  replyingTo = null,
  onCancelReply,
  isFetchingMessages,
  onToggleSidebar,
  isDrawerMode = false,
  isSidebarOpen = false,
}) => {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleNewChatClick = () => {
    if (onNewChat) onNewChat();
  };

  const handleSendMessage = async (message, attachment = null, attachmentType = null) => {
    if ((!(message || '').trim() && !attachment) || isLoading) return;
    setIsLoading(true);
    setError(null);
    try {
      if (onSendMessage) {
        await onSendMessage(message, attachment, attachmentType);
      }
    } catch (err) {
      setError(getErrorMessage(err, 'فشل الاتصال بالخادم.'));
    } finally {
      setIsLoading(false);
    }
  };

  const handleVoiceMessage = () => { };

  return (
    <div className="chat-window">
      <div className="chat-header">
        <button
          type="button"
          className="chat-header-profile-btn"
          onClick={onToggleSidebar}
          aria-label={isDrawerMode ? (isSidebarOpen ? 'Close menu' : 'Open menu') : 'Open sidebar'}
          aria-controls="app-sidebar"
          aria-expanded={isDrawerMode ? isSidebarOpen : undefined}
        >
          <span className="sidebar-toggle-icon" aria-hidden="true">☰</span>
        </button>
        <div className="chat-header-spacer" />
        <div className="chat-header-brand" onClick={handleNewChatClick} role="button" tabIndex={0}>
          <span className="chat-header-brand-text">مختبرات وريد الطبية</span>
        </div>
      </div>

      <MessageList
        messages={messages}
        isSending={isLoading}
        isFetching={isFetchingMessages}
        error={error}
        hasConversation={!!conversationId}
        onSuggestedPromptClick={handleSendMessage}
        userName={userName || 'مستخدم'}
        onReply={onReplyToMessage}
        onDelete={onDeleteMessage}
        onPin={onPinMessage}
        pinnedMessageIds={pinnedMessageIds}
      />

      {replyingTo && (
        <div className="reply-preview-bar">
          <div className="reply-content">
            <span className="reply-label">الرد على:</span>
            <span className="reply-text">{replyingTo.content.slice(0, 60)}...</span>
          </div>
          <button className="reply-close" onClick={onCancelReply}>✕</button>
        </div>
      )}

      <ChatInput
        onSend={handleSendMessage}
        onTyping={() => setError(null)}
        onVoiceMessage={handleVoiceMessage}
        showFileUpload={true}
        disabled={isLoading}
      />
    </div>
  );
};

export default ChatWindow;
