import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post, patch, del, authedFetch } = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  authedFetch: vi.fn(),
}));

vi.mock('./client', () => ({
  apiClient: { defaults: { baseURL: '/api/v1' }, get, post, patch, delete: del },
  authedFetch,
}));

import {
  getChatSessionExecutionMode,
  getAgentTask,
  interruptChatTurnForSubmission,
  listAttachmentSources,
  listDebriefSources,
  listPendingSubmissions,
  promoteAttachmentToDebrief,
  promoteAttachmentToArtifact,
  removeDebriefSource,
  removeConversationAttachmentFromScope,
  retryAttachmentSource,
  retryPendingSubmission,
  streamChatTurn,
  updateChatSessionExecutionMode,
  updatePendingSubmission,
  withdrawPendingSubmission,
} from './chat';

function event(type: string, data: Record<string, unknown> = {}) {
  return JSON.stringify({ type, data, step: 1, elapsed_ms: 2 });
}

describe('streamChatTurn', () => {
  beforeEach(() => {
    get.mockReset();
    post.mockReset();
    patch.mockReset();
    del.mockReset();
    authedFetch.mockReset();
  });

  afterEach(() => vi.useRealTimers());

  it('creates a turn and reconnects from the last Redis stream cursor', async () => {
    post.mockResolvedValue({
      data: {
        submission_id: 'submission-1', version: 1, status: 'admitted',
        turn_id: 'turn-1', queue_position: null,
      },
    });
    authedFetch
      .mockResolvedValueOnce(new Response(`id: 1-0\ndata: ${event('text_delta', { delta: 'A' })}\n\n`))
      .mockResolvedValueOnce(new Response(`id: 2-0\ndata: ${event('done')}\n\n`));
    const deltas: string[] = [];

    await streamChatTurn('session-1', 'hello', {
      onTextDelta: (delta) => deltas.push(delta),
    }, {
      questionIndexes: [5, 2],
      objectReferences: [
        { kind: 'job_opportunity', object_id: 'jo_1', label: 'display only' },
      ],
      submission: {
        submissionId: 'submission-1', version: 1, sourceClientId: 'client-1',
      },
    });

    expect(post).toHaveBeenCalledWith(
      '/chat/session-1/turns',
      {
        submission_id: 'submission-1',
        version: 1,
        message: 'hello',
        mode: 'chat',
        execution_mode: 'standard',
        question_indexes: [5, 2],
        attachments: [],
        object_references: [{ kind: 'job_opportunity', object_id: 'jo_1' }],
        source_client_id: 'client-1',
      },
      { signal: undefined },
    );
    expect(authedFetch.mock.calls[1][0]).toContain('after=1-0');
    expect(deltas).toEqual(['A']);
  });

  it('can resume an existing turn without submitting a new message', async () => {
    authedFetch.mockResolvedValue(new Response(`data: ${event('done')}\n\n`));
    await streamChatTurn('session-1', '', {}, { turnId: 'existing' });
    expect(post).not.toHaveBeenCalled();
  });

  it('does not open SSE when admission queues the submission', async () => {
    const queued = {
      submission_id: 'submission-2', version: 1, status: 'queued' as const,
      turn_id: null, queue_position: 3,
    };
    post.mockResolvedValue({ data: queued });

    await expect(streamChatTurn('session-1', 'later', {}, {
      submission: {
        submissionId: 'submission-2', version: 1, sourceClientId: 'client-1',
      },
    })).resolves.toEqual(queued);

    expect(authedFetch).not.toHaveBeenCalled();
  });

  it('returns a durable failed admission without opening SSE', async () => {
    const failed = {
      submission_id: 'submission-failed', version: 1, status: 'failed' as const,
      turn_id: null, queue_position: 2, error: '引用对象已不可读',
    };
    post.mockResolvedValue({ data: failed });

    await expect(streamChatTurn('session-1', 'analyze it', {}, {
      objectReferences: [{ kind: 'artifact', object_id: 'art_deleted' }],
      submission: {
        submissionId: 'submission-failed', version: 1, sourceClientId: 'client-1',
      },
    })).resolves.toEqual(failed);
    expect(authedFetch).not.toHaveBeenCalled();
  });

  it('reuses the same submission identity when admission transport retries', async () => {
    vi.useFakeTimers();
    post
      .mockRejectedValueOnce(new Error('network unavailable'))
      .mockResolvedValueOnce({
        data: {
          submission_id: 'submission-stable', version: 1, status: 'queued',
          turn_id: null, queue_position: 1,
        },
      });

    const request = streamChatTurn('session-1', 'retry me', {}, {
      submission: {
        submissionId: 'submission-stable', version: 1, sourceClientId: 'client-1',
      },
    });
    await vi.advanceTimersByTimeAsync(200);
    await request;

    expect(post).toHaveBeenCalledTimes(2);
    expect(post.mock.calls[1][1]).toEqual(post.mock.calls[0][1]);
  });

  it('loads the server-owned pending submission projection', async () => {
    const projection = [{
      submission_id: 'submission-3', version: 1, status: 'queued',
      queue_position: 2, message: 'queued message', mode: 'agent',
      question_indexes: [], attachments: [], source_client_id: 'client-1', error: null,
    }];
    get.mockResolvedValue({ data: projection });

    await expect(listPendingSubmissions('session / 1')).resolves.toEqual(projection);
    expect(get).toHaveBeenCalledWith(
      '/chat/session%20%2F%201/submissions',
      { signal: undefined },
    );
  });

  it('uses versioned pending-submission endpoints without local queue mutations', async () => {
    const update = {
      expected_version: 4,
      message: 'revised',
      mode: 'agent' as const,
      execution_mode: 'auto' as const,
      question_indexes: [1],
      attachments: [{ draft_id: 'draft-1' }],
      object_references: [],
    };
    patch.mockResolvedValue({ data: { ...update, submission_id: 'submission-1' } });
    post.mockResolvedValue({ data: { status: 'queued' } });
    del.mockResolvedValue({});

    await updatePendingSubmission('session 1', 'submission/1', update);
    await retryPendingSubmission('session 1', 'submission/1', 5);
    await withdrawPendingSubmission('session 1', 'submission/1', 6);
    await interruptChatTurnForSubmission('session 1', 'turn/1', 'submission/1', 7);

    expect(patch).toHaveBeenCalledWith(
      '/chat/session%201/submissions/submission%2F1', update,
    );
    expect(post).toHaveBeenNthCalledWith(
      1,
      '/chat/session%201/submissions/submission%2F1/retry',
      { expected_version: 5 },
    );
    expect(del).toHaveBeenCalledWith(
      '/chat/session%201/submissions/submission%2F1',
      { params: { expected_version: 6 } },
    );
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/chat/session%201/turns/turn%2F1/interrupt',
      { submission_id: 'submission/1', expected_version: 7 },
    );
  });

  it('reads and CAS-updates the server-owned Conversation execution mode', async () => {
    const current = {
      session_id: 'session / 1', execution_mode: 'standard' as const, version: 4,
    };
    const saved = { ...current, execution_mode: 'auto' as const, version: 5 };
    get.mockResolvedValue({ data: current });
    patch.mockResolvedValue({ data: saved });

    await expect(getChatSessionExecutionMode('session / 1')).resolves.toEqual(current);
    await expect(updateChatSessionExecutionMode('session / 1', 'auto', 4))
      .resolves.toEqual(saved);

    expect(get).toHaveBeenCalledWith(
      '/chat/sessions/session%20%2F%201/execution-mode',
      { signal: undefined },
    );
    expect(patch).toHaveBeenCalledWith(
      '/chat/sessions/session%20%2F%201/execution-mode',
      { execution_mode: 'auto', expected_version: 4 },
    );
  });

  it('uses typed attachment source endpoints and keeps Debrief promotion explicit', async () => {
    const source = {
      source_id: 'ref/1', source_kind: 'conversation_attachment',
      scope_kind: 'conversation', scope_id: 'session 1', status: 'ready',
      file_asset_id: 'asset-1', file_asset_version: 'v1', document_id: 'doc-1',
      title: 'resume.pdf', error_message: null, can_retry: false,
    };
    get.mockResolvedValue({ data: [source] });
    post
      .mockResolvedValueOnce({ data: { source, dispatched: true } })
      .mockResolvedValueOnce({ data: { source } });
    del.mockResolvedValue({});

    await listAttachmentSources('session 1', { submissionId: 'submission/1' });
    await retryAttachmentSource('session 1', 'ref/1');
    await promoteAttachmentToDebrief('session 1', 'ref/1');
    await listDebriefSources('record/1');
    await removeDebriefSource('record/1', 'source/1');

    expect(get).toHaveBeenNthCalledWith(
      1,
      '/chat/session%201/attachment-sources',
      { params: { submission_id: 'submission/1' }, signal: undefined },
    );
    expect(post).toHaveBeenNthCalledWith(
      1,
      '/chat/session%201/attachment-sources/ref%2F1/retry',
    );
    expect(post).toHaveBeenNthCalledWith(
      2,
      '/chat/session%201/attachment-sources/ref%2F1/debrief',
    );
    expect(get).toHaveBeenNthCalledWith(
      2,
      '/interviews/record%2F1/debrief-sources',
      { signal: undefined },
    );
    expect(del).toHaveBeenCalledWith(
      '/interviews/record%2F1/debrief-sources/source%2F1',
    );
  });

  it('removes a failed claimed source through its Conversation owner', async () => {
    del.mockResolvedValue({
      data: { source_id: 'ref/1', status: 'removed', resumed_turn: true },
    });
    await expect(removeConversationAttachmentFromScope('session 1', 'ref/1')).resolves.toEqual({
      source_id: 'ref/1', status: 'removed', resumed_turn: true,
    });
    expect(del).toHaveBeenCalledWith(
      '/chat/session%201/attachment-sources/ref%2F1',
    );
  });

  it('sends an explicit typed command to promote one exact attachment to Artifact', async () => {
    const promoted = {
      source_id: 'ref/1',
      file_asset_id: 'fa-1',
      file_asset_version: 'sha256:abc',
      artifact: { id: 'artifact-1' },
      resume_parse_dispatched: false,
    };
    post.mockResolvedValue({ data: promoted });

    await expect(promoteAttachmentToArtifact('session 1', 'ref/1', {
      operationKey: 'operation-1', artifactKind: 'portfolio', title: '项目材料',
    })).resolves.toEqual(promoted);
    expect(post).toHaveBeenCalledWith(
      '/chat/session%201/attachment-sources/ref%2F1/artifact',
      {
        operation_key: 'operation-1',
        artifact_kind: 'portfolio',
        title: '项目材料',
      },
    );
  });

  it('reads the optional AgentTask projection by the original session and Turn identity', async () => {
    get.mockResolvedValue({ data: null });
    await expect(getAgentTask('session 1', 'turn/1')).resolves.toBeNull();
    expect(get).toHaveBeenCalledWith(
      '/chat/session%201/turns/turn%2F1/agent-task',
      { signal: undefined },
    );
  });
});
