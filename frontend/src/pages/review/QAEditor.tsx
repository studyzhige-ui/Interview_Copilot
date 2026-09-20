import { useEffect, useRef, useState } from 'react';
import { editInterviewQA, getInterviewRecord } from '@/api/interview';
import type { InterviewQA } from '@/types/api';

interface Props {
  recordId: string;
  qa: InterviewQA;
  onSaved: (saved: InterviewQA) => void;
  onClose: () => void;
}

/** An edit is one versioned command. An ambiguous response is reconciled by GET,
 * never by an automatic second PATCH. Server snapshots cannot replace the draft. */
export function QAEditor({ recordId, qa, onSaved, onClose }: Props) {
  const [question, setQuestion] = useState(qa.question);
  const [answer, setAnswer] = useState(qa.answer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [latest, setLatest] = useState<InterviewQA | null>(null);
  const pending = useRef<{ question: string; answer: string; version: number } | null>(null);
  const alive = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const submit = async (version: number | undefined) => {
    if (inFlight.current) return;
    if (!Number.isInteger(version)) {
      setError('当前快照缺少版本，必须先核对服务器状态。');
      return;
    }
    const command = { question, answer, version: version as number };
    pending.current = command;
    inFlight.current = true;
    setBusy(true);
    try {
      const saved = await editInterviewQA(recordId, qa.id, {
        expected_version: command.version,
        question: command.question,
        answer: command.answer,
      });
      if (alive.current) onSaved(saved);
    } catch (exc) {
      if (!alive.current) return;
      const status = (exc as { response?: { status?: number } }).response?.status;
      setLatest(null);
      setError(status === 409
        ? '记录已变化或当前状态不可编辑。草稿已保留，请核对服务器状态。'
        : '保存未确认。草稿已保留，请先核对服务器状态，不要重复提交。');
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };

  const reconcile = async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const detail = await getInterviewRecord(recordId);
      if (!alive.current) return;
      const saved = detail.qa.find((item) => item.id === qa.id);
      if (!saved || !Number.isInteger(saved.version)) {
        setLatest(null);
        setError('服务器已无这个可编辑的问答版本。草稿仍保留，请复制后处理。');
        return;
      }
      const sent = pending.current;
      if (sent && saved.question === sent.question && saved.answer === sent.answer
          && (saved.version as number) >= sent.version) {
        // Inputs were frozen while the request outcome was unknown.
        onSaved(saved);
        return;
      }
      setLatest(saved);
      setError('服务器版本已读取。请比较下方内容，再明确选择是否以该版本保存草稿。');
    } catch {
      if (alive.current) setError('状态核对失败，草稿仍保留。此操作没有重新提交修改。');
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return (
    <section aria-label="编辑问答" className="mt-4 rounded-xl border border-primary-200 p-4">
      <p className="mb-3 text-xs text-stone-500">保存将使旧评分和报告失效，不会自动重新调用模型。</p>
      <label className="block text-sm">问题草稿
        <textarea aria-label="问题草稿" value={question} disabled={busy} readOnly={!!error && !latest}
          onChange={(event) => setQuestion(event.target.value)} rows={3}
          className="mt-1 w-full rounded border p-2" />
      </label>
      <label className="mt-3 block text-sm">回答草稿
        <textarea aria-label="回答草稿" value={answer} disabled={busy} readOnly={!!error && !latest}
          onChange={(event) => setAnswer(event.target.value)} rows={5}
          className="mt-1 w-full rounded border p-2" />
      </label>
      {error && <div role="alert" className="mt-3 text-sm text-danger-600">{error}</div>}
      {latest && <div className="mt-3 rounded bg-stone-50 p-3 text-sm">
        <h4>服务器版本 {latest.version}</h4>
        <p className="whitespace-pre-wrap">问题：{latest.question}</p>
        <p className="whitespace-pre-wrap">回答：{latest.answer}</p>
      </div>}
      <div className="mt-3 flex flex-wrap gap-3 text-sm">
        {!error && <button type="button" disabled={busy} onClick={() => void submit(qa.version)}>
          {busy ? '保存中…' : '保存修改'}
        </button>}
        {error && <button type="button" disabled={busy} onClick={() => void reconcile()}>核对保存状态</button>}
        {latest && <button type="button" disabled={busy} onClick={() => void submit(latest.version)}>
          以服务器当前版本保存我的修改
        </button>}
        <button type="button" disabled={busy} onClick={onClose}>
          {error ? '关闭编辑（不撤销已发送修改）' : '取消编辑'}
        </button>
      </div>
    </section>
  );
}
