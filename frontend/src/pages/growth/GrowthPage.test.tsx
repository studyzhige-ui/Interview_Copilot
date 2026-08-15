import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { GrowthPage } from './GrowthPage';
import { listAbilitySignals } from '@/api/careerProfile';

vi.mock('@/api/careerProfile', () => ({
  listAbilitySignals: vi.fn(),
  changeAbilitySignalStatus: vi.fn(),
  recomputeInterviewAbilitySignals: vi.fn(),
}));

describe('GrowthPage', () => {
  beforeEach(() => {
    vi.mocked(listAbilitySignals).mockResolvedValue([
      {
        id: 'signal-1',
        user_id: 1,
        topic: '高并发与系统设计',
        signal_type: 'architecture',
        level: '精通 / Senior',
        score: 92,
        summary: '能精准定位分布式场景下的缓存击穿与一致性问题，并给出容灾方案。',
        confidence: 0.95,
        limitations: '需进一步深化海量数据冷热归档实践。',
        scope_kind: 'interview_record',
        scope_ref_id: 'rec-101',
        formed_at: '2026-08-14T10:00:00Z',
        rubric_version: 'v2',
        status: 'active',
        status_reason: null,
        supersedes_signal_id: null,
        version: 1,
        created_at: '2026-08-14T10:00:00Z',
        updated_at: '2026-08-14T10:00:00Z',
        status_changed_at: '2026-08-14T10:00:00Z',
        sources: [
          { source_kind: 'interview_record', source_id: 'rec-101', source_version: 'v1' },
        ],
      },
    ]);
  });

  it('renders growth metrics, ability signals and permits evidence inspection', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <MemoryRouter>
        <QueryClientProvider client={client}>
          <GrowthPage />
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText('高并发与系统设计')).toBeInTheDocument();
    expect(screen.getByText('职业能力成长图谱')).toBeInTheDocument();
    expect(screen.getByText('精通 / Senior')).toBeInTheDocument();
    expect(screen.getByText('评分: 92分')).toBeInTheDocument();
    expect(screen.getByText('需进一步深化海量数据冷热归档实践。')).toBeInTheDocument();

    // Toggle sources
    const viewSourcesBtn = screen.getByRole('button', { name: /查看 1 条实战证据链/ });
    fireEvent.click(viewSourcesBtn);
    expect(await screen.findByText('rec-101')).toBeInTheDocument();
  });
});
