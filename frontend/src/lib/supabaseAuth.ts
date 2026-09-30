import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import { apiUrl } from '@/api/apiUrl';
import { decodeJwtPayload, tokenStore } from './token';

interface AuthConfig { provider: 'local' | 'supabase'; supabase_url?: string; publishable_key?: string; email_delivery?: 'team_only' | 'custom_smtp' }
let config: AuthConfig = { provider: 'local' };
let client: SupabaseClient | null = null;
let recovery = false;
let authOperations: Promise<unknown> = Promise.resolve();
export function runCloudAuthOperation<T>(operation: () => Promise<T>): Promise<T> {
  const result = authOperations.then(operation, operation);
  authOperations = result.catch(() => undefined);
  return result;
}
let authGeneration = 0;
let sessionEventsSuppressed = false;
export function beginAuthAttempt() { sessionEventsSuppressed = true; return ++authGeneration; }
export const isCurrentAuthAttempt = (generation: number) => generation === authGeneration;
export function acceptAuthAttempt(generation: number) { if (isCurrentAuthAttempt(generation)) sessionEventsSuppressed = false; }
export function invalidateAuthAttempts() { sessionEventsSuppressed = true; authGeneration += 1; }

export const isSupabaseAuth = () => config.provider === 'supabase';
export const isPublicEmailDeliveryReady = () => config.email_delivery === 'custom_smtp';
export const isPasswordRecovery = () => recovery || new URLSearchParams(window.location.search).get('flow') === 'recovery';
export function finishPasswordRecovery() {
  recovery = false;
  window.history.replaceState(null, '', '/auth');
}
export function isLocalUnlockSession() {
  const token = tokenStore.getAccess();
  return !!token && decodeJwtPayload<{ type?: string }>(token)?.type === 'local_unlock';
}
export function cloudAuth() {
  if (!client) throw new Error('统一账号服务尚未配置');
  return client;
}

/** Bootstrap only public configuration from the user's own local API. */
export async function initializeAuth(onSession: (session: Session | null) => void) {
  const response = await fetch(apiUrl('/auth/config'));
  if (!response.ok) throw new Error('无法读取本地账号配置，请检查本地服务是否已启动');
  config = await response.json() as AuthConfig;
  if (config.provider !== 'local' && config.provider !== 'supabase') throw new Error('账号配置无效');
  if (!isSupabaseAuth()) return;
  if (!config.supabase_url || !config.publishable_key?.startsWith('sb_publishable_')) throw new Error('统一账号配置不完整');
  const current = tokenStore.getAccess();
  if (current && !isLocalUnlockSession() && decodeJwtPayload<{ iss?: string }>(current)?.iss !== `${config.supabase_url.replace(/\/$/, '')}/auth/v1`) {
    tokenStore.clear();
    onSession(null);
  }
  client = createClient(config.supabase_url, config.publishable_key, {
    auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  client.auth.onAuthStateChange((event, session) => {
    if (event === 'PASSWORD_RECOVERY') recovery = true;
    // A background cloud refresh never replaces an explicitly unlocked local
    // capability. A deliberate sign-in below can switch modes explicitly.
    if (isLocalUnlockSession() || sessionEventsSuppressed) return;
    if (session) onSession(session);
    else if (event === 'SIGNED_OUT') onSession(null);
  });
  // Do not wait on network refresh to render the local unlock screen.
  void client.auth.getSession().then(({ data }) => {
    if (data.session && !isLocalUnlockSession() && !sessionEventsSuppressed) onSession(data.session);
  }).catch(() => { /* Local unlock remains available when Auth is unreachable. */ });
}

export async function refreshCloudAccess(rejectedAccess: string | null): Promise<string | null> {
  if (isLocalUnlockSession()) return null; // Local sessions require re-unlock.
  const refresh = tokenStore.getRefresh();
  if (!refresh) return null;
  const { data, error } = await cloudAuth().auth.refreshSession();
  // Logout/account switching wins over an in-flight refresh.
  if (tokenStore.getAccess() !== rejectedAccess && tokenStore.getRefresh() !== refresh) return tokenStore.getAccess();
  if (error || !data.session) return null;
  tokenStore.set(data.session.access_token, data.session.refresh_token);
  return data.session.access_token;
}
