import { isSupabaseAuth, refreshCloudAccess, invalidateAuthAttempts } from '@/lib/supabaseAuth';
import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';
import { tokenStore, tokenAuthority, type AuthoritySnapshot } from '@/lib/token';
import { toast } from '@/store/uiStore';
import { API_BASE, apiUrl } from './apiUrl';

// API base URL — baked in at build time so the same image runs anywhere.
// Default '/api/v1' works for same-origin (SPA + API behind one nginx).
// For split deployments, build with VITE_API_BASE=https://api.example.com/api/v1.
export const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  // The Gmail authorize response sets one path-scoped HttpOnly OAuth-state
  // cookie. Split frontend/API deployments must accept it; normal API calls
  // still authenticate with the explicit Bearer token.
  withCredentials: true,
});

interface RetryConfig extends AxiosRequestConfig {
  _retry?: boolean;
  _authority?: AuthoritySnapshot;
}
const staleAuthority = () => new Error('账号会话已变化，请在当前账号下重新操作');
function canRetry(snapshot: AuthoritySnapshot, token: string | null): boolean {
  return !!token && tokenStore.matches(snapshot) && snapshot.identity === tokenAuthority(token);
}

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const request = config as InternalAxiosRequestConfig & RetryConfig;
  const token = tokenStore.getAccess();
  if (token && !config.headers.has('Authorization')) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  const sent = String(config.headers.get('Authorization') ?? '').replace(/^Bearer /, '') || null;
  if (request._retry) {
    if (!request._authority || !canRetry(request._authority, sent)) throw staleAuthority();
  } else {
    request._authority = { ...tokenStore.snapshot(), identity: tokenAuthority(sent) };
  }
  return config;
}, error => { throw error; }, { synchronous: true });

// A refresh flight belongs to an immutable account/session epoch. Requests
// from A may never join B's refresh or replay A's mutation as B.
const refreshFlights = new Map<string, Promise<string | null>>();
async function refreshAccessToken(rejectedAccess: string | null, snapshot: AuthoritySnapshot): Promise<string | null> {
  if (!canRetry(snapshot, rejectedAccess)) throw staleAuthority();
  const key = JSON.stringify(snapshot);
  const existing = refreshFlights.get(key);
  if (existing) return existing;
  const rotate = async (): Promise<string | null> => {
    if (!canRetry(snapshot, rejectedAccess)) throw staleAuthority();
    // A same-authority rotation may already have completed in another tab.
    const current = tokenStore.getAccess();
    if (current !== rejectedAccess) return current;
    if (isSupabaseAuth()) return refreshCloudAccess(rejectedAccess);
    const ticket = tokenStore.getRefresh();
    if (!ticket) return null;
    try {
      const res = await axios.post(apiUrl('/auth/refresh'), { refresh_token: ticket }, { timeout: 10_000 });
      const access = res.data?.access_token as string | undefined;
      const newRefresh = res.data?.refresh_token as string | undefined;
      if (!access || !newRefresh) throw new Error('登录服务响应不完整，请稍后重试');
      if (!canRetry(snapshot, rejectedAccess)) throw staleAuthority();
      if (tokenStore.getRefresh() !== ticket) return tokenStore.getAccess();
      if (tokenAuthority(access) !== snapshot.identity) throw staleAuthority();
      tokenStore.set(access, newRefresh);
      return access;
    } catch (error) {
      if (!canRetry(snapshot, rejectedAccess)) throw staleAuthority();
      if (axios.isAxiosError(error) && error.response?.status === 401) {
        return tokenStore.getRefresh() !== ticket ? tokenStore.getAccess() : null;
      }
      throw error;
    }
  };
  // Web Locks also serialize one-time local refresh tickets across tabs.
  const pending = (navigator.locks && !isSupabaseAuth()
    ? navigator.locks.request('interview-copilot-token-refresh', rotate)
    : rotate()
  ).then(fresh => {
    if (!tokenStore.matches(snapshot) || (fresh && !canRetry(snapshot, fresh))) throw staleAuthority();
    return fresh;
  }).finally(() => { refreshFlights.delete(key); });
  refreshFlights.set(key, pending);
  return pending;
}

/**
 * Clear tokens and bounce to /auth after either transport fails to refresh.
 */
function redirectToAuth(rejectedAccess: string | null, snapshot: AuthoritySnapshot) {
  // A late failure from A must not clear a newer B session.
  if (!tokenStore.matches(snapshot) || tokenStore.getAccess() !== rejectedAccess) return;
  invalidateAuthAttempts();
  tokenStore.clear();
  if (window.location.pathname !== '/auth') {
    window.location.href = '/auth';
  }
}

/**
 * ``fetch()`` wrapper that mirrors :data:`apiClient`'s auth flow for paths
 * that can't use axios (SSE streams, anything reading the response body
 * as a ReadableStream frame-by-frame). Behavior:
 *
 *   - Attaches the current access token as ``Authorization: Bearer`` if
 *     not already present in ``init.headers``.
 *   - On 401, calls :func:`refreshAccessToken` once and retries.
 *   - If refresh fails (no refresh token / refresh endpoint rejected),
 *     calls :func:`redirectToAuth` and throws.
 *
 * Only ONE refresh attempt per call site — if the SECOND fetch also
 * returns 401 we let that surface as-is rather than looping. A second
 * 401 right after a successful refresh means the backend is invalidating
 * our brand-new token, which is its own bug; auto-retrying again would
 * mask it.
 */
export async function authedFetch(
  input: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has('Authorization') && tokenStore.getAccess()) headers.set('Authorization', `Bearer ${tokenStore.getAccess()}`);
  const rejectedAccess = (headers.get('Authorization') ?? '').replace(/^Bearer /, '') || null;
  const snapshot = { ...tokenStore.snapshot(), identity: tokenAuthority(rejectedAccess) };
  let resp = await fetch(input, { ...init, headers });
  if (resp.status === 401) {
    const fresh = await refreshAccessToken(rejectedAccess, snapshot);
    if (!fresh) {
      redirectToAuth(rejectedAccess, snapshot);
      throw new Error('登录状态已失效，请重新登录');
    }
    if (!canRetry(snapshot, fresh)) throw staleAuthority();
    // Force the approved token, never reread a possibly different account.
    headers.set('Authorization', `Bearer ${fresh}`);
    resp = await fetch(input, { ...init, headers });
  }
  return resp;
}

apiClient.interceptors.response.use(
  (r) => r,
  async (error: AxiosError<{ detail?: string | { code?: string; message?: string } }>) => {
    const status = error.response?.status;
    const original = (error.config ?? {}) as RetryConfig;
    const rejectedAccess = String(original.headers?.Authorization ?? '').replace(/^Bearer /, '') || null;
    const snapshot = original._authority ?? { epoch: null, identity: tokenAuthority(rejectedAccess) };
    const detail = error.response?.data?.detail;
    if (status === 409 && detail && typeof detail === 'object' && 'code' in detail && detail.code === 'LOCAL_PROFILE_REQUIRED') {
      if (window.location.pathname !== '/auth') window.location.href = '/auth';
      return Promise.reject(error);
    }

    // Wrong passwords/enrollment failures are not refresh requests. Replaying
    // these can consume lockout attempts or turn a rejected action into success.
    const credentialOperation = /\/auth\/(?:login|register|local-unlock(?:\/setup)?|supabase\/session|logout)$/.test(original.url ?? '');
    if (status === 401 && credentialOperation) return Promise.reject(error);
    if (status === 401 && !original._retry) {
      original._retry = true;
      const newToken = await refreshAccessToken(rejectedAccess, snapshot);
      if (newToken) {
        if (!canRetry(snapshot, newToken)) throw staleAuthority();
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` };
        return apiClient.request(original);
      }
      redirectToAuth(rejectedAccess, snapshot);
      return Promise.reject(error);
    }
    if (status === 401) {
      redirectToAuth(rejectedAccess, snapshot);
    } else if (status === 429) {
      toast.warn('请求过于频繁，请稍后再试');
    }
    // 4xx and 5xx are surfaced to call-sites via Promise.reject so they can
    // decide their own toast wording. We do not auto-toast 5xx anymore —
    // the call-site has more context (e.g. "删除失败" vs "对话创建失败").
    return Promise.reject(error);
  },
);

/** FastAPI error detail: a plain string, or a structured `{code, message}`
 *  body (used by auth conflict responses like EMAIL_ALREADY_REGISTERED). */
type ErrDetail = string | { code?: string; message?: string };

export function extractErr(e: unknown, fallback = '请求失败'): string {
  const ax = e as AxiosError<{ detail?: ErrDetail }>;
  const detail = ax?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object' && detail.message) return detail.message;
  return ax?.message ?? fallback;
}
