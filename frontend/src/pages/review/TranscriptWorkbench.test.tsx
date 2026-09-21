import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, expect, it, vi } from 'vitest';
import { getTranscript, getTranscriptHistory, correctTranscript, getTranscriptReceipt } from '@/api/transcripts';
import { TranscriptWorkbench } from './TranscriptWorkbench';
import { transcriptPage as page, transcriptReceipt } from './transcriptTestData';
vi.mock('@/api/transcripts', () => ({ getTranscript: vi.fn(), getTranscriptHistory: vi.fn(), correctTranscript: vi.fn(), getTranscriptReceipt: vi.fn(), getTranscriptAudio: vi.fn() }));
vi.mock('./TranscriptAudio', () => ({ TranscriptAudio: () => <div>音频测试边界</div> }));
beforeEach(() => {
  vi.resetAllMocks(); sessionStorage.clear();
  vi.mocked(getTranscript).mockResolvedValue(page);
  vi.mocked(getTranscriptHistory).mockResolvedValue({ items: [], next_cursor: null });
});
function open() {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const reanalyze = vi.fn(), corrected = vi.fn();
  render(<QueryClientProvider client={cache}><TranscriptWorkbench recordId="r1" onCorrected={corrected} onReanalyze={reanalyze} /></QueryClientProvider>);
  return { cache, reanalyze, corrected };
}
it('pins pagination to the displayed immutable transcript version', async () => {
  vi.mocked(getTranscript).mockResolvedValue({ ...page, next_offset: 100, word_count: 150 });
  open(); await screen.findByRole('list', { name: '原始词证据' });
  fireEvent.click(screen.getByText('下一页原词'));
  await waitFor(() => expect(getTranscript).toHaveBeenLastCalledWith('r1', expect.objectContaining({ transcriptId: 'tr1', offset: 100 })));
});
it('historical versions are read-only and never initiate reanalysis', async () => {
  vi.mocked(getTranscript).mockResolvedValue({ ...page, current_transcript_id: 'tr2' });
  const { reanalyze } = open(); await screen.findByText(/正在查看历史版本/);
  expect(screen.queryByRole('button', { name: '纠正 w000001' })).not.toBeInTheDocument();
  expect(screen.getByText('根据当前转写重新提取并分析')).toBeDisabled();
  expect(reanalyze).not.toHaveBeenCalled();
});
it('an incoming server refresh cannot replace the active editor draft or expected version', async () => {
  const { cache } = open(); await screen.findByRole('list', { name: '原始词证据' });
  fireEvent.click(screen.getByRole('button', { name: '纠正 w000001' }));
  fireEvent.change(screen.getByLabelText('原词文字'), { target: { value: '我的草稿' } });
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '核对' } });
  await act(async () => { cache.setQueryData(['transcript', 'r1', 'current', 0], { ...page, transcript_id: 'tr2', current_transcript_id: 'tr2' }); });
  expect(screen.getByLabelText('原词文字')).toHaveValue('我的草稿');
  vi.mocked(correctTranscript).mockRejectedValue({ response: { status: 409 } });
  fireEvent.click(screen.getByText('保存纠正')); await screen.findByRole('alert');
  expect(vi.mocked(correctTranscript).mock.calls[0][1].expected_transcript_id).toBe('tr1');
});
it('a confirmed save invalidates derived state but does not call the model', async () => {
  vi.mocked(correctTranscript).mockImplementation(async (_id, command) => transcriptReceipt(command.request_id));
  const { corrected, reanalyze } = open(); await screen.findByRole('list', { name: '原始词证据' });
  fireEvent.click(screen.getByRole('button', { name: '纠正 w000001' }));
  fireEvent.change(screen.getByLabelText('原词文字'), { target: { value: '改过的词' } });
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '核对' } });
  fireEvent.click(screen.getByText('保存纠正'));
  await waitFor(() => expect(corrected).toHaveBeenCalledWith(true));
  expect(reanalyze).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText('根据当前转写重新提取并分析'));
  expect(reanalyze).toHaveBeenCalledOnce();
});
it('after reload only a stored request identifier is used for GET reconciliation', async () => {
  const id = 'aaaaaaaa-aaaa-4aaa-aaaa-aaaaaaaaaaaa';
  sessionStorage.setItem('transcript-pending-receipt:r1', id);
  vi.mocked(getTranscriptReceipt).mockResolvedValue(transcriptReceipt(id));
  open(); fireEvent.click(await screen.findByText('读取上次纠正收据'));
  await waitFor(() => expect(getTranscriptReceipt).toHaveBeenCalledWith('r1', id));
  expect(correctTranscript).not.toHaveBeenCalled();
  await waitFor(() => expect(sessionStorage.getItem('transcript-pending-receipt:r1')).toBeNull());
});
it('history reads the requested before-version without mutating the source', async () => {
  vi.mocked(getTranscriptHistory).mockResolvedValue({ items: [{
    ...transcriptReceipt('req'), previous_transcript_id: 'tr0', transcript_id: 'tr1',
    reason: '纠正错词', word_ids: ['w000001'], confirmed_roles: { s1: 'candidate' }, created_at: '2026-09-21T03:00:00',
  }], next_cursor: null });
  open();
  const before = await screen.findByText('查看修改前版本');
  expect(screen.getByText('纠正错词').closest('article')?.querySelector('time')).toHaveAttribute('datetime', '2026-09-21T03:00:00Z');
  fireEvent.click(before);
  await waitFor(() => expect(getTranscript).toHaveBeenLastCalledWith('r1', expect.objectContaining({ transcriptId: 'tr0', offset: 0 })));
  expect(correctTranscript).not.toHaveBeenCalled();
});
