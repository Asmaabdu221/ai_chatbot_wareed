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

  useLayoutEffect(() => {
    const root = document.documentElement;
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const resolved = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme;
    root.setAttribute('data-theme', resolved);
  }, [theme]);

  useEffect(() => {
    if (theme !== 'system' || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) => {
      document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [theme]);

  const loadConversations = useCallback(async () => {
    try {
      const data = await getUserConversations();
      setConversations(data.conversations || []);
    } catch (err) {
      console.error('Failed to load conversations:', err);
      setConversations([]);
    }
  }, []);

  useEffect(() => {
    const TIMEOUT_MS = 8000;
    const init = async () => {
      const timeoutPromise = new Promise((_, reject) =>
        setTimeout(() => reject(new Error('Init timeout')), TIMEOUT_MS)
      );
      try {
        await Promise.race([
          (async () => {
            const healthy = await checkAPIHealth();
            setIsAPIHealthy(healthy);
            const me = await getMe();
            setUser(me);
            await loadConversations();
          })(),
          timeoutPromise,
        ]);
      } catch (err) {
        console.error('Init error:', err);
        setIsAPIHealthy(false);
      } finally {
        setIsLoading(false);
      }
    };
    init();
  }, [loadConversations]);

  const convIdFromUrl = searchParams.get('c');
  useEffect(() => {
    if (!convIdFromUrl || isLoading || conversations.length === 0) return;
    const exists = conversations.some((c) => c.id === convIdFromUrl);
    if (exists && currentConversationId !== convIdFromUrl) {
      selectConversation(convIdFromUrl);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convIdFromUrl, isLoading, conversations.length]);

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
  };

  const handleDeleteConversation = async (conversationId) => {
    try {
      await apiDeleteConversation(conversationId);
      setPinnedConversationIds((prev) => {
        const next = prev.filter((id) => id !== conversationId);
        localStorage.setItem('wareed_pinned_conversations', JSON.stringify(next));
        return next;
      });
      setConversations((prev) => prev.filter((c) => c.id !== conversationId));
      if (currentConversationId === conversationId) {
        const rest = conversations.filter((c) => c.id !== conversationId);
        if (rest.length > 0) await selectConversation(rest[0].id);
        else createNewConversation();
      }
      setUiNotice(null);
    } catch (err) {
      console.error('Delete conversation error:', err);
      setUiNotice('تعذر حذف المحادثة. حاول مرة أخرى بعد قليل.');
    }
  };

  const handleRenameConversation = async (conversationId, newTitle) => {
    try {
      await apiUpdateConversation(conversationId, { title: newTitle });
      setConversations((prev) =>
        prev.map((c) => (c.id === conversationId ? { ...c, title: newTitle } : c))
      );
      setUiNotice(null);
    } catch (err) {
      console.error('Rename conversation error:', err);
      setUiNotice('تعذر إعادة تسمية المحادثة. حاول مرة أخرى.');
    }
  };

  const handleSendMessage = async (content) => {
    let convId = currentConversationId;
    if (!convId) {
      const newConv = await createConversation();
      convId = newConv.id;
      setCurrentConversationId(convId);
      setConversations((prev) => [{ ...newConv, message_count: 0 }, ...prev]);
    }
    const data = await sendConversationMessage(convId, content);
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

  if (isLoading) {
    return (
      <div className="app loading">
        <div className="loading-message">جاري التحميل...</div>
      </div>
    );
  }

  const handleThemeChange = (next) => {
    setTheme(next);
    localStorage.setItem('wareed_theme', next);
  };

  const handleProfileUpdated = (updatedUser) => {
    setUser(updatedUser);
  };

  const sidebar = (
    <LeftSidebar
      conversations={conversations}
      pinnedConversationIds={pinnedConversationIds}
      currentConversationId={currentConversationId}
      onSelectConversation={selectConversation}
      onNewConversation={createNewConversation}
      onDeleteConversation={handleDeleteConversation}
      onRenameConversation={handleRenameConversation}
      onPinConversation={handlePinConversation}
      onLogout={handleLogout}
      onCloseSidebar={() => setSidebarOpen(false)}
      onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
      sidebarCollapsed={sidebarCollapsed}
      user={user}
      userEmail={user?.email}
      theme={theme}
      onThemeChange={handleThemeChange}
      onClearChats={handleClearChats}
      onProfileUpdated={handleProfileUpdated}
      isLoading={isLoading}
      showDashboardLink={isAdminUser(user)}
    />
  );

  return (
    <div className="app">
      {!isAPIHealthy && (
        <div className="api-warning arabic-text" dir="auto">
          ⚠️ {formatArabicText(`تحذير: لا يمكن الاتصال بالخادم. تأكد من تشغيل الخادم على ${getApiUrlForDisplay()}`)}
        </div>
      )}
      {uiNotice && (
        <div className="ui-notice arabic-text" role="status" dir="auto">
          <span>{formatArabicText(uiNotice)}</span>
          <button
            type="button"
            className="ui-notice-close"
            onClick={() => setUiNotice(null)}
            aria-label="إغلاق التنبيه"
          >
            ✕
          </button>
        </div>
      )}
      <ChatLayout
        sidebar={sidebar}
        sidebarOpen={sidebarOpen}
        sidebarCollapsed={sidebarCollapsed}
        onCloseSidebar={() => setSidebarOpen(false)}
      >
        <ChatWindow
          conversationId={currentConversationId}
          conversationTitle={currentConversation?.title || 'محادثة جديدة'}
          messages={currentMessages}
          userId={user?.id}
          userEmail={user?.email}
          userName={user?.display_name || user?.username || (user?.email?.split('@')[0]) || null}
          onSendMessage={handleSendMessage}
          onPrescriptionResponse={handlePrescriptionResponse}
          isFetchingMessages={isFetchingMessages}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
          onArchiveConversation={handleDeleteConversation}
          onDeleteConversation={handleDeleteConversation}
          onPinConversation={handlePinConversation}
          pinnedConversationIds={pinnedConversationIds}
        />
      </ChatLayout>
    </div>
  );
}

function AdminDashboardView() {
  const navigate = useNavigate();
  const [theme, setTheme] = useState(localStorage.getItem('wareed_theme') || 'system');
  const [user, setUser] = useState(null);

  useLayoutEffect(() => {
    const root = document.documentElement;
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const resolved = theme === 'system' ? (prefersDark ? 'dark' : 'light') : theme;
    root.setAttribute('data-theme', resolved);
  }, [theme]);

  useEffect(() => {
    const load = async () => {
      try {
        const me = await getMe();
        setUser(me);
      } catch (_) {}
    };
    load();
  }, []);

  const handleLogout = () => {
    clearAuth();
    navigate('/login', { replace: true });
    window.location.reload();
  };

  return (
    <AdminLayout onLogout={handleLogout} userEmail={user?.email}>
      <Dashboard />
    </AdminLayout>
  );
}

function RequireAuth({ children }) {
  const hasToken = !!getAccessToken();
  if (!hasToken) return <Navigate to="/login" replace />;
  return children;
}

function RequireAdmin({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const me = await getMe();
        if (!cancelled) setUser(me);
      } catch (_) {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, []);

  if (loading) {
    return (
      <div className="app loading">
        <div className="loading-message">جاري التحميل...</div>
      </div>
    );
  }

  if (!getAccessToken() || !isAdminUser(user)) {
    return <Navigate to="/" replace />;
  }

  return children;
}

function App() {
  const navigate = useNavigate();
  useEffect(() => {
    setOnUnauthorized(() => {
      clearAuth();
      navigate('/login', { replace: true });
    });
    return () => setOnUnauthorized(null);
  }, [navigate]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <ChatView />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/dashboard"
        element={
          <RequireAuth>
            <RequireAdmin>
              <AdminDashboardView />
            </RequireAdmin>
          </RequireAuth>
        }
      />
      <Route
        path="/help"
        element={
          <RequireAuth>
            <Help />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

function AppWithRouter() {
  return (
    <BrowserRouter>
      <App />
    </BrowserRouter>
  );
}

export default AppWithRouter;
