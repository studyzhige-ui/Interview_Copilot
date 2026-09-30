/** Product-hosted Copilot: same durable conversation kernel, no duplicate business writes. */
import { lazy, Suspense, useCallback, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import type { ProductObjectReference } from '@/types/api';

const ConversationWorkspace = lazy(() => import('@/pages/chat/GeneralChatPage')
  .then((module) => ({ default: module.GeneralChatPage })));

/** Route hints are explicit input, never authority; the server resolves owner/version. */
export function referenceForPage(pathname: string, search: string): ProductObjectReference | null {
  const params = new URLSearchParams(search);
  const reference = pathname === '/career-process' && params.get('opportunity')
    ? { kind: 'job_opportunity' as const, object_id: params.get('opportunity')! }
    : pathname === '/review' && params.get('id')
      ? { kind: 'interview_record' as const, object_id: params.get('id')! }
      : pathname.startsWith('/artifacts/')
        ? { kind: 'artifact' as const, object_id: pathname.slice('/artifacts/'.length) }
        : null;
  if (!reference || !reference.object_id.trim() || reference.object_id.length > 128) return null;
  return reference;
}

export function CopilotWorkspace({ children }: {
  children: (open: () => void) => React.ReactNode;
}) {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [reference, setReference] = useState<ProductObjectReference | null>(null);
  const [origin, setOrigin] = useState<HTMLElement | null>(null);
  const close = () => {
    setOpen(false);
    origin?.focus();
  };
  const show = useCallback(() => {
    setOrigin(document.activeElement as HTMLElement);
    setReference(referenceForPage(location.pathname, location.search));
    setOpen(true);
  }, [location.pathname, location.search]);
  return <>
    {children(show)}
    {open && location.pathname !== '/general-chat' && (
      <section className="copilot-workspace-drawer" aria-label="页面 Copilot" onKeyDown={(event) => {
        if (event.key === 'Escape' && !event.defaultPrevented) close();
      }}>
        <header className="flex items-center justify-between border-b px-4 py-3">
          <div><h2 className="font-semibold">一起处理当前工作</h2>
            <p className="text-xs text-stone-500">引用会显示在输入框中；关闭面板不会取消已提交的任务。</p></div>
          <div className="flex gap-3"><Link to="/general-chat" onClick={close}>完整工作区</Link>
            <button type="button" onClick={close} aria-label="关闭 Copilot">关闭</button></div>
        </header>
        <Suspense fallback={<p role="status">正在打开 Copilot…</p>}>
          <ConversationWorkspace embedded objectReference={reference} onObjectReferenceConsumed={() => setReference(null)} />
        </Suspense>
      </section>
    )}
  </>;
}
