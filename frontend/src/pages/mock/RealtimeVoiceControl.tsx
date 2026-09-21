import { useEffect, useState } from 'react';
import { useRealtimeInterview } from '@/hooks/useRealtimeInterview';

interface Props { recordId: string; disabled: boolean; onActive: (active: boolean) => void; onSynchronize: () => void; onUseText: (text: string) => void }
export function RealtimeVoiceControl({ recordId, disabled, onActive, onSynchronize, onUseText }: Props) {
  const { client, view } = useRealtimeInterview(recordId, onSynchronize);
  const [automatic, setAutomatic] = useState(false);
  const active = view.phase !== 'offline' && view.phase !== 'error';
  useEffect(() => { onActive(active); return () => onActive(false); }, [active, onActive]);
  return <section aria-label="实时语音" className="border-b border-stone-200 bg-stone-50 px-6 py-3 text-sm">
    <div className="flex flex-wrap items-center gap-3">
      <strong>实时语音（本地网络）</strong>
      <button type="button" disabled={!active && disabled} className="rounded border px-3 py-1" onClick={() => { if (active) client.disconnect(); else void client.connect(automatic); }}>{active ? '停止实时语音' : '连接实时语音'}</button>
      <label><input type="checkbox" checked={automatic} disabled={active} onChange={e => setAutomatic(e.target.checked)} /> 停顿后自动提交</label>
      {active && <>
        <button type="button" onClick={() => client.command({ type: 'finish_utterance' })} disabled={view.phase !== 'listening'}>本次说完了</button>
        <button type="button" onClick={() => client.command({ type: 'speak' })} disabled={view.phase !== 'listening'}>朗读当前题</button>
        <button type="button" onClick={() => client.command({ type: 'interrupt' })}>停止朗读</button>
      </>}
    </div>
    <p className="mt-2 text-xs text-stone-600">麦克风接入本地服务。停顿检测不理解语义；默认先核对转写。自动提交可能过早结束回答。连接期间请勿同时使用录音或文字提交。</p>
    <p role="status" className="mt-2">{view.phase === 'connecting' ? '正在连接，请在连接完成后说话…' : view.notice}</p>
    {view.text && <p className="mt-2 whitespace-pre-wrap rounded bg-white p-2">{view.text}</p>}
    {view.phase === 'final' && <div className="mt-2 flex gap-4">
      <button type="button" onClick={() => client.commit()}>确认并提交本次转写</button>
      <button type="button" onClick={() => client.command({ type: 'discard' })}>丢弃并重新说</button>
    </div>}
    {view.text && view.phase !== 'submitting' && <button type="button" className="mt-2 underline" onClick={() => { client.disconnect(); onUseText(view.text); }}>停止实时语音并编辑这段文字</button>}
  </section>;
}
