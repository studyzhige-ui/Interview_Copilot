import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { listJobOpportunities } from '@/api/careerProcess';
import { updateInterviewRecord } from '@/api/interview';
import { InterviewOpportunityControl } from './InterviewOpportunityControl';

vi.mock('@/api/careerProcess', () => ({ listJobOpportunities: vi.fn() }));
vi.mock('@/api/interview', () => ({ updateInterviewRecord: vi.fn() }));

function renderControl(initialJobOpportunityId: string | null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InterviewOpportunityControl
        interviewId="record-1"
        initialJobOpportunityId={initialJobOpportunityId}
      />
    </QueryClientProvider>,
  );
}

describe('InterviewOpportunityControl', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(updateInterviewRecord).mockResolvedValue(undefined);
    vi.mocked(listJobOpportunities).mockResolvedValue([{
      id: 'job-1', user_id: 1, company_name: '甲公司', job_title: '平台工程师',
      location: '上海', team: null, source_url: null, source_provider: null,
      external_job_id: null, external_application_id: null, phase: 'in_process',
      current_step: '一面', outcome: null, archived_at: null, last_event_at: null,
      direction_version: 0, direction_links: [],
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    }]);
  });

  it('displays the persisted relation and explicitly clears it with null', async () => {
    renderControl('job-1');
    const selector = await screen.findByRole('combobox', { name: '本次面试对应岗位' });
    await waitFor(() => expect(selector).toHaveValue('job-1'));
    expect(screen.getByRole('option', { name: /甲公司 · 平台工程师/ })).toBeInTheDocument();

    fireEvent.change(selector, { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: '清除关联' }));
    await waitFor(() => expect(updateInterviewRecord).toHaveBeenCalledWith('record-1', {
      job_opportunity_id: null,
    }));
  });
});
