/** Native transport carries a code, never authority. Supabase must prove PKCE. */
export type NativeAuthPurpose = 'signup' | 'recovery';
export interface NativeAuthIntent { id: string; purpose: NativeAuthPurpose; expiresAt: number; redirectTo: string }
export interface NativeAuthCallback { id: string; purpose: NativeAuthPurpose; code?: string; error?: string }
interface DesktopAuthBridge {
  begin: (purpose: NativeAuthPurpose) => Promise<NativeAuthIntent>;
  cancel: (id: string) => Promise<void>;
  take: () => Promise<NativeAuthCallback | null>;
  onReady: (listener: () => void) => () => void;
}
declare global { interface Window { copilotDesktopAuth?: DesktopAuthBridge } }
const KEY = 'interview_copilot_native_auth_intent';
const MAX_AGE = 10 * 60 * 1000;
const CALLBACKS = { signup: 'interview-copilot://auth/confirm', recovery: 'interview-copilot://auth/recovery' };
function pending(): NativeAuthIntent | null {
  try { return JSON.parse(localStorage.getItem(KEY) ?? 'null') as NativeAuthIntent | null; } catch { return null; }
}
export async function cancelNativeAuthFlow(expectedId?: string) {
  const previous = pending();
  if (expectedId && previous?.id !== expectedId) return;
  localStorage.removeItem(KEY);
  if (previous && window.copilotDesktopAuth) await window.copilotDesktopAuth.cancel(previous.id);
}
export async function authRedirect(purpose: NativeAuthPurpose): Promise<{ url: string; id?: string }> {
  if (!window.copilotDesktopAuth) return { url: `${window.location.origin}/auth${purpose === 'recovery' ? '?flow=recovery' : ''}` };
  await cancelNativeAuthFlow();
  const intent = await window.copilotDesktopAuth.begin(purpose);
  if (intent.purpose !== purpose || intent.redirectTo !== `${CALLBACKS[purpose]}#state=${intent.id}` || typeof intent.id !== 'string' || intent.expiresAt <= Date.now() || intent.expiresAt > Date.now() + MAX_AGE) throw new Error('桌面账号返回配置无效');
  localStorage.setItem(KEY, JSON.stringify(intent));
  return { url: intent.redirectTo, id: intent.id };
}
export async function takeNativeAuthCallback(): Promise<NativeAuthCallback | null> {
  const value = await window.copilotDesktopAuth?.take();
  if (!value) return null;
  const intent = pending(); localStorage.removeItem(KEY);
  if (!intent || intent.id !== value.id || intent.purpose !== value.purpose || intent.expiresAt <= Date.now() || intent.expiresAt > Date.now() + MAX_AGE) throw new Error('邮箱返回与当前操作不匹配或已过期，请重新发送邮件');
  if (value.error || typeof value.code !== 'string' || !/^[A-Za-z0-9_-]{16,256}$/.test(value.code)) throw new Error('邮箱链接无效或已过期，请重新发送邮件');
  return value;
}
export function onNativeAuthCallback(listener: () => void) { return window.copilotDesktopAuth?.onReady(listener); }
