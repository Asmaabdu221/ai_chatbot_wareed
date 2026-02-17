import React from 'react';
import { Link, useLocation } from 'react-router-dom';
import { formatArabicText } from '../utils/arabicFormatters';
import './ChatSidebar.css';

const ChatSidebar = ({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onLogout,
  isLoading,
  showDashboardLink = false,
}) => {
  const location = useLocation();
  const isChat = location.pathname === '/' || location.pathname === '';
  return (
    <div className="chat-sidebar">
      <div className="sidebar-header">
        <h2>🏥 مختبرات وريد الطبية</h2>
        {showDashboardLink && (
          <div className="sidebar-nav">
            <Link className={`nav-link ${isChat ? 'active' : ''}`} to="/">
              المحادثات
            </Link>
            <Link className={`nav-link ${!isChat ? 'active' : ''}`} to="/admin/dashboard">
              لوحة التحكم
            </Link>
          </div>
        )}
        <button className="new-chat-btn" onClick={onNewConversation}>
          + محادثة جديدة
        </button>
      </div>

      <div className="conversations-list">
        {isLoading ? (
          <div className="sidebar-skeleton">
            <div className="sidebar-skeleton-item"></div>
            <div className="sidebar-skeleton-item"></div>
            <div className="sidebar-skeleton-item"></div>
          </div>
        ) : conversations.length === 0 ? (
          <div className="empty-state arabic-text" dir="auto">
            <p>{formatArabicText('لا توجد محادثات بعد')}</p>
            <p className="empty-subtitle">{formatArabicText('ابدأ محادثة جديدة')}</p>
          </div>
        ) : (
          conversations.map(conv => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  onSelectConversation(conv.id);
                }
              }}
            >
              <div className="conversation-content">
                <div className="conversation-title">{conv.title || 'محادثة جديدة'}</div>
                <div className="conversation-meta">
                  {conv.message_count != null ? `${conv.message_count} رسالة` : 'محادثة'}
                </div>
              </div>
              <button
                className="delete-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  if (window.confirm('هل تريد حذف هذه المحادثة؟')) {
                    onDeleteConversation(conv.id);
                  }
                }}
              >
                🗑️
              </button>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        {onLogout && (
          <button type="button" className="logout-btn" onClick={onLogout}>
            تسجيل الخروج
          </button>
        )}
        <div className="footer-info">
          <p>مختبرات وريد الطبية</p>
          <p className="footer-version">v1.0.0</p>
        </div>
      </div>
    </div>
  );
};

export default ChatSidebar;
