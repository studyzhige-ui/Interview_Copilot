import { describe, it, expect } from 'vitest';
import type { AxiosError } from 'axios';

import { loginErr, registerErr, sendCodeErr } from './errors';

/** Tiny helper to build an AxiosError-shaped object for the error
 *  mappers. We only populate the fields the mappers actually read
 *  (status + data.detail) so the test doesn't depend on the rest
 *  of the Axios shape. */
function axiosError(status: number, detail?: string): AxiosError {
  return {
    isAxiosError: true,
    response: {
      status,
      data: detail ? { detail } : {},
      statusText: '',
      headers: {},
      config: {} as never,
    },
  } as unknown as AxiosError;
}

describe('loginErr', () => {
  it('maps the canonical "Incorrect email or password" detail to Chinese', () => {
    const e = axiosError(401, 'Incorrect email or password');
    expect(loginErr(e)).toBe('用户名或密码错误');
  });

  it('falls back to the generic 4xx detail when no mapping exists', () => {
    const e = axiosError(403, 'Forbidden zone');
    expect(loginErr(e)).toBe('Forbidden zone');
  });

  it('returns the 422 placeholder regardless of detail', () => {
    const e = axiosError(422, 'whatever the validator said');
    expect(loginErr(e)).toBe('请检查输入内容');
  });

  it('returns the fallback for non-4xx errors', () => {
    const e = axiosError(500, 'boom');
    expect(loginErr(e)).toBe('登录失败，请稍后重试');
  });
});

describe('registerErr', () => {
  it('maps the anti-enumeration generic 400 detail to the login-nudge message', () => {
    const e = axiosError(400, '注册失败，请检查输入或重试');
    expect(registerErr(e)).toContain('如果该邮箱已注册');
  });

  it('keeps legacy specific-cause mappings working for older backends', () => {
    const e = axiosError(400, '验证码错误');
    expect(registerErr(e)).toBe('验证码错误');
  });
});

describe('sendCodeErr', () => {
  it('returns the raw detail on 429 (cooldown) instead of remapping', () => {
    const e = axiosError(429, '请等待 42 秒后重试');
    expect(sendCodeErr(e)).toBe('请等待 42 秒后重试');
  });

  it('falls back when the status is not 429', () => {
    const e = axiosError(500);
    expect(sendCodeErr(e)).toBe('发送验证码失败，请稍后重试');
  });
});
