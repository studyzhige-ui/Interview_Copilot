import { ReactNode, useId, useLayoutEffect, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  width?: number;
  children: ReactNode;
  footer?: ReactNode;
}

// One stack for all portals: closing a nested dialog must not unlock the page
// or let the same Escape key close its parent as well.
const modalStack: HTMLElement[] = [];
const backgroundState = new Map<HTMLElement, { inert: boolean; hidden: string | null }>();
let originalOverflow = '';
function syncBackground() {
  for (const [element, previous] of backgroundState) {
    element.inert = previous.inert;
    if (previous.hidden === null) element.removeAttribute('aria-hidden');
    else element.setAttribute('aria-hidden', previous.hidden);
  }
  backgroundState.clear();
  const top = modalStack.at(-1);
  if (!top) return;
  for (const element of Array.from(document.body.children)) {
    if (!(element instanceof HTMLElement) || element === top) continue;
    backgroundState.set(element, { inert: element.inert, hidden: element.getAttribute('aria-hidden') });
    element.inert = true;
    element.setAttribute('aria-hidden', 'true');
  }
}
function focusableElements(dialog: HTMLElement) {
  return Array.from(dialog.querySelectorAll<HTMLElement>(
    'button, [href], input, select, textarea, [tabindex], [contenteditable="true"]',
  )).filter((element) => {
    if (element.tabIndex < 0 || element.matches(':disabled') || element.closest('[hidden], [inert]')) return false;
    // display:none on an ancestor is not inherited by getComputedStyle(child).
    for (let current: HTMLElement | null = element; current && current !== dialog.parentElement; current = current.parentElement) {
      const style = getComputedStyle(current);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return true;
  });
}

/** Portal dialog with a shared focus/background boundary for nested dialogs. */
export function Modal({ open, onClose, title, width = 480, children, footer }: ModalProps) {
  const titleId = useId();
  const overlayRef = useRef<HTMLDivElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  // Capture before the commit so a child's autoFocus cannot replace the opener.
  const focusBeforeOpen = useMemo(() => open && typeof document !== 'undefined'
    && document.activeElement instanceof HTMLElement ? document.activeElement : null, [open]);
  useLayoutEffect(() => { closeRef.current = onClose; }, [onClose]);
  useLayoutEffect(() => {
    const overlay = overlayRef.current;
    const dialog = dialogRef.current;
    if (!open || !overlay || !dialog) return;
    const previousFocus = focusBeforeOpen;
    if (!modalStack.length) originalOverflow = document.body.style.overflow;
    modalStack.push(overlay);
    document.body.style.overflow = 'hidden';
    syncBackground();
    // React autoFocus may already have selected an input in this dialog.
    if (!dialog.contains(document.activeElement)) (focusableElements(dialog)[0] ?? dialog).focus();
    const isTop = () => modalStack.at(-1) === overlay;
    const onKey = (event: KeyboardEvent) => {
      if (!isTop() || event.defaultPrevented) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        closeRef.current();
      } else if (event.key === 'Tab') {
        const elements = focusableElements(dialog);
        const first = elements[0];
        const last = elements.at(-1);
        if (!first || !last) { event.preventDefault(); dialog.focus(); return; }
        const active = document.activeElement;
        if (!dialog.contains(active) || active === dialog || (event.shiftKey ? active === first : active === last)) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      }
    };
    const onFocus = (event: FocusEvent) => {
      if (isTop() && event.target instanceof Node && !dialog.contains(event.target)) {
        (focusableElements(dialog)[0] ?? dialog).focus();
      }
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('focusin', onFocus);
    return () => {
      const wasTop = isTop();
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('focusin', onFocus);
      const index = modalStack.indexOf(overlay);
      if (index >= 0) modalStack.splice(index, 1);
      syncBackground();
      if (!modalStack.length) document.body.style.overflow = originalOverflow;
      if (wasTop && previousFocus?.isConnected && !previousFocus.closest('[inert]')) previousFocus.focus();
    };
  }, [open, focusBeforeOpen]);

  if (!open || typeof document === 'undefined') return null;
  return createPortal(
    <div ref={overlayRef}
      className="fixed inset-0 z-[100] flex items-center justify-center bg-stone-900/40 px-4 py-4 overscroll-contain"
      onClick={(event) => { if (event.target === event.currentTarget && modalStack.at(-1) === event.currentTarget) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" tabIndex={-1}
        aria-labelledby={title !== undefined ? titleId : undefined} aria-label={title === undefined ? '对话框' : undefined}
        className="bg-white rounded-2xl shadow-xl border border-stone-200 flex flex-col outline-none"
        style={{ width, maxWidth: '100%', maxHeight: 'min(85vh, calc(100dvh - 2rem))' }}>
        {title !== undefined && <div className="flex shrink-0 items-center justify-between px-5 py-3.5 border-b border-stone-100">
          <div id={titleId} role="heading" aria-level={2} className="text-[15px] font-semibold text-stone-800">{title}</div>
          <button type="button" onClick={onClose} className="p-2 rounded hover:bg-stone-100 text-stone-500" aria-label="关闭"><X size={16} /></button>
        </div>}
        <div className="flex-1 min-h-0 overflow-auto p-5">{children}</div>
        {footer && <div className="shrink-0 px-5 py-3 border-t border-stone-100 flex justify-end gap-2">{footer}</div>}
      </div>
    </div>, document.body,
  );
}
