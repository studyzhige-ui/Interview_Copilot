import type { AxiosError } from 'axios';

interface BusinessError {
  code?: string;
  message?: string;
}

type ApiErr = AxiosError<{ detail?: string | BusinessError }>;

function statusOf(e: unknown): number | undefined {
  return (e as ApiErr)?.response?.status;
}

function detailOf(e: unknown): string | undefined {
  const d = (e as ApiErr)?.response?.data?.detail;
  if (typeof d === 'string') return d;
  return typeof d?.message === 'string' ? d.message : undefined;
}

function clientError(e: unknown, fallback: string): string {
  const s = statusOf(e);
  const detail = detailOf(e);
  if (s === 422) return '请检查输入内容';
  if (s && s >= 400 && s < 500) {
    return detail ?? fallback;
  }
  return fallback;
}

export function loginErr(e: unknown): string {
  return clientError(e, '登录失败，请稍后重试');
}

export function registerErr(e: unknown): string {
  return clientError(e, '注册失败，请稍后重试');
}

export function sendCodeErr(e: unknown): string {
  // 429 (rate-limited / cooldown) — detail already has the cooldown seconds
  const s = (e as { response?: { status?: number } }).response?.status;
  const detail = detailOf(e);
  if (s === 429 && detail) return detail;
  return clientError(e, '发送验证码失败，请稍后重试');
}
