import { FormEvent, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { useNavigate } from 'react-router-dom';
import { Btn } from '@/components/ui/Btn';
import { Field } from '@/components/ui/Field';
import { apiClient, extractErr } from '@/api/client';
import { type MeResponse } from '@/api/auth';
import { useAuthStore } from '@/store/authStore';
import { cloudAuth, finishPasswordRecovery, isLocalUnlockSession, isPasswordRecovery, beginAuthAttempt, isCurrentAuthAttempt, acceptCloudSession, discardUnacceptedSession, completePasswordRecovery, getRecoveryState, subscribeRecovery, runCloudAuthOperation, invalidateAuthAttempts, isPublicEmailDeliveryReady } from '@/lib/supabaseAuth';

type Mode = 'login' | 'register' | 'reset' | 'recover' | 'unlock' | 'setup';

export function SupabaseAuthPanel() {
  const navigate = useNavigate();
  const [requestedMode, setMode] = useState<Mode>(() => isPasswordRecovery() ? 'recover' : 'login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [linkLegacy, setLinkLegacy] = useState(false);
  const [legacyUsername, setLegacyUsername] = useState('');
  const [legacyPassword, setLegacyPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const inFlight = useRef(false);
  const alive = useRef(true);
  const recovery = useSyncExternalStore(subscribeRecovery, getRecoveryState);
  const mode: Mode = recovery.status !== 'none' ? 'recover' : requestedMode;
  const isAuthed = useAuthStore(s => s.isAuthed);
  const hasLocalProfile = useAuthStore(s => !!s.me);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; if (inFlight.current) invalidateAuthAttempts(); };
  }, []);

  const switchMode = (next: Mode) => {
    if (inFlight.current) return;
    if (mode === 'recover' && next !== 'recover') finishPasswordRecovery();
    setMode(next); setPassword(''); setConfirm(''); setError(''); setMessage('');
  };
  const finish = () => { if (alive.current) { inFlight.current = false; navigate('/today', { replace: true }); } };
  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;
    if ((mode === 'setup' || mode === 'recover' || mode === 'register') && password !== confirm) { setError('两次密码不一致'); return; }
    if (mode === 'login' || mode === 'unlock') useAuthStore.getState().clearSession();
    const attempt = beginAuthAttempt(mode === 'login' || mode === 'unlock' || mode === 'recover');
    inFlight.current = true; setBusy(true); setError(''); setMessage('');
    let pendingSession: import('@supabase/supabase-js').Session | null = null;
    try {
      const auth = cloudAuth().auth;
      const redirect = `${window.location.origin}/auth`;
      if (mode === 'unlock') {
        const response = await apiClient.post('/auth/local-unlock', { email: email.trim(), password });
        if (!isCurrentAuthAttempt(attempt)) return;
        useAuthStore.getState().setSession(response.data.access_token, '');
        finish();
      } else if (mode === 'register') {
        const { error: failure } = await runCloudAuthOperation(() => auth.signUp({ email: email.trim(), password, options: { emailRedirectTo: redirect } }));
        if (failure) throw failure;
        if (!isCurrentAuthAttempt(attempt)) return;
        setPassword(''); setConfirm('');
        setMessage('请查看邮箱中的确认邮件，完成验证后回到这里登录。已有账号可直接登录');
      } else if (mode === 'reset') {
        const { error: failure } = await runCloudAuthOperation(() => auth.resetPasswordForEmail(email.trim(), { redirectTo: `${redirect}?flow=recovery` }));
        if (failure) throw failure;
        if (!isCurrentAuthAttempt(attempt)) return;
        setMessage('如果该邮箱可以重置密码，你将收到邮件。请在发起请求的同一浏览器中打开链接');
      } else if (mode === 'recover') {
        const completed = await completePasswordRecovery(password);
        if (completed && alive.current) {
          setMode('login'); setPassword(''); setConfirm('');
          setMessage('密码已更新，请重新登录。当前电脑的资料不会删除');
        }
      } else if (mode === 'setup') {
        await apiClient.post('/auth/local-unlock/setup', { password });
        if (!isCurrentAuthAttempt(attempt)) return;
        setPassword(''); setConfirm('');
        setMessage('本地解锁已设置。此密码仅保存在当前电脑，不会上传到 Supabase');
        finish();
      } else {
        const { data, error: failure } = await runCloudAuthOperation(async () => {
          const result = await auth.signInWithPassword({ email: email.trim(), password });
          if (!isCurrentAuthAttempt(attempt) && result.data.session) await auth.signOut({ scope: 'local' });
          return result;
        });
        if (failure || !data.session) throw failure ?? new Error('未获得有效登录会话');
        pendingSession = data.session;
        if (!isCurrentAuthAttempt(attempt)) return;
        const response = await apiClient.post<{ profile: MeResponse; local_unlock_enabled: boolean }>('/auth/supabase/session', linkLegacy ? { legacy_username: legacyUsername.trim(), legacy_password: legacyPassword } : {}, { headers: { Authorization: `Bearer ${data.session.access_token}` } });
        if (!isCurrentAuthAttempt(attempt)) return;
        if (!acceptCloudSession(data.session, attempt)) return;
        pendingSession = null;
        useAuthStore.getState().setMe(response.data.profile);
        setPassword(''); setLegacyPassword('');
        if (!response.data.local_unlock_enabled) {
          setMode('setup'); setMessage('设置独立的本地解锁密码，以便账号服务离线时继续使用当前电脑的资料与任务');
        } else finish();
      }
    } catch (failure) {
      if (alive.current && isCurrentAuthAttempt(attempt)) setError(extractErr(failure, '暂时无法完成，请重试'));
    } finally {
      if (pendingSession) await discardUnacceptedSession(pendingSession).catch(() => undefined);
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const labels: Record<Mode, string> = { login: '统一账号登录', register: '注册统一账号', reset: '找回账号密码', recover: '设置新账号密码', unlock: '本地解锁', setup: '设置本地解锁' };
  return <section aria-label="统一账号">
    <h1 className="mb-4 text-base font-semibold">{labels[mode]}</h1>
    <p className="mb-4 text-xs text-stone-500">账号由 Supabase Auth 验证。资料、录音、向量索引和任务保存在当前电脑，同一账号不会自动同步这些内容</p>
    {!isPublicEmailDeliveryReady() && <p role="note" className="mb-4 rounded bg-amber-50 p-3 text-xs text-amber-800">当前账号邮件仅用于项目团队测试。公众注册与密码邮件需要先配置邮件发送服务；不会通过关闭邮箱验证绕过限制</p>}
    {mode === 'recover' && <p role={recovery.status === 'failed' ? 'alert' : 'status'} className="mb-3 text-sm">{recovery.status === 'ready' ? `将重置 ${recovery.email ?? '已验证账号'} 的账号密码` : recovery.message ?? '请先验证重置邮件链接'}</p>}
    <form onSubmit={onSubmit}>
      {mode !== 'setup' && mode !== 'recover' && <Field disabled={busy} label="邮箱" type="email" autoComplete="email" value={email} onChange={setEmail} />}
      {mode !== 'reset' && <Field disabled={busy} label={mode === 'setup' || mode === 'unlock' ? '独立的本地解锁密码' : '账号密码'} type="password" autoComplete={mode === 'login' || mode === 'unlock' ? 'current-password' : 'new-password'} value={password} onChange={setPassword} placeholder={mode === 'setup' ? '至少 12 位，建议与账号密码不同' : undefined} />}
      {(mode === 'setup' || mode === 'recover' || mode === 'register') && <Field disabled={busy} label="再次输入密码" type="password" autoComplete="new-password" value={confirm} onChange={setConfirm} />}
      {mode === 'login' && <div className="mb-4 text-sm">
        <label><input type="checkbox" checked={linkLegacy} onChange={e => setLinkLegacy(e.target.checked)} disabled={busy} /> 关联已有本地账号的资料</label>
        {linkLegacy && <><Field disabled={busy} label="原本地用户名" value={legacyUsername} onChange={setLegacyUsername} /><Field disabled={busy} label="原本地账号密码" type="password" value={legacyPassword} onChange={setLegacyPassword} /></>}
      </div>}
      {error && <p role="alert" className="mb-3 text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="mb-3 text-sm text-stone-600">{message}</p>}
      <Btn type="submit" full loading={busy} disabled={busy || (mode === 'recover' && recovery.status !== 'ready') || ((mode !== 'setup' && mode !== 'recover') && !email.trim()) || (mode !== 'reset' && password.length < (mode === 'setup' ? 12 : 6))}>{labels[mode]}</Btn>
    </form>
    <div className="mt-4 flex flex-wrap gap-3 text-sm">
      {mode !== 'login' && <button type="button" disabled={busy} onClick={() => switchMode('login')}>返回登录</button>}
      {mode === 'login' && <><button type="button" disabled={busy} onClick={() => switchMode('register')}>注册</button><button type="button" disabled={busy} onClick={() => switchMode('reset')}>忘记密码</button></>}
      {mode !== 'unlock' && mode !== 'recover' && <button type="button" disabled={busy} onClick={() => switchMode('unlock')}>离线时使用本地解锁</button>}
      {isAuthed && !isLocalUnlockSession() && <button type="button" disabled={busy} onClick={() => switchMode('setup')}>设置或更换本地解锁</button>}
      {isAuthed && hasLocalProfile && <button type="button" disabled={busy} onClick={finish}>{mode === 'setup' ? '暂不设置，进入应用' : '返回应用'}</button>}
    </div>
    {mode === 'unlock' && <p className="mt-3 text-xs text-stone-500">需先在这台电脑完成在线登录并设置独立密码。本地解锁不授予云端账号权限，外部模型仍按已有 BYOK 配置及权限运行</p>}
  </section>;
}
