import { apiClient } from './client';
import { tokenStore } from '@/lib/token';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

/**
 * Best-effort server-side revocation of the current token pair.
 * Always resolves (failures are logged + swallowed) so the UI logout flow
 * never blocks on network. Pair this with `tokenStore.clear()` on the FE.
 */
export async function logout(): Promise<void> {
  const refresh = tokenStore.getRefresh();
  try {
    await apiClient.post('/auth/logout', refresh ? { refresh_token: refresh } : {});
  } catch {
    // Backend may already have revoked / be down — local clear still happens.
  }
}

export type CodePurpose = 'register' | 'reset_password' | 'change_email';

export interface RegisterPayload {
  username: string;
  password: string;
  email: string;
  code: string;
}

export async function sendVerificationCode(
  email: string,
  purpose: CodePurpose = 'register',
): Promise<{ expires_in: number }> {
  const res = await apiClient.post('/auth/send-code', { email, purpose });
  return res.data;
}

export async function register(payload: RegisterPayload): Promise<{ message: string; user_id: number }> {
  const res = await apiClient.post('/auth/register', payload);
  return res.data;
}

export async function login(username: string, password: string): Promise<TokenPair> {
  const form = new URLSearchParams({ username, password });
  const res = await apiClient.post('/auth/login', form, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  });
  return res.data;
}

export interface MeResponse {
  username: string;
  email: string | null;
  nickname: string | null;
  avatar_url: string | null;
  bio: string | null;
  email_verified: boolean;
  created_at: string;
  updated_at: string;
  /** Whether memory recall (vector lookup over past interview_fact items)
   *  should run by default for this user. Per-session toggle in the chat
   *  header overrides this. Opt-in by design — default false. */
  memory_recall_default: boolean;
}

export async function getMe(): Promise<MeResponse> {
  const res = await apiClient.get('/auth/me');
  return res.data;
}

export async function updateMe(patch: {
  nickname?: string;
  avatar_url?: string;
  bio?: string;
  memory_recall_default?: boolean;
}): Promise<MeResponse> {
  const res = await apiClient.patch('/auth/me', patch);
  return res.data;
}

export async function uploadAvatar(file: File): Promise<MeResponse> {
  const form = new FormData();
  form.append('file', file);
  const res = await apiClient.post('/auth/me/avatar', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}
