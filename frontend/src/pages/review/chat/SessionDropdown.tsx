import { useEffect, useRef } from 'react';
import {
  MessageSquare, ChevronDown, Plus, Pencil, X as XIcon,
} from 'lucide-react';
import type { ChatSessionListItem } from '@/types/api';

/**
 * Row 2 of the panel (internal/debrief mode only): the session dropdown
 * with rename-in-place, per-row streaming dots, delete buttons, and the
 * "+ 新会话" button.
 */
export function SessionDropdown({
  sessions,
  activeSessionId,
  activeSessionTitle,
  streaming,
  streamingSet,
  open,
  setOpen,
  dropdownRef,
  onSelect,
  renaming,
  setRenaming,
  commitRename,
  creating,
  onNewChat,
  onRemoveChat,
}: {
  sessions: ChatSessionListItem[];
  activeSessionId: string | null;
  activeSessionTitle: string;
  streaming: boolean;
  streamingSet: Set<string>;
  open: boolean;
  setOpen: (v: boolean | ((prev: boolean) => boolean)) => void;
  dropdownRef: React.MutableRefObject<HTMLDivElement | null>;
  onSelect: (id: string) => void;
  renaming: { id: string; title: string } | null;
  setRenaming: (v: { id: string; title: string } | null) => void;
  commitRename: () => Promise<void>;
  creating: boolean;
  onNewChat: () => void;
  onRemoveChat: (id: string) => void;
}) {
  const renameInputRef = useRef<HTMLInputElement | null>(null);

  // Focus the rename input whenever a rename starts.
  useEffect(() => {
    if (!renaming) return;
    requestAnimationFrame(() => {
      const el = renameInputRef.current;
      if (!el) return;
      el.focus();
      el.setSelectionRange(el.value.length, el.value.length);
    });
  }, [renaming]);

  const activeSession = sessions.find((s) => s.session_id === activeSessionId);

  return (
    <div className="px-3 py-2 border-b border-stone-200 flex items-center gap-1.5">
      <div ref={dropdownRef} className="relative flex-1 min-w-0">
        {renaming && renaming.id === activeSessionId ? (
          <input
            ref={renameInputRef}
            value={renaming.title}
            onChange={(e) => setRenaming({ id: renaming.id, title: e.target.value })}
            onBlur={() => { void commitRename(); }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') { e.preventDefault(); void commitRename(); }
              else if (e.key === 'Escape') { e.preventDefault(); setRenaming(null); }
            }}
            placeholder="按 Enter 保存，Esc 取消"
            className="w-full px-3 py-2 text-sm border border-primary-300 rounded-lg outline-none focus:ring-2 focus:ring-primary-200"
          />
        ) : (
          <button
            onClick={() => setOpen((v) => !v)}
            disabled={sessions.length === 0}
            className="w-full inline-flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-stone-200 bg-white hover:bg-stone-50 text-stone-700 text-sm disabled:opacity-60"
          >
            <span className="flex items-center gap-2 min-w-0">
              <MessageSquare size={13} className="text-stone-500 shrink-0" />
              <span className="truncate">{activeSessionId ? activeSessionTitle : '尚无会话'}</span>
              {streaming && (
                <span className="shrink-0 inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
              )}
            </span>
            <ChevronDown size={14} className={[
              'text-stone-400 transition-transform',
              open ? 'rotate-180' : '',
            ].join(' ')} />
          </button>
        )}
        {open && (
          <div className="absolute left-0 right-0 top-full mt-1 max-h-[320px] overflow-y-auto p-1 bg-white border border-stone-200 rounded-lg shadow-lg z-30">
            {sessions.length === 0 && (
              <div className="px-3 py-3 text-sm text-stone-400 text-center">点右侧 + 新建一段会话</div>
            )}
            {sessions.map((s) => {
              const act = s.session_id === activeSessionId;
              const isStreaming = streamingSet.has(s.session_id);
              return (
                <div
                  key={s.session_id}
                  className={[
                    'group flex items-center gap-2 px-2.5 py-1.5 rounded-md cursor-pointer',
                    act ? 'bg-primary-50' : 'hover:bg-stone-50',
                  ].join(' ')}
                >
                  <span
                    onClick={() => { onSelect(s.session_id); setOpen(false); }}
                    onDoubleClick={(e) => { e.stopPropagation(); setRenaming({ id: s.session_id, title: s.title }); }}
                    className={[
                      'flex-1 min-w-0 truncate text-sm',
                      act ? 'text-primary-700 font-semibold' : 'text-stone-700',
                    ].join(' ')}
                    title="双击重命名"
                  >
                    {s.title}
                  </span>
                  {isStreaming && (
                    <span className="shrink-0 inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse" />
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      if (s.session_id === activeSessionId) setOpen(false);
                      setRenaming({ id: s.session_id, title: s.title });
                    }}
                    title="重命名"
                    className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-stone-600 hover:bg-stone-100 flex items-center justify-center"
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onRemoveChat(s.session_id); }}
                    title="删除"
                    className="opacity-0 group-hover:opacity-100 w-6 h-6 rounded text-stone-400 hover:text-danger-500 hover:bg-danger-50 flex items-center justify-center"
                  >
                    <XIcon size={12} />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
      {activeSession && !renaming && (
        <button
          onClick={() => setRenaming({ id: activeSession.session_id, title: activeSession.title })}
          title="重命名当前会话"
          className="shrink-0 w-9 h-9 rounded-lg border border-stone-200 bg-white text-stone-500 hover:bg-stone-50 hover:text-primary-700 hover:border-primary-200 flex items-center justify-center"
        >
          <Pencil size={14} />
        </button>
      )}
      <button
        onClick={onNewChat}
        disabled={creating}
        title="新建一段会话"
        className="shrink-0 inline-flex items-center gap-1 px-3 h-9 rounded-lg border border-dashed border-stone-300 text-stone-600 hover:bg-stone-50 hover:border-primary-300 hover:text-primary-700 text-sm disabled:opacity-50"
      >
        <Plus size={14} />
        <span>新会话</span>
      </button>
    </div>
  );
}
