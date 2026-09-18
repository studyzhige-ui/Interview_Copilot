import type { RecoverableSubmission } from './types';

const key = (sessionId: string) => `chat-unconfirmed:${sessionId}`;

export function saveUnconfirmed(sessionId: string, value?: RecoverableSubmission) {
  try {
    if (value) sessionStorage.setItem(key(sessionId), JSON.stringify(value));
    else sessionStorage.removeItem(key(sessionId));
  } catch { /* The current page still retains the original submission. */ }
}

export function readUnconfirmed(sessionId: string): RecoverableSubmission | undefined {
  try {
    const value = JSON.parse(sessionStorage.getItem(key(sessionId)) ?? 'null');
    if (!value || typeof value.payload !== 'string' || !value.submission
      || typeof value.submission.submissionId !== 'string' || typeof value.submission.sourceClientId !== 'string'
      || value.submission.version !== 1 || !Array.isArray(value.attachments)
      || !Array.isArray(value.objectReferences) || !Array.isArray(value.questionIndexes)
      || !['CHAT', 'AGENT'].includes(value.mode) || !['standard', 'auto'].includes(value.executionMode)) return undefined;
    return value;
  } catch { return undefined; }
}
