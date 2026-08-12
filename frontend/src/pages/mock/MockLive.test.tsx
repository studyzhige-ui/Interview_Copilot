import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getMockLiveState,
  prepareMockAnswerAudio,
  submitMockAnswer,
} from '@/api/mock';
import { MockLive } from './MockLive';

const navigate = vi.hoisted(() => vi.fn());
const recorder = vi.hoisted(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  blob: null as Blob | null,
}));

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useBlocker: () => ({ state: 'unblocked' }),
    useNavigate: () => navigate,
  };
});

vi.mock('@/api/mock', () => ({
  abandonMockInterview: vi.fn(),
  finishMockInterview: vi.fn(),
  getMockLiveState: vi.fn(),
  prepareMockAnswerAudio: vi.fn(),
  submitMockAnswer: vi.fn(),
}));

vi.mock('@/hooks/useMediaRecorder', async () => {
  const React = await import('react');
  return {
    useMediaRecorder: () => {
      const [state, setState] = React.useState<'idle' | 'recording'>('idle');
      return {
        state,
        start: async () => {
          recorder.start();
          setState('recording');
        },
        stop: async () => {
          recorder.stop();
          setState('idle');
          return recorder.blob;
        },
        durationMs: 0,
        errorMessage: null,
      };
    },
  };
});

vi.mock('@/hooks/useTts', () => ({
  useTts: () => ({
    state: { phase: 'idle' },
    speak: vi.fn(),
    stop: vi.fn(),
  }),
}));

const opening = { id: 10, speaker: 'interviewer' as const, text: '请先做自我介绍' };

describe('MockLive', () => {
  beforeEach(() => {
    vi.mocked(getMockLiveState).mockReset();
    vi.mocked(prepareMockAnswerAudio).mockReset();
    vi.mocked(submitMockAnswer).mockReset();
    recorder.start.mockReset();
    recorder.stop.mockReset();
    recorder.blob = new Blob(['recording'], { type: 'audio/webm' });
    navigate.mockReset();
    Element.prototype.scrollTo = vi.fn();
  });

  it('loads the complete server conversation when resuming', async () => {
    vi.mocked(getMockLiveState).mockResolvedValue({
      messages: [
        opening,
        { id: 11, speaker: 'candidate', text: '我有三年后端经验' },
        { id: 12, speaker: 'interviewer', text: '请讲讲最近的项目' },
      ],
    });

    render(
      <MockLive
        recordId="record-1"
        ttsVoice="zh-CN-YunxiNeural"
        onFinished={vi.fn()}
        onAbandoned={vi.fn()}
      />,
    );

    expect(await screen.findByText('请先做自我介绍')).toBeInTheDocument();
    expect(screen.getByText('我有三年后端经验')).toBeInTheDocument();
    expect(screen.getByText('请讲讲最近的项目')).toBeInTheDocument();
  });

  it('reconciles a lost response and automatically resumes the interviewer turn', async () => {
    vi.mocked(submitMockAnswer)
      .mockRejectedValueOnce(new Error('network lost'))
      .mockResolvedValueOnce({
        message: { id: 12, speaker: 'interviewer', text: '请继续讲项目难点' },
        end_suggested: false,
      });
    vi.mocked(getMockLiveState).mockResolvedValue({
      messages: [
        opening,
        { id: 11, speaker: 'candidate', text: '我负责接口性能优化' },
      ],
    });

    render(
      <MockLive
        recordId="record-1"
        initialMessages={[opening]}
        ttsVoice="zh-CN-YunxiNeural"
        onFinished={vi.fn()}
        onAbandoned={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '我负责接口性能优化' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交' }));

    expect(await screen.findByText('请继续讲项目难点')).toBeInTheDocument();
    await waitFor(() => expect(submitMockAnswer).toHaveBeenCalledTimes(2));
    expect(submitMockAnswer).toHaveBeenLastCalledWith('record-1', {
      answer_text: '我负责接口性能优化',
      question_message_id: 10,
    });
  });

  it('keeps the transcript editable and submits the saved recording only after confirmation', async () => {
    vi.mocked(prepareMockAnswerAudio).mockResolvedValue({
      text: '这是尚未确认的语音转写',
      audio_file_asset_id: 'fa_voice_1',
    });
    vi.mocked(submitMockAnswer).mockResolvedValue({
      message: { id: 11, speaker: 'interviewer', text: '请继续说明具体做法' },
      end_suggested: false,
    });

    render(
      <MockLive
        recordId="record-1"
        initialMessages={[opening]}
        ttsVoice="zh-CN-YunxiNeural"
        onFinished={vi.fn()}
        onAbandoned={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '开始录音' }));
    fireEvent.click(await screen.findByRole('button', { name: '结束录音' }));

    const editor = await screen.findByRole('textbox');
    expect(editor).toHaveValue('这是尚未确认的语音转写');
    expect(submitMockAnswer).not.toHaveBeenCalled();

    fireEvent.change(editor, { target: { value: '这是我修订后的回答' } });
    fireEvent.click(screen.getByRole('button', { name: '提交' }));

    await waitFor(() => {
      expect(submitMockAnswer).toHaveBeenCalledWith('record-1', {
        answer_text: '这是我修订后的回答',
        answer_audio_file_asset_id: 'fa_voice_1',
        question_message_id: 10,
      });
    });
  });

  it('retries transcription with the same recording instead of asking the user to record again', async () => {
    vi.mocked(prepareMockAnswerAudio)
      .mockRejectedValueOnce(new Error('转写服务暂不可用'))
      .mockResolvedValueOnce({
        text: '重试后恢复的转写',
        audio_file_asset_id: 'fa_voice_retry',
      });

    render(
      <MockLive
        recordId="record-1"
        initialMessages={[opening]}
        ttsVoice="zh-CN-YunxiNeural"
        onFinished={vi.fn()}
        onAbandoned={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '开始录音' }));
    fireEvent.click(await screen.findByRole('button', { name: '结束录音' }));
    fireEvent.click(await screen.findByRole('button', { name: '重试转写' }));

    expect(await screen.findByRole('textbox')).toHaveValue('重试后恢复的转写');
    expect(recorder.stop).toHaveBeenCalledTimes(1);
    expect(prepareMockAnswerAudio).toHaveBeenCalledTimes(2);
    expect(prepareMockAnswerAudio).toHaveBeenNthCalledWith(1, 'record-1', recorder.blob);
    expect(prepareMockAnswerAudio).toHaveBeenNthCalledWith(2, 'record-1', recorder.blob);
  });

  it('lets the candidate confirm a model-suggested ending', async () => {
    vi.mocked(submitMockAnswer).mockResolvedValue({
      message: {
        id: 11,
        speaker: 'interviewer',
        text: '感谢参与，准备好后可以结束本次面试并生成复盘。',
      },
      end_suggested: true,
    });

    render(
      <MockLive
        recordId="record-1"
        initialMessages={[opening]}
        ttsVoice="zh-CN-YunxiNeural"
        onFinished={vi.fn()}
        onAbandoned={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: '没有其他问题了，谢谢。' },
    });
    fireEvent.click(screen.getByRole('button', { name: '提交' }));

    const finishSuggestion = await screen.findByRole('button', {
      name: '结束并生成复盘',
    });
    fireEvent.click(finishSuggestion);
    expect(screen.getByText('结束本次面试')).toBeInTheDocument();
  });
});
