import { expect, it } from 'vitest';
import { money } from './money';
it('formats integer micro-units without IEEE754 rounding', () => {
  expect(money('1')).toBe('0.000001');
  expect(money('9007199254740993')).toBe('9,007,199,254.740993');
  expect(money('0')).toBe('0');
  expect(money('1000000')).toBe('1');
  expect(money('-1')).toBe('无效金额');
  expect(money('NaN')).toBe('无效金额');
});
