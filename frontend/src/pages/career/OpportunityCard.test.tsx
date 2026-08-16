import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { OpportunityCard } from './OpportunityCard';
import type { JobOpportunity } from '@/types/career';

const MOCK_OPPORTUNITY: JobOpportunity = {
  id: 'opp-tencent',
  user_id: 1,
  company_name: '腾讯科技',
  job_title: '分布式架构专家',
  location: '深圳',
  team: '微信事业群',
  source_url: null,
  source_provider: null,
  external_job_id: null,
  external_application_id: null,
  phase: 'in_process',
  current_step: '技术二面',
  outcome: null,
  archived_at: null,
  last_event_at: '2026-08-15T12:00:00Z',
  direction_version: 1,
  direction_links: [],
  created_at: '2026-08-10T00:00:00Z',
  updated_at: '2026-08-15T12:00:00Z',
};

describe('OpportunityCard', () => {
  it('renders horizontal opportunity card with company, title, meta and dynamic stages', () => {
    render(
      <MemoryRouter>
        <OpportunityCard opportunity={MOCK_OPPORTUNITY} />
      </MemoryRouter>,
    );

    expect(screen.getByText('腾讯科技')).toBeInTheDocument();
    expect(screen.getByText('· 分布式架构专家')).toBeInTheDocument();
    expect(screen.getByText('深圳')).toBeInTheDocument();
    expect(screen.getByText('微信事业群')).toBeInTheDocument();

    // Stage timeline
    expect(screen.getAllByText('技术二面').length).toBeGreaterThan(0);
    expect(screen.getByText('面试空间')).toBeInTheDocument();
  });
});
