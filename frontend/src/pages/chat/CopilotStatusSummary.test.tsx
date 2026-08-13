import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getCareerProfile } from '@/api/careerProfile';
import { listJobOpportunities, listNextActions } from '@/api/careerProcess';
import { CopilotStatusSummary } from './CopilotStatusSummary';

vi.mock('@/api/careerProfile', () => ({ getCareerProfile: vi.fn() }));
vi.mock('@/api/careerProcess', () => ({
  listJobOpportunities: vi.fn(),
  listNextActions: vi.fn(),
}));

function renderSummary() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CopilotStatusSummary />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CopilotStatusSummary', () => {
  beforeEach(() => {
    vi.mocked(getCareerProfile).mockResolvedValue({
      id: 'profile-1', user_id: 1, personal_facts: [], version: 1,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
      directions: [{
        id: 'direction-1', label: 'Backend', lifecycle: 'active', priority: 1,
        criteria: {
          role_keywords: [], seniority: [], locations: [], work_modes: [],
          salary_min: null, salary_max: null, salary_currency: null,
          industries: [], technologies: [], exclusions: [],
        },
        confirmed_source_kind: 'user_edit', confirmed_source_id: null,
        confirmed_at: '2026-08-01T00:00:00Z',
      }],
    });
    vi.mocked(listJobOpportunities).mockResolvedValue([{
      id: 'job-1', user_id: 1, company_name: 'Example', job_title: 'Engineer',
      location: null, team: null, source_url: null, source_provider: null,
      external_job_id: null, external_application_id: null, phase: 'in_process',
      current_step: 'Interview', outcome: null, archived_at: null,
      last_event_at: null, direction_version: 1, direction_links: [],
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    }]);
    vi.mocked(listNextActions).mockResolvedValue([{
      id: 'action-1', user_id: 1, job_opportunity_id: 'job-1',
      interview_record_id: null, offer_id: null, artifact_id: null,
      content: 'Prepare interview', status: 'planned', time_kind: 'flexible',
      starts_at: null, ends_at: null, due_at: null, original_time_text: null,
      source_timezone: null, source_kind: 'user_request', source_identity: 'ui:1',
      source_version: null, planned_at: null, resolved_at: null, close_reason: null,
      reminder_at: null, reminder_next_attempt_at: null, reminder_channel: null,
      reminder_delivered_at: null, reminder_dismissed_at: null, version: 1,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    }]);
  });

  it('derives a bounded overview from the three canonical owners', async () => {
    renderSummary();

    expect(await screen.findByText('方向')).toBeInTheDocument();
    expect(screen.getByText('机会')).toBeInTheDocument();
    expect(screen.getByText('行动')).toBeInTheDocument();
    expect(screen.getByText('没有需要立即处理的阻塞项。')).toBeInTheDocument();
    expect(listNextActions).toHaveBeenCalledWith(['suggested', 'planned']);
  });

  it('surfaces the absence of an active direction without creating state', async () => {
    vi.mocked(getCareerProfile).mockResolvedValueOnce({
      id: 'profile-1', user_id: 1, personal_facts: [], directions: [], version: 1,
      created_at: '2026-08-01T00:00:00Z', updated_at: '2026-08-01T00:00:00Z',
    });
    renderSummary();

    expect(await screen.findByText('还没有启用的求职方向')).toBeInTheDocument();
  });
});
