import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { authRedirect, cancelNativeAuthFlow, takeNativeAuthCallback } from './desktopAuth';
const fixture = { id: '00000000-0000-4000-8000-000000000001', purpose: 'recovery' as const, expiresAt: 0, redirectTo: 'interview-copilot://auth/recovery#state=00000000-0000-4000-8000-000000000001' };
const code = 'synthetic-code-not-a-real-authentication-secret';
beforeEach(() => { localStorage.clear(); fixture.expiresAt = Date.now() + 600000; });
afterEach(() => { delete window.copilotDesktopAuth; vi.restoreAllMocks(); });
function bridge() {
  const value = { begin: vi.fn().mockResolvedValue({ ...fixture }), cancel: vi.fn().mockResolvedValue(undefined), take: vi.fn().mockResolvedValue({ id: fixture.id, purpose: fixture.purpose, code }), onReady: vi.fn() };
  window.copilotDesktopAuth = value; return value;
}
it('web mode retains the exact approved callback URLs', async () => {
  expect(await authRedirect('signup')).toEqual({ url: `${window.location.origin}/auth` });
  expect(await authRedirect('recovery')).toEqual({ url: `${window.location.origin}/auth?flow=recovery` });
});
it('native callback must match the initiating partition and is consumed once', async () => {
  bridge(); expect(await authRedirect('recovery')).toEqual({ url: fixture.redirectTo, id: fixture.id });
  expect(await takeNativeAuthCallback()).toEqual({ id: fixture.id, purpose: 'recovery', code });
  await expect(takeNativeAuthCallback()).rejects.toThrow('不匹配或已过期');
});
it.each(['unknown', 'expired', 'logout', 'wrong-purpose'])('rejects %s callbacks before SDK use', async kind => {
  const ipc = bridge();
  if (kind !== 'unknown') await authRedirect('recovery');
  if (kind === 'expired') vi.spyOn(Date, 'now').mockReturnValue(fixture.expiresAt + 1);
  if (kind === 'logout') await cancelNativeAuthFlow();
  if (kind === 'wrong-purpose') ipc.take.mockResolvedValue({ id: fixture.id, purpose: 'signup', code });
  await expect(takeNativeAuthCallback()).rejects.toThrow('不匹配或已过期');
});
it('a late failure cannot cancel a newer pending flow', async () => {
  const ipc = bridge(); await authRedirect('recovery');
  ipc.begin.mockResolvedValue({ ...fixture, id: '00000000-0000-4000-8000-000000000002', redirectTo: 'interview-copilot://auth/recovery#state=00000000-0000-4000-8000-000000000002' });
  const newer = await authRedirect('recovery');
  await cancelNativeAuthFlow(fixture.id);
  ipc.take.mockResolvedValue({ id: newer.id, purpose: 'recovery', code });
  expect(await takeNativeAuthCallback()).toMatchObject({ id: newer.id });
});
it('never accepts access or refresh tokens as callback codes', async () => {
  const ipc = bridge(); await authRedirect('recovery');
  ipc.take.mockResolvedValue({ id: fixture.id, purpose: fixture.purpose, code: 'eyJ.header.payload.signature' });
  await expect(takeNativeAuthCallback()).rejects.toThrow('链接无效');
});
