import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listResumes } from '@/api/resumes';
import { MockSetup } from './MockSetup';

vi.mock('@/api/resumes', () => ({
  createResumeFromFile: vi.fn(),
  listResumes: vi.fn(),
  waitForResumeUsable: vi.fn(),
}));

vi.mock('@/api/mock', () => ({ parseJdForMock: vi.fn() }));

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
  });

  it('uses 20 as the default advisory target and allows selecting 30', async () => {
    const onReady = vi.fn();
    render(<MockSetup onReady={onReady} starting={false} />);

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
    fireEvent.click(screen.getByRole('button', { name: /开始模拟面试/ }));
    expect(onReady).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_question_count: 30 }),
    );
  });
});
