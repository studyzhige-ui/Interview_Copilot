import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  width?: number;
  children: ReactNode;
  footer?: ReactNode;
}

export function Modal({ open, onClose, title, width = 480, children, footer }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-stone-900/30 px-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-lg border border-stone-200 max-h-[80vh] flex flex-col"
        style={{ width }}
        onClick={(e) => e.stopPropagation()}
      >
        {title !== undefined && (
          <div className="flex items-center justify-between px-5 py-3 border-b border-stone-200">
            <div className="text-base font-semibold text-stone-800">{title}</div>
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
          <div className="px-5 py-3 border-t border-stone-200 flex justify-end gap-2">{footer}</div>
        )}
      </div>
    </div>
  );
}
