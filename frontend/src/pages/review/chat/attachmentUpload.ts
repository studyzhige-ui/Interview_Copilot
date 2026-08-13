import { KNOWLEDGE_ACCEPT } from '@/api/knowledge';

const MEDIA_EXTENSIONS = new Set([
  'aac', 'flac', 'm4a', 'm4b', 'mkv', 'mov', 'mp3', 'mp4', 'ogg', 'wav', 'webm',
]);

export const CONVERSATION_ATTACHMENT_ACCEPT = [
  KNOWLEDGE_ACCEPT,
  ...Array.from(MEDIA_EXTENSIONS, (extension) => `.${extension}`),
  'audio/*',
  'video/*',
].join(',');

export function conversationAttachmentPurpose(
  file: Pick<File, 'name' | 'type'>,
): 'knowledge_document' | 'interview_audio' {
  const mediaMime = file.type.startsWith('audio/') || file.type.startsWith('video/');
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  return mediaMime || MEDIA_EXTENSIONS.has(extension)
    ? 'interview_audio'
    : 'knowledge_document';
}
