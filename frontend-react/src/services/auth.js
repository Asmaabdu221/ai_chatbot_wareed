/**
 * Auth service: JWT storage (localStorage), login, register, refresh, getMe.
 * Platform-agnostic (Web); same flow for mobile when implemented.
 */

const ACCESS_TOKEN_KEY = 'wareed_access_token';
const REFRESH_TOKEN_KEY = 'wareed_refresh_token';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens(accessToken, refreshToken) {
  if (accessToken) localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  if (refreshToken) localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearAuth() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

export function isAuthenticated() {
  return !!getAccessToken();
}
