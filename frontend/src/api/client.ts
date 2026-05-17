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

async function refreshAccessToken(): Promise<string | null> {
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

function redirectToAuth() {
  tokenStore.clear();
  if (window.location.pathname !== '/auth') {
    window.location.href = '/auth';
  }
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
