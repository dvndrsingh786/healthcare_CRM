/**
 * Where the login tokens live.
 *
 * - The short-lived access token (15 minutes) is kept in memory only.
 * - The refresh token is kept in sessionStorage so a page reload does not log the user out.
 *   sessionStorage is per browser tab and cleared when the tab closes. It is readable by scripts
 *   on this page, so the app must never render untrusted HTML (React escapes by default).
 *   A stricter option for production is an httpOnly cookie set by the API (see README).
 */
const REFRESH_KEY = "hcrm.refresh_token";

let accessToken: string | null = null;

export function getAccessToken() {
  return accessToken;
}

export function getRefreshToken() {
  try {
    return sessionStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

export function setTokens(access: string, refresh: string) {
  accessToken = access;
  try {
    sessionStorage.setItem(REFRESH_KEY, refresh);
  } catch {
    // Storage unavailable (private mode): the session simply ends on reload.
  }
}

export function clearTokens() {
  accessToken = null;
  try {
    sessionStorage.removeItem(REFRESH_KEY);
  } catch {
    // ignore
  }
}
