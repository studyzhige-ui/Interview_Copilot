import { describe, expect, it } from 'vitest';
import {
  CONVERSATION_ATTACHMENT_ACCEPT,
  conversationAttachmentPurpose,
} from './attachmentUpload';

describe('Conversation attachment upload routing', () => {
  it('routes media to transcription and documents to document parsing', () => {
    expect(conversationAttachmentPurpose({ name: 'interview.m4a', type: 'audio/mp4' }))
      .toBe('interview_audio');
    expect(conversationAttachmentPurpose({ name: 'recording.webm', type: '' }))
      .toBe('interview_audio');
    expect(conversationAttachmentPurpose({ name: 'resume.pdf', type: 'application/pdf' }))
      .toBe('knowledge_document');
  });

  it('advertises both document and bounded media formats', () => {
    expect(CONVERSATION_ATTACHMENT_ACCEPT).toContain('.pdf');
    expect(CONVERSATION_ATTACHMENT_ACCEPT).toContain('.mp3');
    expect(CONVERSATION_ATTACHMENT_ACCEPT).toContain('audio/*');
  });
});
