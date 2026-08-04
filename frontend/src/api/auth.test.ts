import { beforeEach, describe, expect, it, vi } from 'vitest';

const { post } = vi.hoisted(() => ({ post: vi.fn() }));

vi.mock('./client', () => ({ apiClient: { post } }));
vi.mock('./fileAssets', () => ({ uploadFileAsset: vi.fn() }));
vi.mock('@/lib/token', () => ({
  tokenStore: { getRefresh: vi.fn(), clear: vi.fn() },
}));

import { resetPassword, sendVerificationCode } from './auth';

describe('password recovery API', () => {
  beforeEach(() => post.mockReset());

  it('requests a reset-password verification code', async () => {
    post.mockResolvedValue({ data: { status: 'sent', expires_in: 600 } });

    await sendVerificationCode('alice@example.com', 'reset_password');

    expect(post).toHaveBeenCalledWith('/auth/send-code', {
      email: 'alice@example.com',
      purpose: 'reset_password',
    });
  });

  it('submits the one-time code and new password', async () => {
    post.mockResolvedValue({ data: { status: 'ok', message: '密码已重置' } });

    const result = await resetPassword('alice@example.com', '123456', 'newpw123');

    expect(post).toHaveBeenCalledWith('/auth/reset-password', {
      email: 'alice@example.com',
      code: '123456',
      new_password: 'newpw123',
    });
    expect(result.status).toBe('ok');
  });
});
