import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listResumes } from '@/api/resumes';
import { listJobOpportunities } from '@/api/careerProcess';
import { MockSetup } from './MockSetup';

vi.mock('@/api/resumes', () => ({
  createResumeFromFile: vi.fn(),
  listResumes: vi.fn(),
  waitForResumeUsable: vi.fn(),
}));

vi.mock('@/api/mock', () => ({ parseJdForMock: vi.fn() }));
vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn() }));

function renderSetup(
  onReady: Parameters<typeof MockSetup>[0]['onReady'],
  props: Pick<Parameters<typeof MockSetup>[0], 'prefill' | 'onPrefillApplied'> = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MockSetup onReady={onReady} starting={false} {...props} />
    </QueryClientProvider>,
  );
}

describe('MockSetup', () => {
  beforeEach(() => {
    vi.mocked(listResumes).mockReset().mockResolvedValue([
      {
        id: 'resume-1',
        title: '我的简历',
        is_default: true,
        parse_status: 'ready',
        file_asset_id: null,
        has_text: true,
        created_at: '2026-08-10T10:00:00Z',
        updated_at: '2026-08-10T10:00:00Z',
      },
    ]);
    vi.mocked(listJobOpportunities).mockReset().mockResolvedValue([{
      id: 'job-1', user_id: 1, company_name: '甲公司', job_title: '后端工程师',
      location: null, team: null, source_url: null, source_provider: null,
      external_job_id: null, external_application_id: null, phase: 'in_process',
      current_step: '面试', outcome: null, archived_at: null, last_event_at: null,
      direction_version: 0, direction_links: [],
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    }]);
  });

  it('uses 20 as the default advisory target and allows selecting 30', async () => {
    const onReady = vi.fn();
    renderSetup(onReady);

    await screen.findByRole('button', { name: /选已有.*1/ });
    fireEvent.click(screen.getByRole('button', { name: /粘贴文本/ }));
    fireEvent.change(screen.getByPlaceholderText(/把 JD 全文粘贴到这里/), {
      target: { value: '这是一个用于测试的后端工程师岗位说明，要求熟悉 Python 和数据库。' },
    });

    fireEvent.click(screen.getByRole('button', { name: /开始模拟面试/ }));
    await waitFor(() => {
      expect(onReady).toHaveBeenLastCalledWith(
        expect.objectContaining({ target_question_count: 20 }),
      );
    });

    fireEvent.click(screen.getByRole('button', { name: /深入面试/ }));
    fireEvent.change(screen.getByRole('combobox', { name: '模拟面试关联岗位' }), {
      target: { value: 'job-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: /开始模拟面试/ }));
    expect(onReady).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_question_count: 30, job_opportunity_id: 'job-1' }),
    );
  });

  it('retains a JobOpportunity supplied by the typed prefill handoff', async () => {
    const onReady = vi.fn<Parameters<typeof MockSetup>[0]['onReady']>();
    renderSetup(onReady, {
      prefill: {
        kind: 'mock_prefill', resume_id: 'resume-1',
        jd_text: '这是一个长度足够的预填岗位说明，要求熟悉 Python 与数据库。',
        interviewer_style: 'professional', target_question_count: 20,
        job_opportunity_id: 'job-1',
      },
      onPrefillApplied: vi.fn(),
    });

    await waitFor(() => expect(screen.getByRole('combobox', {
      name: '模拟面试关联岗位',
    })).toHaveValue('job-1'));
    fireEvent.click(screen.getByRole('button', { name: /开始模拟面试/ }));
    expect(onReady).toHaveBeenCalledWith(expect.objectContaining({
      job_opportunity_id: 'job-1',
    }));
  });
});
