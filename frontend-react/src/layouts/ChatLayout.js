/**
 * ChatLayout - Main chat UI structure.
 * Sidebar on LEFT, main chat on right. Flexbox-based, responsive.
 */

import React from 'react';
import './ChatLayout.css';

const ChatLayout = ({ sidebar, sidebarOpen, sidebarCollapsed, onCloseSidebar, children }) => {
  return (
    <div className="chat-layout">
      <main className="chat-layout-main">{children}</main>
      <aside className={`chat-layout-sidebar ${sidebarOpen ? 'open' : ''} ${sidebarCollapsed ? 'collapsed' : ''}`}>{sidebar}</aside>
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
