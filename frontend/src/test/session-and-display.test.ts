import { describe, expect, it } from 'vitest';
import { tokenStore, decodeJwtPayload } from '@/lib/token';
import { money } from '@/lib/money';
import { formatScore } from '@/lib/scoring';

const token = (sub: string, exp: number) => `header.${btoa(JSON.stringify({ sub, exp, token_version: 1 }))}.signature`;

describe('account authority fences', () => {
  it('accepts refresh within one authority, invalidates old responses after an account switch', () => {
    tokenStore.set(token('alice', 1), 'r1');
    const pendingRequest = tokenStore.snapshot();
    tokenStore.set(token('alice', 2), 'r2');
    expect(tokenStore.matches(pendingRequest)).toBe(true);
    tokenStore.set(token('bob', 3), 'r3');
    expect(tokenStore.matches(pendingRequest)).toBe(false);
  });
  it('logout fences pending work even when the same account logs back in', () => {
    tokenStore.set(token('alice', 1), 'r');
    const pendingRequest = tokenStore.snapshot();
    tokenStore.clear();
    expect(tokenStore.getAccess()).toBeNull();
    expect(tokenStore.isLocked()).toBe(true);
    tokenStore.set(token('alice', 1), 'r');
    expect(tokenStore.matches(pendingRequest)).toBe(false);
  });
  it('malformed tokens are never treated as decoded identity', () => {
    expect(decodeJwtPayload('broken')).toBeNull();
  });
});

describe('evidence display', () => {
  it('does not round money through a floating-point integer', () => {
    expect(money('9007199254740993000001').replaceAll(',', '')).toBe('9007199254740993.000001');
    expect(money('-1')).toBe('无效金额');
  });
  it.each([undefined, null, NaN, Infinity, -1, 11, 5.55])('does not invent a score for %s', value => {
    expect(formatScore(value)).toBe('未评估');
  });
  it('shows the defined ten-point score', () => { expect(formatScore(7.2)).toBe('7.2/10'); });
});
