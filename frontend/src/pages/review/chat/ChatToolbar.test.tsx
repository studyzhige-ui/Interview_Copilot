import type { ComponentProps } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { ChatToolbar } from './ChatToolbar';

const readyModel = {
  id: 'openai:gpt-ready',
  provider: 'openai',
  display_name: 'GPT Ready',
  model: 'gpt-ready',
  api_base: 'https://api.openai.com/v1',
  api_key_env: 'OPENAI_API_KEY',
  supports_function_calling: true,
  description: '',
  context_window: 128_000,
  max_output_tokens: 8_192,
  ready: true,
  selected_for: ['primary'],
};

const unavailableModel = {
  ...readyModel,
  id: 'anthropic:not-ready',
  provider: 'anthropic',
  display_name: '尚未配置模型',
  model: 'not-ready',
  api_key_env: 'ANTHROPIC_API_KEY',
  ready: false,
  selected_for: [],
};

function toolbarProps(
  overrides: Partial<ComponentProps<typeof ChatToolbar>> = {},
): ComponentProps<typeof ChatToolbar> {
  return {
    activeSessionId: 'session-1',
    externalMode: true,
    mode: 'AGENT',
    setMode: vi.fn(),
    allowModeSwitch: false,
    executionMode: 'standard',
    setExecutionMode: vi.fn().mockResolvedValue(undefined),
    executionModePending: false,
    modelProfiles: [readyModel, unavailableModel],
    activeModelProfileId: readyModel.id,
    activeModelName: readyModel.display_name,
    pickModel: vi.fn().mockResolvedValue(true),
    input: '',
    setInput: vi.fn(),
    streaming: false,
    onSend: vi.fn(),
    onCancel: vi.fn(),
    attachments: [],
    setAttachments: vi.fn(),
    pendingSubmissions: [],
    activeTurnId: 'turn-1',
    onUpdatePendingSubmission: vi.fn().mockResolvedValue(undefined),
    onWithdrawPendingSubmission: vi.fn().mockResolvedValue(undefined),
    onRetryPendingSubmission: vi.fn().mockResolvedValue(undefined),
    onInterruptForSubmission: vi.fn().mockResolvedValue(undefined),
    questionIndexes: [],
    onRemoveQuestion: vi.fn(),
    onClearQuestions: vi.fn(),
    productObjectReferences: [],
    onRemoveProductObjectReference: vi.fn(),
    ...overrides,
  };
}

function renderToolbar(overrides: Partial<ComponentProps<typeof ChatToolbar>> = {}) {
  render(
    <MemoryRouter>
      <ChatToolbar {...toolbarProps(overrides)} />
    </MemoryRouter>,
  );
}

describe('ChatToolbar', () => {
  it('renders server-retained submissions with controls, including failed errors', () => {
    renderToolbar({
      pendingSubmissions: [
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
      ],
      productObjectReferences: [{
        kind: 'job_opportunity',
        object_id: 'jo_1',
        label: 'Example · Backend',
      }],
    });

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

  it('uses a Codex-style composer with inline approval, attachment, and ready-model controls', async () => {
    const setExecutionMode = vi.fn().mockResolvedValue(undefined);
    renderToolbar({ setExecutionMode });

    expect(screen.getByLabelText('消息输入')).toHaveAttribute('placeholder', '随心输入 · Shift+Enter 换行');
    expect(screen.getByRole('button', { name: '添加附件' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '发送消息' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: '选择审批模式' }));
    expect(screen.getByText('工具操作如何获得批准？')).toBeInTheDocument();
    fireEvent.click(screen.getByText('仅在当前任务明确范围内减少普通审批；风险、越界与歧义仍会询问。'));
    await waitFor(() => expect(setExecutionMode).toHaveBeenCalledWith('auto'));

    fireEvent.click(screen.getByRole('button', { name: '选择回答模型' }));
    expect(screen.getAllByText('GPT Ready')).toHaveLength(2);
    expect(screen.queryByText('尚未配置模型')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '前往回答模型配置' })).toHaveAttribute('href', '/models');
  });
});
