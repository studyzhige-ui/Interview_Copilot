/** All evaluation scores use 0–10. Physical metrics retain their own units. */
export const SCORE_MAX = 10;
export const SCORE_SCALE_VERSION = 'score10-v1';
export function validScore(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= SCORE_MAX
    && Math.abs(value * 10 - Math.round(value * 10)) <= 1e-8;
}
export function formatScore(value: unknown): string {
  if (!validScore(value)) return '未评估';
  return `${Number(value.toFixed(1))}/10`;
}
/** A drawing ratio only: never persist or display this as a percentage score. */
export function scoreFraction(value: unknown): number {
  return validScore(value) ? value / SCORE_MAX : 0;
}
