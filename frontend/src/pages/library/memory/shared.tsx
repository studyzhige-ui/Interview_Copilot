/** Shared bits for the Memory tab sections. */
import { Spinner } from '@/components/ui/Spinner';
import type { MasteryLevel } from '@/types/api';

export type SubTab = 'overview' | 'profile' | 'abilities' | 'strategy' | 'audit';

// One mastery vocabulary for every memory view (dot tone, pill tone, label)
// — two sections drifting into different palettes for the same domain is
// exactly how 'stable' ended up rendering like 未评估.
export const MASTERY_META: Record<string, { label: string; dot: string; pill: string }> = {
  weak:      { label: '弱',    dot: 'bg-warning-500', pill: 'bg-red-50 text-red-700 border-red-200' },
  improving: { label: '进步中', dot: 'bg-primary-400', pill: 'bg-amber-50 text-amber-700 border-amber-200' },
  stable:    { label: '稳定',  dot: 'bg-sky-400',     pill: 'bg-sky-50 text-sky-700 border-sky-200' },
  strong:    { label: '强',    dot: 'bg-success-500', pill: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
};

export function MasteryDot({ level }: { level: MasteryLevel | null }) {
  const tone = (level && MASTERY_META[level]?.dot) || 'bg-stone-300';
  // null = no row in DB → 未评估.
  const title = level === null ? '未评估' : (MASTERY_META[level]?.label ?? level);
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
