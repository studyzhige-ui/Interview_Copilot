import { apiClient } from './client';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
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
}

export async function getMe(): Promise<MeResponse> {
  const res = await apiClient.get('/auth/me');
  return res.data;
}

export async function updateMe(patch: {
  nickname?: string;
  avatar_url?: string;
  bio?: string;
}): Promise<MeResponse> {
  const res = await apiClient.patch('/auth/me', patch);
  return res.data;
}
