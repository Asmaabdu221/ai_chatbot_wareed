/**
 * LeftSidebar - Previous chats sidebar on the LEFT.
 * User name at bottom (clickable). Expandable user panel within sidebar.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { formatArabicText } from '../utils/arabicFormatters';
import EditProfileModal from './EditProfileModal';
import ChatItemDropdown, { ThreeDotsIcon } from './ChatItemDropdown';
import ShareModal from './ShareModal';
import RenameModal from './RenameModal';
import './LeftSidebar.css';

const getUserName = (email) => {
  if (!email) return 'مستخدم';
  return email.split('@')[0];
};

const getInitials = (email) => {
  if (!email) return '?';
  const part = email.split('@')[0];
  if (part.length >= 2) return part.slice(0, 2).toUpperCase();
  return part.toUpperCase();
};

const SettingsIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
  </svg>
);

const HelpIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
    <line x1="12" y1="17" x2="12.01" y2="17" />
  </svg>
);

const LogoutIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
    <polyline points="16 17 21 12 16 7" />
    <line x1="21" y1="12" x2="9" y2="12" />
  </svg>
);

const UserPanel = ({ user, userEmail, theme, onThemeChange, onLogout, onCloseSidebar, onOpenEditProfile }) => {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef(null);
  const displayName = user?.display_name || user?.username || getUserName(userEmail);
  const avatarSrc = user?.avatar_url
    ? (user.avatar_url.startsWith('/') ? user.avatar_url : `/${user.avatar_url}`)
    : null;

  useEffect(() => {
    const handleClickOutside = (e) => {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) {
        setSettingsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="left-sidebar-user-panel">
      <div className="left-sidebar-user-info">
        <div className="left-sidebar-user-avatar">
          {avatarSrc ? <img src={avatarSrc} alt="" /> : getInitials(userEmail)}
        </div>
        <div className="left-sidebar-user-details">
          <button
            type="button"
            className="left-sidebar-user-name left-sidebar-user-name-btn"
            onClick={onOpenEditProfile}
          >
            {displayName}
          </button>
          <div className="left-sidebar-user-email">{userEmail}</div>
        </div>
      </div>

      <div className="left-sidebar-panel-divider" />

      <div className="left-sidebar-panel-section" ref={settingsRef}>
        <button
          type="button"
          className="left-sidebar-menu-item"
          onClick={() => setSettingsOpen((v) => !v)}
          aria-expanded={settingsOpen}
        >
          <span className="left-sidebar-menu-icon"><SettingsIcon /></span>
          <span className="left-sidebar-menu-text">الإعدادات</span>
          <span className="left-sidebar-chevron">{settingsOpen ? '▼' : '▶'}</span>
        </button>
        {settingsOpen && (
          <div className="left-sidebar-settings-dropdown">
            <button
              type="button"
              className={`left-sidebar-dropdown-opt ${theme === 'light' ? 'active' : ''}`}
              onClick={() => { onThemeChange('light'); setSettingsOpen(false); }}
            >
              فاتح
            </button>
            <button
              type="button"
              className={`left-sidebar-dropdown-opt ${theme === 'system' ? 'active' : ''}`}
              onClick={() => { onThemeChange('system'); setSettingsOpen(false); }}
            >
              افتراضي النظام
            </button>
            <button
              type="button"
              className={`left-sidebar-dropdown-opt ${theme === 'dark' ? 'active' : ''}`}
              onClick={() => { onThemeChange('dark'); setSettingsOpen(false); }}
            >
              داكن
            </button>
          </div>
        )}
      </div>

      <Link
        to="/help"
        className="left-sidebar-menu-item left-sidebar-menu-link"
        onClick={() => onCloseSidebar?.()}
      >
        <span className="left-sidebar-menu-icon"><HelpIcon /></span>
        <span className="left-sidebar-menu-text">المساعدة</span>
        <span className="left-sidebar-chevron">▶</span>
      </Link>

      <button type="button" className="left-sidebar-menu-item left-sidebar-logout" onClick={onLogout}>
        <span className="left-sidebar-menu-icon"><LogoutIcon /></span>
        <span className="left-sidebar-menu-text">تسجيل الخروج</span>
      </button>
    </div>
  );
};

const PlusIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="12" y1="5" x2="12" y2="19" />
    <line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);

const CloseIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <line x1="18" y1="6" x2="6" y2="18" />
    <line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);

const SearchIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" y1="21" x2="16.65" y2="16.65" />
  </svg>
);

const PanelLeftIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
    <line x1="9" y1="3" x2="9" y2="21" />
  </svg>
);

const PanelRightIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
    <line x1="15" y1="3" x2="15" y2="21" />
  </svg>
);

const LeftSidebar = ({
  conversations,
  pinnedConversationIds = [],
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onRenameConversation,
  onPinConversation,
  onLogout,
  onCloseSidebar,
  onToggleCollapse,
  sidebarCollapsed = false,
  user,
  userEmail,
  theme,
  onThemeChange,
  onClearChats,
  onProfileUpdated,
  isLoading,
  showDashboardLink = false,
}) => {
  const location = useLocation();
  const isChat = location.pathname === '/' || location.pathname === '';
  const [userPanelExpanded, setUserPanelExpanded] = useState(false);
  const [editProfileOpen, setEditProfileOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [dropdownConvId, setDropdownConvId] = useState(null);
  const [shareConv, setShareConv] = useState(null);
  const [renameConv, setRenameConv] = useState(null);
  const dotsAnchorRef = useRef(null);
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia?.('(max-width: 640px)')?.matches);
  const footerRef = useRef(null);

  useEffect(() => {
    if (!userPanelExpanded) return;
    const handleClickOutside = (e) => {
      if (footerRef.current && !footerRef.current.contains(e.target)) {
        setUserPanelExpanded(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [userPanelExpanded]);

  useEffect(() => {
    const mq = window.matchMedia?.('(max-width: 640px)');
    if (!mq) return;
    const handler = () => setIsMobile(mq.matches);
    mq.addEventListener('change', handler);
    setIsMobile(mq.matches);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const showCollapsed = sidebarCollapsed && !isMobile;

  const filteredConversations = searchQuery.trim()
    ? conversations.filter((c) =>
        (c.title || 'محادثة جديدة').toLowerCase().includes(searchQuery.toLowerCase())
      )
    : conversations;

  const sortedConversations = [...filteredConversations].sort((a, b) => {
    const aPinned = pinnedConversationIds.includes(a.id);
    const bPinned = pinnedConversationIds.includes(b.id);
    if (aPinned && !bPinned) return -1;
    if (!aPinned && bPinned) return 1;
    return 0;
  });

  if (showCollapsed) {
    return (
      <div className="left-sidebar left-sidebar-collapsed">
        <div className="left-sidebar-collapsed-icons">
          <button
            type="button"
            className="left-sidebar-collapsed-icon-btn"
            onClick={onNewConversation}
            aria-label="محادثة جديدة"
            title="محادثة جديدة"
          >
            <PlusIcon />
          </button>
          <button
            type="button"
            className="left-sidebar-collapsed-icon-btn"
            onClick={() => {
              onToggleCollapse?.();
              setSearchQuery('');
            }}
            aria-label="بحث في المحادثات"
            title="بحث في المحادثات"
          >
            <SearchIcon />
          </button>
          <button
            type="button"
            className="left-sidebar-collapsed-icon-btn"
            onClick={onToggleCollapse}
            aria-label="إظهار الشريط الجانبي"
            title="إظهار الشريط الجانبي"
          >
            <PanelRightIcon />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="left-sidebar">
      <div className="left-sidebar-header">
        <button
          type="button"
          className="left-sidebar-close-btn"
          onClick={onCloseSidebar}
          aria-label="إغلاق الشريط الجانبي"
          title="إغلاق الشريط الجانبي"
        >
          <CloseIcon />
        </button>
        <button
          type="button"
          className="left-sidebar-collapse-btn"
          onClick={onToggleCollapse}
          aria-label="طي الشريط الجانبي"
          title="طي الشريط الجانبي"
        >
          <PanelLeftIcon />
        </button>
        <img
          src="/images/wareed-logo.png"
          alt="  "
          className="left-sidebar-logo"
        />
      </div>

      <button className="new-chat-btn" onClick={onNewConversation} dir="rtl">
        <span className="new-chat-btn-text">محادثة جديدة</span>
        <span className="new-chat-btn-icon">
          <PlusIcon />
        </span>
      </button>

      <div className="left-sidebar-search">
        <span className="left-sidebar-search-icon" aria-hidden="true">
          <SearchIcon />
        </span>
        <input
          type="search"
          className="left-sidebar-search-input"
          placeholder="بحث في المحادثات..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          aria-label="بحث في المحادثات"
        />
      </div>

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

      <div className="left-sidebar-chat-section">
        <div className="left-sidebar-chat-title" dir="auto">{formatArabicText('المحادثات السابقة')}</div>
        <div className="conversations-list">
        {isLoading ? (
          <div className="sidebar-skeleton">
            <div className="sidebar-skeleton-item" />
            <div className="sidebar-skeleton-item" />
            <div className="sidebar-skeleton-item" />
          </div>
        ) : conversations.length === 0 ? (
          <div className="empty-state arabic-text" dir="auto">
            <p>{formatArabicText('لا توجد محادثات')}</p>
          </div>
        ) : filteredConversations.length === 0 ? (
          <div className="empty-state arabic-text" dir="auto">
            <p>{formatArabicText('لا توجد نتائج للبحث')}</p>
          </div>
        ) : (
          sortedConversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${conv.id === currentConversationId ? 'active' : ''}`}
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
                {pinnedConversationIds.includes(conv.id) && (
                  <span className="conversation-pin-indicator" title="مثبتة">📌</span>
                )}
                <div className="conversation-title">{conv.title || 'محادثة جديدة'}</div>
              </div>
              <button
                type="button"
                className="chat-item-dots-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  dotsAnchorRef.current = e.currentTarget;
                  setDropdownConvId(dropdownConvId === conv.id ? null : conv.id);
                }}
                aria-label="خيارات المحادثة"
                aria-haspopup="menu"
                aria-expanded={dropdownConvId === conv.id}
              >
                <ThreeDotsIcon />
              </button>
            </div>
          ))
        )}
        </div>
      </div>

      <div className="left-sidebar-footer" ref={footerRef}>
        <button
          type="button"
          className="left-sidebar-name-trigger"
          onClick={() => setUserPanelExpanded((v) => !v)}
          aria-expanded={userPanelExpanded}
          aria-label="فتح قائمة المستخدم"
        >
          <span className="left-sidebar-name-text">{user?.display_name || user?.username || getUserName(userEmail)}</span>
          <span className="left-sidebar-name-avatar">
            {user?.avatar_url ? (
              <img src={user.avatar_url.startsWith('/') ? user.avatar_url : `/${user.avatar_url}`} alt="" />
            ) : (
              getInitials(userEmail)
            )}
          </span>
        </button>
        {userPanelExpanded && (
          <div className="left-sidebar-user-panel-popup">
            <UserPanel
              user={user}
              userEmail={userEmail}
              theme={theme}
              onThemeChange={onThemeChange}
              onLogout={onLogout}
              onCloseSidebar={onCloseSidebar}
              onOpenEditProfile={() => {
                setEditProfileOpen(true);
                setUserPanelExpanded(false);
              }}
            />
          </div>
        )}
      </div>

      {editProfileOpen && (
        <EditProfileModal
          user={user}
          onClose={() => setEditProfileOpen(false)}
          onProfileUpdated={onProfileUpdated}
        />
      )}

      {dropdownConvId && (
        <ChatItemDropdown
          isOpen={!!dropdownConvId}
          onClose={() => setDropdownConvId(null)}
          anchorRef={dotsAnchorRef}
          conversation={sortedConversations.find((c) => c.id === dropdownConvId)}
          onShare={(conv) => {
            setShareConv(conv);
            setDropdownConvId(null);
          }}
          onRename={(conv) => {
            setRenameConv(conv);
            setDropdownConvId(null);
          }}
          onPin={(conv) => {
            if (conv?.id) onPinConversation?.(conv.id);
          }}
          onArchive={(conv) => {
            if (window.confirm('هل تريد أرشفة هذه المحادثة؟')) {
              onDeleteConversation(conv.id);
            }
          }}
          onDelete={(conv) => {
            const title = conv?.title || 'هذه المحادثة';
            if (window.confirm(`هل أنت متأكد من حذف "${title}"؟`)) {
              onDeleteConversation(conv.id);
            }
          }}
        />
      )}

      {shareConv && (
        <ShareModal
          isOpen={!!shareConv}
          onClose={() => setShareConv(null)}
          conversation={shareConv}
        />
      )}

      {renameConv && (
        <RenameModal
          conversation={renameConv}
          onClose={() => setRenameConv(null)}
          onSave={(newTitle) => {
            if (onRenameConversation && newTitle?.trim()) {
              onRenameConversation(renameConv.id, newTitle.trim());
            }
            setRenameConv(null);
          }}
        />
      )}
    </div>
  );
};

export default LeftSidebar;
