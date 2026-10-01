import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { getTranscriptAudio } from '@/api/transcripts';
import { TranscriptAudio } from './TranscriptAudio';
import { transcriptPage as page } from './transcriptTestData';
vi.mock('@/api/transcripts', () => ({ getTranscriptAudio: vi.fn() }));
beforeEach(() => {
  vi.resetAllMocks();
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  URL.createObjectURL = vi.fn(() => 'blob:verified-clip');
  URL.revokeObjectURL = vi.fn();
});
it('sends the selected version and word IDs and releases the clip on unmount', async () => {
  vi.mocked(getTranscriptAudio).mockResolvedValue(new Blob(['wav'], { type: 'audio/wav' }));
  const { unmount } = render(<TranscriptAudio recordId="r1" page={page} />);
  fireEvent.click(screen.getByText('读取原录音片段'));
  await waitFor(() => expect(screen.getByLabelText('所选原录音')).toHaveAttribute('src', 'blob:verified-clip'));
  expect(getTranscriptAudio).toHaveBeenCalledWith('r1', {
    transcript_id: 'tr1', first_word_id: 'w000001', last_word_id: 'w000001',
  }, page.audio_sha256, expect.any(AbortSignal));
  unmount(); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:verified-clip');
});
it('suppresses a late reply when the selected word range changes', async () => {
  let resolve!: (value: Blob) => void;
  vi.mocked(getTranscriptAudio).mockReturnValue(new Promise((res) => { resolve = res; }));
  render(<TranscriptAudio recordId="r1" page={page} />);
  fireEvent.click(screen.getByText('读取原录音片段'));
  const signal = vi.mocked(getTranscriptAudio).mock.calls[0][3];
  fireEvent.change(screen.getByLabelText('回放起始词'), { target: { value: 'w000002' } });
  await act(async () => resolve(new Blob(['late'], { type: 'audio/wav' })));
  expect(signal.aborted).toBe(true);
  expect(URL.createObjectURL).not.toHaveBeenCalled();
  expect(screen.getByLabelText('所选原录音')).not.toHaveAttribute('src');
});
it('does not create or play an audio URL when source verification fails', async () => {
  vi.mocked(getTranscriptAudio).mockRejectedValue({ response: { status: 409 } });
  render(<TranscriptAudio recordId="r1" page={page} />);
  fireEvent.click(screen.getByText('读取原录音片段'));
  await screen.findByRole('alert');
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});
