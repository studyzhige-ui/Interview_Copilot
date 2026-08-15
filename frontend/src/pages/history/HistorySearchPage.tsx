import { FormEvent, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  Braces,
  Clock,
  MessageSquareText,
  Search,
  Wrench,
  ChevronDown,
  ChevronUp,
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
    <article className="rounded-3xl border border-slate-200/90 bg-white p-5 shadow-xs hover:border-blue-200 transition-all space-y-3.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-7 h-7 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
              <Icon size={15} aria-hidden />
            </div>
            <h2 className="truncate text-sm font-bold text-slate-800">{recordLabel}</h2>
            <Pill tone={resultTone(result)}>
              {result.kind === 'message' ? 'message' : result.tool_status ?? '状态未知'}
            </Pill>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Conversation：{result.conversation_title || '未命名会话'}
            <span className="ml-2 font-mono text-slate-400">({result.conversation_type})</span>
          </p>
        </div>
        <time
          className="inline-flex shrink-0 items-center gap-1.5 text-xs text-slate-400 font-mono"
          dateTime={result.occurred_at}
          title={result.occurred_at}
        >
          <Clock size={13} aria-hidden />
          <span>{formatOccurredAt(result.occurred_at)}</span>
        </time>
      </div>

      <div className="rounded-2xl bg-slate-50/70 p-3.5 text-sm text-slate-700 leading-relaxed whitespace-pre-wrap border border-slate-100 font-sans">
        {result.excerpt || '（无正文预览）'}
      </div>

      <div className="flex justify-end pt-1">
        <button
          type="button"
          disabled={loadingDetail}
          onClick={() => {
            if (detail) {
              setDetail(null);
              return;
            }
            setLoadingDetail(true);
            setDetailError(false);
            readInteractionHistoryRecord(result.identity)
              .then((data) => setDetail(data))
              .catch(() => setDetailError(true))
              .finally(() => setLoadingDetail(false));
          }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold text-blue-600 hover:bg-blue-50 transition-colors cursor-pointer"
        >
          <Braces size={13} />
          <span>{detail ? '收起完整上下文' : '查看完整结构化记录'}</span>
          {detail ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>
      </div>

      {loadingDetail && (
        <div className="flex items-center gap-2 text-xs text-slate-500 py-2">
          <Spinner size={13} />
          <span>正在检索完整记录…</span>
        </div>
      )}

      {detailError && (
        <p className="text-xs text-red-500" role="alert">
          读取详细记录失败，请稍后重试。
        </p>
      )}

      {detail && (
        <div className="rounded-2xl border border-slate-200 bg-slate-900 text-slate-100 p-4 text-xs font-mono overflow-x-auto shadow-inner">
          <pre>{JSON.stringify(detail, null, 2)}</pre>
        </div>
      )}

      <dl className="grid gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500 sm:grid-cols-2 md:grid-cols-4">
        <div className="min-w-0">
          <dt className="font-medium text-slate-400">Exact identity</dt>
          <dd className="mt-0.5 break-all font-mono text-slate-700" data-testid="history-exact-identity">{result.identity}</dd>
        </div>
        <div className="min-w-0">
          <dt className="font-medium text-slate-400">Conversation ID</dt>
          <dd className="mt-0.5 break-all font-mono text-slate-700">{result.conversation_id}</dd>
        </div>
        {result.turn_id && (
          <div className="min-w-0">
            <dt className="font-medium text-slate-400">Turn ID</dt>
            <dd className="mt-0.5 break-all font-mono text-slate-700">{result.turn_id}</dd>
          </div>
        )}
        {result.kind === 'message' && result.message_id !== null && (
          <div>
            <dt className="font-medium text-slate-400">Message</dt>
            <dd className="mt-0.5 font-mono text-slate-700">#{result.message_id}{result.seq !== null ? ` · seq ${result.seq}` : ''}</dd>
          </div>
        )}
        {result.kind === 'tool_call' && result.tool_call_id && (
          <div className="min-w-0">
            <dt className="font-medium text-slate-400">ToolCall ID</dt>
            <dd className="mt-0.5 break-all font-mono text-slate-700">{result.tool_call_id}</dd>
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
    <div className="h-full overflow-y-auto p-4 md:p-8">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-purple-50 text-purple-700 text-xs font-semibold mb-2">
              <Clock size={13} />
              <span>全局历史探索</span>
            </div>
            <h1 className="text-2xl font-bold text-slate-900 tracking-tight">历史记录</h1>
            <p className="mt-1 text-sm text-slate-500">
              精确检索全站已保存的消息、对话与 Tool 真实调用轨迹。
            </p>
          </div>
        </header>

        <div className="flex gap-2 rounded-2xl border border-amber-200 bg-amber-50/80 p-4 text-xs text-amber-900" role="note">
          <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-600" aria-hidden />
          <p>历史记录只说明当时发生过什么，不代表当前事实或当前状态；需要判断现状时，请重新读取对应真实资产与记录。</p>
        </div>

        {/* Search Card */}
        <form className="rounded-3xl border border-slate-200/90 bg-white p-6 shadow-sm space-y-4" onSubmit={submit}>
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-slate-700" htmlFor="history-query">
              搜索内容
            </label>
            <div className="flex flex-col sm:flex-row gap-2.5">
              <div className="relative flex-1">
                <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" aria-hidden />
                <input
                  id="history-query"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="输入消息或 Tool 调用中的原文..."
                  className="h-11 w-full rounded-2xl border border-slate-200/90 bg-slate-50/50 pl-10 pr-4 text-sm text-slate-800 outline-none focus:border-blue-400 focus:bg-white transition-all"
                />
              </div>
              <Btn type="submit" size="md" icon={<Search size={15} />} loading={historyQuery.isFetching} className="px-6 rounded-2xl">
                搜索历史
              </Btn>
            </div>
            {validationMessage && (
              <p className="mt-2 text-xs text-red-500" role="alert">{validationMessage}</p>
            )}
          </div>

          <details className="pt-2 border-t border-slate-100 space-y-3" open>
            <summary className="cursor-pointer text-xs font-bold text-slate-500 uppercase tracking-wider select-none py-1">
              范围与类型筛选
            </summary>

            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-500" htmlFor="history-conversation-id">
                指定会话 ID（可选）
              </label>
              <input
                id="history-conversation-id"
                value={conversationId}
                onChange={(event) => setConversationId(event.target.value)}
                placeholder="例如 conv-123456..."
                className="h-9 w-full rounded-xl border border-slate-200/90 bg-slate-50/50 px-3 text-xs font-mono text-slate-800 outline-none focus:border-blue-400 focus:bg-white transition-all"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 pt-1">
              <div className="space-y-2">
                <div className="text-xs font-semibold text-slate-600">记录类型</div>
                <div className="flex flex-wrap gap-3">
                  {KIND_OPTIONS.map((opt) => (
                    <label key={opt.value} className="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer">
                      <input
                        type="checkbox"
                        aria-label={opt.label}
                        checked={kinds.includes(opt.value)}
                        onChange={() => setKinds((curr) => toggleValue(curr, opt.value))}
                        className="rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                      />
                      <span>{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-semibold text-slate-600">角色过滤</div>
                <div className="flex flex-wrap gap-3">
                  {ROLE_OPTIONS.map((opt) => (
                    <label key={opt.value} className="inline-flex items-center gap-1.5 text-xs text-slate-700 cursor-pointer">
                      <input
                        type="checkbox"
                        aria-label={opt.label}
                        checked={roles.includes(opt.value)}
                        onChange={() => setRoles((curr) => toggleValue(curr, opt.value))}
                        className="rounded border-slate-300 text-purple-600 focus:ring-purple-500"
                      />
                      <span>{opt.label}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </details>
        </form>

        {/* Results Stream */}
        <section className="space-y-4">
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>搜索结果 {submitted ? `(${results.length} 条)` : ''}</span>
          </div>

          {historyQuery.isLoading && (
            <div className="p-12 text-center text-slate-400 flex items-center justify-center gap-2">
              <Spinner size={18} />
              <span>正在全库检索历史记录…</span>
            </div>
          )}

          {submitted && !historyQuery.isLoading && results.length === 0 && (
            <EmptyState
              icon={<Search size={32} />}
              title="未找到匹配的历史记录"
              description="尝试调整关键词或放宽类型与角色过滤条件。"
            />
          )}

          {results.map((result) => (
            <ResultCard key={result.identity} result={result} />
          ))}
        </section>
      </div>
    </div>
  );
}
