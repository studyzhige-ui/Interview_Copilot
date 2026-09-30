import { describe, expect, it } from 'vitest';
import { formatScore, scoreFraction, validScore } from './scoring';
describe('the single ten-point display scale', () => {
  it('shows zero as measured and missing as unassessed', () => {
    expect(formatScore(0)).toBe('0/10');
    expect(formatScore(8.2)).toBe('8.2/10');
    expect(formatScore(null)).toBe('未评估');
    for (const invalid of [false, '10', 100, NaN, Infinity, -1]) {
      expect(validScore(invalid)).toBe(false);
      expect(formatScore(invalid)).toBe('未评估');
    }
  });
  it('uses percentages only to size a shape, not as score units', () => {
    expect(scoreFraction(8)).toBe(0.8);
    expect(scoreFraction(100)).toBe(0);
  });
});
