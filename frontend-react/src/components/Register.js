import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../services/api';
import { setTokens, isAuthenticated } from '../services/auth';
import { getErrorMessage } from '../utils/errorUtils';
import './Login.css'; /* auth styles shared with Login */

function Register() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated()) navigate('/', { replace: true });
  }, [navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!name.trim() || !email.trim() || !password) {
      setError('يرجى ملء جميع الحقول المطلوبة.');
      return;
    }
    if (password.length < 8) {
      setError('كلمة المرور يجب أن تكون 8 أحرف على الأقل.');
      return;
    }
    if (password !== confirmPassword) {
      setError('كلمة المرور وتأكيدها غير متطابقين.');
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.post("/api/auth/register", {
        username: name.trim(), // Assuming username is used for full name in backend
        email,
        password,
      });
      setTokens(data.access_token, data.refresh_token);
      navigate('/', { replace: true });
      window.location.reload();
    } catch (err) {
      setError(getErrorMessage(err, 'فشل إنشاء الحساب. يرجى المحاولة مرة أخرى.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page" dir="rtl" style={{ backgroundImage: "url('/images/login-ramadan.png')" }}>
      <div className="auth-card">
        <div className="auth-header">
          <img src="/images/wareed-logo.png" alt="وريد" className="auth-logo" />
          <h1>إنشاء حساب</h1>
          <p>مختبرات وريد الطبية</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          {error && <div className="auth-error">{error}</div>}

          <label>
            الاسم الكامل
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="أدخل اسمك الكامل"
              disabled={loading}
              required
            />
          </label>

          <label>
            البريد الإلكتروني
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="user@email.com"
              autoComplete="email"
              disabled={loading}
              required
            />
          </label>

          <label>
            كلمة المرور (8 أحرف على الأقل)
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              disabled={loading}
              required
            />
          </label>

          <label>
            تأكيد كلمة المرور
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="new-password"
              disabled={loading}
              required
            />
          </label>

          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? 'جاري إنشاء الحساب...' : 'إنشاء حساب جديد'}
          </button>
        </form>

        <p className="auth-switch">
          لديك حساب بالفعل؟ <Link to="/login">تسجيل الدخول</Link>
        </p>
      </div>
    </div>
  );
}

export default Register;
