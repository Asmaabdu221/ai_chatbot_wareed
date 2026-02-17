import React from 'react';
import './SettingsPanel.css';

const SettingsPanel = ({
  isOpen,
  onClose,
  theme,
  onThemeChange,
  userEmail,
  onClearChats,
  onLogout,
  appVersion = 'v1.0.0',
}) => {
  return (
    <div className={`settings-overlay ${isOpen ? 'open' : ''}`} aria-hidden={!isOpen}>
      <div className="settings-panel" role="dialog" aria-modal="true">
        <div className="settings-header">
          <h3>الإعدادات</h3>
          <button className="settings-close" onClick={onClose} aria-label="إغلاق">
            ✕
          </button>
        </div>

        <div className="settings-section">
          <div className="settings-title">المظهر</div>
          <div className="settings-options">
            <label className="settings-radio">
              <input
                type="radio"
                name="theme"
                value="system"
                checked={theme === 'system'}
                onChange={() => onThemeChange('system')}
              />
              <span>افتراضي النظام</span>
            </label>
            <label className="settings-radio">
              <input
                type="radio"
                name="theme"
                value="light"
                checked={theme === 'light'}
                onChange={() => onThemeChange('light')}
              />
              <span>فاتح</span>
            </label>
            <label className="settings-radio">
              <input
                type="radio"
                name="theme"
                value="dark"
                checked={theme === 'dark'}
                onChange={() => onThemeChange('dark')}
              />
              <span>داكن</span>
            </label>
          </div>
        </div>

        <div className="settings-section">
          <div className="settings-title">اللغة</div>
          <select className="settings-select" disabled title="Coming soon">
            <option>العربية</option>
            <option>English (Coming soon)</option>
          </select>
        </div>

        <div className="settings-section">
          <div className="settings-title">الحساب</div>
          <div className="settings-row">
            <span>البريد الإلكتروني</span>
            <span className="settings-value">{userEmail || '—'}</span>
          </div>
        </div>

        <div className="settings-section">
          <div className="settings-title">المحادثات</div>
          <button className="settings-button" onClick={onClearChats}>
            مسح المحادثات 
          </button>
        </div>

        <div className="settings-section">
          <button className="settings-button danger" onClick={onLogout}>
            تسجيل الخروج
          </button>
        </div>

        <div className="settings-footer">
          <span>الإصدار</span>
          <span className="settings-value">{appVersion}</span>
        </div>
      </div>
      <button className="settings-backdrop" onClick={onClose} aria-label="إغلاق" />
    </div>
  );
};

export default SettingsPanel;
