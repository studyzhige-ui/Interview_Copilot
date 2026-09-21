import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { correctTranscript, getTranscriptReceipt, type TranscriptReceipt } from '@/api/transcripts';
import { TranscriptEditor } from './TranscriptEditor';
import { transcriptPage as page, transcriptReceipt } from './transcriptTestData';

vi.mock('@/api/transcripts', () => ({ correctTranscript: vi.fn(), getTranscriptReceipt: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
function open() {
  const saved = vi.fn(), pending = vi.fn();
  const result = render(<TranscriptEditor recordId="r1" page={page} word={page.words[0]}
    onSaved={saved} onPending={pending} onClose={vi.fn()} />);
  fireEvent.change(screen.getByLabelText('原词文字'), { target: { value: '纠正词' } });
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '核对录音' } });
  return { saved, pending, ...result };
}
it('sends one UUID-bound edit only after explicit save and blocks double-click', async () => {
  let resolve!: (value: TranscriptReceipt) => void;
  vi.mocked(correctTranscript).mockReturnValue(new Promise((res) => { resolve = res; }));
  const { saved } = open();
  expect(correctTranscript).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('保存纠正')); fireEvent.click(screen.getByText('保存纠正'));
  expect(correctTranscript).toHaveBeenCalledOnce();
  const command = vi.mocked(correctTranscript).mock.calls[0][1];
  expect(command.expected_transcript_id).toBe('tr1');
  expect(command.request_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(command.words).toEqual([{ word_id: 'w000001', text: '纠正词', speaker_id: 's1' }]);
  await act(async () => resolve(transcriptReceipt(command.request_id)));
  expect(saved).toHaveBeenCalledOnce();
});
it('reconciles lost success using a receipt GET without another write', async () => {
  vi.mocked(correctTranscript).mockRejectedValue(new Error('lost reply'));
  const { saved } = open(); fireEvent.click(screen.getByText('保存纠正'));
  await screen.findByRole('alert');
  const id = vi.mocked(correctTranscript).mock.calls[0][1].request_id;
  vi.mocked(getTranscriptReceipt).mockResolvedValue(transcriptReceipt(id));
  expect(screen.getByLabelText('原词文字')).toHaveValue('纠正词');
  expect(screen.getByLabelText('原词文字')).toHaveAttribute('readonly');
  fireEvent.click(screen.getByText('核对纠正收据'));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(correctTranscript).toHaveBeenCalledOnce();
});
it('404 reconciliation permits only explicit replay of the exact frozen request', async () => {
  vi.mocked(correctTranscript).mockRejectedValue(new Error('lost'));
  vi.mocked(getTranscriptReceipt).mockRejectedValue({ response: { status: 404 } });
  open(); fireEvent.click(screen.getByText('保存纠正')); await screen.findByRole('alert');
  const command = vi.mocked(correctTranscript).mock.calls[0][1];
  fireEvent.click(screen.getByText('核对纠正收据'));
  const replay = await screen.findByText('使用原请求安全重试');
  await act(async () => { fireEvent.click(replay); });
  expect(correctTranscript).toHaveBeenCalledTimes(2);
  expect(vi.mocked(correctTranscript).mock.calls[1][1]).toBe(command);
});
it('does not rebase or replay a conflicting edit', async () => {
  vi.mocked(correctTranscript).mockRejectedValue({ response: { status: 409 } });
  vi.mocked(getTranscriptReceipt).mockRejectedValue({ response: { status: 404 } });
  open(); fireEvent.click(screen.getByText('保存纠正')); await screen.findByRole('alert');
  fireEvent.click(screen.getByText('核对纠正收据'));
  await screen.findByText(/尚未查到收据/);
  expect(screen.queryByText('使用原请求安全重试')).not.toBeInTheDocument();
  expect(screen.getByLabelText('原词文字')).toHaveValue('纠正词');
  expect(correctTranscript).toHaveBeenCalledOnce();
});
it('does not silently accept a suggested speaker role', async () => {
  render(<TranscriptEditor recordId="r1" page={page} speaker="s1" onSaved={vi.fn()} onPending={vi.fn()} onClose={vi.fn()} />);
  expect(screen.getByLabelText('确认角色')).toHaveValue('unknown');
  fireEvent.change(screen.getByLabelText('确认角色'), { target: { value: 'candidate' } });
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '本人确认' } });
  vi.mocked(correctTranscript).mockRejectedValue(new Error('offline'));
  fireEvent.click(screen.getByText('保存纠正')); await screen.findByRole('alert');
  expect(vi.mocked(correctTranscript).mock.calls[0][1].speaker_roles).toEqual({ s1: 'candidate' });
  expect(vi.mocked(correctTranscript).mock.calls[0][1].words).toEqual([]);
});
it('keeps the parent unchanged after unmount and leaves pending receipt recovery available', async () => {
  let resolve!: (value: TranscriptReceipt) => void;
  vi.mocked(correctTranscript).mockReturnValue(new Promise((res) => { resolve = res; }));
  const { unmount, saved, pending } = open();
  fireEvent.click(screen.getByText('保存纠正'));
  const command = vi.mocked(correctTranscript).mock.calls[0][1];
  unmount(); await act(async () => resolve(transcriptReceipt(command.request_id)));
  expect(saved).not.toHaveBeenCalled();
  expect(pending).toHaveBeenLastCalledWith(command.request_id);
});
