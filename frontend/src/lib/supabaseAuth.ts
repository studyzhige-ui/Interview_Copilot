import { createClient, type Session, type SupabaseClient } from '@supabase/supabase-js';
import type { NativeAuthCallback } from './desktopAuth';
import { apiUrl } from '@/api/apiUrl';
import { decodeJwtPayload, tokenStore } from './token';

type AppSession = Pick<Session, 'access_token' | 'refresh_token'>;
interface AuthConfig { provider: 'local' | 'supabase'; supabase_url?: string; publishable_key?: string; email_delivery?: 'team_only' | 'custom_smtp' }
interface CloudIdentity { iss: string; sub: string; session_id: string }
export interface RecoveryState { status: 'none' | 'pending' | 'ready' | 'failed'; email?: string; message?: string }
interface RecoveryProof { session: Session; identity: CloudIdentity; expiresAt: number }
let callbackNotice = '';
export const getAuthCallbackNotice = () => callbackNotice;
let config: AuthConfig = { provider: 'local' };
let client: SupabaseClient | null = null;
let sink: ((session: AppSession | null) => void) | null = null;
let authGeneration = 0;
let sessionEventsSuppressed = false;
let authOperations: Promise<unknown> = Promise.resolve();
let recoveryProof: RecoveryProof | null = null;
let recoveryState: RecoveryState = { status: 'none' };
const recoveryListeners = new Set<() => void>();

async function boundedAuthFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (init?.signal?.aborted) controller.abort();
  init?.signal?.addEventListener('abort', abort, { once: true });
  const timer = setTimeout(abort, 8000);
  try { return await fetch(input, { ...init, signal: controller.signal }); }
  finally { clearTimeout(timer); init?.signal?.removeEventListener('abort', abort); }
}
export function runCloudAuthOperation<T>(operation: () => Promise<T>): Promise<T> {
  const result = authOperations.then(operation, operation);
  authOperations = result.catch(() => undefined);
  return result;
}
export function beginAuthAttempt(suppressEvents = true) { sessionEventsSuppressed = suppressEvents; return ++authGeneration; }
export const isCurrentAuthAttempt = (generation: number) => generation === authGeneration;
export function invalidateAuthAttempts() { sessionEventsSuppressed = true; authGeneration += 1; }
export const isSupabaseAuth = () => config.provider === 'supabase';
export const isPublicEmailDeliveryReady = () => config.email_delivery === 'custom_smtp';
export const getRecoveryState = () => recoveryState;
export const isPasswordRecovery = () => recoveryState.status !== 'none';
export function subscribeRecovery(listener: () => void) { recoveryListeners.add(listener); return () => { recoveryListeners.delete(listener); }; }
function setRecovery(state: RecoveryState) { recoveryState = state; recoveryListeners.forEach(listener => listener()); }
function identity(token: string | null): CloudIdentity | null {
  if (!token) return null;
  const value = decodeJwtPayload<Partial<CloudIdentity>>(token);
  const issuer = `${config.supabase_url?.replace(/\/$/, '')}/auth/v1`;
  return value?.iss === issuer && typeof value.sub === 'string' && typeof value.session_id === 'string'
    ? value as CloudIdentity : null;
}
function sameIdentity(a: CloudIdentity | null, b: CloudIdentity | null) {
  return !!a && !!b && a.iss === b.iss && a.sub === b.sub && a.session_id === b.session_id;
}
function publish(session: AppSession | null) {
  // The sink synchronously updates AuthStore and clears owner-scoped query data
  // before the transport can issue another request. Never update only the token.
  sink?.(session);
  if (session) tokenStore.set(session.access_token, session.refresh_token);
  else tokenStore.clear();
}
export function isLocalUnlockSession() {
  const token = tokenStore.getAccess();
  return !!token && decodeJwtPayload<{ type?: string }>(token)?.type === 'local_unlock';
}
export function cloudAuth() {
  if (!client) throw new Error('统一账号服务尚未配置');
  return client;
}
export function acceptCloudSession(session: Session, generation: number) {
  if (!isCurrentAuthAttempt(generation)) return false;
  const owner = identity(session.access_token);
  if (!owner || owner.sub !== session.user.id) throw new Error('账号会话身份不一致，请重新登录');
  publish(session);
  sessionEventsSuppressed = false;
  return true;
}
export function synchronizeStoredSession(session: AppSession | null) {
  invalidateAuthAttempts();
  finishPasswordRecovery();
  publish(session);
  sessionEventsSuppressed = !session || isLocalUnlockSession();
}
export async function discardUnacceptedSession(session: Session) {
  return runCloudAuthOperation(async () => {
    const { data } = await cloudAuth().auth.getSession();
    if (data.session && sameIdentity(identity(data.session.access_token), identity(session.access_token))) {
      await cloudAuth().auth.signOut({ scope: 'local' });
    }
  });
}
export function finishPasswordRecovery() {
  recoveryProof = null;
  setRecovery({ status: 'none' });
  if (new URLSearchParams(window.location.search).has('flow')) window.history.replaceState(null, '', '/auth');
}

/** A query parameter requests a recovery screen; only an SDK recovery exchange grants proof. */
export async function initializeAuth(onSession: (session: AppSession | null) => void, nativeCallback?: NativeAuthCallback | null) {
  sink = onSession;
  const response = await fetch(apiUrl('/auth/config'));
  if (!response.ok) throw new Error('无法读取本地账号配置，请检查本地服务是否已启动');
  config = await response.json() as AuthConfig;
  if (config.provider !== 'local' && config.provider !== 'supabase') throw new Error('账号配置无效');
  if (!isSupabaseAuth()) return;
  if (!config.supabase_url || !config.publishable_key?.startsWith('sb_publishable_')) throw new Error('统一账号配置不完整');
  const recoveryRequested = nativeCallback?.purpose === 'recovery' || new URLSearchParams(window.location.search).get('flow') === 'recovery';
  if (recoveryRequested) {
    invalidateAuthAttempts();
    publish(null); // Quarantine any old account before processing this link.
    setRecovery({ status: 'pending', message: '正在验证重置链接…' });
  } else if (nativeCallback) {
    invalidateAuthAttempts(); publish(null);
  } else {
    const current = tokenStore.getAccess();
    if (current && !isLocalUnlockSession() && !identity(current)) publish(null);
    sessionEventsSuppressed = tokenStore.isLocked();
  }
  client = createClient(config.supabase_url, config.publishable_key, {
    global: { fetch: boundedAuthFetch },
    auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: !nativeCallback },
  });
  client.auth.onAuthStateChange((event, session) => {
    if (event === 'PASSWORD_RECOVERY') {
      const owner = identity(session?.access_token ?? null);
      if (!session || !owner || owner.sub !== session.user.id || !session.expires_at) {
        setRecovery({ status: 'failed', message: '无法验证重置会话，请重新获取邮件链接' });
        return;
      }
      if (recoveryProof?.session.access_token === session.access_token && sameIdentity(recoveryProof.identity, owner)) return;
      invalidateAuthAttempts();
      publish(null);
      recoveryProof = { session, identity: owner, expiresAt: Math.min(session.expires_at, Date.now() / 1000 + 600) };
      setRecovery({ status: 'ready', email: session.user.email });
      return;
    }
    if (recoveryProof && session && !sameIdentity(recoveryProof.identity, identity(session.access_token))) {
      recoveryProof = null;
      setRecovery({ status: 'failed', message: '账号会话已变化，请重新打开重置链接' });
    }
    if (isLocalUnlockSession() || sessionEventsSuppressed || recoveryState.status !== 'none') return;
    const current = tokenStore.getAccess();
    if (session && (!current || sameIdentity(identity(current), identity(session.access_token)))) publish(session);
    else if (event === 'SIGNED_OUT') {
      const generation = authGeneration;
      queueMicrotask(() => { void runCloudAuthOperation(async () => {
        const { data } = await cloudAuth().auth.getSession();
        if (!data.session && isCurrentAuthAttempt(generation)) publish(null);
      }); });
    }
  });
  if (nativeCallback) {
    // The OS handler and local intent only route this code. The SDK exchanges
    // it using the verifier in this persistent Electron partition; only its
    // PASSWORD_RECOVERY event can unlock the password submission screen.
    const { data, error } = await client.auth.exchangeCodeForSession(nativeCallback.code!);
    if (error || !data.session || !identity(data.session.access_token) || data.session.user.id !== identity(data.session.access_token)?.sub) {
      if (recoveryRequested) setRecovery({ status: 'failed', message: '链接无效、已过期或来自其他应用，请重新发送邮件' });
      else throw new Error('邮箱链接无法验证，请重新发送确认邮件');
      return;
    }
    if (recoveryRequested) {
      if (recoveryState.status !== 'ready') setRecovery({ status: 'failed', message: '此链接不是有效的密码重置操作，请重新发送邮件' });
    } else {
      if (recoveryState.status === 'ready') { finishPasswordRecovery(); throw new Error('邮件类型与当前操作不一致，请重新发送'); }
      await client.auth.signOut({ scope: 'local' });
      callbackNotice = '邮箱验证已完成，请使用统一账号登录';
    }
    return;
  }
  if (!recoveryRequested && tokenStore.isLocked()) {
    void runCloudAuthOperation(() => cloudAuth().auth.signOut({ scope: 'local' })).catch(() => undefined);
  }
  void client.auth.getSession().then(({ data }) => {
    if (recoveryRequested) {
      // auth-js emits PASSWORD_RECOVERY on its next timer after the PKCE
      // initialization promise resolves. Allow that event, never substitute A.
      setTimeout(() => {
        if (recoveryState.status === 'pending') setRecovery({ status: 'failed', message: '链接无效、已过期或来自其他浏览器，请重新获取重置邮件' });
      }, 0);
    } else if (data.session && !isLocalUnlockSession() && !sessionEventsSuppressed) {
      const current = tokenStore.getAccess();
      if (!current || sameIdentity(identity(current), identity(data.session.access_token))) publish(data.session);
    }
  }).catch(() => {
    if (recoveryRequested) setRecovery({ status: 'failed', message: '无法验证重置链接，请联网后重新获取邮件' });
  });
}

export async function refreshCloudAccess(rejectedAccess: string | null): Promise<string | null> {
  if (isLocalUnlockSession() || sessionEventsSuppressed || recoveryState.status !== 'none') return null;
  const expected = identity(rejectedAccess);
  const ticket = tokenStore.getRefresh();
  if (!expected || !ticket) return null;
  const generation = authGeneration;
  const { data, error } = await cloudAuth().auth.refreshSession();
  if (!isCurrentAuthAttempt(generation)) return null;
  const current = tokenStore.getAccess();
  if (current !== rejectedAccess && current !== data.session?.access_token) return sameIdentity(expected, identity(current)) ? current : null;
  if (error || !data.session || !sameIdentity(expected, identity(data.session.access_token))) return null;
  publish(data.session);
  return data.session.access_token;
}

export async function completePasswordRecovery(password: string): Promise<boolean> {
  const proof = recoveryProof;
  const generation = authGeneration;
  if (!proof || recoveryState.status !== 'ready' || proof.expiresAt <= Date.now() / 1000) throw new Error('没有有效的重置会话，请重新获取邮件链接');
  return runCloudAuthOperation(async () => {
    if (recoveryProof !== proof || !isCurrentAuthAttempt(generation)) throw new Error('重置会话已变化，请重试');
    // A dedicated non-persistent SDK client is bound to B's proven recovery
    // token. A concurrent sign-in to A/C cannot retarget updateUser's authority.
    const isolated = createClient(config.supabase_url!, config.publishable_key!, {
      global: { fetch: boundedAuthFetch },
      auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false, storageKey: `copilot-recovery-${crypto.randomUUID()}` },
    });
    const { data, error } = await isolated.auth.setSession({ access_token: proof.session.access_token, refresh_token: proof.session.refresh_token });
    if (error || !data.session || !sameIdentity(identity(data.session.access_token), proof.identity) || data.session.user.id !== proof.identity.sub || recoveryProof !== proof || !isCurrentAuthAttempt(generation)) throw new Error('无法验证重置账号，请重新获取链接');
    const changed = await isolated.auth.updateUser({ password });
    if (changed.error) throw changed.error;
    await isolated.auth.signOut({ scope: 'local' });
    if (recoveryProof !== proof || !isCurrentAuthAttempt(generation)) return false;
    publish(null);
    finishPasswordRecovery();
    sessionEventsSuppressed = true;
    return true;
  });
}
