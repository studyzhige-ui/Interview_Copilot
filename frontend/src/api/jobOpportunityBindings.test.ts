import { beforeEach, describe, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('./client', () => ({ apiClient: client }));
vi.mock('./fileAssets', () => ({ uploadFileAsset: vi.fn() }));

import { startAnalyze, updateInterviewRecord } from './interview';
import { startMockInterview } from './mock';

describe('Interview JobOpportunity API bindings', () => {
  beforeEach(() => Object.values(client).forEach((mock) => mock.mockReset()));

  it('forwards the selected JobOpportunity when starting upload analysis', async () => {
    client.post.mockResolvedValue({ data: { status: 'processing', record_id: 'record-1' } });
    await startAnalyze({
      upload_id: 'audio-1',
      resume_file_asset_id: 'resume-asset-1',
      language: 'zh',
      job_opportunity_id: 'job-1',
    });
    expect(client.post).toHaveBeenCalledWith('/analyze', {
      upload_id: 'audio-1',
      resume_file_asset_id: 'resume-asset-1',
      language: 'zh',
      job_opportunity_id: 'job-1',
    });
  });

  it('sends explicit null when clearing an InterviewRecord relation', async () => {
    client.patch.mockResolvedValue({ data: {} });
    await updateInterviewRecord('record/1', { job_opportunity_id: null });
    expect(client.patch).toHaveBeenCalledWith('/interview-records/record%2F1', {
      job_opportunity_id: null,
    });
  });

  it('forwards the selected JobOpportunity when starting a mock interview', async () => {
    client.post.mockResolvedValue({ data: { record_id: 'record-2' } });
    await startMockInterview({
      resume_id: 'resume-1',
      jd_text: '这是一个长度足够的岗位说明，用于模拟面试测试。',
      interviewer_style: 'professional',
      target_question_count: 20,
      job_opportunity_id: 'job-2',
    });
    expect(client.post).toHaveBeenCalledWith('/mock-interviews/start', {
      resume_id: 'resume-1',
      jd_text: '这是一个长度足够的岗位说明，用于模拟面试测试。',
      interviewer_style: 'professional',
      target_question_count: 20,
      job_opportunity_id: 'job-2',
    });
  });
});
