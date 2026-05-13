import { useEffect, useRef, useState } from 'react';
import { Upload, Search, Pencil, Trash2, Check, X, FileText, RefreshCw } from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import {
  deleteKnowledgeDocument,
  listKnowledgeCategories,
  listKnowledgeDocuments,
  updateKnowledgeDocument,
  uploadKnowledgeFile,
} from '@/api/knowledge';
import type { KnowledgeCategory, KnowledgeDoc } from '@/types/api';

function statusTone(s: string): { tone: 'success' | 'warn' | 'danger' | 'neutral'; label: string } {
  switch (s) {
    case 'success':    return { tone: 'success', label: '就绪' };
    case 'completed':  return { tone: 'success', label: '就绪' };
    case 'processing': return { tone: 'warn', label: '处理中' };
    case 'pending':    return { tone: 'warn', label: '排队中' };
    case 'failed':     return { tone: 'danger', label: '失败' };
    default:           return { tone: 'neutral', label: s };
  }
}

export function LibraryPage() {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [cats, setCats] = useState<KnowledgeCategory[]>([]);
  const [filter, setFilter] = useState<string>('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeDoc | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const [d, c] = await Promise.all([
        listKnowledgeDocuments(filter ? { category: filter } : {}),
        listKnowledgeCategories(),
      ]);
      setDocs(d);
      setCats(c);
    } catch {
      toast.error('资料库加载失败');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const onUpload = async (f: File) => {
    setUploading(true);
    try {
      await uploadKnowledgeFile(f, { category: filter || undefined });
      toast.success('上传成功，正在后台处理');
      await refresh();
    } catch {
      toast.error('上传失败');
    } finally {
      setUploading(false);
    }
  };

  const onSaveRename = async () => {
    if (!editing) return;
    try {
      await updateKnowledgeDocument(editing.id, { title: editing.title });
      setEditing(null);
      toast.success('已保存');
      await refresh();
    } catch {
      toast.error('保存失败');
    }
  };

  const onConfirmDelete = async () => {
    if (!deleting) return;
    try {
      await deleteKnowledgeDocument(deleting.id);
      setDeleting(null);
      toast.success('已删除');
      await refresh();
    } catch {
      toast.error('删除失败');
    }
  };

  const filtered = docs.filter((d) =>
    !query.trim() ? true : d.title.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <div className="p-6 max-w-6xl mx-auto">
      <div className="flex items-center gap-3 mb-4">
        <h2 className="text-xl font-semibold text-stone-800">个人资料库</h2>
        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={refresh}
            className="p-2 rounded-md text-stone-500 hover:bg-stone-100"
            title="刷新"
          >
            <RefreshCw size={14} />
          </button>
          <Btn
            icon={<Upload size={14} />}
            onClick={() => fileRef.current?.click()}
            loading={uploading}
          >
            上传文件
          </Btn>
          <input
            ref={fileRef}
            type="file"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onUpload(f);
              e.target.value = '';
            }}
          />
        </div>
      </div>

      <div className="bg-white border border-stone-200 rounded-xl shadow-xs">
        <div className="px-4 py-3 border-b border-stone-200 flex items-center gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索文件名"
              className="w-full pl-7 pr-2.5 py-1.5 bg-stone-50 border border-stone-200 rounded-md text-xs outline-none focus:border-primary-300"
            />
          </div>
          <div className="flex items-center gap-1 overflow-x-auto">
            <CatChip active={filter === ''} onClick={() => setFilter('')}>全部</CatChip>
            {cats.map((c) => (
              <CatChip
                key={c.category}
                active={filter === c.category}
                onClick={() => setFilter(c.category)}
              >
                {c.category} <span className="opacity-60">· {c.count}</span>
              </CatChip>
            ))}
          </div>
        </div>

        {loading ? (
          <div className="p-6 text-sm text-stone-500 flex items-center gap-2">
            <Spinner size={14} /> 载入中...
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="资料库还是空的"
            description="点右上「上传文件」添加简历 / JD / 个人笔记"
          />
        ) : (
          <table className="w-full text-sm">
            <thead className="text-[11px] text-stone-500 uppercase tracking-wider">
              <tr className="border-b border-stone-200">
                <th className="text-left font-medium px-4 py-2.5">文件名</th>
                <th className="text-left font-medium px-4 py-2.5 w-28">分类</th>
                <th className="text-left font-medium px-4 py-2.5 w-24">状态</th>
                <th className="text-left font-medium px-4 py-2.5 w-40">更新时间</th>
                <th className="px-4 py-2.5 w-24" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => {
                const st = statusTone(d.status);
                const isEditing = editing?.id === d.id;
                return (
                  <tr key={d.id} className="border-b border-stone-100 last:border-b-0 hover:bg-stone-50/50">
                    <td className="px-4 py-3">
                      {isEditing ? (
                        <div className="flex items-center gap-1">
                          <input
                            autoFocus
                            value={editing.title}
                            onChange={(e) => setEditing({ ...editing, title: e.target.value })}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') onSaveRename();
                              if (e.key === 'Escape') setEditing(null);
                            }}
                            className="flex-1 text-sm px-2 py-1 border border-primary-300 rounded outline-none"
                          />
                          <button onClick={onSaveRename} className="p-1 text-success-500 hover:bg-success-50 rounded">
                            <Check size={14} />
                          </button>
                          <button onClick={() => setEditing(null)} className="p-1 text-stone-400 hover:bg-stone-100 rounded">
                            <X size={14} />
                          </button>
                        </div>
                      ) : (
                        <div className="text-stone-800 truncate max-w-md">{d.title}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-stone-600">{d.category}</td>
                    <td className="px-4 py-3">
                      <Pill tone={st.tone}>{st.label}</Pill>
                    </td>
                    <td className="px-4 py-3 text-stone-500 text-xs">
                      {d.updated_at?.slice(0, 19).replace('T', ' ')}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        onClick={() => setEditing({ id: d.id, title: d.title })}
                        className="p-1.5 text-stone-500 hover:bg-stone-100 rounded"
                        title="重命名"
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        onClick={() => setDeleting(d)}
                        className="p-1.5 text-danger-500 hover:bg-danger-50 rounded ml-1"
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConfirmDialog
        open={!!deleting}
        danger
        title="删除资料"
        description={`确认删除「${deleting?.title}」？此操作不可恢复。`}
        confirmText="删除"
        onConfirm={onConfirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}

function CatChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={[
        'px-2.5 py-1 text-xs rounded-full whitespace-nowrap',
        active
          ? 'bg-primary-50 text-primary-700 border border-primary-100'
          : 'bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100',
      ].join(' ')}
    >
      {children}
    </button>
  );
}
