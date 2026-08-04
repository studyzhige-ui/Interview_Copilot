import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Upload, Search, Pencil, Trash2, FileText, RefreshCw,
  ChevronLeft, ChevronRight, ArrowDown, ArrowUp, Folder, Brain,
} from 'lucide-react';
import { Btn } from '@/components/ui/Btn';
import { EmptyState } from '@/components/ui/EmptyState';
import { Pill } from '@/components/ui/Pill';
import { Modal } from '@/components/ui/Modal';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';
import {
  KNOWLEDGE_ACCEPT,
  deleteKnowledgeDocument,
  listKnowledgeCategories,
  listKnowledgeDocuments,
  updateKnowledgeDocument,
  uploadKnowledgeFile,
} from '@/api/knowledge';
import type { KnowledgeDoc } from '@/types/api';
import { MemoryTab } from './memory/MemoryTab';
import { ResumeSection } from './ResumeSection';

type TopTab = 'knowledge' | 'resumes' | 'memory';

// Personal resumes are a separate profile entity, not RAG material. Keeping
// knowledge categories distinct prevents an uploaded resume from appearing to
// affect mock-interview context when it actually does not.
const CATEGORIES = ['面试题库', '技术资料', '项目资料'] as const;
type Category = typeof CATEGORIES[number];

const PAGE_SIZE = 10;

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

// Compact short label for the "类型" column. Falls back to the file extension
// from the title if MIME is unknown, then to "—".
function shortFileType(d: { title: string; content_type: string | null }): string {
  const ct = (d.content_type ?? '').toLowerCase();
  if (ct.includes('pdf')) return 'PDF';
  if (ct.includes('wordprocessingml') || ct.includes('msword') || ct.includes('docx')) return 'DOCX';
  if (ct.includes('text/plain')) return 'TXT';
  if (ct.includes('markdown')) return 'MD';
  if (ct.includes('html')) return 'HTML';
  if (ct.startsWith('image/')) return ct.split('/')[1]?.toUpperCase() ?? 'IMG';
  if (ct.startsWith('audio/')) return 'AUDIO';
  if (ct.startsWith('video/')) return 'VIDEO';
  // Fallback: title extension
  const m = d.title.match(/\.([a-z0-9]{1,5})$/i);
  if (m) return m[1].toUpperCase();
  return '—';
}

function humanSize(n: number | null): string {
  if (n == null || n < 0) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function LibraryPage() {
  const [tab, setTab] = useState<TopTab>('knowledge');
  return (
    <div className="p-4 md:p-6 max-w-6xl mx-auto">
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <h2 className="text-xl font-semibold text-stone-800">资料与记忆</h2>
        <div className="ml-3 inline-flex items-center gap-1 p-0.5 bg-stone-100 rounded-lg">
          <TopTabBtn active={tab === 'knowledge'} icon={<Folder size={13} />} onClick={() => setTab('knowledge')}>
            知识库
          </TopTabBtn>
          <TopTabBtn active={tab === 'resumes'} icon={<FileText size={13} />} onClick={() => setTab('resumes')}>
            简历
          </TopTabBtn>
          <TopTabBtn active={tab === 'memory'} icon={<Brain size={13} />}  onClick={() => setTab('memory')}>
            记忆
          </TopTabBtn>
        </div>
      </div>
      {tab === 'knowledge' && <FilesSection />}
      {tab === 'resumes' && <ResumeSection />}
      {tab === 'memory' && <MemoryTab />}
    </div>
  );
}

function TopTabBtn({
  active, icon, children, onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'inline-flex items-center gap-1.5 px-3 py-1 rounded-md text-sm',
        active
          ? 'bg-white text-primary-700 shadow-xs font-medium'
          : 'text-stone-600 hover:text-stone-800',
      ].join(' ')}
    >
      {icon}
      {children}
    </button>
  );
}

function FilesSection() {
  const [filter, setFilter] = useState<string>('');
  const [query, setQuery] = useState('');
  const [sortDir, setSortDir] = useState<'desc' | 'asc'>('desc');
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<{ id: string; title: string } | null>(null);
  const [deleting, setDeleting] = useState<KnowledgeDoc | null>(null);
  const [uploading, setUploading] = useState(false);
  // Pending file waiting for category choice
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [pickCategory, setPickCategory] = useState<Category>('技术资料');
  const fileRef = useRef<HTMLInputElement | null>(null);
  const queryClient = useQueryClient();
  const knowledgeQuery = useQuery({
    queryKey: ['knowledge', 'documents', filter],
    queryFn: ({ signal }) => Promise.all([
      listKnowledgeDocuments(filter ? { category: filter } : {}, { signal }),
      listKnowledgeCategories({ signal }),
    ]),
    refetchInterval: (query) => query.state.data?.[0].some(
      (doc) => doc.status === 'processing' || doc.status === 'pending',
    ) ? 2500 : false,
  });
  const [docs, cats] = knowledgeQuery.data ?? [[], []];
  const loading = knowledgeQuery.isPending;
  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['knowledge'] });
  };

  useEffect(() => {
    if (knowledgeQuery.error) toast.error('资料库加载失败');
  }, [knowledgeQuery.error]);

  const onPickFile = (f: File) => {
    setPendingFile(f);
    // Default category guess from filename
    const lc = f.name.toLowerCase();
    if (lc.includes('题') || lc.includes('面经')) {
      setPickCategory('面试题库');
    } else if (lc.includes('项目') || lc.includes('project')) {
      setPickCategory('项目资料');
    } else {
      setPickCategory('技术资料');
    }
  };

  const confirmUpload = async () => {
    if (!pendingFile) return;
    const file = pendingFile;
    const category = pickCategory;
    setPendingFile(null);
    setUploading(true);
    try {
      await uploadKnowledgeFile(file, { category });
      toast.success(`已上传到「${category}」，正在后台处理`);
      await refresh();
    } catch (e) {
      // Surface the backend's specific message (e.g. the format-whitelist
      // rejection or a parser-level friendly error) instead of a generic failure.
      toast.error(extractErr(e, '上传失败'));
    } finally {
      setUploading(false);
    }
  };

  const onSaveRename = async () => {
    if (!editing) return;
    const title = editing.title.trim();
    if (!title) { setEditing(null); return; }
    try {
      await updateKnowledgeDocument(editing.id, { title });
      setEditing(null);
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

  // Filter + search + sort, then paginate
  const processed = useMemo(() => {
    let arr = docs;
    if (query.trim()) {
      const q = query.toLowerCase();
      arr = arr.filter((d) => d.title.toLowerCase().includes(q));
    }
    arr = [...arr].sort((a, b) => {
      const av = a.updated_at ?? a.created_at ?? '';
      const bv = b.updated_at ?? b.created_at ?? '';
      return sortDir === 'desc' ? bv.localeCompare(av) : av.localeCompare(bv);
    });
    return arr;
  }, [docs, query, sortDir]);

  const totalPages = Math.max(1, Math.ceil(processed.length / PAGE_SIZE));
  const visiblePage = Math.min(page, totalPages);
  const pageStart = (visiblePage - 1) * PAGE_SIZE;
  const pageItems = processed.slice(pageStart, pageStart + PAGE_SIZE);

  return (
    <>
      <div className="flex items-center gap-3 mb-4">
        <span className="text-xs text-stone-400">{processed.length} 条</span>
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
            accept={KNOWLEDGE_ACCEPT}
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onPickFile(f);
              e.target.value = '';
            }}
          />
        </div>
      </div>

      <div className="bg-white border border-stone-200 rounded-xl shadow-xs overflow-x-auto">
        <div className="px-4 py-3 border-b border-stone-200 flex items-center gap-3 flex-wrap">
          <div className="relative flex-1 max-w-sm">
            <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索文件名"
              className="w-full pl-7 pr-2.5 py-1.5 bg-stone-50 border border-stone-200 rounded-md text-sm outline-none focus:border-primary-300"
            />
          </div>
          <div className="flex items-center gap-1 overflow-x-auto">
            <CatChip active={filter === ''} onClick={() => { setPage(1); setFilter(''); }}>全部</CatChip>
            {CATEGORIES.map((c) => {
              const count = cats.find((x) => x.category === c)?.count ?? 0;
              return (
                <CatChip key={c} active={filter === c} onClick={() => { setPage(1); setFilter(c); }}>
                  {c} <span className="opacity-60">· {count}</span>
                </CatChip>
              );
            })}
            {/* Any extra non-standard categories that exist in DB */}
            {cats
              .filter((c) => !CATEGORIES.includes(c.category as Category) && c.category !== '默认')
              .map((c) => (
                <CatChip
                  key={c.category}
                  active={filter === c.category}
                  onClick={() => { setPage(1); setFilter(c.category); }}
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
        ) : processed.length === 0 ? (
          <EmptyState
            icon={<FileText size={28} />}
            title="资料库还是空的"
            description="点右上「上传文件」添加题库、技术文档或项目资料；个人简历请使用上方「简历」页签。"
          />
        ) : (
          <>
            <table className="w-full min-w-[860px] text-sm">
              <thead className="text-xs text-stone-500 uppercase tracking-wider">
                <tr className="border-b border-stone-200">
                  <th className="text-left font-medium px-4 py-3">文件名</th>
                  <th className="text-left font-medium px-4 py-3 w-24">类型</th>
                  <th className="text-left font-medium px-4 py-3 w-24">大小</th>
                  <th className="text-left font-medium px-4 py-3 w-28">分类</th>
                  <th className="text-left font-medium px-4 py-3 w-24">状态</th>
                  <th className="text-left font-medium px-4 py-3 w-44">
                    <button
                      onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
                      className="inline-flex items-center gap-1 hover:text-stone-700"
                      title="点击切换排序"
                    >
                      <span>更新时间</span>
                      {sortDir === 'desc'
                        ? <ArrowDown size={12} className="text-primary-500" />
                        : <ArrowUp size={12} className="text-primary-500" />}
                    </button>
                  </th>
                  <th className="px-4 py-3 w-24" />
                </tr>
              </thead>
              <tbody>
                {pageItems.map((d) => {
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
                              onBlur={onSaveRename}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') { e.preventDefault(); onSaveRename(); }
                                if (e.key === 'Escape') { e.preventDefault(); setEditing(null); }
                              }}
                              className="flex-1 text-sm px-2 py-1 border border-primary-300 rounded outline-none focus:ring-2 focus:ring-primary-200"
                              placeholder="Enter 保存，Esc 取消"
                            />
                          </div>
                        ) : (
                          <div className="text-stone-800 truncate max-w-md">{d.title}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className="inline-block px-2 py-0.5 rounded-md bg-stone-100 text-stone-600 text-[11px] font-mono font-medium"
                          title={d.content_type ?? ''}
                        >
                          {shortFileType(d)}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-stone-600 text-xs font-mono">
                        {humanSize(d.size_bytes)}
                      </td>
                      <td className="px-4 py-3 text-stone-600">{d.category}</td>
                      <td className="px-4 py-3">
                        <Pill tone={st.tone}>{st.label}</Pill>
                      </td>
                      <td className="px-4 py-3 text-stone-500 text-xs font-mono">
                        {(d.updated_at ?? d.created_at)?.slice(0, 19).replace('T', ' ')}
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
            {totalPages > 1 && (
              <div className="px-4 py-3 border-t border-stone-100 flex items-center justify-between text-xs text-stone-500">
                <span>
                  第 {pageStart + 1}–{Math.min(processed.length, pageStart + PAGE_SIZE)} 条 / 共 {processed.length} 条
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={visiblePage === 1}
                    className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
                  >
                    <ChevronLeft size={14} />
                  </button>
                  <span className="px-2">
                    {visiblePage} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                    disabled={visiblePage === totalPages}
                    className="w-7 h-7 rounded hover:bg-stone-100 disabled:opacity-30 inline-flex items-center justify-center"
                  >
                    <ChevronRight size={14} />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Upload category picker modal */}
      <Modal
        open={!!pendingFile}
        onClose={() => setPendingFile(null)}
        title="选择分类"
        width={420}
        footer={
          <>
            <Btn kind="ghost" onClick={() => setPendingFile(null)}>取消</Btn>
            <Btn onClick={confirmUpload}>确认上传</Btn>
          </>
        }
      >
        <div className="text-sm text-stone-600 mb-3 truncate">
          文件：<span className="font-mono text-stone-800">{pendingFile?.name}</span>
        </div>
        <div className="flex flex-col gap-2">
          {CATEGORIES.map((c) => (
            <label
              key={c}
              className={[
                'flex items-center gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors',
                pickCategory === c
                  ? 'bg-primary-50 border-primary-200'
                  : 'bg-white border-stone-200 hover:bg-stone-50',
              ].join(' ')}
            >
              <input
                type="radio"
                checked={pickCategory === c}
                onChange={() => setPickCategory(c)}
                className="accent-primary-500"
              />
              <span className={pickCategory === c ? 'text-primary-700 font-medium' : 'text-stone-700'}>
                {c}
              </span>
              <span className="ml-auto text-xs text-stone-400">
                {c === '面试题库' && '常考题、面经'}
                {c === '技术资料' && '技术文档、规范'}
                {c === '项目资料' && '项目说明、设计材料'}
              </span>
            </label>
          ))}
        </div>
      </Modal>

      <ConfirmDialog
        open={!!deleting}
        danger
        title="删除资料"
        description={`确认删除「${deleting?.title}」？此操作不可恢复。`}
        confirmText="删除"
        onConfirm={onConfirmDelete}
        onCancel={() => setDeleting(null)}
      />
    </>
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
        'px-3 py-1 text-sm rounded-full whitespace-nowrap',
        active
          ? 'bg-primary-50 text-primary-700 border border-primary-100'
          : 'bg-stone-50 text-stone-600 border border-stone-200 hover:bg-stone-100',
      ].join(' ')}
    >
      {children}
    </button>
  );
}
