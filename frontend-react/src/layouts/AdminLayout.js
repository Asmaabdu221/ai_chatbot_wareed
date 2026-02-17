/**
 * AdminLayout - Separate layout for admin dashboard.
 * No chat sidebar. Minimal header with logo and logout.
 * Only accessible via /admin/dashboard with role-based protection.
 */

import React from 'react';
import { Link } from 'react-router-dom';
import './AdminLayout.css';

const AdminLayout = ({ children, onLogout, userEmail }) => {
  return (
    <div className="admin-layout">
      <header className="admin-header">
        <div className="admin-header-left">
          <Link to="/" className="admin-logo-link" aria-label="العودة للمحادثات">
            <img
              src="/images/wareed-logo.png"
              alt="مختبرات وريد الطبية"
              className="admin-logo"
            />
          </Link>
          <span className="admin-badge">لوحة التحكم</span>
        </div>
        <div className="admin-header-right">
          {userEmail && (
            <span className="admin-user-email" title={userEmail}>
              {userEmail}
            </span>
          )}
          <button type="button" className="admin-logout-btn" onClick={onLogout}>
            تسجيل الخروج
          </button>
        </div>
      </header>
      <main className="admin-main">{children}</main>
    </div>
  );
};

export default AdminLayout;
