/** Reload recovery persists only intent identity, never an answer or recording. */
const key = (recordId: string) => `mock-answer-intent:${recordId}`;
interface AnswerIntent { requestId: string; questionMessageId: number }
export function readAnswerIntent(recordId: string): AnswerIntent | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key(recordId)) ?? 'null');
    if (value && typeof value.requestId === 'string'
      && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value.requestId)
      && Number.isSafeInteger(value.questionMessageId) && value.questionMessageId > 0) {
      return { requestId: value.requestId, questionMessageId: value.questionMessageId };
    }
  } catch { /* unavailable storage cannot authorize a model request */ }
  return null;
}
export function rememberAnswerIntent(recordId: string, requestId: string, questionMessageId: number) {
  try { sessionStorage.setItem(key(recordId), JSON.stringify({ requestId, questionMessageId })); } catch { /* in-memory recovery remains */ }
}
export function clearAnswerIntent(recordId: string, requestId?: string) {
  if (requestId && readAnswerIntent(recordId)?.requestId !== requestId) return;
  try { sessionStorage.removeItem(key(recordId)); } catch { /* unavailable storage */ }
}
