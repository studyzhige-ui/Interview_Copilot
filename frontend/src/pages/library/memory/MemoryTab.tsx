/**
 * Memory tab — v3 architecture browser inside the Library page.
 *
 * Five sub-areas matching the REAL v3 stores (the previous 知识点/习惯
 * tabs called doc types retired with the v3 migration and 404'd):
 *
 *   概览      — OverviewSection: user_profile + ability states + strategy
 *   用户画像  — SingleDocSection kind="profile" (editable, optimistic lock)
 *   能力状态  — AbilityStatesSection: the structured ledger + user veto
 *   学习策略  — SingleDocSection kind="strategy" (editable, optimistic lock)
 *   审计      — AuditSection: memory_audit_log list + before/after detail
 *
 * Edits go through ``PUT /memory/{doc}`` which holds the per-user
 * memory-lock server-side AND carries the optimistic-concurrency token
 * (MEM-3), so user edits can't silently erase background extraction.
 */
import { useState } from 'react';
import {
  Brain, FileText, Compass, Target, History,
} from 'lucide-react';
import { OverviewSection } from './OverviewSection';
import { AbilityStatesSection } from './AbilityStatesSection';
import { SingleDocSection } from './SingleDocSection';
import { AuditSection } from './AuditSection';
import type { SubTab } from './shared';

interface SubTabDef {
  id: SubTab;
  label: string;
  icon: typeof Brain;
}

const SUB_TABS: SubTabDef[] = [
  { id: 'overview',  label: '概览',     icon: Brain },
  { id: 'profile',   label: '用户画像', icon: FileText },
  { id: 'abilities', label: '能力状态', icon: Target },
  { id: 'strategy',  label: '学习策略', icon: Compass },
  { id: 'audit',     label: '审计',     icon: History },
];

export function MemoryTab() {
  const [sub, setSub] = useState<SubTab>('overview');
  return (
    <div className="bg-white border border-stone-200 rounded-xl shadow-xs">
      <div className="px-4 py-3 border-b border-stone-200 flex items-center gap-1.5 overflow-x-auto">
        {SUB_TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setSub(id)}
            className={[
              'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm whitespace-nowrap',
              sub === id
                ? 'bg-primary-50 text-primary-700 border border-primary-100'
                : 'text-stone-600 hover:bg-stone-100 border border-transparent',
            ].join(' ')}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>
      <div className="p-5">
        {sub === 'overview'  && <OverviewSection switchTo={setSub} />}
        {sub === 'profile'   && <SingleDocSection kind="profile" />}
        {sub === 'abilities' && <AbilityStatesSection />}
        {sub === 'strategy'  && <SingleDocSection kind="strategy" />}
        {sub === 'audit'     && <AuditSection />}
      </div>
    </div>
  );
}
