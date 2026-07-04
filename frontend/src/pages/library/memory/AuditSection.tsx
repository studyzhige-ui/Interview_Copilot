/** 审计 — memory_audit_log paginated list + before/after detail. */
import { useState } from 'react';
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  History, RefreshCw, ChevronLeft, ChevronRight, ChevronDown, ExternalLink,
} from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { getMemoryAuditEntry, listMemoryAudit } from '@/api/memory';
import type {
  MemoryAuditEntry, MemoryChangeType, MemoryDocType,
} from '@/types/api';
import { useToastOnError } from '@/hooks/useToastOnError';
import { LoadingBlock } from './shared';

const AUDIT_PAGE_SIZE = 20;

const DOC_TYPE_LABEL: Record<MemoryDocType, string> = {
  user_profile: '个人资料',
  knowledge: '知识',
  strategy: '策略',
  habit: '习惯',
};

const CHANGE_TYPE_LABEL: Record<MemoryChangeType, string> = {
  patch_realtime: '实时提取',
  patch_dreaming: '夜间整理',
  user_edit: '手动编辑',
  user_delete: '手动删除',
  migration: '迁移',
};

const CHANGE_TYPE_TONE: Record<MemoryChangeType, 'success' | 'warn' | 'danger' | 'neutral'> = {
  patch_realtime: 'success',
  patch_dreaming: 'success',
  user_edit: 'warn',
  user_delete: 'danger',
  migration: 'neutral',
};

export function AuditSection() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [docFilter, setDocFilter] = useState<MemoryDocType | 'all'>('all');
  const [changeFilter, setChangeFilter] = useState<MemoryChangeType | 'all'>('all');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // React Query keys on (filters, page): switching either aborts the stale
  // fetch, and keepPreviousData avoids a flash of empty list between pages.
  const { data, isPending, error } = useQuery({
    queryKey: ['memory', 'audit', { docFilter, changeFilter, page }],
    queryFn: ({ signal }) => listMemoryAudit(
      {
        doc_type: docFilter === 'all' ? undefined : docFilter,
        change_type: changeFilter === 'all' ? undefined : changeFilter,
        limit: AUDIT_PAGE_SIZE,
        offset: (page - 1) * AUDIT_PAGE_SIZE,
      },
      { signal },
    ),
    placeholderData: keepPreviousData,
  });
  useToastOnError(error, '审计日志加载失败');

  const entries = data?.entries ?? [];
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['memory', 'audit'] });

  return (
    <div>
      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap mb-3">
        <FilterGroup<MemoryDocType | 'all'>
          label="文档"
          value={docFilter}
          options={[
            { v: 'all', label: '全部' },
            { v: 'user_profile', label: '个人资料' },
            { v: 'knowledge', label: '知识' },
            { v: 'strategy', label: '策略' },
            { v: 'habit', label: '习惯' },
          ]}
          onChange={(v) => { setDocFilter(v); setPage(1); }}
        />
        <FilterGroup<MemoryChangeType | 'all'>
          label="变更"
          value={changeFilter}
          options={[
            { v: 'all', label: '全部' },
            { v: 'patch_realtime', label: '实时提取' },
            { v: 'patch_dreaming', label: '夜间整理' },
            { v: 'user_edit', label: '手动编辑' },
            { v: 'user_delete', label: '手动删除' },
            { v: 'migration', label: '迁移' },
          ]}
          onChange={(v) => { setChangeFilter(v); setPage(1); }}
        />
        <button
          onClick={refresh}
          className="ml-auto inline-flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-700 px-2 py-1"
        >
          <RefreshCw size={11} /> 刷新
        </button>
      </div>

      {isPending && <LoadingBlock />}
      {!isPending && entries.length === 0 && (
        <EmptyState
          icon={<History size={28} />}
          title="没有审计记录"
          description="切换筛选条件或来一次新对话试试。"
        />
      )}
      {!isPending && entries.length > 0 && (
        <div className="border border-stone-200 rounded-lg overflow-hidden">
          {entries.map((e) => (
            <AuditRow
              key={e.id}
              entry={e}
              expanded={expandedId === e.id}
              onToggle={() => setExpandedId((id) => (id === e.id ? null : e.id))}
            />
          ))}
        </div>
      )}

      {totalPages > 1 && (
        <div className="mt-3 flex items-center justify-between text-xs text-stone-500">
          <span>共 {total} 条</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
            >
              <ChevronLeft size={14} />
            </button>
            <span className="px-2">{page} / {totalPages}</span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function FilterGroup<T extends string>({
  label, value, options, onChange,
}: {
  label: string;
  value: T;
  options: ReadonlyArray<{ v: T; label: string }>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] text-stone-400 uppercase tracking-wider">{label}</span>
      <div className="flex items-center gap-1">
        {options.map((o) => (
          <button
            key={o.v}
            onClick={() => onChange(o.v)}
            className={[
              'px-2 py-0.5 rounded-full text-[11px]',
              value === o.v
                ? 'bg-primary-50 text-primary-700 border border-primary-100'
                : 'text-stone-500 hover:bg-stone-100',
            ].join(' ')}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function AuditRow({
  entry, expanded, onToggle,
}: {
  entry: MemoryAuditEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="border-b border-stone-100 last:border-b-0">
      <button
        onClick={onToggle}
        className="w-full px-3 py-2.5 text-left hover:bg-stone-50/60 flex items-start gap-3"
      >
        {expanded ? <ChevronDown size={14} className="mt-0.5 text-stone-400" />
                  : <ChevronRight size={14} className="mt-0.5 text-stone-400" />}
        <div className="text-xs font-mono text-stone-500 shrink-0 w-32">
          {entry.created_at
            ? new Date(entry.created_at).toLocaleString(undefined, {
                year: 'numeric', month: '2-digit', day: '2-digit',
                hour: '2-digit', minute: '2-digit',
              })
            : '—'}
        </div>
        <Pill tone={CHANGE_TYPE_TONE[entry.change_type]}>
          {CHANGE_TYPE_LABEL[entry.change_type]}
        </Pill>
        <div className="text-xs text-stone-500 shrink-0">
          {DOC_TYPE_LABEL[entry.doc_type]}
          {entry.topic && <span className="text-stone-400"> · {entry.topic}</span>}
        </div>
        <div className="text-sm text-stone-700 flex-1 truncate">{entry.summary}</div>
      </button>
      {expanded && <AuditDetail entryId={entry.id} entry={entry} />}
    </div>
  );
}

function AuditDetail({ entryId, entry }: { entryId: string; entry: MemoryAuditEntry }) {
  const { data: detail, isPending, error } = useQuery({
    queryKey: ['memory', 'audit-entry', entryId],
    queryFn: ({ signal }) => getMemoryAuditEntry(entryId, { signal }),
  });
  useToastOnError(error, '审计详情加载失败');
  return (
    <div className="bg-stone-50 px-3 py-3 border-t border-stone-100">
      {isPending && <Spinner size={14} />}
      {detail && (
        <div className="space-y-2">
          {(entry.source_session_id || entry.source_record_id) && (
            <div className="flex items-center gap-3 text-[11px] font-mono text-stone-500">
              {entry.source_session_id && (
                <span className="inline-flex items-center gap-1">
                  <ExternalLink size={10} /> session={entry.source_session_id}
                </span>
              )}
              {entry.source_record_id && (
                <span className="inline-flex items-center gap-1">
                  <ExternalLink size={10} /> record={entry.source_record_id}
                </span>
              )}
            </div>
          )}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <DiffPane label="变更前 (before)" body={detail.before_body} />
            <DiffPane label="变更后 (after)" body={detail.after_body} highlight />
          </div>
        </div>
      )}
    </div>
  );
}

function DiffPane({
  label, body, highlight,
}: { label: string; body: string; highlight?: boolean }) {
  return (
    <div className="border border-stone-200 rounded bg-white">
      <div className="px-2.5 py-1 border-b border-stone-100 text-[10px] uppercase tracking-wider text-stone-500">
        {label}
      </div>
      <pre className={[
        'p-2 text-[11px] leading-snug font-mono whitespace-pre-wrap break-words overflow-x-auto max-h-[280px] overflow-y-auto',
        highlight ? 'text-stone-800' : 'text-stone-500',
      ].join(' ')}>
        {body || '（空）'}
      </pre>
    </div>
  );
}
