const DEFAULT_API_BASE = '/api/v1';

export const API_BASE = (
  (import.meta.env.VITE_API_BASE as string | undefined)?.trim() || DEFAULT_API_BASE
).replace(/\/+$/, '');

/** Build an API URL for fetch-based transports such as SSE and token refresh. */
export function apiUrl(path: string): string {
  return `${API_BASE}/${path.replace(/^\/+/, '')}`;
}
