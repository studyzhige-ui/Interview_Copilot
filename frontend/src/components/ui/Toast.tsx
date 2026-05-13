import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-react';
import { useUIStore, type ToastKind } from '@/store/uiStore';

const iconFor = (k: ToastKind) => {
  switch (k) {
    case 'success': return <CheckCircle2 size={16} className="text-success-500" />;
    case 'warning': return <AlertTriangle size={16} className="text-warning-500" />;
    case 'danger':  return <XCircle size={16} className="text-danger-500" />;
    default:        return <Info size={16} className="text-info-500" />;
  }
};

export function ToastViewport() {
  const toasts = useUIStore((s) => s.toasts);
  const dismiss = useUIStore((s) => s.dismissToast);
  return (
    <div className="pointer-events-none fixed top-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex items-center gap-2 rounded-lg bg-white pl-3 pr-2 py-2 shadow-md border border-stone-200 text-sm text-stone-800 min-w-[220px]"
        >
          {iconFor(t.kind)}
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => dismiss(t.id)}
            className="p-1 rounded hover:bg-stone-100 text-stone-400"
            aria-label="关闭"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
