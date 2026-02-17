/**
 * Admin access utilities.
 * Role-based check: admin emails from REACT_APP_ADMIN_EMAILS (comma-separated).
 * When backend adds is_admin to User model, switch to API response.
 */

const ADMIN_EMAILS = (process.env.REACT_APP_ADMIN_EMAILS || '')
  .split(',')
  .map((e) => e.trim().toLowerCase())
  .filter(Boolean);

export function isAdminUser(user) {
  if (!user?.email) return false;
  const email = String(user.email).trim().toLowerCase();
  return ADMIN_EMAILS.includes(email);
}
