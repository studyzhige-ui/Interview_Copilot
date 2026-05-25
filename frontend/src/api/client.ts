import axios, { AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios';
import { tokenStore } from '@/lib/token';
import { toast } from '@/store/uiStore';

// API base URL — baked in at build time so the same image runs anywhere.
// Default '/api/v1' works for same-origin (SPA + API behind one nginx).
// For split deployments, build with VITE_API_BASE=https://api.example.com/api/v1.
const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1';

export const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
});

apiClient.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = tokenStore.getAccess();
  if (token) {
    config.headers.set('Authorization', `Bearer ${token}`);
  }
  return config;
});

interface RetryConfig extends AxiosRequestConfig {
  _retry?: boolean;
}

let refreshInFlight: Promise<string | null> | null = null;

/**
 * Refresh the access token using the stored refresh token.
 *
 * Exported so non-axios paths (notably ``streamChatSSE``, which uses
 * raw ``fetch`` and therefore bypasses the response interceptor below)
 * can also recover from a 401. In-flight de-duplication is process-wide:
 * a second caller that arrives while a refresh is already pending awaits
 * the same promise rather than firing a duplicate refresh request.
 *
 * Returns the new access token on success, or ``null`` if there's no
 * refresh token / the refresh endpoint rejected it. Callers should
 * fall back to :func:`redirectToAuth` on ``null``.
 */
export async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  const refresh = tokenStore.getRefresh();
  if (!refresh) return null;

  refreshInFlight = (async () => {
    try {
      const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refresh });
      const access = res.data?.access_token as string | undefined;
      const newRefresh = (res.data?.refresh_token as string | undefined) ?? refresh;
      if (!access) return null;
      tokenStore.set(access, newRefresh);
      return access;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

/**
 * Clear tokens and bounce to /auth. Exported for the same reason as
 * :func:`refreshAccessToken` — non-axios paths need to share the
 * "unrecoverable auth" exit so the user lands on the login page
 * instead of seeing an opaque "连接中断" toast.
 */
export function redirectToAuth() {
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
  const doFetch = (): Promise<Response> => {
    const token = tokenStore.getAccess() ?? '';
    const headers = new Headers(init.headers as HeadersInit | undefined);
    if (token && !headers.has('Authorization')) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    return fetch(input, { ...init, headers });
  };

  let resp = await doFetch();
  if (resp.status === 401) {
    const fresh = await refreshAccessToken();
    if (!fresh) {
      redirectToAuth();
      throw new Error('登录状态已失效，请重新登录');
    }
    resp = await doFetch();
  }
  return resp;
}

apiClient.interceptors.response.use(
  (r) => r,
  async (error: AxiosError<{ detail?: string }>) => {
    const status = error.response?.status;
    const original = (error.config ?? {}) as RetryConfig;

    if (status === 401 && !original._retry) {
      original._retry = true;
      const newToken = await refreshAccessToken();
      if (newToken) {
        original.headers = { ...(original.headers ?? {}), Authorization: `Bearer ${newToken}` };
        return apiClient.request(original);
      }
      redirectToAuth();
      return Promise.reject(error);
    }
    if (status === 401) {
      redirectToAuth();
    } else if (status === 429) {
      toast.warn('请求过于频繁，请稍后再试');
    }
    // 4xx and 5xx are surfaced to call-sites via Promise.reject so they can
    // decide their own toast wording. We do not auto-toast 5xx anymore —
    // the call-site has more context (e.g. "删除失败" vs "对话创建失败").
    return Promise.reject(error);
  },
);

export function extractErr(e: unknown, fallback = '请求失败'): string {
  const ax = e as AxiosError<{ detail?: string }>;
  return ax?.response?.data?.detail ?? ax?.message ?? fallback;
}
