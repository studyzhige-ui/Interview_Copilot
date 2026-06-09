import { apiClient } from './client';
import { uploadFileAsset } from './fileAssets';
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

/**
 * Change the current user's password. On success the backend bumps the
 * user's `token_version`, so EVERY existing access + refresh token
 * (including the one this request used) is immediately invalidated — the
 * caller must clear local tokens and send the user back to /auth to log in
 * with the new password. No new token pair is returned by design.
 */
export async function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ status: string; message: string }> {
  const res = await apiClient.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
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
  /** Global cross-session memory toggle (Phase H, mirrors Claude Code's
   *  ``isAutoMemoryEnabled``). When OFF, new chat sessions do NOT inject
   *  the v3 memory bundle (user_profile / knowledge / strategy / habit
   *  docs) into the LLM prompt. The DB column is still readable for
   *  the personalization page — toggle gates injection, not storage.
   *  Per-session override available via the chat header.
   *  Default: false (opt-in). */
  global_memory_enabled: boolean;
}

export async function getMe(): Promise<MeResponse> {
  const res = await apiClient.get('/auth/me');
  return res.data;
}

export async function updateMe(patch: {
  nickname?: string;
  avatar_url?: string;
  bio?: string;
  /** Canonical (Phase H). Backend also accepts the legacy alias
   *  ``memory_recall_default`` via Pydantic ``populate_by_name``. */
  global_memory_enabled?: boolean;
}): Promise<MeResponse> {
  const res = await apiClient.patch('/auth/me', patch);
  return res.data;
}

export async function uploadAvatar(file: File): Promise<MeResponse> {
  // Unified presigned flow (purpose='avatar'): bytes PUT straight to object
  // storage, then the server validates + sets the avatar from the confirmed
  // file_asset. No multipart server-receives-bytes path.
  const fileAssetId = await uploadFileAsset(file, 'avatar');
  const res = await apiClient.post('/auth/me/avatar', { file_asset_id: fileAssetId });
  return res.data;
}
