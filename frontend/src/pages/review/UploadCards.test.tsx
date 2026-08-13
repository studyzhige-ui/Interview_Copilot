import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  startAnalyze: vi.fn(), uploadAudio: vi.fn(), updateInterviewRecord: vi.fn(),
  uploadFileAsset: vi.fn(),
}));

vi.mock('@/api/interview', () => ({
  startAnalyze: api.startAnalyze,
  uploadAudio: api.uploadAudio,
  updateInterviewRecord: api.updateInterviewRecord,
}));
vi.mock('@/api/fileAssets', () => ({ uploadFileAsset: api.uploadFileAsset }));
vi.mock('@/pages/career/JobOpportunitySelect', () => ({
  JobOpportunitySelect: ({ value, onChange }: { value: string; onChange: (value: string) => void }) => (
    <select aria-label="录音复盘关联岗位" value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">不关联</option><option value="job-1">甲公司 · 后端工程师</option>
    </select>
  ),
}));

import { UploadCards } from './UploadCards';

describe('UploadCards JobOpportunity binding', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.uploadAudio.mockResolvedValue({ upload_id: 'audio-asset', filename: 'audio.mp3' });
    api.uploadFileAsset.mockResolvedValue('resume-asset');
    api.startAnalyze.mockResolvedValue({
      status: 'processing', message: 'queued', record_id: 'record-1', task_id: 'task-1',
    });
  });

  it('forwards the explicitly selected JobOpportunity to analysis creation', async () => {
    const onStart = vi.fn();
    const { container } = render(<UploadCards analysis={null} onStart={onStart} />);
    const inputs = container.querySelectorAll<HTMLInputElement>('input[type="file"]');
    fireEvent.change(inputs[0], { target: { files: [new File(['audio'], 'audio.mp3', { type: 'audio/mpeg' })] } });
    fireEvent.change(inputs[1], { target: { files: [new File(['resume'], 'resume.pdf', { type: 'application/pdf' })] } });
    await waitFor(() => expect(screen.getByRole('button', { name: '开始分析' })).toBeEnabled());
    fireEvent.change(screen.getByRole('combobox', { name: '录音复盘关联岗位' }), {
      target: { value: 'job-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: '开始分析' }));
    await waitFor(() => expect(api.startAnalyze).toHaveBeenCalledWith({
      upload_id: 'audio-asset',
      resume_file_asset_id: 'resume-asset',
      jd_file_asset_id: undefined,
      job_opportunity_id: 'job-1',
      language: 'zh',
    }));
  });
});
