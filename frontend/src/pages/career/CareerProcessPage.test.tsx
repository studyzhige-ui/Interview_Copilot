import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CareerProcessPage } from './CareerProcessPage';
import { listJobDescriptionSnapshots, listJobOpportunities, listJobOpportunityMergeCandidates, listJobOpportunityMerges, listNextActions, listProcessEvents } from '@/api/careerProcess';
import { getCareerProfile } from '@/api/careerProfile';

vi.mock('@/api/careerProcess', () => ({
  appendProcessEvent: vi.fn(), createJobOpportunity: vi.fn(), createNextAction: vi.fn(),
  editNextAction: vi.fn(),
  correctProcessEvent: vi.fn(),
  listJobOpportunities: vi.fn(), listNextActions: vi.fn(), listProcessEvents: vi.fn(),
  listJobOpportunityMergeCandidates: vi.fn(), listJobOpportunityMerges: vi.fn(),
  listJobDescriptionSnapshots: vi.fn(), createJobDescriptionSnapshot: vi.fn(),
  mergeJobOpportunities: vi.fn(), retractJobOpportunityMerge: vi.fn(),
  replaceJobOpportunityDirections: vi.fn(),
  transitionNextAction: vi.fn(),
}));
vi.mock('@/api/careerProfile', () => ({ getCareerProfile: vi.fn() }));
vi.mock('@/api/offers', () => ({ listCurrentOffers: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/artifacts', () => ({ listArtifacts: vi.fn().mockResolvedValue([]) }));
vi.mock('@/api/interview', () => ({ listInterviewRecords: vi.fn().mockResolvedValue([]) }));

describe('CareerProcessPage', () => {
  beforeEach(() => {
    vi.mocked(listJobOpportunityMergeCandidates).mockResolvedValue([]);
    vi.mocked(listJobOpportunityMerges).mockResolvedValue([]);
    vi.mocked(listJobDescriptionSnapshots).mockResolvedValue([]);
    vi.mocked(listJobOpportunities).mockResolvedValue([{
      id: 'job-1', user_id: 1, company_name: '示例科技', job_title: 'Agent 工程师', location: '上海', team: null,
      source_url: null, source_provider: null, external_job_id: null, external_application_id: null,
      phase: 'in_process', current_step: '一面结束', outcome: null, archived_at: null,
      direction_version: 1,
      direction_links: [{
        career_profile_direction_id: 'direction-1', position: 0,
        source_kind: 'user_assertion', source_identity: 'ui:create',
        match_reason: '岗位匹配', confirmed_at: '2026-08-12T10:00:00Z',
      }],
      last_event_at: '2026-08-13T10:00:00Z', created_at: '2026-08-12T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
    }]);
    vi.mocked(getCareerProfile).mockResolvedValue({
      id: 'profile-1', user_id: 1, personal_facts: [], version: 1,
      created_at: '2026-08-12T10:00:00Z', updated_at: '2026-08-12T10:00:00Z',
      directions: [{
        id: 'direction-1', label: 'Backend / Agent', lifecycle: 'active', priority: 0,
        criteria: { role_keywords: [], seniority: [], locations: [], work_modes: [], salary_min: null, salary_max: null, salary_currency: null, industries: [], technologies: [], exclusions: [] },
        confirmed_source_kind: 'user_edit', confirmed_source_id: null,
        confirmed_at: '2026-08-12T10:00:00Z',
      }],
    });
    vi.mocked(listProcessEvents).mockResolvedValue([{
      id: 'event-1', job_opportunity_id: 'job-1', sequence: 2, operation: 'assert', kind: 'interview_completed',
      occurred_at: '2026-08-13T10:00:00Z', observed_at: '2026-08-13T10:00:00Z', source_kind: 'user_assertion',
      source_identity: 'ui:1', source_version: null, description: '完成技术一面', step_summary: '等待结果',
      corrects_event_id: null, created_at: '2026-08-13T10:00:00Z',
      analysis_context_json: {},
    }]);
    vi.mocked(listNextActions).mockResolvedValue([{
      id: 'action-1', user_id: 1, job_opportunity_id: 'job-1', content: '整理一面复盘', status: 'planned',
      interview_record_id: null, offer_id: null, artifact_id: null,
      time_kind: 'flexible', starts_at: null, ends_at: null, due_at: null, original_time_text: null,
      source_timezone: null, source_kind: 'user_request', source_identity: 'ui:2', source_version: null,
      planned_at: '2026-08-13T10:00:00Z', resolved_at: null, close_reason: null,
      reminder_at: null, reminder_next_attempt_at: null, reminder_channel: null,
      reminder_delivered_at: null, reminder_dismissed_at: null, version: 0,
      created_at: '2026-08-13T10:00:00Z', updated_at: '2026-08-13T10:00:00Z',
    }]);
  });

  it('shows an opportunity timeline and its active next action', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<MemoryRouter><QueryClientProvider client={client}><CareerProcessPage /></QueryClientProvider></MemoryRouter>);
    expect(await screen.findAllByText('示例科技')).not.toHaveLength(0);
    expect(await screen.findByText('完成技术一面')).toBeInTheDocument();
    expect(screen.getByText('Backend / Agent')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '关联求职方向' }));
    expect(screen.getByRole('checkbox', { name: /Backend \/ Agent/ })).toBeChecked();
    expect(screen.getByText('整理一面复盘')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Offer 条款/ })).toHaveAttribute('href', '/career-process/job-1/offer');
    const handoffs = screen.getAllByRole('link', { name: /询问 Copilot/ });
    expect(handoffs.map((link) => link.getAttribute('href'))).toEqual(expect.arrayContaining([
      expect.stringContaining('object_kind=job_opportunity&object_id=job-1'),
      expect.stringContaining('object_kind=next_action&object_id=action-1'),
    ]));
  });
});
