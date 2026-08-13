import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AttachmentSource, PendingSubmissionItem } from '@/types/api';

const {
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  promoteAttachmentToArtifact,
  removeDebriefSource,
  removeConversationAttachmentFromScope,
  retryAttachmentSource,
} = vi.hoisted(() => ({
  listAttachmentSources: vi.fn(),
  listDebriefSources: vi.fn(),
  promoteAttachmentToDebrief: vi.fn(),
  promoteAttachmentToArtifact: vi.fn(),
  removeDebriefSource: vi.fn(),
  removeConversationAttachmentFromScope: vi.fn(),
  retryAttachmentSource: vi.fn(),
}));
const { getFileAssetDeletionImpact, permanentlyDeleteFileAsset } = vi.hoisted(() => ({
  getFileAssetDeletionImpact: vi.fn(),
  permanentlyDeleteFileAsset: vi.fn(),
}));

vi.mock('@/api/chat', () => ({
  listAttachmentSources,
  listDebriefSources,
  promoteAttachmentToDebrief,
  promoteAttachmentToArtifact,
  removeDebriefSource,
  removeConversationAttachmentFromScope,
  retryAttachmentSource,
}));
vi.mock('@/api/fileAssets', () => ({
  getFileAssetDeletionImpact,
  permanentlyDeleteFileAsset,
}));

import { AttachmentSources } from './AttachmentSources';

const diagnostics = {
  parse_quality: {
    parser_id: 'docling_local', quality_score: 0.9, ocr_used: false, warnings: [],
  },
  coverage: {
    chunk_count: 1, parsed_char_count: 120, page_count: 1, page_start: 1, page_end: 1,
    full_text_projection_available: true, visual_layout_reviewed: false,
  },
};

const conversationSource: AttachmentSource = {
  ...diagnostics,
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
  ...diagnostics,
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
  ...diagnostics,
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
    promoteAttachmentToArtifact.mockResolvedValue({
      source_id: conversationSource.source_id,
      file_asset_id: conversationSource.file_asset_id,
      file_asset_version: conversationSource.file_asset_version,
      resume_parse_dispatched: true,
      artifact: {
        id: 'artifact-resume', kind: 'resume', archived_at: null,
        current_version: {
          id: 'version-resume', artifact_id: 'artifact-resume', version_no: 1,
          title: conversationSource.title, content_text: null, content_format: 'source_file',
          file_asset_id: conversationSource.file_asset_id,
          file_asset_version: conversationSource.file_asset_version,
          origin_kind: 'explicit_save', source_message_id: null, source_turn_id: 'turn-1',
          source_owner_type: 'conversation_attachment_ref',
          source_owner_id: conversationSource.source_id, created_at: '2026-08-13T00:00:00Z',
        },
      },
    });
    retryAttachmentSource.mockResolvedValue({ source: pendingSource, dispatched: true });
    removeDebriefSource.mockResolvedValue(undefined);
    removeConversationAttachmentFromScope.mockResolvedValue({
      source_id: 'failed-conversation-ref', status: 'removed', resumed_turn: true,
    });
    getFileAssetDeletionImpact.mockResolvedValue({
      file_asset_id: conversationSource.file_asset_id,
      filename: conversationSource.title,
      purpose: 'knowledge_document',
      size_bytes: 1_024,
      reference_impacts: [{
        reference_type: 'conversation_attachment',
        active_count: 1,
        tombstone_count: 0,
        effect: '撤销未来读取并保留 tombstone',
      }],
      known_external_transmission_count: 2,
      confirmation_token: 'a'.repeat(64),
      disclosures: ['原始字节和解析投影将被删除'],
    });
    permanentlyDeleteFileAsset.mockResolvedValue(undefined);
  });

  it('soft-removes ready or failed Conversation refs and displays resumed_turn', async () => {
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
    expect(screen.getByRole('button', { name: '从本对话移除 interview-notes.pdf' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: '移除失败项并继续 unreadable-resume.pdf' }));
    await waitFor(() => {
      expect(removeConversationAttachmentFromScope).toHaveBeenCalledWith(
        'session-1', 'failed-conversation-ref',
      );
    });
    expect(await screen.findByRole('status')).toHaveTextContent('服务端已恢复当前 Turn');
  });

  it('shows references and known external transmissions before strong permanent delete', async () => {
    render(
      <AttachmentSources
        sessionId="session-1"
        pendingSubmissions={[]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(await screen.findByRole('button', {
      name: '永久删除原始文件 interview-notes.pdf',
    }));
    expect(await screen.findByText(/已完成外传：/)).toHaveTextContent('2 次');
    expect(screen.getByText(/conversation_attachment：有效 1/)).toBeInTheDocument();
    const confirm = screen.getByRole('button', { name: '永久删除' });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole('textbox', { name: /输入完整文件名/ }), {
      target: { value: 'interview-notes.pdf' },
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(permanentlyDeleteFileAsset).toHaveBeenCalledWith(
      expect.objectContaining({ file_asset_id: 'asset-conversation' }),
      'interview-notes.pdf',
    ));
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

  it('requires an explicit modal command before promoting the exact file to Artifact', async () => {
    render(
      <AttachmentSources
        sessionId="session-1"
        pendingSubmissions={[]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const open = await screen.findByRole('button', {
      name: '保存为正式材料 interview-notes.pdf',
    });
    expect(promoteAttachmentToArtifact).not.toHaveBeenCalled();
    fireEvent.click(open);
    expect(screen.getByText(/新增正式 Artifact scope/)).toHaveTextContent('冻结当前文件版本');
    fireEvent.change(screen.getByRole('combobox', { name: '材料类型' }), {
      target: { value: 'resume' },
    });
    expect(screen.getByText(/候选必须由你确认/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '确认保存' }));

    await waitFor(() => expect(promoteAttachmentToArtifact).toHaveBeenCalledWith(
      'session-1',
      'conversation-ref',
      expect.objectContaining({
        operationKey: expect.any(String),
        artifactKind: 'resume',
        title: 'interview-notes.pdf',
      }),
    ));
    expect(await screen.findByText(/不会自动改写个人详情/)).toBeInTheDocument();
  });

  it('surfaces parser warnings and truthful text-versus-layout coverage', async () => {
    listAttachmentSources.mockResolvedValue([{
      ...conversationSource,
      parse_quality: {
        ...conversationSource.parse_quality,
        ocr_used: true,
        warnings: ['扫描件文本置信度较低'],
      },
    }]);
    render(
      <AttachmentSources
        sessionId="session-1"
        pendingSubmissions={[]}
        refreshKey="1"
        onRemovePendingSource={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(await screen.findByText('解析提示：扫描件文本置信度较低')).toBeInTheDocument();
    expect(screen.getByText(/使用 OCR/)).toHaveTextContent('未证明已检查视觉版式');
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
