import { useEffect, useRef, useState } from 'react';
import { prepareInterview, type PreparationBrief } from '@/api/preparation';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';

type PinnedCommand = PreparationBrief['start_request'];
interface Props {
  resumeId: string;
  jdText: string;
  jobOpportunityId?: string;
  disabled: boolean;
  onPractice: (command: PinnedCommand) => void;
}

export function PreparationPanel({ resumeId, jdText, jobOpportunityId, disabled, onPractice }: Props) {
  const key = JSON.stringify([resumeId, jdText, jobOpportunityId]);
  const [snapshot, setSnapshot] = useState<{ key: string; brief: PreparationBrief } | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ key: string; text: string } | null>(null);
  const [page, setPage] = useState(0);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => { active.current?.abort(); active.current = null; }, [key]);
  const brief = snapshot?.key === key ? snapshot.brief : null;
  const error = failure?.key === key ? failure.text : null;
  const busy = pendingKey === key;
  const load = async () => {
    if (disabled || active.current) return;
    const controller = new AbortController(); active.current = controller;
    setPendingKey(key); setFailure(null); setSnapshot(null);
    try {
      const value = await prepareInterview({ resume_id: resumeId, jd_text: jdText,
        job_opportunity_id: jobOpportunityId, purpose: 'full' }, controller.signal);
      if (!controller.signal.aborted && active.current === controller) { setSnapshot({ key, brief: value }); setPage(0); }
    } catch (reason) {
      if (!controller.signal.aborted) setFailure({ key, text: extractErr(reason, '准备资料读取失败，请检查来源后重试') });
    } finally {
      if (active.current === controller) { active.current = null; setPendingKey(null); }
    }
  };
  const download = () => {
    if (!brief) return;
    const url = URL.createObjectURL(new Blob([brief.markdown], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a'); link.href = url; link.download = `interview-preparation-${brief.snapshot_id.slice(0, 12)}.md`;
    link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 0);
  };
  return <section aria-label="岗位证据与专项准备" className="w-full mt-6 rounded-xl border border-stone-200 p-4 space-y-3">
    <h3 className="font-semibold">岗位证据与专项准备</h3>
    <p className="text-sm text-stone-600">核对简历与岗位原文，再选择具体目标练习。不调用模型，不自动启动面试。</p>
    <Btn kind="secondary" disabled={disabled || busy} onClick={() => void load()}>{busy ? '正在核对资料…' : '生成原文准备预览'}</Btn>
    {error && <p role="alert">{error}</p>}
    {brief && <>
      <p className="text-xs text-stone-500">简历版本 {brief.resume_version_id} · 资料快照 {brief.snapshot_id.slice(0, 12)}</p>
      <p role="note" className="text-sm text-amber-800">{brief.disclaimer}</p>
      <p className="text-sm">共 {brief.items.length} 段岗位原文；当前 {page * 8 + 1}–{Math.min((page + 1) * 8, brief.items.length)}。</p>
      {brief.items.slice(page * 8, (page + 1) * 8).map((item) => <article key={item.requirement.id} className="rounded-lg border p-3 space-y-2">
        <h4 className="text-xs text-stone-500">岗位原文 {item.requirement.id}</h4>
        <p className="whitespace-pre-wrap text-sm">{item.requirement.text}</p>
        {item.evidence_candidates.length ? <div className="space-y-2">
          <p className="text-xs text-stone-500">待核实的简历原文，不等于已满足要求</p>
          {item.evidence_candidates.map((source) => <blockquote key={source.id} className="border-l-2 pl-2 text-sm whitespace-pre-wrap">{source.text}<small className="block text-stone-500">{source.id} · 字符 {source.start}–{source.end}</small></blockquote>)}
        </div> : <p className="text-sm text-amber-800">未定位到共词证据，请核实是否有未写入简历的真实经历；这不代表不会。</p>}
        <Btn kind="secondary" disabled={disabled || busy} onClick={() => onPractice({ ...brief.start_request, purpose: 'focused_practice', focus: item.practice_focus })}>围绕此项开始专项练习</Btn>
      </article>)}
      <div className="flex flex-wrap gap-3">
        <Btn kind="secondary" disabled={page === 0} onClick={() => setPage(page - 1)}>上一页原文</Btn>
        <Btn kind="secondary" disabled={(page + 1) * 8 >= brief.items.length} onClick={() => setPage(page + 1)}>下一页原文</Btn>
        <Btn kind="secondary" onClick={download}>导出准备笔记</Btn>
      </div>
      <details><summary>查看岗位相关简历摘录（不覆盖原简历）</summary>
        {brief.resume_excerpts.map((source) => <p className="whitespace-pre-wrap text-sm py-2" key={source.id}>{source.text}</p>)}
        <p className="text-sm text-stone-500">未选入 {brief.omitted_resume_excerpt_count} 段；这是原文摘录，不是完整简历。未生成新的经历或数字。</p>
      </details>
    </>}
  </section>;
}
