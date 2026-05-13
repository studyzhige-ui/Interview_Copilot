import { useEffect, useRef, useState } from 'react';
import { Plus, MoreHorizontal, Pencil, Trash2, Search, Check, X, Tag } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { toast } from '@/store/uiStore';
import { deleteInterviewRecord, updateInterviewRecord } from '@/api/interview';
import { extractErr } from '@/api/client';
import type { InterviewRecordListItem } from '@/types/api';

interface Props {
  records: InterviewRecordListItem[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onChanged: () => void;
  onDraftMutate: (id: string, patch: Partial<InterviewRecordListItem>) => void;
  onDraftDelete: (id: string) => void;
  width?: number;
}

function isDraftId(id: string): boolean {
  return id.startsWith('draft-');
}

function formatDate(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return `${d.getMonth() + 1}/${String(d.getDate()).padStart(2, '0')}`;
  } catch {
    return iso.slice(0, 10);
  }
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
  if (r.tag) return { label: r.tag, tone: TAG_TONE[r.tag] ?? 'sand' };
  if (r.source === 'mock') return { label: '模拟', tone: 'primary' };
  if (r.source === 'upload') return { label: '上传', tone: 'sand' };
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
  width = 260,
}: Props) {
  const [openMenu, setOpenMenu] = useState<string | null>(null);
  const [tagMenu, setTagMenu] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<InterviewRecordListItem | null>(null);
  const [query, setQuery] = useState('');
  const listRef = useRef<HTMLDivElement | null>(null);

  // Close any open inline-rename / ⋯ menu / tag submenu when the user clicks
  // outside the session list. Pressing Escape also closes everything.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (listRef.current && !listRef.current.contains(e.target as Node)) {
        setEditing(null);
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
  }, []);

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
      ref={listRef}
      style={{ width }}
      className="shrink-0 bg-white border-r border-stone-200 flex flex-col"
    >
      <div className="p-4 border-b border-stone-200">
        <div className="flex items-center justify-between mb-2.5">
          <div className="text-sm font-semibold text-stone-800">我的面试</div>
          <button
            onClick={onNew}
            title="新建面试"
            className="w-7 h-7 rounded-lg bg-primary-50 text-primary-600 hover:bg-primary-100 flex items-center justify-center"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索面试记录"
            className="w-full pl-8 pr-2.5 py-1.5 bg-stone-50 border border-stone-200 rounded-md text-xs text-stone-700 outline-none focus:border-primary-300"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {filtered.length === 0 && (
          <div className="text-xs text-stone-400 text-center mt-8 px-4 leading-relaxed">
            还没有面试记录。点 + 新建一条，上传音视频和简历后自动开始分析。
          </div>
        )}
        {filtered.map((r) => {
          const act = r.id === activeId;
          const pill = tagOrSource(r);
          const isEditing = editing?.id === r.id;
          return (
            <div
              key={r.id}
              onClick={() => onSelect(r.id)}
              className={[
                'relative px-3 py-2.5 rounded-lg cursor-pointer mb-1 border',
                act
                  ? 'bg-primary-50 border-primary-100'
                  : 'border-transparent hover:bg-stone-50',
              ].join(' ')}
            >
              <div className="flex items-center gap-2">
                {isEditing ? (
                  <>
                    <input
                      autoFocus
                      value={editing.title}
                      onChange={(e) => setEditing({ id: r.id, title: e.target.value })}
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => {
                        e.stopPropagation();
                        if (e.key === 'Enter') commitRename();
                        if (e.key === 'Escape') setEditing(null);
                      }}
                      className="flex-1 min-w-0 text-[13px] px-1 py-0.5 border border-primary-300 rounded outline-none"
                    />
                    <button
                      onClick={(e) => { e.stopPropagation(); commitRename(); }}
                      className="p-0.5 text-success-500 hover:bg-success-50 rounded"
                    >
                      <Check size={14} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); setEditing(null); }}
                      className="p-0.5 text-stone-400 hover:bg-stone-100 rounded"
                    >
                      <X size={14} />
                    </button>
                  </>
                ) : (
                  <>
                    <div
                      className={[
                        'flex-1 min-w-0 text-sm truncate',
                        act ? 'text-primary-700 font-semibold' : 'text-stone-800 font-medium',
                      ].join(' ')}
                    >
                      {r.title || '未命名面试'}
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setOpenMenu(openMenu === r.id ? null : r.id);
                      }}
                      className="w-6 h-6 rounded text-stone-400 hover:bg-stone-100 hover:text-stone-600 flex items-center justify-center"
                    >
                      <MoreHorizontal size={14} />
                    </button>
                  </>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1.5">
                <span className="text-xs text-stone-500">
                  {formatDate(r.created_at)}
                </span>
                <Pill tone={pill.tone}>{pill.label}</Pill>
              </div>
              {openMenu === r.id && !isEditing && (
                <div
                  onClick={(e) => e.stopPropagation()}
                  className="absolute right-2 top-9 w-44 p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-20"
                >
                  <button
                    onClick={() => startRename(r)}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[13px] text-stone-700 hover:bg-stone-50 rounded"
                  >
                    <Pencil size={13} />
                    <span>重命名</span>
                  </button>
                  <button
                    onClick={() => setTagMenu(tagMenu === r.id ? null : r.id)}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[13px] text-stone-700 hover:bg-stone-50 rounded"
                  >
                    <Tag size={13} />
                    <span>标签</span>
                    {r.tag && <Pill tone={TAG_TONE[r.tag] ?? 'sand'}>{r.tag}</Pill>}
                  </button>
                  {tagMenu === r.id && (
                    <div className="ml-3 mt-1 mb-1 pl-2 border-l border-stone-100">
                      {TAG_OPTIONS.map((t) => (
                        <button
                          key={t}
                          onClick={() => applyTag(r, t)}
                          className={[
                            'w-full flex items-center gap-2 px-2 py-1 text-[12px] rounded',
                            r.tag === t ? 'text-primary-700 bg-primary-50' : 'text-stone-700 hover:bg-stone-50',
                          ].join(' ')}
                        >
                          {r.tag === t && <Check size={11} />}
                          <span className={r.tag === t ? 'ml-0' : 'ml-[15px]'}>{t}</span>
                        </button>
                      ))}
                      {r.tag && (
                        <button
                          onClick={() => applyTag(r, null)}
                          className="w-full flex items-center gap-2 px-2 py-1 text-[12px] text-stone-500 hover:bg-stone-50 rounded"
                        >
                          <span className="ml-[15px]">清空标签</span>
                        </button>
                      )}
                    </div>
                  )}
                  <button
                    onClick={() => { setDeleting(r); setOpenMenu(null); }}
                    className="w-full flex items-center gap-2 px-2.5 py-1.5 text-[13px] text-danger-500 hover:bg-danger-50 rounded"
                  >
                    <Trash2 size={13} />
                    <span>删除</span>
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <ConfirmDialog
        open={!!deleting}
        danger
        title={deleting && isDraftId(deleting.id) ? '取消新建' : '删除面试记录'}
        description={
          deleting && isDraftId(deleting.id)
            ? `确认放弃「${deleting.title}」的本地草稿？`
            : `确认删除「${deleting?.title}」？相关的复盘对话会保留但失去关联。`
        }
        confirmText={deleting && isDraftId(deleting.id) ? '丢弃' : '删除'}
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </aside>
  );
}
