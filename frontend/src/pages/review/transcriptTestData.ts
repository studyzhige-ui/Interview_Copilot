import type { TranscriptPage, TranscriptReceipt } from '@/api/transcripts';
export const transcriptPage: TranscriptPage = {
  transcript_id: 'tr1', current_transcript_id: 'tr1', source: 'local_qwen_asr', language: 'zh',
  audio_file_asset_id: 'fa1', audio_file_asset_version: 'file_asset:fa1', audio_sha256: 'a'.repeat(64),
  duration_seconds: 10, word_count: 2, next_offset: null, speakers: ['s1'],
  confirmed_roles: {}, suggested_roles: { s1: 'candidate' },
  words: [
    { word_id: 'w000001', text: '原词', start: 1, end: 1.5, alignment_status: 'aligned', speaker_id: 's1', overlap: false },
    { word_id: 'w000002', text: '项目', start: 2, end: 2.5, alignment_status: 'aligned', speaker_id: 's1', overlap: false },
  ],
};
export const transcriptReceipt = (id: string): TranscriptReceipt => ({
  request_id: id, previous_transcript_id: 'tr1', transcript_id: 'tr2', current_transcript_id: 'tr2',
  review_generation: 1, created_at: '2026-09-21T03:00:00Z', reanalysis_required: true,
});
