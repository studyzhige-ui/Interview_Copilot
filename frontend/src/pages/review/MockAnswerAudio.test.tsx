import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { getInterviewRecord } from '@/api/interview';
import { useAuthStore } from '@/store/authStore';
import type { InterviewRecordDetail } from '@/types/api';
import { MockAnswerAudio } from './MockAnswerAudio';
vi.mock('@/api/interview', () => ({ getInterviewRecord: vi.fn() }));
const props = { recordId: 'record-a', qaId: 'qa-a', assetId: 'asset-a', url: '/old-capability' };
function detail(url: string | null = '/fresh-capability', asset = 'asset-a'): InterviewRecordDetail {
  return { id: 'record-a', qa: [{ id: 'qa-a', answer_audio_url: url, answer_audio_file_asset_id: asset }] } as InterviewRecordDetail;
}
beforeEach(() => {
  vi.mocked(getInterviewRecord).mockReset();
  useAuthStore.setState({ subjectId: 'owner-a', isAuthed: true });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
it('renews once through the authorized detail and restores playback position', async () => {
  vi.mocked(getInterviewRecord).mockResolvedValue(detail());
  render(<MockAnswerAudio {...props} />);
  const old = screen.getByLabelText('回答原录音') as HTMLAudioElement;
  old.currentTime = 12;
  fireEvent.error(old);
  await waitFor(() => expect(screen.getByLabelText('回答原录音')).toHaveAttribute('src', '/fresh-capability'));
  const fresh = screen.getByLabelText('回答原录音') as HTMLAudioElement;
  fireEvent.loadedMetadata(fresh);
  expect(fresh.currentTime).toBe(12);
  expect(getInterviewRecord).toHaveBeenCalledWith('record-a', { signal: expect.any(AbortSignal) });
  fireEvent.error(fresh);
  expect(screen.getByRole('alert')).toBeInTheDocument();
  expect(fresh).not.toHaveAttribute('src');
  expect(getInterviewRecord).toHaveBeenCalledTimes(1);
});
it.each(['denied', 'deleted', 'source-replaced'])('does not reuse an old URL after %s refresh', async (scenario) => {
  if (scenario === 'denied') vi.mocked(getInterviewRecord).mockRejectedValue(new Error('403'));
  else vi.mocked(getInterviewRecord).mockResolvedValue(scenario === 'deleted' ? detail(null) : detail('/different-source', 'asset-b'));
  render(<MockAnswerAudio {...props} />);
  fireEvent.error(screen.getByLabelText('回答原录音'));
  expect(await screen.findByRole('alert')).toBeInTheDocument();
  expect(screen.getByLabelText('回答原录音')).not.toHaveAttribute('src');
  expect(getInterviewRecord).toHaveBeenCalledTimes(1);
});
it('ignores repeated media errors while the single renewal is pending', async () => {
  let resolve!: (value: InterviewRecordDetail) => void;
  vi.mocked(getInterviewRecord).mockReturnValue(new Promise((done) => { resolve = done; }));
  render(<MockAnswerAudio {...props} />);
  const player = screen.getByLabelText('回答原录音');
  fireEvent.error(player); fireEvent.error(player);
  expect(getInterviewRecord).toHaveBeenCalledTimes(1);
  await act(async () => resolve(detail()));
  expect(screen.getByLabelText('回答原录音')).toHaveAttribute('src', '/fresh-capability');
});
it.each(['account', 'record', 'logout'])('discards late renewal after %s changes', async (change) => {
  let resolve!: (value: InterviewRecordDetail) => void;
  vi.mocked(getInterviewRecord).mockReturnValue(new Promise((done) => { resolve = done; }));
  const view = render(<MockAnswerAudio {...props} />);
  fireEvent.error(screen.getByLabelText('回答原录音'));
  const signal = vi.mocked(getInterviewRecord).mock.calls[0][1]!.signal!;
  if (change === 'account') act(() => useAuthStore.setState({ subjectId: 'owner-b' }));
  else if (change === 'logout') act(() => useAuthStore.setState({ subjectId: null, isAuthed: false }));
  else view.rerender(<MockAnswerAudio {...props} recordId="record-b" url="/record-b-capability" />);
  expect(signal.aborted).toBe(true);
  await act(async () => resolve(detail()));
  if (change === 'record') expect(screen.getByLabelText('回答原录音')).toHaveAttribute('src', '/record-b-capability');
  else expect(screen.queryByLabelText('回答原录音')).toBeNull();
});
