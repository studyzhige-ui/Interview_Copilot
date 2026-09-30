import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import { deleteChatSession, getChatSessionDeletionImpact, listChatSessions } from '@/api/chat';
import type { ChatSessionListItem, ConversationDeletionImpact } from '@/types/api';
import { GeneralChatPage } from './GeneralChatPage';
vi.mock('@/api/chat', () => ({ createChatSession: vi.fn(), deleteChatSession: vi.fn(), getChatSessionDeletionImpact: vi.fn(), listChatSessions: vi.fn(), renameChatSession: vi.fn() }));
vi.mock('./CopilotStatusSummary', () => ({ CopilotStatusSummary: () => null }));
vi.mock('@/pages/review/chat/ChatPanel', () => ({ ChatPanel: ({ sessionId }: { sessionId: string }) => <div>当前会话:{sessionId}</div> }));
const sessions: ChatSessionListItem[] = ['one', 'two'].map((id) => ({ session_id: id, title: id, type: 'general', state_summary: '', execution_mode: 'standard', execution_mode_version: 0, turn_count: 1, updated_at: '2026-09-30' }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listChatSessions).mockResolvedValue(sessions);
  vi.mocked(deleteChatSession).mockResolvedValue(undefined);
  vi.mocked(getChatSessionDeletionImpact).mockResolvedValue({ disclosures: [] } as unknown as ConversationDeletionImpact);
});
function show(embedded = false) {
  const router = createMemoryRouter([{ path: '/general-chat', element: <GeneralChatPage embedded={embedded} /> }], { initialEntries: ['/general-chat?session=one&object_kind=artifact&object_id=art-1'] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RouterProvider router={router} /></QueryClientProvider>);
  return router;
}
async function deleteFirst() {
  await screen.findByText('当前会话:one');
  fireEvent.click(screen.getAllByTitle('删除')[0]);
  const confirm = await screen.findByText('删除', { selector: 'button', exact: true });
  await waitFor(() => expect(confirm).not.toBeDisabled());
  fireEvent.click(confirm);
}
it('removes only the deleted URL selection and opens a remaining session', async () => {
  const router = show();
  await deleteFirst();
  expect(await screen.findByText('当前会话:two')).toBeInTheDocument();
  expect(router.state.location.search).not.toContain('session=one');
  expect(router.state.location.search).toContain('object_id=art-1');
});
it('preserves a newer selection made while deletion is in flight', async () => {
  let resolve!: () => void;
  vi.mocked(deleteChatSession).mockReturnValue(new Promise<void>((done) => { resolve = done; }));
  const router = show();
  await deleteFirst();
  await act(() => router.navigate('/general-chat?session=two'));
  await act(async () => resolve());
  expect(await screen.findByText('当前会话:two')).toBeInTheDocument();
  expect(router.state.location.search).toBe('?session=two');
});
it('clears the last conversation to the welcome state', async () => {
  vi.mocked(listChatSessions).mockResolvedValue([sessions[0]]);
  show();
  await deleteFirst();
  expect(await screen.findByText('今天，想先完成什么？')).toBeInTheDocument();
  expect(screen.queryByText('当前会话:one')).not.toBeInTheDocument();
});
it('does not mutate the host URL when deleting in embedded mode', async () => {
  const router = show(true);
  await deleteFirst();
  expect(await screen.findByText('当前会话:two')).toBeInTheDocument();
  expect(router.state.location.search).toContain('session=one');
});
