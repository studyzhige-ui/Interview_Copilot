import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PreparationPanel } from './PreparationPanel';
import { prepareInterview, type PreparationBrief } from '@/api/preparation';
vi.mock('@/api/preparation', () => ({ prepareInterview: vi.fn() }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const quote = { id: 'r001', start: 0, end: 6, text: 'Python' };
const brief = {
  schema_version: 1, method: 'source-excerpts-v1', snapshot_id: 'a'.repeat(64),
  resume_version_id: 'v1', resume_sha256: 'b'.repeat(64), jd_sha256: 'c'.repeat(64),
  items: [{ requirement: { ...quote, id: 'j001' }, evidence_candidates: [quote], shared_terms: ['python'], status: 'review_evidence', practice_focus: 'Verify Python experience, never invent.' }],
  resume_excerpts: [quote], omitted_resume_excerpt_count: 1,
  start_request: { purpose: 'full', focus: null, resume_id: 'r', resume_version_id: 'v1',
    resume_sha256: 'b'.repeat(64), jd_sha256: 'c'.repeat(64), jd_text: 'Python role needs real projects',
    jd_snapshot_id: null, jd_snapshot_version: null, job_opportunity_id: null,
    input_mode: 'text', interviewer_style: 'professional', target_question_count: 20 },
  markdown: '# preparation', disclaimer: '未定位到证据不是能力缺失结论。',
} satisfies PreparationBrief;
const props = { resumeId: 'r', jdText: 'Python role needs real projects', disabled: false, onPractice: vi.fn() };
it('preview is explicit, preserves original evidence, and starts only a selected pinned drill', async () => {
  vi.mocked(prepareInterview).mockResolvedValueOnce(brief);
  render(<PreparationPanel {...props} />);
  expect(prepareInterview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '生成原文准备预览' }));
  await screen.findByText(brief.disclaimer);
  expect(props.onPractice).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: '围绕此项开始专项练习' }));
  expect(props.onPractice).toHaveBeenCalledWith({ ...brief.start_request,
    purpose: 'focused_practice', focus: brief.items[0].practice_focus });
});
it('source change aborts old reads and a late result cannot offer an old practice', async () => {
  let resolve!: (value: PreparationBrief) => void;
  vi.mocked(prepareInterview).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const { rerender } = render(<PreparationPanel {...props} />);
  fireEvent.click(screen.getByRole('button', { name: '生成原文准备预览' }));
  const signal = vi.mocked(prepareInterview).mock.calls[0][1];
  rerender(<PreparationPanel {...props} resumeId="different" />);
  expect(signal.aborted).toBe(true);
  await act(async () => { resolve(brief); });
  expect(screen.queryByRole('button', { name: '围绕此项开始专项练习' })).toBeNull();
});
it('unmount aborts source reads and read failure does not start a model call', async () => {
  vi.mocked(prepareInterview).mockRejectedValueOnce(new Error('failed'));
  const { unmount } = render(<PreparationPanel {...props} />);
  fireEvent.click(screen.getByRole('button', { name: '生成原文准备预览' }));
  await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy());
  expect(props.onPractice).not.toHaveBeenCalled();
  unmount(); expect(prepareInterview).toHaveBeenCalledTimes(1);
});
