import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ChatToolbar } from './ChatToolbar';

describe('ChatToolbar pending projection', () => {
  it('renders server-retained submissions with controls, including failed errors', () => {
    render(
      <ChatToolbar
        activeSessionId="session-1"
        externalMode
        mode="AGENT"
        setMode={vi.fn()}
        allowModeSwitch={false}
        executionMode="standard"
        setExecutionMode={vi.fn()}
        executionModePending={false}
        input=""
        setInput={vi.fn()}
        streaming={false}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        attachments={[]}
        setAttachments={vi.fn()}
        pendingSubmissions={[
          {
            submission_id: 'submission-1', version: 1, status: 'queued',
            queue_position: 2, message: '分析这份岗位说明', mode: 'agent',
            execution_mode: 'standard',
            question_indexes: [], attachments: [], object_references: [], source_client_id: 'client-1', error: null,
          },
          {
            submission_id: 'submission-2', version: 1, status: 'failed',
            queue_position: 3, message: '然后准备追问', mode: 'agent',
            execution_mode: 'auto',
            question_indexes: [], attachments: [], object_references: [], source_client_id: 'client-1',
            error: '附件解析失败',
          },
        ]}
        activeTurnId="turn-1"
        onUpdatePendingSubmission={vi.fn().mockResolvedValue(undefined)}
        onWithdrawPendingSubmission={vi.fn().mockResolvedValue(undefined)}
        onRetryPendingSubmission={vi.fn().mockResolvedValue(undefined)}
        onInterruptForSubmission={vi.fn().mockResolvedValue(undefined)}
        questionIndexes={[]}
        onRemoveQuestion={vi.fn()}
        onClearQuestions={vi.fn()}
        productObjectReferences={[{
          kind: 'job_opportunity',
          object_id: 'jo_1',
          label: 'Example · Backend',
        }]}
        onRemoveProductObjectReference={vi.fn()}
      />,
    );

    expect(screen.getByLabelText('待处理消息')).toHaveTextContent('待处理 2 条');
    expect(screen.getByText('分析这份岗位说明')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getByText('附件解析失败')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /编辑排队消息 分析这份岗位说明/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /撤回排队消息 分析这份岗位说明/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /重试排队消息 然后准备追问/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /停止当前并发送此条 分析这份岗位说明/ })).toBeInTheDocument();
    expect(screen.getByLabelText('本轮产品对象引用')).toHaveTextContent('Example · Backend');
  });
});
