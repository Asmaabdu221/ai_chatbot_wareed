import React, { useState, useEffect, useCallback, useLayoutEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import ChatLayout from './layouts/ChatLayout';
import AdminLayout from './layouts/AdminLayout';
import LeftSidebar from './components/LeftSidebar';
import ChatWindow from './components/ChatWindow';
import Login from './components/Login';
import Register from './components/Register';
import Dashboard from './components/Dashboard';
import Help from './components/Help';
import { formatArabicText } from './utils/arabicFormatters';
import { isAdminUser } from './utils/adminUtils';
import {
  checkAPIHealth,
  setOnUnauthorized,
  getUserConversations,
  getConversationMessages,
  createConversation,
  sendConversationMessage,
  savePrescriptionMessages,
  deleteConversation as apiDeleteConversation,
  updateConversation as apiUpdateConversation,
  getMe,
  getApiUrlForDisplay,
} from './services/api';
import { getAccessToken, clearAuth } from './services/auth';
import './App.css';
import './layouts/ChatLayout.css';

function ChatView() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentMessages, setCurrentMessages] = useState([]);
  const [isAPIHealthy, setIsAPIHealthy] = useState(true);
  const [isLoading, setIsLoading] = useState(true);
  const [isFetchingMessages, setIsFetchingMessages] = useState(false);
  const [user, setUser] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [theme, setTheme] = useState(localStorage.getItem('wareed_theme') || 'system');
  const [uiNotice, setUiNotice] = useState(null);
  const [pinnedConversationIds, setPinnedConversationIds] = useState(() => {
    try {
      const stored = localStorage.getItem('wareed_pinned_conversations');
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });

  const [pinnedMessageIds, setPinnedMessageIds] = useState([]);
  const [replyingToMessage, setReplyingToMessage] = useState(null);

  const currentConversation = conversations.find((c) => c.id === currentConversationId);

  const handlePinConversation = (conversationId) => {
    setPinnedConversationIds((prev) => {
      const next = prev.includes(conversationId)
        ? prev.filter((id) => id !== conversationId)
        : [...prev, conversationId];
      localStorage.setItem('wareed_pinned_conversations', JSON.stringify(next));
      return next;
    });
  };

  const handleDeleteMessage = (messageId) => {
    if (window.confirm('هل تريد حذف هذه الرسالة؟')) {
      setCurrentMessages((prev) => prev.filter((m) => m.id !== messageId));
    }
  };

  const handlePinMessage = (messageId) => {
    setPinnedMessageIds((prev) =>
      prev.includes(messageId) ? prev.filter(id => id !== messageId) : [...prev, messageId]
    );
  };

  const selectConversation = async (conversationId) => {
    try {
      setIsFetchingMessages(true);
      setCurrentConversationId(conversationId);
      const data = await getConversationMessages(conversationId);
      const list = data.messages || [];
      setCurrentMessages(list.map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        created_at: m.created_at,
        token_count: m.token_count,
        replyTo: m.reply_to // Support if backend provides it
      })));
      setSidebarOpen(false);
      setUiNotice(null);
    } catch (err) {
      console.error('Failed to load messages:', err);
      setCurrentMessages([]);
      setUiNotice('تعذر تحميل الرسائل حالياً. تحقق من الاتصال ثم حاول مرة أخرى.');
    } finally {
      setIsFetchingMessages(false);
    }
  };

  const createNewConversation = () => {
    setCurrentConversationId(null);
    setCurrentMessages([]);
    setReplyingToMessage(null);
  };

  const handleDeleteConversation = async (conversationId) => {
    if (!conversationId) return;
    try {
      await apiDeleteConversation(conversationId);

      const remaining = conversations.filter((c) => c.id !== conversationId);
      setConversations(remaining);

      setPinnedConversationIds((prev) => {
        const next = prev.filter((id) => id !== conversationId);
        localStorage.setItem('wareed_pinned_conversations', JSON.stringify(next));
        return next;
      });

      if (currentConversationId === conversationId) {
        if (remaining.length > 0) {
          await selectConversation(remaining[0].id);
        } else {
          createNewConversation();
        }
      }

      setUiNotice(null);
    } catch (err) {
      console.error('Delete conversation error:', err);
      setUiNotice('تعذر حذف المحادثة. حاول مرة أخرى بعد قليل.');
    }
  };

  const handleSendMessage = async (content, attachment = null, attachmentType = null) => {
    const normalizedContent = typeof content === 'string' ? content.trim() : '';
    if (!normalizedContent && !attachment) {
      throw new Error('محتوى الرسالة مطلوب.');
    }

    let convId = currentConversationId;
    if (!convId) {
      const newConv = await createConversation();
      convId = newConv.id;
      setCurrentConversationId(convId);
      setConversations((prev) => [{ ...newConv, message_count: 0 }, ...prev]);
    }

    // Store reply metadata locally for UI linking only
    const replyRef = replyingToMessage ? {
      content: replyingToMessage.content,
      role: replyingToMessage.role
    } : null;

    if (process.env.NODE_ENV === 'development') {
      console.info('[Chat] Sending message', {
        conversationId: convId,
        hasAttachment: !!attachment,
        attachmentType: attachmentType || null,
        contentLength: normalizedContent.length,
      });
    }

    const data = await sendConversationMessage(convId, normalizedContent, attachment, attachmentType);
    const userMsg = {
      id: data.user_message.id,
      role: 'user',
      content: data.user_message.content,
      created_at: data.user_message.created_at,
      replyTo: replyRef // UI-only link
    };
    const assistantMsg = {
      id: data.assistant_message.id,
      role: 'assistant',
      content: data.assistant_message.content,
      created_at: data.assistant_message.created_at,
      token_count: data.assistant_message.token_count,
    };
    setCurrentMessages((prev) => [...prev, userMsg, assistantMsg]);
    setReplyingToMessage(null);
  };

  const handleQuickAction = async (content) => {
    await handleSendMessage(content);
    if (typeof window !== 'undefined') {
      window.dispatchEvent(new CustomEvent('wareed:focus-composer'));
    }
  };

  const handlePrescriptionResponse = async (userContent, assistantContent) => {
    let convId = currentConversationId;
    if (!convId) {
      const newConv = await createConversation();
      convId = newConv.id;
      setCurrentConversationId(convId);
      setConversations((prev) => [{ ...newConv, message_count: 0 }, ...prev]);
    }
    const data = await savePrescriptionMessages(convId, userContent, assistantContent);
    const userMsg = {
      id: data.user_message.id,
      role: 'user',
      content: data.user_message.content,
      created_at: data.user_message.created_at,
    };
    const assistantMsg = {
      id: data.assistant_message.id,
      role: 'assistant',
      content: data.assistant_message.content,
      created_at: data.assistant_message.created_at,
      token_count: data.assistant_message.token_count,
    };
    setCurrentMessages((prev) => [...prev, userMsg, assistantMsg]);
  };

  const handleClearChats = () => {
    if (window.confirm('سيتم مسح المحادثات محلياً فقط. هل أنت متأكد؟')) {
      setConversations([]);
      setCurrentConversationId(null);
      setCurrentMessages([]);
    }
  };

  const handleLogout = () => {
    clearAuth();
    navigate('/login', { replace: true });
    window.location.reload();
  };

  const loadConversations = useCallback(async () => {
    try {
      const data = await getUserConversations();
      setConversations(data.conversations || []);
    } catch (err) {
      console.error('Failed to load conversations:', err);
      setConversations([]);
    }
  }, []);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const resolved = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme;
    root.setAttribute('data-theme', resolved);
  }, [theme]);

  useEffect(() => {
    const TIMEOUT_MS = 8000;
    const init = async () => {
      const healthy = await checkAPIHealth();
      setIsAPIHealthy(healthy);
      const me = await getMe();
      setUser(me);
      await loadConversations();
      setIsLoading(false);
    };
    init();
  }, [loadConversations]);

  const sidebar = (
    <LeftSidebar
      conversations={conversations}
      pinnedConversationIds={pinnedConversationIds}
      currentConversationId={currentConversationId}
      onSelectConversation={selectConversation}
      onNewConversation={createNewConversation}
      onDeleteConversation={handleDeleteConversation}
      onLogout={handleLogout}
      onCloseSidebar={() => setSidebarOpen(false)}
      onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      sidebarCollapsed={sidebarCollapsed}
      user={user}
      userEmail={user?.email}
      theme={theme}
      onThemeChange={(next) => { setTheme(next); localStorage.setItem('wareed_theme', next); }}
      onClearChats={handleClearChats}
      onProfileUpdated={(updatedUser) => {
        if (!updatedUser) return;
        setUser((prev) => {
          const nextUser = {
          ...(prev || {}),
          ...updatedUser,
          avatar_version: updatedUser.avatar_version || Date.now(),
          };
          console.log("[Avatar State] setUser next state:", {
            id: nextUser?.id,
            email: nextUser?.email,
            avatar_url: nextUser?.avatar_url,
            avatar_version: nextUser?.avatar_version,
          });
          return nextUser;
        });
      }}
      onQuickAction={handleQuickAction}
    />
  );

  if (isLoading) return <div className="app loading">جاري التحميل...</div>;

  return (
    <div className="app">
      {!isAPIHealthy && <div className="api-warning">⚠️ خطأ في الاتصال بالخادم</div>}
      <ChatLayout
        sidebar={sidebar}
        sidebarOpen={sidebarOpen}
        sidebarCollapsed={sidebarCollapsed}
        onCloseSidebar={() => setSidebarOpen(false)}
        onToggleSidebarCollapse={() => setSidebarCollapsed((v) => !v)}
      >
        <ChatWindow
          messages={currentMessages}
          onSendMessage={handleSendMessage}
          onReplyToMessage={setReplyingToMessage}
          onDeleteMessage={handleDeleteMessage}
          onPinMessage={handlePinMessage}
          pinnedMessageIds={pinnedMessageIds}
          replyingTo={replyingToMessage}
          onCancelReply={() => setReplyingToMessage(null)}
          userName={user?.display_name || user?.username}
          isFetchingMessages={isFetchingMessages}
          onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        />
      </ChatLayout>
    </div>
  );
}

function AdminDashboardView() {
  const navigate = useNavigate();
  const [user, setUser] = useState(null);
  useEffect(() => { getMe().then(setUser); }, []);
  return (
    <AdminLayout onLogout={() => { clearAuth(); navigate('/login'); }} userEmail={user?.email}>
      <Dashboard />
    </AdminLayout>
  );
}

function RequireAuth({ children }) {
  if (!getAccessToken()) return <Navigate to="/login" replace />;
  return children;
}

function App() {
  const navigate = useNavigate();
  useEffect(() => {
    setOnUnauthorized(() => { clearAuth(); navigate('/login'); });
  }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/" element={<RequireAuth><ChatView /></RequireAuth>} />
      <Route path="/admin/dashboard" element={<RequireAuth><AdminDashboardView /></RequireAuth>} />
      <Route path="/help" element={<RequireAuth><Help /></RequireAuth>} />
    </Routes>
  );
}

export default function AppWithRouter() {
  return <BrowserRouter><App /></BrowserRouter>;
}
