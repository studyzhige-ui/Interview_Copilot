import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { TodayPage } from './TodayPage';
import { listJobOpportunities } from '@/api/careerProcess';
import { listPersistentTasks } from '@/api/persistentTasks';

vi.mock('@/api/careerProcess', () => ({
  listJobOpportunities: vi.fn(),
}));

vi.mock('@/api/persistentTasks', () => ({
  listPersistentTasks: vi.fn(),
}));

describe('TodayPage', () => {
  beforeEach(() => {
    vi.mocked(listJobOpportunities).mockResolvedValue([
      {
        id: 'opp-1',
        user_id: 1,
        company_name: '腾讯科技',
        job_title: '后端开发专家',
        location: '深圳',
        team: '微信',
        source_url: null,
        source_provider: null,
        external_job_id: null,
        external_application_id: null,
        phase: 'in_process',
        current_step: '技术一面',
        outcome: null,
        archived_at: null,
        last_event_at: '2026-08-15T10:00:00Z',
        direction_version: 1,
        direction_links: [],
        created_at: '2026-08-10T00:00:00Z',
        updated_at: '2026-08-15T10:00:00Z',
      },
    ]);

    vi.mocked(listPersistentTasks).mockResolvedValue([]);
  });

  it('renders four quadrants and central floating Copilot island', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <TodayPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    // 4 Quadrants
    expect(await screen.findByText('下一步')).toBeInTheDocument();
    expect(screen.getByText('待我确认')).toBeInTheDocument();
    expect(screen.getByText('求职动态')).toBeInTheDocument();
    expect(screen.getByText('Copilot 工作')).toBeInTheDocument();

    // Central Floating Island
    expect(screen.getByPlaceholderText('向 Copilot 提问、指派任务或开启对话…')).toBeInTheDocument();
    expect(screen.getByText('发送')).toBeInTheDocument();
  });
});
