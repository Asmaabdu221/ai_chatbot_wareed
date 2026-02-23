/**
 * ChatLayout - Main chat UI structure.
 * Sidebar on LEFT, main chat on right. Flexbox-based, responsive.
 */

import React, { useEffect } from 'react';
import './ChatLayout.css';

const ChatLayout = ({
  sidebar,
  sidebarOpen,
  sidebarCollapsed,
  onCloseSidebar,
  onToggleSidebarCollapse,
  children,
}) => {
  useEffect(() => {
    const isMobile = typeof window !== 'undefined' && window.innerWidth <= 768;
    if (!isMobile) return undefined;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = sidebarOpen ? 'hidden' : prevOverflow || '';
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [sidebarOpen]);

  return (
    <div className="chat-layout">
      <main className="chat-layout-main">{children}</main>
      <aside
        className={`chat-layout-sidebar ${sidebarOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}`}
        onClick={(e) => e.stopPropagation()}
      >
        {sidebar}
      </aside>
      {sidebarCollapsed && (
        <button
          type="button"
          className="chat-layout-floating-toggle"
          onClick={onToggleSidebarCollapse}
          aria-label="إظهار الشريط الجانبي"
          title="إظهار الشريط الجانبي"
        >
          ☰
        </button>
      )}
      <button
        type="button"
        className={`chat-layout-backdrop ${sidebarOpen ? 'visible' : ''}`}
        onClick={onCloseSidebar}
        aria-label="إغلاق القائمة"
        aria-hidden={!sidebarOpen}
      />
    </div>
  );
};

export default ChatLayout;
