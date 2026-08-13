import { FormEvent, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Braces,
  Clock3,
  MessageSquareText,
  Search,
  Wrench,
} from 'lucide-react';
import { readInteractionHistoryRecord, searchInteractionHistory } from '@/api/history';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import type {
  HistorySearchInput,
  HistorySearchKind,
  HistoryRecordDetail,
  HistorySearchResult,
  HistorySearchRole,
} from '@/types/history';

const KIND_OPTIONS: Array<{ value: HistorySearchKind; label: string }> = [
  { value: 'message', label: '消息' },
  { value: 'tool_call', label: 'Tool 调用' },
];

const ROLE_OPTIONS: Array<{ value: HistorySearchRole; label: string }> = [
  { value: 'user', label: '用户' },
  { value: 'assistant', label: '助手' },
  { value: 'tool', label: 'Tool' },
  { value: 'system', label: '系统' },
];

const ROLE_LABELS: Record<string, string> = {
  user: '用户',
  assistant: '助手',
  tool: 'Tool',
  system: '系统',
};

function toggleValue<T extends string>(values: T[], value: T): T[] {
  return values.includes(value)
    ? values.filter((item) => item !== value)
    : [...values, value];
}

function formatOccurredAt(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function resultTone(result: HistorySearchResult): 'primary' | 'neutral' | 'success' | 'warn' | 'danger' {
  if (result.kind === 'message') return 'primary';
  if (result.tool_status === 'completed' || result.tool_status === 'success') return 'success';
  if (result.tool_status === 'failed' || result.tool_status === 'error') return 'danger';
  if (result.tool_status === 'running' || result.tool_status === 'pending') return 'warn';
  return 'neutral';
}

function ResultCard({ result }: { result: HistorySearchResult }) {
  const [detail, setDetail] = useState<HistoryRecordDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState(false);
  const Icon = result.kind === 'message' ? MessageSquareText : Wrench;
  const recordLabel = result.kind === 'message'
    ? `消息 · ${ROLE_LABELS[result.role ?? ''] ?? result.role ?? '角色未知'}`
    : `Tool · ${result.tool_name ?? '名称未知'}`;

  return (
    <article className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Icon size={16} className="shrink-0 text-primary-700" aria-hidden />
            <h2 className="truncate text-sm font-semibold text-stone-800">{recordLabel}</h2>
            <Pill tone={resultTone(result)}>
              {result.kind === 'message' ? 'message' : result.tool_status ?? '状态未知'}
            </Pill>
          </div>
          <p className="mt-1 text-xs text-stone-500">
            Conversation：{result.conversation_title || '未命名会话'}
            <span className="ml-2">({result.conversation_type})</span>
          </p>
        </div>
        <time
          className="inline-flex shrink-0 items-center gap-1 text-xs text-stone-500"
          dateTime={result.occurred_at}
          title={result.occurred_at}
        >
          <Clock3 size={13} aria-hidden />
          {formatOccurredAt(result.occurred_at)}
        </time>
      </div>

      <p className="mt-4 whitespace-pre-wrap break-words rounded-lg bg-stone-50 px-3 py-2.5 text-sm leading-relaxed text-stone-700">
        {result.excerpt}
      </p>

      <div className="mt-3">
        <Btn
          kind="ghost"
          loading={loadingDetail}
          onClick={async () => {
            if (detail) {
              setDetail(null);
              return;
            }
            setLoadingDetail(true);
            setDetailError(false);
            try {
              setDetail(await readInteractionHistoryRecord(result.identity));
            } catch {
              setDetailError(true);
            } finally {
              setLoadingDetail(false);
            }
          }}
        >
          {detail ? '收起完整记录' : '精确回读完整记录'}
        </Btn>
        {detailError && <p className="mt-2 text-xs text-danger-600">完整记录读取失败。</p>}
        {detail && (
          <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-stone-200 bg-stone-950 p-3 text-xs text-stone-100">
            {detail.kind === 'message'
              ? detail.content
              : JSON.stringify(
                  {
                    arguments: detail.arguments,
                    result: detail.result,
                    error: detail.error,
                  },
                  null,
                  2,
                )}
          </pre>
        )}
      </div>

      <dl className="mt-3 grid gap-x-5 gap-y-2 text-xs text-stone-500 sm:grid-cols-2">
        <div className="min-w-0">
          <dt className="font-medium text-stone-600">Exact identity</dt>
          <dd className="mt-0.5 break-all font-mono" data-testid="history-exact-identity">{result.identity}</dd>
        </div>
        <div className="min-w-0">
          <dt className="font-medium text-stone-600">Conversation ID</dt>
          <dd className="mt-0.5 break-all font-mono">{result.conversation_id}</dd>
        </div>
        {result.turn_id && (
          <div className="min-w-0">
            <dt className="font-medium text-stone-600">Turn ID</dt>
            <dd className="mt-0.5 break-all font-mono">{result.turn_id}</dd>
          </div>
        )}
        {result.kind === 'message' && result.message_id !== null && (
          <div>
            <dt className="font-medium text-stone-600">Message</dt>
            <dd className="mt-0.5 font-mono">#{result.message_id}{result.seq !== null ? ` · seq ${result.seq}` : ''}</dd>
          </div>
        )}
        {result.kind === 'tool_call' && result.tool_call_id && (
          <div className="min-w-0">
            <dt className="font-medium text-stone-600">ToolCall ID</dt>
            <dd className="mt-0.5 break-all font-mono">{result.tool_call_id}</dd>
          </div>
        )}
      </dl>
    </article>
  );
}

export function HistorySearchPage() {
  const [query, setQuery] = useState('');
  const [conversationId, setConversationId] = useState('');
  const [kinds, setKinds] = useState<HistorySearchKind[]>(['message', 'tool_call']);
  const [roles, setRoles] = useState<HistorySearchRole[]>([]);
  const [submitted, setSubmitted] = useState<HistorySearchInput | null>(null);
  const [validationMessage, setValidationMessage] = useState('');

  const historyQuery = useQuery({
    queryKey: ['interaction-history', 'search', submitted],
    queryFn: () => searchInteractionHistory(submitted!),
    enabled: submitted !== null,
    retry: false,
  });

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = query.trim().replace(/\s+/g, ' ');
    if (normalized.length < 2) {
      setValidationMessage('请输入至少 2 个字符。');
      return;
    }
    if (kinds.length === 0) {
      setValidationMessage('请至少选择一种记录类型。');
      return;
    }
    setValidationMessage('');
    setSubmitted({
      query: normalized,
      conversationId: conversationId.trim() || undefined,
      kinds,
      roles,
      limit: 20,
    });
  };

  const results = historyQuery.data?.results ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
      <header>
        <div className="flex items-center gap-2">
          <Search size={21} className="text-primary-700" aria-hidden />
          <h1 className="text-xl font-semibold text-stone-800">历史记录</h1>
        </div>
        <p className="mt-1 text-sm text-stone-500">精确检索已保存的消息与 Tool 调用，不生成新的业务事实。</p>
      </header>

      <div className="flex gap-2 rounded-xl border border-warning-200 bg-warning-50 p-3 text-sm text-warning-700" role="note">
        <AlertTriangle size={17} className="mt-0.5 shrink-0" aria-hidden />
        <p>历史记录只说明当时发生过什么，不代表当前事实或当前状态；需要判断现状时，请重新读取对应真实资产与记录。</p>
      </div>

      <form className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs" onSubmit={submit}>
        <label className="block text-sm font-medium text-stone-700" htmlFor="history-query">搜索内容</label>
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-400" aria-hidden />
            <input
              id="history-query"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="输入消息或 Tool 调用中的原文"
              className="h-10 w-full rounded-md border border-stone-300 bg-white pl-9 pr-3 text-sm text-stone-800 outline-none focus:border-primary-400 focus:ring-2 focus:ring-primary-100"
            />
          </div>
          <Btn type="submit" icon={<Search size={15} />} loading={historyQuery.isFetching}>搜索历史</Btn>
        </div>
        {validationMessage && <p className="mt-2 text-xs text-danger-500" role="alert">{validationMessage}</p>}

        <details className="mt-4 border-t border-stone-100 pt-3">
          <summary className="cursor-pointer text-sm font-medium text-stone-600">范围与类型筛选</summary>
          <div className="mt-3 grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto_auto]">
            <label className="text-xs font-medium text-stone-600" htmlFor="history-conversation-id">
              Conversation ID（可选）
              <input
                id="history-conversation-id"
                value={conversationId}
                onChange={(event) => setConversationId(event.target.value)}
                placeholder="只搜索指定会话"
                className="mt-1 h-9 w-full rounded-md border border-stone-300 px-3 font-mono text-xs font-normal text-stone-800 outline-none focus:border-primary-400"
              />
            </label>
            <fieldset>
              <legend className="text-xs font-medium text-stone-600">记录类型</legend>
              <div className="mt-2 flex flex-wrap gap-3">
                {KIND_OPTIONS.map((option) => (
                  <label key={option.value} className="flex items-center gap-1.5 text-xs text-stone-700">
                    <input
                      type="checkbox"
                      checked={kinds.includes(option.value)}
                      onChange={() => setKinds((current) => toggleValue(current, option.value))}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>
            <fieldset>
              <legend className="text-xs font-medium text-stone-600">消息角色（可选）</legend>
              <div className="mt-2 flex flex-wrap gap-3">
                {ROLE_OPTIONS.map((option) => (
                  <label key={option.value} className="flex items-center gap-1.5 text-xs text-stone-700">
                    <input
                      type="checkbox"
                      checked={roles.includes(option.value)}
                      onChange={() => setRoles((current) => toggleValue(current, option.value))}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </details>
      </form>

      {historyQuery.isPending && submitted && (
        <div className="flex justify-center py-12 text-stone-400"><Spinner size={20} /></div>
      )}
      {historyQuery.isError && (
        <div className="rounded-xl border border-danger-200 bg-danger-50 p-4 text-sm text-danger-700" role="alert">
          历史记录搜索失败，请稍后重试。
        </div>
      )}
      {historyQuery.isSuccess && (
        <section aria-live="polite">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm text-stone-600">
              “{historyQuery.data.query}” 找到 {historyQuery.data.count} 条记录
            </p>
            <div className="inline-flex items-center gap-1 text-xs text-stone-400">
              <Braces size={13} aria-hidden />精确记录投影
            </div>
          </div>
          {results.length === 0 ? (
            <div className="rounded-xl border border-stone-200 bg-white p-6">
              <EmptyState title="没有匹配的历史记录" description="可以减少筛选条件或换一个关键词。" />
            </div>
          ) : (
            <div className="space-y-3">
              {results.map((result) => <ResultCard key={result.identity} result={result} />)}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
