/**
 * Extract a user-friendly error message from API error responses.
 * Handles both string and FastAPI validation error (array) formats.
 *
 * FastAPI validation errors:
 * { "detail": [{ "type": "...", "loc": [...], "msg": "...", "input": ... }] }
 *
 * Simple errors:
 * { "detail": "Error message string" }
 */
export function getErrorMessage(err, fallback = 'حدث خطأ غير متوقع. يرجى المحاولة مرة أخرى.') {
  if (!err) return fallback;
  const detail = err.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0];
    if (first && typeof first.msg === 'string') return first.msg;
    if (first && typeof first === 'object') return JSON.stringify(first);
  }
  return err.message || fallback;
}
