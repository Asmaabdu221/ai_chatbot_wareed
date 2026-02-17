import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { login } from '../services/api';
import { setTokens, isAuthenticated } from '../services/auth';
import { getErrorMessage } from '../utils/errorUtils';
import './Login.css';

function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isAuthenticated()) navigate('/', { replace: true });
  }, [navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!email.trim() || !password) {
      setError('يرجى إدخال البريد الإلكتروني وكلمة المرور.');
      return;
    }
    setLoading(true);
    try {
      const data = await login(email.trim(), password);
      setTokens(data.access_token, data.refresh_token);
      navigate('/', { replace: true });
      window.location.reload();
    } catch (err) {
      setError(getErrorMessage(err, 'فشل تسجيل الدخول. يرجى المحاولة مرة أخرى.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page" dir="rtl">
      <div className="auth-card">
        <div className="auth-header">
          <img src="/images/wareed-logo.png" alt="وريد" className="auth-logo" />
          <h1>تسجيل الدخول</h1>
          <p>مختبرات وريد الطبية</p>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          {error && <div className="auth-error">{error}</div>}
          <label>
            البريد الإلكتروني
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="example@email.com"
              autoComplete="email"
              disabled={loading}
            />
          </label>
          <label>
            كلمة المرور
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
              disabled={loading}
            />
          </label>
          <button type="submit" className="auth-submit" disabled={loading}>
            {loading ? 'جاري الدخول...' : 'دخول'}
          </button>
        </form>

        <p className="auth-switch">
          ليس لديك حساب؟ <Link to="/register">إنشاء حساب</Link>
        </p>
      </div>
    </div>
  );
}

export default Login;
