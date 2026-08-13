import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Archive, Bot, Clipboard, Download, FilePlus2, FileText, Link2, Pencil, RefreshCw } from 'lucide-react';
import {
  archiveArtifact,
  createArtifact,
  createArtifactVersion,
  getArtifact,
  listArtifactRelations,
  listArtifactSubmissions,
  listArtifactVersions,
  listArtifacts,
  recordArtifactSubmission,
  relateArtifactToOpportunity,
} from '@/api/artifacts';
import { listJobOpportunities } from '@/api/careerProcess';
import { downloadFileAsset } from '@/api/fileAssets';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Modal } from '@/components/ui/Modal';
import { Pill } from '@/components/ui/Pill';
import { Spinner } from '@/components/ui/Spinner';
import { toast } from '@/store/uiStore';
import type { Artifact } from '@/types/career';
import { FormItem, SelectInput, TextArea, TextInput, displayDate } from '@/pages/career/CareerFields';
import {
  JobOpportunitySelect,
  OPPORTUNITIES_KEY,
  jobOpportunityLabel,
} from '@/pages/career/JobOpportunitySelect';
import { copilotObjectHandoffHref } from '@/lib/copilotObjectReference';

interface ArtifactForm {
  kind: string;
  title: string;
  content: string;
  format: string;
}

const blankForm: ArtifactForm = { kind: 'resume', title: '', content: '', format: 'markdown' };

function ArtifactEditor({
  open,
  artifact,
  busy,
  onClose,
  onSave,
}: {
  open: boolean;
  artifact?: Artifact;
  busy: boolean;
  onClose: () => void;
  onSave: (form: ArtifactForm) => void;
}) {
  const [form, setForm] = useState<ArtifactForm>(() => artifact ? {
    kind: artifact.kind,
    title: artifact.current_version.title,
    content: artifact.current_version.content_text ?? '',
    format: artifact.current_version.content_format,
  } : blankForm);
  const update = (key: keyof ArtifactForm, value: string) => setForm((current) => ({ ...current, [key]: value }));
  return <Modal open={open} onClose={onClose} title={artifact ? `创建 v${artifact.current_version.version_no + 1}` : '保存求职材料'} width={760} footer={<>
    <Btn kind="ghost" onClick={onClose} disabled={busy}>取消</Btn>
    <Btn loading={busy} disabled={!form.title.trim() || !form.content.trim()} onClick={() => onSave(form)}>{artifact ? '保存新版本' : '保存材料'}</Btn>
  </>}>
    <div className="grid gap-4 sm:grid-cols-2">
      <FormItem label="材料类型">
        <SelectInput value={form.kind} onChange={(e) => update('kind', e.target.value)} disabled={Boolean(artifact)}>
          <option value="resume">简历</option><option value="cover_letter">求职信</option>
          <option value="portfolio">作品集说明</option><option value="interview_notes">面试材料</option>
          <option value="offer_source">Offer 原文</option><option value="other">其他</option>
        </SelectInput>
      </FormItem>
      <FormItem label="内容格式"><SelectInput value={form.format} onChange={(e) => update('format', e.target.value)}><option value="markdown">Markdown</option><option value="plain_text">纯文本</option></SelectInput></FormItem>
      <div className="sm:col-span-2"><FormItem label="标题"><TextInput autoFocus value={form.title} onChange={(e) => update('title', e.target.value)} /></FormItem></div>
      <div className="sm:col-span-2"><FormItem label="内容" hint="只有你明确点击保存时才会成为正式材料"><TextArea rows={16} value={form.content} onChange={(e) => update('content', e.target.value)} /></FormItem></div>
    </div>
  </Modal>;
}

export function ArtifactsPage() {
  const { artifactId } = useParams<{ artifactId?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [includeArchived, setIncludeArchived] = useState(false);
  const [editor, setEditor] = useState<'create' | 'edit' | null>(null);
  const [archiveOpen, setArchiveOpen] = useState(false);
  const [relateOpen, setRelateOpen] = useState(false);
  const [submitOpen, setSubmitOpen] = useState(false);
  const [jobId, setJobId] = useState('');
  const [submissionJobId, setSubmissionJobId] = useState('');
  const [versionSelection, setVersionSelection] = useState<{
    artifactId: string;
    versionId: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloadingFileAssetId, setDownloadingFileAssetId] = useState<string | null>(null);
  const artifactQuery = useQuery({
    queryKey: ['artifact', artifactId],
    queryFn: () => getArtifact(artifactId!),
    enabled: Boolean(artifactId),
    retry: false,
  });
  const artifactsQuery = useQuery({
    queryKey: ['artifacts', includeArchived],
    queryFn: () => listArtifacts(includeArchived),
    enabled: !artifactId,
  });
  const versionsQuery = useQuery({
    queryKey: ['artifact', artifactId, 'versions'],
    queryFn: () => listArtifactVersions(artifactId!),
    enabled: Boolean(artifactId),
  });
  const relationsQuery = useQuery({
    queryKey: ['artifact', artifactId, 'relations'],
    queryFn: () => listArtifactRelations(artifactId!),
    enabled: Boolean(artifactId),
  });
  const submissionsQuery = useQuery({
    queryKey: ['artifact', artifactId, 'submissions'],
    queryFn: () => listArtifactSubmissions(artifactId!),
    enabled: Boolean(artifactId),
  });
  const opportunitiesQuery = useQuery({
    queryKey: OPPORTUNITIES_KEY,
    queryFn: () => listJobOpportunities(true),
    enabled: Boolean(artifactId),
  });
  const artifact = artifactQuery.data;

  const run = async (operation: () => Promise<void>, success: string): Promise<boolean> => {
    setBusy(true);
    try { await operation(); toast.success(success); return true; }
    catch (error) { toast.error(extractErr(error)); return false; }
    finally { setBusy(false); }
  };

  const save = async (form: ArtifactForm) => {
    setBusy(true);
    try {
      const version = { title: form.title.trim(), content_text: form.content.trim(), content_format: form.format };
      if (artifact) {
        const updated = await createArtifactVersion({ artifactId: artifact.id, operationKey: crypto.randomUUID(), version });
        queryClient.setQueryData(['artifact', artifact.id], updated);
        await queryClient.invalidateQueries({ queryKey: ['artifact', artifact.id, 'versions'] });
        setVersionSelection({ artifactId: artifact.id, versionId: updated.current_version.id });
        toast.success(`已保存 v${updated.current_version.version_no}`);
      } else {
        const created = await createArtifact({ operationKey: crypto.randomUUID(), kind: form.kind, version });
        await queryClient.invalidateQueries({ queryKey: ['artifacts'] });
        toast.success('材料已保存');
        navigate(`/artifacts/${encodeURIComponent(created.id)}`);
      }
      setEditor(null);
    } catch (error) { toast.error(extractErr(error)); }
    finally { setBusy(false); }
  };

  if (!artifactId) return <div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-xl font-semibold text-stone-800">求职材料</h1><p className="mt-1 text-sm text-stone-500">只有明确保存的内容才会成为 Artifact；普通对话回复不会自动进入材料库。</p></div><Btn icon={<FilePlus2 size={15} />} onClick={() => setEditor('create')}>保存新材料</Btn></header>
    <div className="flex items-center justify-between gap-3"><label className="flex items-center gap-2 text-xs text-stone-600"><input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />显示已归档材料</label><button className="rounded p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700" onClick={() => artifactsQuery.refetch()} aria-label="刷新材料列表"><RefreshCw size={15} /></button></div>
    {artifactsQuery.isLoading ? <div className="flex items-center gap-2 rounded-xl border border-stone-200 bg-white p-6 text-sm text-stone-500"><Spinner size={15} />正在加载材料…</div> : artifactsQuery.isError ? <div className="rounded-xl border border-stone-200 bg-white"><EmptyState icon={<FileText size={30} />} title="材料列表暂时无法加载" description={extractErr(artifactsQuery.error)} action={<Btn size="sm" onClick={() => artifactsQuery.refetch()}>重试</Btn>} /></div> : artifactsQuery.data?.length ? <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{artifactsQuery.data.map((item) => <button key={item.id} onClick={() => navigate(`/artifacts/${encodeURIComponent(item.id)}`)} className="rounded-xl border border-stone-200 bg-white p-4 text-left shadow-xs transition hover:border-primary-300 hover:bg-primary-50/20"><div className="flex items-start justify-between gap-3"><div className="rounded-md bg-primary-50 p-2 text-primary-700"><FileText size={18} /></div><div className="flex gap-1"><Pill>{item.kind}</Pill><Pill tone="primary">v{item.current_version.version_no}</Pill></div></div><h2 className="mt-4 truncate font-medium text-stone-800">{item.current_version.title}</h2><p className="mt-2 line-clamp-3 text-xs leading-relaxed text-stone-500">{item.current_version.content_text || '文件型材料'}</p>{item.archived_at && <div className="mt-3"><Pill tone="neutral">已归档</Pill></div>}</button>)}</section> : <div className="rounded-xl border border-stone-200 bg-white"><EmptyState icon={<FilePlus2 size={30} />} title="还没有求职材料" description="保存简历、求职信或作品集说明后，可以持续创建清晰版本。" action={<Btn size="sm" onClick={() => setEditor('create')}>保存第一份材料</Btn>} /></div>}
    {editor === 'create' && <ArtifactEditor open busy={busy} onClose={() => setEditor(null)} onSave={save} />}
  </div>;

  if (artifactQuery.isLoading) return <div className="flex items-center gap-2 p-6 text-sm text-stone-500"><Spinner size={15} />正在加载材料…</div>;
  if (!artifact) return <div className="p-6"><EmptyState icon={<FileText size={32} />} title="没有找到这份材料" description={extractErr(artifactQuery.error)} action={<Btn onClick={() => navigate('/artifacts')}>返回材料页</Btn>} /></div>;

  const versions = versionsQuery.data ?? [artifact.current_version];
  const version = versionSelection?.artifactId === artifact.id
    ? versions.find((item) => item.id === versionSelection.versionId) ?? artifact.current_version
    : artifact.current_version;
  const versionFileAssetId = version.file_asset_id;
  const relations = relationsQuery.data ?? [];
  const submissions = submissionsQuery.data ?? [];
  const opportunityById = new Map(
    (opportunitiesQuery.data ?? []).map((opportunity) => [opportunity.id, opportunity]),
  );
  const opportunityText = (id: string) => {
    const opportunity = opportunityById.get(id);
    return opportunity ? jobOpportunityLabel(opportunity) : '岗位机会暂时不可读取';
  };
  return <div className="mx-auto max-w-5xl space-y-5 p-4 md:p-6">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><h1 className="text-xl font-semibold text-stone-800">{version.title}</h1><Pill tone="primary">v{version.version_no}</Pill><Pill>{artifact.kind}</Pill>{artifact.archived_at && <Pill tone="neutral">已归档</Pill>}</div><button onClick={() => navigator.clipboard.writeText(artifact.id).then(() => toast.success('材料 ID 已复制'))} className="mt-2 inline-flex items-center gap-1 text-xs text-stone-500 hover:text-primary-700" title={artifact.id}><Clipboard size={12} />复制材料 ID</button></div><div className="flex flex-wrap gap-2"><Btn kind="ghost" size="sm" onClick={() => navigate('/artifacts')}>返回</Btn><Link to={copilotObjectHandoffHref('artifact', artifact.id, version.title)}><Btn kind="outline" size="sm" icon={<Bot size={14} />}>询问 Copilot</Btn></Link>{versionFileAssetId && <Btn kind="outline" size="sm" icon={<Download size={14} />} loading={downloadingFileAssetId === versionFileAssetId} onClick={async () => { setDownloadingFileAssetId(versionFileAssetId); try { await downloadFileAsset(versionFileAssetId, version.title); toast.success(`已下载 v${version.version_no}`); } catch (error) { toast.error(extractErr(error, '文件下载失败')); } finally { setDownloadingFileAssetId(null); } }}>下载文件</Btn>}{!artifact.archived_at && <><Btn kind="outline" size="sm" icon={<Link2 size={14} />} onClick={() => setRelateOpen(true)}>关联岗位</Btn><Btn size="sm" icon={<Pencil size={14} />} onClick={() => setEditor('edit')}>创建新版本</Btn><Btn kind="ghost" size="sm" icon={<Archive size={14} />} onClick={() => setArchiveOpen(true)}>归档</Btn></>}</div></header>
    <section className="rounded-xl border border-stone-200 bg-white shadow-xs"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-stone-100 px-5 py-3 text-xs text-stone-500"><span>{version.id === artifact.current_version.id ? '当前版本' : '历史版本'} · {version.content_format}</span><span>来源：{version.origin_kind} · {displayDate(version.created_at)}</span></div><pre className="whitespace-pre-wrap break-words p-5 font-sans text-sm leading-7 text-stone-700">{version.content_text || '该版本保存为文件资产。'}</pre></section>

    <section className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <h2 className="text-sm font-semibold text-stone-800">版本历史</h2>
      {versionsQuery.isError ? <p className="mt-2 text-xs text-danger-700">{extractErr(versionsQuery.error, '版本历史加载失败')}</p> : (
        <div className="mt-3 flex flex-wrap gap-2">
          {versions.map((item) => <button key={item.id} type="button" onClick={() => setVersionSelection({ artifactId: artifact.id, versionId: item.id })} className={`rounded-lg border px-3 py-2 text-left text-xs transition ${item.id === version.id ? 'border-primary-300 bg-primary-50 text-primary-800' : 'border-stone-200 text-stone-600 hover:bg-stone-50'}`}><span className="font-medium">v{item.version_no} · {item.title}</span><span className="ml-2 text-stone-400">{displayDate(item.created_at)}</span></button>)}
        </div>
      )}
    </section>

    <section className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <h2 className="text-sm font-semibold text-stone-800">关联岗位</h2>
      <p className="mt-1 text-xs text-stone-500">关联表示这份材料与岗位有关，不代表已经投递。</p>
      {relationsQuery.isLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-stone-400"><Spinner size={12} />正在读取岗位关联…</div> : relationsQuery.isError ? <p className="mt-3 text-xs text-danger-700">{extractErr(relationsQuery.error, '岗位关联加载失败')}</p> : relations.length ? <div className="mt-3 flex flex-wrap gap-2">{relations.map((relation) => <Pill key={relation.id}>{opportunityText(relation.job_opportunity_id)}</Pill>)}</div> : <p className="mt-3 text-xs text-stone-400">尚未关联岗位</p>}
    </section>

    <section className="rounded-xl border border-stone-200 bg-white p-4 shadow-xs">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-sm font-semibold text-stone-800">投递记录</h2>
      <p className="mt-1 text-xs text-stone-500">每条记录展示投递当时冻结的精确版本，不会替换成材料当前版本。</p></div>{!artifact.archived_at && <Btn size="sm" kind="outline" onClick={() => setSubmitOpen(true)}>确认已投递当前查看版本</Btn>}</div>
      {submissionsQuery.isLoading ? <div className="mt-3 flex items-center gap-2 text-xs text-stone-400"><Spinner size={12} />正在读取投递记录…</div> : submissionsQuery.isError ? <p className="mt-3 text-xs text-danger-700">{extractErr(submissionsQuery.error, '投递记录加载失败')}</p> : submissions.length ? <div className="mt-3 space-y-3">{submissions.map((submission) => <article key={submission.id} className="rounded-lg border border-stone-200 bg-stone-50 p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-medium text-stone-700">{opportunityText(submission.job_opportunity_id)}</div><div className="flex items-center gap-2"><Pill tone="primary">投递时 v{submission.submitted_version.version_no}</Pill><span className="text-[11px] text-stone-400">{displayDate(submission.submitted_at)}</span></div></div><div className="mt-2 text-xs font-medium text-stone-600">{submission.submitted_version.title}</div><pre className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed text-stone-500">{submission.submitted_version.content_text || '该冻结版本为文件资产。'}</pre></article>)}</div> : <p className="mt-3 text-xs text-stone-400">暂无已确认的投递记录</p>}
    </section>
    {editor === 'edit' && <ArtifactEditor open artifact={artifact} busy={busy} onClose={() => setEditor(null)} onSave={save} />}
    <ConfirmDialog open={archiveOpen} title="归档这份材料？" description="归档后不能再创建新版本，但已保存内容仍保留。" confirmText="归档" loading={busy} onCancel={() => setArchiveOpen(false)} onConfirm={async () => { const ok = await run(async () => { const updated = await archiveArtifact(artifact.id); queryClient.setQueryData(['artifact', artifact.id], updated); await queryClient.invalidateQueries({ queryKey: ['artifacts'] }); }, '材料已归档'); if (ok) setArchiveOpen(false); }} />
    <Modal open={relateOpen} onClose={() => setRelateOpen(false)} title="关联岗位机会" width={500} footer={<><Btn kind="ghost" onClick={() => setRelateOpen(false)}>取消</Btn><Btn loading={busy} disabled={!jobId} onClick={async () => { const ok = await run(async () => { await relateArtifactToOpportunity(artifact.id, jobId); await queryClient.invalidateQueries({ queryKey: ['artifact', artifact.id, 'relations'] }); }, '材料已关联岗位'); if (ok) { setJobId(''); setRelateOpen(false); } }}>关联</Btn></>}><FormItem label="岗位机会" hint="从你的求职进展中选择；关联不会改变材料内容或版本"><JobOpportunitySelect value={jobId} onChange={setJobId} emptyLabel="选择一个岗位" excludeIds={relations.map((relation) => relation.job_opportunity_id)} /></FormItem></Modal>
    <Modal open={submitOpen} onClose={() => setSubmitOpen(false)} title="确认已投递的精确版本" width={520} footer={<><Btn kind="ghost" onClick={() => setSubmitOpen(false)} disabled={busy}>取消</Btn><Btn loading={busy} disabled={!submissionJobId} onClick={async () => { const ok = await run(async () => { await recordArtifactSubmission({ artifactId: artifact.id, artifactVersionId: version.id, jobOpportunityId: submissionJobId, operationKey: crypto.randomUUID() }); await Promise.all([queryClient.invalidateQueries({ queryKey: ['artifact', artifact.id, 'submissions'] }), queryClient.invalidateQueries({ queryKey: ['artifact', artifact.id, 'relations'] })]); }, `已冻结并记录 v${version.version_no} 的投递`); if (ok) { setSubmissionJobId(''); setSubmitOpen(false); } }}>确认已投递</Btn></>}>
      <div className="space-y-4"><div className="rounded-lg border border-primary-100 bg-primary-50 p-3 text-sm text-primary-900"><div className="font-medium">将冻结 v{version.version_no} · {version.title}</div><p className="mt-1 text-xs text-primary-700">这是明确的产品命令，只记录已经发生的投递；不会发送材料，也不会改写当前版本。</p></div><FormItem label="实际投递岗位"><JobOpportunitySelect value={submissionJobId} onChange={setSubmissionJobId} emptyLabel="选择一个岗位" /></FormItem></div>
    </Modal>
  </div>;
}
