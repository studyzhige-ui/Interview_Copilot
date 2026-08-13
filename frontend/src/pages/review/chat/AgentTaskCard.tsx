import { useState } from 'react';
import { Check, ChevronDown, Circle, CircleDot, ListChecks, SkipForward } from 'lucide-react';
import { Pill } from '@/components/ui/Pill';
import type { AgentTask, AgentTaskPhaseStatus } from '@/types/api';

const statusMeta: Record<AgentTaskPhaseStatus, {
  label: string;
  icon: typeof Circle;
  className: string;
}> = {
  pending: { label: '未开始', icon: Circle, className: 'text-stone-400' },
  in_progress: { label: '进行中', icon: CircleDot, className: 'text-primary-600' },
  completed: { label: '已完成', icon: Check, className: 'text-success-600' },
  skipped: { label: '已跳过', icon: SkipForward, className: 'text-stone-400' },
};

export function AgentTaskCard({ task }: { task: AgentTask }) {
  const [expanded, setExpanded] = useState(false);
  const completed = task.phases.filter((phase) => phase.status === 'completed').length;
  const currentIndex = task.phases.findIndex((phase) => phase.status === 'in_progress');
  const compactPhases = currentIndex >= 0
    ? task.phases.slice(currentIndex, currentIndex + 2)
    : task.phases.filter((phase) => phase.status === 'pending').slice(0, 1);
  const visiblePhases = expanded ? task.phases : compactPhases;
  return (
    <section
      className="mx-3 mb-2 rounded-xl border border-primary-100 bg-primary-50/40 p-3"
      aria-label="当前执行计划"
    >
      <div className="flex items-start gap-2">
        <ListChecks size={16} className="mt-0.5 shrink-0 text-primary-700" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-medium text-stone-800">{task.objective}</div>
            <Pill tone={task.frozen_at ? 'neutral' : 'primary'}>
              {completed}/{task.phases.length} 阶段
            </Pill>
          </div>
          {visiblePhases.length > 0 && <ol className="mt-2 space-y-1.5">
            {visiblePhases.map((phase) => {
              const meta = statusMeta[phase.status];
              const Icon = meta.icon;
              return (
                <li key={phase.id} className="flex items-start gap-2 text-xs">
                  <Icon size={13} className={`mt-0.5 shrink-0 ${meta.className}`} />
                  <span className={phase.status === 'in_progress' ? 'font-medium text-stone-800' : 'text-stone-600'}>
                    {phase.title}
                  </span>
                  <span className="ml-auto shrink-0 text-[10px] text-stone-400">{meta.label}</span>
                </li>
              );
            })}
          </ol>}
          {task.phases.length > compactPhases.length && (
            <button
              type="button"
              className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-primary-700 hover:text-primary-800"
              onClick={() => setExpanded((value) => !value)}
              aria-expanded={expanded}
            >
              <ChevronDown size={12} className={expanded ? 'rotate-180' : ''} />
              {expanded ? '收起完整计划' : `查看全部 ${task.phases.length} 个阶段`}
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
