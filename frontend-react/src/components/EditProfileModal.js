/**
 * EditProfileModal - نافذة تعديل الملف الشخصي
 * تحميل الصورة، تحديث الاسم واسم المستخدم، حفظ في قاعدة البيانات
 */

import React, { useState, useEffect, useRef } from 'react';
import { updateProfile, uploadAvatar, getMe } from '../services/api';
import { getErrorMessage } from '../utils/errorUtils';
import './EditProfileModal.css';

const getInitials = (displayName, email) => {
  if (displayName && displayName.length >= 2) {
    return displayName.slice(0, 2).toUpperCase();
  }
  if (email) {
    const part = email.split('@')[0];
    if (part.length >= 2) return part.slice(0, 2).toUpperCase();
    return part.toUpperCase();
  }
  return '?';
};

const CameraIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
    <circle cx="12" cy="13" r="4" />
  </svg>
);

const getAvatarSrc = (avatarUrl) => {
  if (!avatarUrl) return null;
  const version = Date.now();
  const sep = avatarUrl.includes('?') ? '&' : '?';
  return `${avatarUrl}${sep}t=${encodeURIComponent(version)}`;
};

const EditProfileModal = ({ user, onClose, onProfileUpdated }) => {
  const fileInputRef = useRef(null);
  const [displayNameVal, setDisplayNameVal] = useState('');
  const [usernameVal, setUsernameVal] = useState('');
  const [avatarUrl, setAvatarUrl] = useState(null);
  const [avatarPreview, setAvatarPreview] = useState(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const [error, setError] = useState(null);

  const displayName = user?.display_name || (user?.email ? user.email.split('@')[0] : '');
  const username = user?.username || (user?.email ? user.email.split('@')[0] : '');

  useEffect(() => {
    setDisplayNameVal(displayName || '');
    setUsernameVal(username || '');
    setAvatarUrl(user?.avatar_url || null);
    setAvatarPreview(null);
  }, [user, displayName, username]);

  const handleImageSelect = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const ext = (file.name || '').split('.').pop()?.toLowerCase();
    if (!['jpg', 'jpeg', 'png', 'webp'].includes(ext || '')) {
      setError('صيغة غير مدعومة. استخدم JPEG أو PNG أو WebP.');
      e.target.value = '';
      return;
    }
    setError(null);
    setAvatarPreview(URL.createObjectURL(file));
    setIsUploadingAvatar(true);
    try {
      const { avatar_url } = await uploadAvatar(file);
      console.log("[Avatar Upload] returned avatar_url:", avatar_url);
      setAvatarUrl(avatar_url);
      onProfileUpdated?.({
        ...(user || {}),
        avatar_url,
      });
    } catch (err) {
      setError(getErrorMessage(err, 'فشل رفع الصورة.'));
    } finally {
      setIsUploadingAvatar(false);
      e.target.value = '';
    }
  };

  const handleSave = async () => {
    setError(null);
    setIsSaving(true);
    try {
      await updateProfile(displayNameVal.trim() || null, usernameVal.trim() || null);
      const updated = await getMe();
      onProfileUpdated?.({
        ...updated,
      });
      onClose();
    } catch (err) {
      setError(getErrorMessage(err, 'فشل حفظ التغييرات.'));
    } finally {
      setIsSaving(false);
    }
  };

  const avatarSrc = avatarPreview || getAvatarSrc(avatarUrl);
  const initials = getInitials(displayNameVal || displayName, user?.email);

  return (
    <div className="edit-profile-modal-overlay" onClick={onClose}>
      <div className="edit-profile-modal" onClick={(e) => e.stopPropagation()} dir="rtl">
        <h2 className="edit-profile-title">تعديل الملف الشخصي</h2>

        <div className="edit-profile-avatar-wrap">
          <div className="edit-profile-avatar">
            {avatarSrc ? (
              <img src={avatarSrc} alt="" />
            ) : (
              initials
            )}
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/jpg,image/png,image/webp"
            onChange={handleFileChange}
            style={{ display: 'none' }}
            aria-hidden="true"
          />
          <button
            type="button"
            className="edit-profile-avatar-btn"
            onClick={handleImageSelect}
            disabled={isUploadingAvatar}
            aria-label="تغيير الصورة"
          >
            {isUploadingAvatar ? '...' : <CameraIcon />}
          </button>
        </div>

        <div className="edit-profile-field">
          <label htmlFor="edit-display-name">الاسم المعروض</label>
          <input
            id="edit-display-name"
            type="text"
            value={displayNameVal}
            onChange={(e) => setDisplayNameVal(e.target.value)}
            className="edit-profile-input"
          />
        </div>

        <div className="edit-profile-field">
          <label htmlFor="edit-username">اسم المستخدم</label>
          <input
            id="edit-username"
            type="text"
            value={usernameVal}
            onChange={(e) => setUsernameVal(e.target.value)}
            className="edit-profile-input"
          />
        </div>

        <p className="edit-profile-hint">
          يساعدك ملفك الشخصي على التعرف عليك. يتم استخدام اسمك واسم المستخدم أيضاً في تطبيق وريد.
        </p>

        {error && (
          <div className="edit-profile-error" role="alert">
            ⚠️ {error}
          </div>
        )}

        <div className="edit-profile-actions">
          <button type="button" className="edit-profile-cancel" onClick={onClose} disabled={isSaving}>
            إلغاء
          </button>
          <button type="button" className="edit-profile-save" onClick={handleSave} disabled={isSaving}>
            {isSaving ? 'جاري الحفظ...' : 'حفظ'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default EditProfileModal;
