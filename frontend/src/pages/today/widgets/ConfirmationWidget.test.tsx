import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmationWidget, ConfirmationItem } from './ConfirmationWidget';

const MOCK_ITEMS: ConfirmationItem[] = [
  {
    id: 'test-1',
    category: 'external_action',
    title: '腾讯面试时间确认',
    description: 'HR 提议下周二 10:30 进行技术一面',
    contextReason: '日历无冲突，是否确认？',
    suggestedAction: '确认回信',
  },
  {
    id: 'test-2',
    category: 'fact',
    title: '字节跳动二面通过',
    description: '收到邮件通知进入 HR 面',
    contextReason: '是否更新进度？',
    suggestedAction: '更新状态',
  },
];

describe('ConfirmationWidget', () => {
  it('renders top card expanded with full info and collapsed card in backlog', () => {
    render(<ConfirmationWidget initialItems={MOCK_ITEMS} />);

    // Top card full details
    expect(screen.getByText('腾讯面试时间确认')).toBeInTheDocument();
    expect(screen.getByText('HR 提议下周二 10:30 进行技术一面')).toBeInTheDocument();
    expect(screen.getByText('确认回信')).toBeInTheDocument();

    // Backlog card title
    expect(screen.getByText('字节跳动二面通过')).toBeInTheDocument();
  });

  it('switches expanded card when clicking a collapsed card', () => {
    render(<ConfirmationWidget initialItems={MOCK_ITEMS} />);

    const collapsedCard = screen.getByText('字节跳动二面通过');
    fireEvent.click(collapsedCard);

    // Now second card is expanded
    expect(screen.getByText('收到邮件通知进入 HR 面')).toBeInTheDocument();
    expect(screen.getByText('更新状态')).toBeInTheDocument();
  });

  it('dismisses top card on confirm and promotes next card to top', async () => {
    const handleResolve = vi.fn();
    render(<ConfirmationWidget initialItems={MOCK_ITEMS} onResolve={handleResolve} />);

    const confirmBtn = screen.getByText('确认回信');
    fireEvent.click(confirmBtn);

    await waitFor(() => {
      expect(handleResolve).toHaveBeenCalledWith(
        expect.objectContaining({ id: 'test-1' }),
        'approve',
        undefined,
      );
    });

    // Second card automatically expands
    await waitFor(() => {
      expect(screen.getByText('收到邮件通知进入 HR 面')).toBeInTheDocument();
      expect(screen.getByText('更新状态')).toBeInTheDocument();
    });
  });

  it('displays empty state when all cards are resolved', async () => {
    render(<ConfirmationWidget initialItems={[MOCK_ITEMS[0]]} />);

    fireEvent.click(screen.getByText('确认回信'));

    await waitFor(() => {
      expect(screen.getByText('🎉 全部处理完毕')).toBeInTheDocument();
      expect(screen.getByText('当前无待确认或阻断事项')).toBeInTheDocument();
    });
  });
});
