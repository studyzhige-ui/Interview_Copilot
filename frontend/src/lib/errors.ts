import type { AxiosError } from 'axios';

type ApiErr = AxiosError<{ detail?: string }>;

const LOGIN_MAP: Record<string, string> = {
  'Incorrect email or password': '用户名或密码错误',
};

const REGISTER_MAP: Record<string, string> = {
  // Backend now collapses username-taken / email-taken / wrong-code into a
  // single generic 400 (anti-enumeration). Map it to a hint that nudges
  // the user toward login without revealing which field actually failed.
  '注册失败，请检查输入或重试': '注册失败 — 检查输入；如果该邮箱已注册请改用登录或重置密码',
  // Legacy backends may still emit these specific strings — keep the map
  // entries so older deployments degrade gracefully.
  'The user with this username already exists in the system': '该用户名已被占用',
  '该用户名已被占用': '该用户名已被占用',
  '该邮箱已注册': '该邮箱已注册',
  '验证码错误': '验证码错误',
  '验证码已过期或未发送，请重新获取': '验证码已过期，请重新获取',
  '尝试次数过多，请重新获取验证码': '尝试次数过多，请重新获取验证码',
};

const CODE_MAP: Record<string, string> = {
  '该邮箱已注册': '该邮箱已注册',
};

function statusOf(e: unknown): number | undefined {
  return (e as ApiErr)?.response?.status;
}

function detailOf(e: unknown): string | undefined {
  const d = (e as ApiErr)?.response?.data?.detail;
  return typeof d === 'string' ? d : undefined;
}

function mapWith(e: unknown, table: Record<string, string>, fallback: string): string {
  const s = statusOf(e);
  const detail = detailOf(e);
  if (s === 422) return '请检查输入内容';
  if (s && s >= 400 && s < 500) {
    if (detail && table[detail]) return table[detail];
    return detail ?? fallback;
  }
  return fallback;
}

export function loginErr(e: unknown): string {
  return mapWith(e, LOGIN_MAP, '登录失败，请稍后重试');
}

export function registerErr(e: unknown): string {
  return mapWith(e, REGISTER_MAP, '注册失败，请稍后重试');
}

export function sendCodeErr(e: unknown): string {
  // 429 (rate-limited / cooldown) — detail already has the cooldown seconds
  const s = (e as { response?: { status?: number } }).response?.status;
  const d = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail;
  if (s === 429 && d) return d;
  return mapWith(e, CODE_MAP, '发送验证码失败，请稍后重试');
}
