/**
 * Typed API client. Paths, parameters and bodies are checked against the backend's OpenAPI
 * document (src/api/schema.d.ts, regenerate with `npm run api:types`).
 *
 * Every request carries the access token. On a 401 the client refreshes the tokens once and
 * retries; parallel requests share one refresh (refresh tokens are single-use and rotated).
 */
import createClient from "openapi-fetch";

import { ApiError, toApiError } from "./errors";
import type { paths } from "./schema";
import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "./tokens";

type SessionListener = () => void;
const sessionEndedListeners = new Set<SessionListener>();

/** Called when the session can no longer be refreshed (the user must log in again). */
export function onSessionEnded(listener: SessionListener) {
  sessionEndedListeners.add(listener);
  return () => {
    sessionEndedListeners.delete(listener);
  };
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;
  const response = await fetch("/api/v1/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!response.ok) {
    clearTokens();
    return false;
  }
  const tokens = (await response.json()) as { access_token: string; refresh_token: string };
  setTokens(tokens.access_token, tokens.refresh_token);
  return true;
}

/** One refresh at a time: every request that hit a 401 waits for the same attempt. */
export function refreshOnce(): Promise<boolean> {
  if (!refreshing) {
    refreshing = refreshTokens().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

function withToken(request: Request): Request {
  const token = getAccessToken();
  if (!token) return request;
  const headers = new Headers(request.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return new Request(request, { headers });
}

async function authFetch(input: Request): Promise<Response> {
  const retry = input.clone();
  const response = await fetch(withToken(input));
  const isAuthCall = new URL(input.url).pathname.startsWith("/api/v1/auth/login");
  if (response.status !== 401 || isAuthCall) return response;

  if (await refreshOnce()) {
    return fetch(withToken(retry));
  }
  sessionEndedListeners.forEach((listener) => listener());
  return response;
}

export const api = createClient<paths>({
  baseUrl: window.location.origin,
  fetch: authFetch,
});

/**
 * Unwrap an openapi-fetch result: return the data or throw an ApiError.
 *   const patient = await unwrap(api.GET("/api/v1/patients/{patient_id}", {...}))
 */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    throw toApiError(response.status, error);
  }
  return data as T;
}

export { ApiError };
