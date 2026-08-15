import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { Plus, MoreHorizontal, Pencil, Trash2, Search, Tag, Loader2, Sparkles } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { deleteInterviewRecord, updateInterviewRecord } from '@/api/interview';
import { extractErr } from '@/api/client';
import type { InterviewRecordListItem } from '@/types/api';
import type { AnalysisProgress } from './AnalysisRunner';

interface Props {
  records: InterviewRecordListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onChanged: () => void;
  onDraftMutate: (id: string, patch: Partial<InterviewRecordListItem>) => void;
  onDraftDelete: (id: string) => void;
  analyzingStates?: Map<string, AnalysisProgress>;
  width?: number;
  className?: string;
}

function progressLabel(p: AnalysisProgress | undefined): string {
  if (!p) return '';
  if (p.phase === 'connecting') return '连接中';
  if (p.phase === 'error')      return '失败';
  if (p.phase === 'done')       return '完成';
  const s = (p.status || '').toLowerCase();
  if (s.includes('transcrib'))    return '转写中';
  if (s.includes('diariz'))       return '分离说话人';
  if (s.includes('extract'))      return '提取问答';
  if (s.includes('summar'))       return '摘要中';
  if (s.includes('analyz') || s.includes('analysis')) return '深度分析';
  if (s.includes('report') || s.includes('writ'))     return '生成报告';
  return '处理中';
}

function isDraftId(id: string): boolean {
  return id.startsWith('draft-');
}

function formatDate(iso: string): string {
  if (!iso) return '';
  const stamp = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  const d = new Date(stamp);
  if (isNaN(d.getTime())) return iso.slice(0, 10);
  return `${d.getMonth() + 1}/${String(d.getDate()).padStart(2, '0')}`;
}

const TAG_OPTIONS = ['Backend', 'Frontend', 'Algorithm', 'System', 'HR'] as const;

const TAG_TONE: Record<string, 'sand' | 'primary' | 'success' | 'warn' | 'neutral'> = {
  Backend: 'sand',
  Frontend: 'primary',
  Algorithm: 'warn',
  System: 'neutral',
  HR: 'success',
};

function tagOrSource(r: InterviewRecordListItem): { label: string; tone: 'sand' | 'primary' | 'success' | 'warn' | 'neutral' } {
  if (r.tag) return { label: r.tag, tone: TAG_TONE[r.tag] ?? 'primary' };
  if (r.source === 'mock') return { label: '模拟', tone: 'primary' };
  if (r.source === 'upload') return { label: '录音', tone: 'sand' };
  if (r.source === 'draft') return { label: '草稿', tone: 'neutral' };
  return { label: r.source || '其他', tone: 'neutral' };
}

export function SessionList({
  records,
  activeId,
  onSelect,
  onNew,
  onChanged,
  onDraftMutate,
  onDraftDelete,
  analyzingStates,
  width = 280,
  className = '',
}: Props) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [tagMenu, setTagMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<InterviewRecordListItem | null>(null);
  const [query, setQuery] = useState('');
  const popupRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Node;
      if (openMenu && !popupRef.current?.contains(t)) {
        setOpenMenu(null);
        setTagMenu(null);
      }
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setEditing(null);
        setOpenMenu(null);
        setTagMenu(null);
      }
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [openMenu]);

  const filtered = query.trim()
    ? records.filter((r) => r.title.toLowerCase().includes(query.toLowerCase()))
    : records;

  const startRename = (r: InterviewRecordListItem) => {
    setEditing({ id: r.id, title: r.title });
    setOpenMenu(null);
  };

  const commitRename = async () => {
    if (!editing) return;
    const title = editing.title.trim();
    if (!title) { setEditing(null); return; }
    if (isDraftId(editing.id)) {
      onDraftMutate(editing.id, { title });
      setEditing(null);
      return;
    }
    try {
      await updateInterviewRecord(editing.id, { title });
      setEditing(null);
      onChanged();
    } catch (e) {
      toast.error(extractErr(e, '重命名失败'));
    }
  };

  const applyTag = async (r: InterviewRecordListItem, tag: string | null) => {
    setTagMenu(null);
    setOpenMenu(null);
    if (isDraftId(r.id)) {
      onDraftMutate(r.id, { tag });
      return;
    }
    try {
      await updateInterviewRecord(r.id, { tag: tag ?? '' });
      onChanged();
    } catch (e) {
      toast.error(extractErr(e, '更新标签失败'));
    }
  };

  const confirmDelete = async () => {
    if (!deleting) return;
    if (isDraftId(deleting.id)) {
      onDraftDelete(deleting.id);
      setDeleting(null);
      return;
    }
    try {
      await deleteInterviewRecord(deleting.id);
      toast.success('已删除');
      setDeleting(null);
      onChanged();
    } catch (e) {
      toast.error(extractErr(e, '删除失败'));
    }
  };

  return (
    <aside
      style={{ '--record-list-width': `${width}px` } as CSSProperties}
      className={`w-full lg:w-[var(--record-list-width)] shrink-0 bg-white/90 backdrop-blur-md border-r border-slate-200/80 flex flex-col h-full ${className}`}
    >
      {/* Header with Search and New Review Action */}
      <div className="p-3.5 border-b border-slate-100 flex flex-col gap-2.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-sm font-bold text-slate-800 tracking-tight">
            <span>复盘档案</span>
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
              {records.length}
            </span>
          </div>

          <button
            type="button"
            onClick={onNew}
            title="新建面试复盘"
            className="flex items-center gap-1 px-3 py-1.5 rounded-full bg-blue-50 hover:bg-blue-100 text-blue-600 text-xs font-semibold transition-all active:scale-95 shadow-xs cursor-pointer"
          >
            <Plus size={14} />
            <span>新建</span>
          </button>
        </div>

        {/* Search Bar */}
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索面试记录..."
            className="w-full pl-9 pr-3 py-1.5 bg-slate-50 hover:bg-slate-100/80 focus:bg-white border border-slate-200/80 rounded-full text-xs text-slate-800 placeholder-slate-400 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100 transition-all"
          />
        </div>
      </div>

      {/* Record List Items */}
      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {filtered.length === 0 && (
          <div className="flex flex-col items-center justify-center text-center py-12 px-4">
            <div className="w-10 h-10 rounded-2xl bg-blue-50 text-blue-600 flex items-center justify-center mb-2">
              <Sparkles size={18} />
            </div>
            <div className="text-xs font-medium text-slate-700">暂无匹配面试记录</div>
            <p className="text-[11px] text-slate-400 mt-1">
              点击上方「新建」即可上传录音并智能解析
            </p>
          </div>
        )}

        {filtered.map((r) => {
          const act = r.id === activeId;
          const pill = tagOrSource(r);
          const isEditing = editing?.id === r.id;
          const progress = analyzingStates?.get(r.id);
          const isAnalyzing = r.status === 'analyzing' || (progress && progress.phase === 'progress');

          return (
            <div
              key={r.id}
              onClick={() => onSelect(r.id)}
              className={[
                'group relative p-3 rounded-2xl cursor-pointer transition-all duration-150 border select-none',
                act
                  ? 'bg-blue-50/80 border-blue-200/90 shadow-xs ring-1 ring-blue-100'
                  : 'bg-transparent border-transparent hover:bg-slate-50 hover:border-slate-200/60',
              ].join(' ')}
            >
              <div className="flex items-start justify-between gap-2">
                {isEditing ? (
                  <input
                    autoFocus
                    value={editing.title}
                    onChange={(e) => setEditing({ id: r.id, title: e.target.value })}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={() => { void commitRename(); }}
                    onKeyDown={(e) => {
                      e.stopPropagation();
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        void commitRename();
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        setEditing(null);
                      }
                    }}
                    className="flex-1 px-2 py-1 bg-white border border-blue-400 rounded-lg text-xs font-semibold text-slate-800 outline-none"
                  />
                ) : (
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-xs font-semibold truncate ${act ? 'text-blue-900' : 'text-slate-800'}`}>
                        {r.title || '未命名面试'}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 mt-1.5">
                      <Pill tone={pill.tone}>{pill.label}</Pill>
                      <span className="text-[11px] text-slate-400">{formatDate(r.created_at)}</span>
                      {isAnalyzing && (
                        <span className="flex items-center gap-1 text-[11px] text-blue-600 font-medium ml-auto">
                          <Loader2 size={11} className="animate-spin text-blue-500" />
                          <span>{progressLabel(progress) || '分析中'}</span>
                        </span>
                      )}
                    </div>
                  </div>
                )}

                {/* More Actions Menu Button */}
                {!isEditing && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setOpenMenu(openMenu === r.id ? null : r.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-opacity"
                  >
                    <MoreHorizontal size={14} />
                  </button>
                )}
              </div>

              {/* Action Dropdown Popup */}
              {openMenu === r.id && (
                <div
                  ref={popupRef}
                  onClick={(e) => e.stopPropagation()}
                  className="absolute right-2 top-10 w-36 bg-white rounded-xl shadow-xl border border-slate-200 p-1 z-40 animate-in fade-in zoom-in-95 duration-100"
                >
                  <button
                    type="button"
                    onClick={() => startRename(r)}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50 rounded-lg"
                  >
                    <Pencil size={13} className="text-slate-400" />
                    <span>重命名</span>
                  </button>

                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setTagMenu(tagMenu === r.id ? null : r.id)}
                      className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs text-slate-700 hover:bg-slate-50 rounded-lg"
                    >
                      <div className="flex items-center gap-2">
                        <Tag size={13} className="text-slate-400" />
                        <span>标签分类</span>
                      </div>
                    </button>

                    {tagMenu === r.id && (
                      <div className="mt-1 p-1 bg-slate-50 rounded-lg border border-slate-200 flex flex-col gap-0.5">
                        {TAG_OPTIONS.map((opt) => (
                          <button
                            key={opt}
                            type="button"
                            onClick={() => applyTag(r, opt)}
                            className="w-full text-left px-2 py-1 text-[11px] text-slate-700 hover:bg-white hover:text-blue-600 rounded"
                          >
                            {opt}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>

                  <div className="my-1 border-t border-slate-100" />

                  <button
                    type="button"
                    onClick={() => {
                      setOpenMenu(null);
                      setDeleting(r);
                    }}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-xs text-red-600 hover:bg-red-50 rounded-lg"
                  >
                    <Trash2 size={13} className="text-red-400" />
                    <span>删除</span>
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {deleting && (
        <ConfirmDialog
          open={!!deleting}
          title="删除复盘记录"
          description={`确定要删除「${deleting.title}」吗？此操作无法撤销。`}
          confirmText="删除"
          danger
          onConfirm={confirmDelete}
          onCancel={() => setDeleting(null)}
        />
      )}
    </aside>
  );
}
