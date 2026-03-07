/**
 * ChatLayout - Main chat UI structure.
 * Sidebar on LEFT, main chat on right. Flexbox-based, responsive.
 */

import React, { useEffect, useState } from 'react';
import './ChatLayout.css';

const DRAWER_BREAKPOINT = 1024;

const ChatLayout = ({
  sidebar,
  sidebarOpen,
  sidebarCollapsed,
  onCloseSidebar,
  onToggleSidebarCollapse,
  children,
}) => {
  const [isDrawerMode, setIsDrawerMode] = useState(
    () => typeof window !== 'undefined' && window.matchMedia?.(`(max-width: ${DRAWER_BREAKPOINT - 1}px)`)?.matches
  );

  useEffect(() => {
    const mq = window.matchMedia?.(`(max-width: ${DRAWER_BREAKPOINT - 1}px)`);
    if (!mq) return undefined;
    const handler = () => setIsDrawerMode(mq.matches);
    handler();
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  useEffect(() => {
    if (!isDrawerMode) return undefined;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = sidebarOpen ? 'hidden' : prevOverflow || '';
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [isDrawerMode, sidebarOpen]);

  useEffect(() => {
    if (!isDrawerMode || !sidebarOpen) return undefined;
    const onKeyDown = (e) => {
      if (e.key === 'Escape') onCloseSidebar?.();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isDrawerMode, onCloseSidebar, sidebarOpen]);

  return (
    <div className="chat-layout">
      <main className="chat-layout-main">{children}</main>
      <aside
        id="app-sidebar"
        className={`chat-layout-sidebar ${isDrawerMode ? 'drawer' : 'desktop'} ${sidebarOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}`}
        onClick={(e) => e.stopPropagation()}
        aria-hidden={isDrawerMode ? !sidebarOpen : undefined}
        aria-label="Sidebar navigation"
      >
        {sidebar}
      </aside>
      {sidebarCollapsed && !isDrawerMode && (
        <button
          type="button"
          className="chat-layout-floating-toggle"
          onClick={onToggleSidebarCollapse}
          aria-label="Show sidebar"
          title="Show sidebar"
        >
          Menu
        </button>
      )}
      <button
        type="button"
        className={`chat-layout-backdrop ${isDrawerMode && sidebarOpen ? 'visible' : ''}`}
        onClick={onCloseSidebar}
        aria-label="Close sidebar"
        aria-hidden={!isDrawerMode || !sidebarOpen}
      />
    </div>
  );
};

export default ChatLayout;

