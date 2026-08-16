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

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, ...props }: any) => <div {...props}>{children}</div>,
  },
  AnimatePresence: ({ children }: any) => <>{children}</>,
}));

describe('TodayPage', () => {
  beforeEach(() => {
    vi.mocked(listJobOpportunities).mockResolvedValue([]);
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
  });
});
