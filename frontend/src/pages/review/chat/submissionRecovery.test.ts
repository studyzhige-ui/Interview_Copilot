import { beforeEach, expect, it } from 'vitest';
import { readUnconfirmed, saveUnconfirmed } from './submissionRecovery';

beforeEach(() => sessionStorage.clear());

it('retains the exact submission across runtime reconstruction and clears on acknowledgement', () => {
  const request = { payload: '请分析简历', attachments: [], objectReferences: [], questionIndexes: [], mode: 'AGENT' as const, executionMode: 'standard' as const, submission: { submissionId: 'one', sourceClientId: 'client', version: 1 } };
  saveUnconfirmed('conversation', request);
  expect(readUnconfirmed('conversation')).toEqual(request);
  expect(readUnconfirmed('other')).toBeUndefined();
  saveUnconfirmed('conversation');
  expect(readUnconfirmed('conversation')).toBeUndefined();
});

it('ignores corrupt recovery data rather than preventing the conversation from opening', () => {
  sessionStorage.setItem('chat-unconfirmed:conversation', '{broken');
  expect(readUnconfirmed('conversation')).toBeUndefined();
});
