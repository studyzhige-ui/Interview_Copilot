import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';

const fixture = vi.hoisted(() => {
  const auth = { signUp: vi.fn(), signInWithPassword: vi.fn(), resetPasswordForEmail: vi.fn(), updateUser: vi.fn(), signOut: vi.fn(), onAuthStateChange: vi.fn() };
  const state = { isAuthed: false, setSession: vi.fn(), setMe: vi.fn(), clearSession: vi.fn() };
  return { auth, state, post: vi.fn(), generation: 0, recovery: false };
});
vi.mock('@/api/client', () => ({ apiClient: { post: fixture.post }, extractErr: (e: Error) => e.message }));
vi.mock('@/store/authStore', () => ({ useAuthStore: Object.assign((select: (s: typeof fixture.state) => unknown) => select(fixture.state), { getState: () => fixture.state }) }));
vi.mock('@/lib/supabaseAuth', () => ({
  cloudAuth: () => ({ auth: fixture.auth }), isLocalUnlockSession: () => false,
  isPasswordRecovery: () => fixture.recovery, isPublicEmailDeliveryReady: () => false, finishPasswordRecovery: vi.fn(),
  beginAuthAttempt: () => ++fixture.generation, isCurrentAuthAttempt: (g: number) => g === fixture.generation, acceptAuthAttempt: vi.fn(), invalidateAuthAttempts: () => { fixture.generation += 1; }, runCloudAuthOperation: (fn: () => Promise<unknown>) => fn(),
}));
import { SupabaseAuthPanel } from './SupabaseAuthPanel';

beforeEach(() => {
  vi.clearAllMocks(); fixture.recovery = false; fixture.generation = 0; fixture.state.isAuthed = false;
  fixture.auth.onAuthStateChange.mockReturnValue({ data: { subscription: { unsubscribe: vi.fn() } } });
  fixture.auth.signInWithPassword.mockResolvedValue({ data: { session: { access_token: 'cloud-access', refresh_token: 'cloud-refresh' } }, error: null });
  fixture.auth.signUp.mockResolvedValue({ data: { session: null }, error: null });
  fixture.auth.resetPasswordForEmail.mockResolvedValue({ error: null });
  fixture.auth.updateUser.mockResolvedValue({ error: null }); fixture.auth.signOut.mockResolvedValue({ error: null });
  fixture.post.mockResolvedValue({ data: { profile: { username: 'owner' }, local_unlock_enabled: true } });
});
function show() { render(<MemoryRouter initialEntries={['/auth']}><Routes><Route path="/auth" element={<SupabaseAuthPanel />} /><Route path="/today" element={<p>Local workspace</p>} /></Routes></MemoryRouter>); }
function fill(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
function credentials() { fill('邮箱', 'owner@example.test'); fill('账号密码', 'cloud-password'); }

it('signs up with an exact callback and waits for email confirmation without provisioning local ownership', async () => {
  show(); fireEvent.click(screen.getByRole('button', { name: '注册' })); credentials(); fill('再次输入密码', 'cloud-password');
  fireEvent.click(screen.getByRole('button', { name: '注册统一账号' }));
  expect(await screen.findByRole('status')).toHaveTextContent('确认邮件');
  expect(fixture.auth.signUp).toHaveBeenCalledWith({ email: 'owner@example.test', password: 'cloud-password', options: { emailRedirectTo: `${window.location.origin}/auth` } });
  expect(fixture.post).not.toHaveBeenCalled();
});

it('links legacy ownership only with both independently entered account proofs', async () => {
  show(); credentials(); fireEvent.click(screen.getByRole('checkbox'));
  fill('原本地用户名', 'legacy-owner'); fill('原本地账号密码', 'local-password');
  fireEvent.click(screen.getByRole('button', { name: '统一账号登录' }));
  await screen.findByText('Local workspace');
  expect(fixture.auth.signInWithPassword).toHaveBeenCalledWith({ email: 'owner@example.test', password: 'cloud-password' });
  expect(fixture.post).toHaveBeenCalledWith('/auth/supabase/session', { legacy_username: 'legacy-owner', legacy_password: 'local-password' }, { headers: { Authorization: 'Bearer cloud-access' } });
});

it('offers a separate local unlock after the first verified cloud sign-in', async () => {
  fixture.post.mockResolvedValueOnce({ data: { profile: { username: 'owner' }, local_unlock_enabled: false } });
  show(); credentials(); fireEvent.click(screen.getByRole('button', { name: '统一账号登录' }));
  await screen.findByRole('heading', { name: '设置本地解锁' });
  fill('独立的本地解锁密码', 'separate-unlock-password'); fill('再次输入密码', 'separate-unlock-password');
  fireEvent.click(screen.getByRole('button', { name: '设置本地解锁' }));
  await screen.findByText('Local workspace');
  expect(fixture.post).toHaveBeenLastCalledWith('/auth/local-unlock/setup', { password: 'separate-unlock-password' });
  expect(fixture.auth.updateUser).not.toHaveBeenCalled();
});

it('unlocks existing local work without any cloud sign-in call', async () => {
  fixture.post.mockResolvedValue({ data: { access_token: 'local-business-token', refresh_token: '' } });
  show(); fireEvent.click(screen.getByRole('button', { name: '离线时使用本地解锁' }));
  fill('邮箱', 'owner@example.test'); fill('独立的本地解锁密码', 'local-unlock-password');
  fireEvent.click(screen.getByRole('button', { name: '本地解锁' }));
  await screen.findByText('Local workspace');
  expect(fixture.post).toHaveBeenCalledWith('/auth/local-unlock', { email: 'owner@example.test', password: 'local-unlock-password' });
  expect(fixture.state.setSession).toHaveBeenCalledWith('local-business-token', '');
  expect(fixture.auth.signInWithPassword).not.toHaveBeenCalled();
});

it('keeps repeated login clicks within a single pending attempt', async () => {
  let resolve!: (value: unknown) => void;
  fixture.auth.signInWithPassword.mockReturnValue(new Promise(r => { resolve = r; }));
  show(); credentials(); const button = screen.getByRole('button', { name: '统一账号登录' });
  fireEvent.click(button); fireEvent.click(button);
  expect(fixture.auth.signInWithPassword).toHaveBeenCalledTimes(1);
  await act(async () => resolve({ data: { session: null }, error: new Error('network unavailable') }));
  expect(await screen.findByRole('alert')).toHaveTextContent('network unavailable');
  expect(fixture.post).not.toHaveBeenCalled();
});

it('a superseding logout prevents a late login from restoring the app session', async () => {
  let resolve!: (value: unknown) => void;
  fixture.auth.signInWithPassword.mockReturnValue(new Promise(r => { resolve = r; }));
  show(); credentials(); fireEvent.click(screen.getByRole('button', { name: '统一账号登录' }));
  fixture.generation += 1;
  await act(async () => resolve({ data: { session: { access_token: 'late', refresh_token: 'late' } }, error: null }));
  expect(fixture.state.setSession).not.toHaveBeenCalled(); expect(fixture.post).not.toHaveBeenCalled();
});

it('requests password recovery through Auth with the exact recovery callback', async () => {
  show(); fireEvent.click(screen.getByRole('button', { name: '忘记密码' })); fill('邮箱', 'owner@example.test');
  fireEvent.click(screen.getByRole('button', { name: '找回账号密码' }));
  await screen.findByRole('status');
  expect(fixture.auth.resetPasswordForEmail).toHaveBeenCalledWith('owner@example.test', { redirectTo: `${window.location.origin}/auth?flow=recovery` });
});

it('updates the recovered cloud password and requires a new sign-in', async () => {
  fixture.recovery = true; show(); fill('账号密码', 'new-cloud-password'); fill('再次输入密码', 'new-cloud-password');
  fireEvent.click(screen.getByRole('button', { name: '设置新账号密码' }));
  await waitFor(() => expect(fixture.state.clearSession).toHaveBeenCalledOnce());
  expect(fixture.auth.updateUser).toHaveBeenCalledWith({ password: 'new-cloud-password' });
  expect(fixture.post).not.toHaveBeenCalled();
});
