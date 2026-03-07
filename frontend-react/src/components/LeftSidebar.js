/**
 * LeftSidebar - Previous chats sidebar on the LEFT.
 * User name at bottom (clickable). Expandable user panel within sidebar.
 */

import React, { useState, useEffect, useRef } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { formatArabicText } from '../utils/arabicFormatters';
import { getErrorMessage } from '../utils/errorUtils';
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

const getAvatarSrcWithVersion = (user) => {
  const raw = user?.avatar_url;
  if (!raw) return null;
  const version = Date.now();
  const sep = raw.includes('?') ? '&' : '?';
  return `${raw}${sep}t=${encodeURIComponent(version)}`;
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
  const avatarSrc = getAvatarSrcWithVersion(user);

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

const QUICK_ACTION_PROMPTS = [
  { label: '\u0627\u0636\u0641 \u0635\u0648\u0631\u0629 \u0648\u0648\u0635\u0641\u0629 \u0637\u0628\u064a\u0629', message: '\u0623\u0631\u063a\u0628 \u0628\u0631\u0641\u0639 \u0635\u0648\u0631\u0629 \u0623\u0648 \u0645\u0644\u0641 \u062a\u062d\u0644\u064a\u0644/\u0648\u0635\u0641\u0629 \u0637\u0628\u064a\u0629.' },
  { label: '\u0627\u0633\u062a\u0639\u0644\u0645 \u0639\u0646 \u0627\u0644\u0623\u0633\u0639\u0627\u0631', message: '\u0623\u0631\u064a\u062f \u0627\u0644\u0627\u0633\u062a\u0639\u0644\u0627\u0645 \u0639\u0646 \u0627\u0644\u0623\u0633\u0639\u0627\u0631.' },
  { label: '\u0628\u0627\u0642\u0627\u062a \u0648\u0631\u064a\u062f', message: '\u0623\u0631\u064a\u062f \u0645\u0639\u0631\u0641\u0629 \u0628\u0627\u0642\u0627\u062a \u0648\u0631\u064a\u062f.' },
  { label: '\u0634\u0631\u062d \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0644\u064a\u0644', message: '\u0623\u0631\u064a\u062f \u0634\u0631\u062d \u0646\u062a\u0627\u0626\u062c \u0627\u0644\u062a\u062d\u0644\u064a\u0644.' },
];

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
  onQuickAction,
  isLoading,
  showDashboardLink = false,
  isDrawerMode = false,
}) => {
  const location = useLocation();
  const isChat = location.pathname === '/' || location.pathname === '';
  const [userPanelExpanded, setUserPanelExpanded] = useState(false);
  const [editProfileOpen, setEditProfileOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [dropdownConvId, setDropdownConvId] = useState(null);
  const [shareConv, setShareConv] = useState(null);
  const [renameConv, setRenameConv] = useState(null);
  const [quickActionError, setQuickActionError] = useState(null);
  const dotsAnchorRef = useRef(null);
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

  const showCollapsed = sidebarCollapsed && !isDrawerMode;

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

  const handleCloseSidebarClick = () => {
    if (process.env.NODE_ENV === 'development') {
      console.log('SIDEBAR_CLOSE_CLICKED');
    }
    onCloseSidebar?.();
  };

  const handleConversationSelect = (conversationId) => {
    if (isDrawerMode) onCloseSidebar?.();
    onSelectConversation(conversationId);
  };


  const handleQuickAction = async (message) => {
    if (!onQuickAction) return;
    const text = typeof message === 'string' ? message.trim() : '';
    if (!text) {
      setQuickActionError('محتوى الرسالة مطلوب.');
      return;
    }

    setQuickActionError(null);
    try {
      if (process.env.NODE_ENV === 'development') {
        console.info('[QuickAction] sending:', { message: text });
      }
      await onQuickAction(text);
      if (isDrawerMode) onCloseSidebar?.();
    } catch (err) {
      console.error('[QuickAction] send failed:', err);
      setQuickActionError(getErrorMessage(err, 'تعذر إرسال الرسالة. حاول مرة أخرى.'));
    }
  };

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
          onClick={handleCloseSidebarClick}
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
          alt="مختبرات وريد"
          className="left-sidebar-logo"
          onClick={onNewConversation}
          title="بدء محادثة جديدة"
          style={{ cursor: 'pointer' }}
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

      <div className="left-sidebar-quick-actions" dir="rtl">
        {QUICK_ACTION_PROMPTS.map((action) => (
          <button
            key={action.label}
            type="button"
            className="left-sidebar-quick-action-btn"
            onClick={() => { void handleQuickAction(action.message); }}
          >
            {action.label}
          </button>
        ))}
        {quickActionError && (
          <div className="left-sidebar-quick-action-error" role="alert" dir="auto">
            {quickActionError}
          </div>
        )}
      </div>

      {showDashboardLink && (
        <div className="sidebar-nav">
          <Link className={`nav-link ${isChat ? 'active' : ''}`} to="/" onClick={() => isDrawerMode && onCloseSidebar?.()}>
            المحادثات
          </Link>
          <Link className={`nav-link ${!isChat ? 'active' : ''}`} to="/admin/dashboard" onClick={() => isDrawerMode && onCloseSidebar?.()}>
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
                onClick={() => handleConversationSelect(conv.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleConversationSelect(conv.id);
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
              <img src={getAvatarSrcWithVersion(user)} alt="" />
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
              onDeleteConversation ? onDeleteConversation(conv.id) : (process.env.NODE_ENV === 'development' && console.error('[Sidebar] onDeleteConversation is not provided'));
            }
          }}
          onDelete={(conv) => {
            const title = conv?.title || 'هذه المحادثة';
            if (window.confirm(`هل أنت متأكد من حذف "${title}"؟`)) {
              onDeleteConversation ? onDeleteConversation(conv.id) : (process.env.NODE_ENV === 'development' && console.error('[Sidebar] onDeleteConversation is not provided'));
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

