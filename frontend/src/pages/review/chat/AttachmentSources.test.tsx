import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AttachmentSource, PendingSubmissionItem } from '@/types/api';

const {
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  removeDebriefSource,
  removeFailedConversationAttachment,
  retryAttachmentSource,
} = vi.hoisted(() => ({
  listAttachmentSources: vi.fn(),
  listDebriefSources: vi.fn(),
  promoteAttachmentToDebrief: vi.fn(),
  removeDebriefSource: vi.fn(),
  removeFailedConversationAttachment: vi.fn(),
  retryAttachmentSource: vi.fn(),
}));

vi.mock('@/api/chat', () => ({
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  removeDebriefSource,
  removeFailedConversationAttachment,
  retryAttachmentSource,
}));

import { AttachmentSources } from './AttachmentSources';

const conversationSource: AttachmentSource = {
  source_id: 'conversation-ref',
  source_kind: 'conversation_attachment',
  scope_kind: 'conversation',
  scope_id: 'session-1',
  status: 'ready',
  file_asset_id: 'asset-conversation',
  file_asset_version: 'v1',
  document_id: 'doc-conversation',
  title: 'interview-notes.pdf',
  error_message: null,
  can_retry: false,
};

const pendingSource: AttachmentSource = {
  source_id: 'pending-draft',
  source_kind: 'draft',
  scope_kind: 'pending_submission',
  scope_id: 'submission-1',
  status: 'failed',
  file_asset_id: 'asset-pending',
  file_asset_version: 'v1',
  document_id: 'doc-pending',
  title: 'broken.docx',
  error_message: '无法解析文档',
  can_retry: true,
};

const failedConversationSource: AttachmentSource = {
  ...conversationSource,
  source_id: 'failed-conversation-ref',
  status: 'failed',
  title: 'unreadable-resume.pdf',
  error_message: '文件已损坏',
  can_retry: true,
};

const debriefSource: AttachmentSource = {
  source_id: 'debrief-ref',
  source_kind: 'debrief_project_source',
  scope_kind: 'debrief_project',
  scope_id: 'record-1',
  status: 'failed',
  file_asset_id: 'asset-debrief',
  file_asset_version: 'v1',
  document_id: 'doc-debrief',
  title: 'debrief-notes.pdf',
  error_message: '解析服务超时',
  can_retry: true,
};

const pending: PendingSubmissionItem = {
  submission_id: 'submission-1',
  version: 1,
  status: 'queued',
  queue_position: 1,
  message: '分析附件',
  mode: 'agent',
  execution_mode: 'standard',
  question_indexes: [],
  attachments: [{ draft_id: 'pending-draft' }],
  object_references: [],
  source_client_id: 'client-1',
  error: null,
};

describe('AttachmentSources', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listAttachmentSources.mockImplementation(
      (_sessionId: string, opts?: { submissionId?: string }) => Promise.resolve(
        opts?.submissionId ? [pendingSource] : [conversationSource],
      ),
    );
    listDebriefSources.mockResolvedValue([]);
    promoteAttachmentToDebrief.mockResolvedValue(conversationSource);
    retryAttachmentSource.mockResolvedValue({ source: pendingSource, dispatched: true });
    removeDebriefSource.mockResolvedValue(undefined);
    removeFailedConversationAttachment.mockResolvedValue({
      source_id: 'failed-conversation-ref', status: 'removed', resumed_turn: true,
    });
  });

  it('offers removal only for a failed claimed Conversation source and displays resumed_turn', async () => {
    listAttachmentSources.mockImplementation(
      (_sessionId: string, opts?: { submissionId?: string }) => Promise.resolve(
        opts?.submissionId ? [] : [conversationSource, failedConversationSource],
      ),
    );
    render(
      <AttachmentSources
        sessionId="session-1"
        pendingSubmissions={[]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(await screen.findByText('unreadable-resume.pdf')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '移除失败项并继续 interview-notes.pdf' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '移除失败项并继续 unreadable-resume.pdf' }));
    await waitFor(() => {
      expect(removeFailedConversationAttachment).toHaveBeenCalledWith(
        'session-1', 'failed-conversation-ref',
      );
    });
    expect(await screen.findByRole('status')).toHaveTextContent('服务端已恢复当前 Turn');
  });

  it('shows real scope and status, and never promotes without an explicit click', async () => {
    render(
      <AttachmentSources
        sessionId="session-1"
        interviewId="record-1"
        pendingSubmissions={[pending]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(await screen.findByText('interview-notes.pdf')).toBeInTheDocument();
    expect(screen.getByText('broken.docx')).toBeInTheDocument();
    expect(screen.getByText('无法解析文档')).toBeInTheDocument();
    expect(screen.getByText('本对话 · 已就绪')).toBeInTheDocument();
    expect(screen.getByText('待发送 #1 · 失败')).toBeInTheDocument();
    expect(promoteAttachmentToDebrief).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: '添加到本次复盘资料 interview-notes.pdf' }));
    await waitFor(() => {
      expect(promoteAttachmentToDebrief).toHaveBeenCalledWith('session-1', 'conversation-ref');
    });
  });

  it('routes retry and pending removal through server commands', async () => {
    const removePending = vi.fn().mockResolvedValue(undefined);
    render(
      <AttachmentSources
        sessionId="session-1"
        pendingSubmissions={[pending]}
        refreshKey="1"
        onRemovePendingSource={removePending}
      />,
    );

    await screen.findByText('broken.docx');
    fireEvent.click(screen.getByRole('button', { name: '重试附件 broken.docx' }));
    await waitFor(() => {
      expect(retryAttachmentSource).toHaveBeenCalledWith('session-1', 'pending-draft');
    });

    fireEvent.click(screen.getByRole('button', { name: '移除附件来源 broken.docx' }));
    await waitFor(() => {
      expect(removePending).toHaveBeenCalledWith(pending, 'pending-draft');
    });
  });

  it('retries and removes a Debrief source through its persisted scope', async () => {
    listDebriefSources.mockResolvedValue([debriefSource]);
    render(
      <AttachmentSources
        sessionId="session-1"
        interviewId="record-1"
        pendingSubmissions={[]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(await screen.findByText('debrief-notes.pdf')).toBeInTheDocument();
    expect(screen.getByText('本次复盘 · 失败')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '重试附件 debrief-notes.pdf' }));
    await waitFor(() => {
      expect(retryAttachmentSource).toHaveBeenCalledWith('session-1', 'debrief-ref');
    });

    fireEvent.click(screen.getByRole('button', { name: '移除附件来源 debrief-notes.pdf' }));
    await waitFor(() => {
      expect(removeDebriefSource).toHaveBeenCalledWith('record-1', 'debrief-ref');
    });
  });
});
