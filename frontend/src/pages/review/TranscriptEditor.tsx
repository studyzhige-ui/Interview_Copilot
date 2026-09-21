import { useEffect, useRef, useState } from 'react';
import { correctTranscript, getTranscriptReceipt, type SpeakerRole, type TranscriptCommand,
  type TranscriptPage, type TranscriptReceipt, type TranscriptWord } from '@/api/transcripts';
import { extractErr } from '@/api/client';

export const ROLE_LABELS: Record<SpeakerRole, string> = {
  candidate: '候选人', interviewer: '面试官', unknown: '尚未确认',
};

interface Props {
  recordId: string;
  page: TranscriptPage;
  word?: TranscriptWord;
  speaker?: string;
  onPending: (requestId: string | null) => void;
  onSaved: (receipt: TranscriptReceipt) => void;
  onClose: () => void;
}

/** One frozen UUID and body per save. Only GET reconciles an ambiguous reply. */
export function TranscriptEditor({ recordId, page, word, speaker, onPending, onSaved, onClose }: Props) {
  const [text, setText] = useState(word?.text ?? '');
  const [speakerId, setSpeakerId] = useState(word?.speaker_id ?? '');
  const [role, setRole] = useState<SpeakerRole>(speaker ? page.confirmed_roles[speaker] ?? 'unknown' : 'unknown');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [unknown, setUnknown] = useState(false);
  const [canReplay, setCanReplay] = useState(false);
  const [requestId, setRequestId] = useState('');
  const pending = useRef<TranscriptCommand | null>(null);
  const alive = useRef(false);
  const inFlight = useRef(false);
  const conflicted = useRef(false);
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  const send = async (command: TranscriptCommand) => {
    if (inFlight.current) return;
    inFlight.current = true;
    pending.current = command;
    setRequestId(command.request_id);
    onPending(command.request_id);
    setBusy(true); setError(''); setCanReplay(false);
    try {
      const receipt = await correctTranscript(recordId, command);
      if (receipt.request_id !== command.request_id || receipt.previous_transcript_id !== command.expected_transcript_id) {
        throw new Error('纠正收据身份不一致');
      }
      if (alive.current) onSaved(receipt);
    } catch (exc) {
      if (!alive.current) return;
      const status = (exc as { response?: { status?: number } }).response?.status;
      if (status === 400 || status === 422) {
        pending.current = null; onPending(null); setUnknown(false);
        setError('修改未通过校验，请检查文字、角色和修改原因。草稿已保留。');
      } else {
        conflicted.current = status === 409;
        setUnknown(true);
        setError(status === 409
          ? '转写版本或状态已变化。草稿保留，不会自动套用到新版本；请核对收据和最新转写。'
          : '保存结果尚未确认。草稿和原请求编号已保留，请核对收据，不要新建重复请求。');
      }
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const save = () => {
    if (busy || unknown || !reason.trim()) return;
    const words: TranscriptCommand['words'] = [];
    if (word) {
      if (!text.trim()) { setError('原词不能删除或改为空白。'); return; }
      if (text === word.text && (speakerId || null) === word.speaker_id) {
        setError('没有需要保存的更改。'); return;
      }
      words.push({ word_id: word.word_id, text, speaker_id: speakerId || null });
    }
    const command: TranscriptCommand = {
      request_id: crypto.randomUUID(), expected_transcript_id: page.transcript_id,
      words, speaker_roles: speaker ? { [speaker]: role } : {}, reason: reason.trim(),
    };
    void send(command);
  };
  const reconcile = async () => {
    if (inFlight.current || !pending.current) return;
    inFlight.current = true; setBusy(true); setCanReplay(false);
    try {
      const receipt = await getTranscriptReceipt(recordId, pending.current.request_id);
      if (receipt.request_id !== pending.current.request_id || receipt.previous_transcript_id !== pending.current.expected_transcript_id) throw new Error('收据身份不一致');
      if (alive.current) onSaved(receipt);
    } catch (exc) {
      if (!alive.current) return;
      const missing = (exc as { response?: { status?: number } }).response?.status === 404;
      setCanReplay(missing && !conflicted.current);
      setError(missing
        ? '尚未查到收据，不代表服务器一定未执行。可继续核对；仅在明确重试时复用原编号和原内容。'
        : '收据核对失败，未重新发送修改。');
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };

  return <section aria-label={word ? '纠正原词' : '确认说话人角色'} className="space-y-3 rounded-xl border border-primary-200 p-4">
    <p className="text-xs text-stone-500">基于版本 {page.transcript_id}。保存使旧问答、评分和报告失效，不会自动调用模型。</p>
    {word && <>
      <label className="block text-sm">原词文字
        <textarea aria-label="原词文字" value={text} maxLength={500} readOnly={busy || unknown}
          onChange={(event) => setText(event.target.value)} className="mt-1 w-full rounded border p-2" />
      </label>
      <label className="block text-sm">该词说话人
        <select aria-label="该词说话人" value={speakerId} disabled={busy || unknown}
          onChange={(event) => setSpeakerId(event.target.value)} className="ml-2 rounded border p-1">
          <option value="">无法确认</option>
          {page.speakers.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
      </label>
      <p className="text-xs text-stone-500">文字纠正后原时间标记为估计值，不冒充重新对齐。</p>
    </>}
    {speaker && <label className="block text-sm">{speaker} 的角色
      <select aria-label="确认角色" value={role} disabled={busy || unknown}
        onChange={(event) => setRole(event.target.value as SpeakerRole)} className="ml-2 rounded border p-1">
        {Object.entries(ROLE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </label>}
    <label className="block text-sm">修改原因
      <input aria-label="修改原因" value={reason} maxLength={1000} readOnly={busy || unknown}
        onChange={(event) => setReason(event.target.value)} className="ml-2 rounded border p-2" />
    </label>
    {error && <p role="alert" className="text-sm text-danger-600">{error}</p>}
    {unknown && <p className="break-all text-xs">请求编号：{requestId}</p>}
    <div className="flex flex-wrap gap-3 text-sm">
      {!unknown && <button disabled={busy || !reason.trim()} onClick={save}>保存纠正</button>}
      {unknown && <button disabled={busy} onClick={() => void reconcile()}>核对纠正收据</button>}
      {canReplay && <button disabled={busy} onClick={() => pending.current && void send(pending.current)}>使用原请求安全重试</button>}
      <button disabled={busy} onClick={onClose}>{unknown ? '关闭草稿（不撤销已发送修改）' : '取消编辑'}</button>
    </div>
  </section>;
}

export function PendingTranscriptReceipt({ recordId, requestId, onSaved, onDismiss }: {
  recordId: string; requestId: string; onSaved: (receipt: TranscriptReceipt) => void; onDismiss: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const alive = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const check = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const receipt = await getTranscriptReceipt(recordId, requestId);
      if (receipt.request_id !== requestId) throw new Error('收据编号不一致');
      if (alive.current) onSaved(receipt);
    } catch (exc) {
      if (alive.current) setError(extractErr(exc, '收据读取失败，未重复提交'));
    } finally { if (alive.current) setBusy(false); }
  };
  return <aside role="status" className="space-y-2 rounded border border-amber-200 p-3 text-sm">
    <p>上次保存尚未核对。请求编号：{requestId}。这里只保存编号，不保存转写草稿。</p>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={() => void check()}>读取上次纠正收据</button>
    <button disabled={busy} onClick={onDismiss} className="ml-3">清除本地标记（不撤销服务器修改）</button>
  </aside>;
}
