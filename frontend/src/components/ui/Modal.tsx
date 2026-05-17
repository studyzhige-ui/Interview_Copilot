import { ReactNode, useEffect } from 'react';
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

/**
 * Centered modal. Always rendered into `document.body` via React Portal so
 * ancestor `transform` / `filter` / `overflow:hidden` (e.g. the AppShell
 * scroll container) can't break the centering or trap the backdrop.
 */
export function Modal({ open, onClose, title, width = 480, children, footer }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    // Also lock body scroll while the modal is open so background doesn't move
    // when the modal is taller than the viewport.
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open, onClose]);

  if (!open || typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-stone-900/40 px-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl border border-stone-200 max-h-[85vh] flex flex-col"
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
      >
        {title !== undefined && (
          <div className="flex items-center justify-between px-5 py-3.5 border-b border-stone-100">
            <div className="text-[15px] font-semibold text-stone-800">{title}</div>
            <button
              onClick={onClose}
              className="p-1 rounded hover:bg-stone-100 text-stone-500"
              aria-label="关闭"
            >
              <X size={16} />
            </button>
          </div>
        )}
        <div className="flex-1 overflow-auto p-5">{children}</div>
        {footer && (
          <div className="px-5 py-3 border-t border-stone-100 flex justify-end gap-2">{footer}</div>
        )}
      </div>
    </div>,
    document.body,
  );
}
