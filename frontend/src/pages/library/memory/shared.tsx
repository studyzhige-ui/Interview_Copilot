/** Shared bits for the Memory tab sections. */
import { Spinner } from '@/components/ui/Spinner';
import type { MasteryLevel } from '@/types/api';

export type SubTab = 'overview' | 'profile' | 'abilities' | 'strategy' | 'audit';

export function MasteryDot({ level }: { level: MasteryLevel | null }) {
  const tone =
    level === 'strong'      ? 'bg-success-500'
    : level === 'improving' ? 'bg-primary-400'
    : level === 'weak'        ? 'bg-warning-500'
    : 'bg-stone-300';
  // null (no row in DB) vs 'unknown' (explicit "I don't know yet") are
  // semantically different — keep the tooltip honest.
  const title =
    level === null ? '未评估' : level;
  return (
    <span
      title={title}
      className={['inline-block w-1.5 h-1.5 rounded-full shrink-0', tone].join(' ')}
    />
  );
}

export function LoadingBlock() {
  return (
    <div className="py-8 flex items-center justify-center text-sm text-stone-500 gap-2">
      <Spinner size={14} /> 载入中…
    </div>
  );
}
