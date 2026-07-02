/**
 * Memory tab — v3 architecture browser inside the Library page.
 *
 * Replaces the retired ``memory_items`` browser. Six sub-areas, one file
 * per section under this directory:
 *
 *   概览      — OverviewSection: snapshot of all four v3 doc types
 *   个人资料  — ProfileSection: user_profile_doc body (read-only)
 *   知识点    — KnowledgeSection: knowledge_doc topics + view / edit / delete
 *   策略      — SingleDocSection kind="strategy"
 *   习惯      — SingleDocSection kind="habit"
 *   审计      — AuditSection: memory_audit_log list + before/after detail
 *
 * Edits go through ``PUT /memory/{doc}`` which holds the per-user
 * memory-lock server-side, so user-edits serialise with realtime
 * extraction and dreaming writers. Data fetching is React Query
 * (keys under ['memory', ...]); mutations invalidate their keys.
 */
import { useState } from 'react';
import {
  Brain, FileText, BookOpen, Compass, Target, History,
} from 'lucide-react';
import { OverviewSection } from './OverviewSection';
import { ProfileSection } from './ProfileSection';
import { KnowledgeSection } from './KnowledgeSection';
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
  { id: 'profile',   label: '个人资料', icon: FileText },
  { id: 'knowledge', label: '知识点',   icon: BookOpen },
  { id: 'strategy',  label: '策略',     icon: Compass },
  { id: 'habit',     label: '习惯',     icon: Target },
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
        {sub === 'profile'   && <ProfileSection />}
        {sub === 'knowledge' && <KnowledgeSection />}
        {sub === 'strategy'  && <SingleDocSection kind="strategy" />}
        {sub === 'habit'     && <SingleDocSection kind="habit" />}
        {sub === 'audit'     && <AuditSection />}
      </div>
    </div>
  );
}
