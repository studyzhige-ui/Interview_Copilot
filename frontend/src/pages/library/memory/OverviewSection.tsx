/** 概览 — overview snapshot of all four v3 doc types. */
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Brain, FileText, BookOpen, Compass, Target, RefreshCw, ChevronRight,
} from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { getMemoryOverview } from '@/api/memory';
import { useToastOnError } from '@/hooks/useToastOnError';
import { LoadingBlock, MasteryDot, type SubTab } from './shared';

export function OverviewSection({ switchTo }: { switchTo: (s: SubTab) => void }) {
  const queryClient = useQueryClient();
  const { data, isPending, error } = useQuery({
    queryKey: ['memory', 'overview'],
    queryFn: getMemoryOverview,
  });
  useToastOnError(error, '记忆概览加载失败');

  if (isPending) return <LoadingBlock />;
  if (!data) return null;

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['memory', 'overview'] });

  const empty = !data.user_profile_body.trim()
    && data.knowledge_topics.length === 0
    && !data.strategy_body.trim()
    && !data.habit_body.trim();

  if (empty) {
    return (
      <EmptyState
        icon={<Brain size={28} />}
        title="还没有跨会话记忆"
        description="开几场对话或面试复盘后，系统会自动总结出你的认知、策略与习惯。也可以在「个人中心」开启「全局记忆」让对话主动注入。"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <OverviewCard
        icon={<FileText size={14} />}
        title="个人资料"
        subtitle="durable identity & preferences"
        empty={!data.user_profile_body.trim()}
        emptyHint="未生成 — 在「个人中心」填写 bio 或在对话中提及你的目标公司 / 技术栈"
        onOpen={() => switchTo('profile')}
      >
        <PreviewBody body={data.user_profile_body} />
      </OverviewCard>

      <OverviewCard
        icon={<BookOpen size={14} />}
        title="知识点"
        subtitle={`${data.knowledge_topics.length} 个主题`}
        empty={data.knowledge_topics.length === 0}
        emptyHint="对话中讨论过的技术主题会自动建档"
        onOpen={() => switchTo('knowledge')}
      >
        <div className="space-y-1.5">
          {data.knowledge_topics.slice(0, 6).map((t) => (
            <div key={t.topic} className="flex items-center gap-2 text-[13px]">
              <span className="font-medium text-stone-800 truncate">{t.topic}</span>
              <MasteryDot level={t.mastery_level} />
              <span className="text-[11px] text-stone-400 ml-auto shrink-0">
                {t.fact_count} 条
              </span>
            </div>
          ))}
          {data.knowledge_topics.length > 6 && (
            <div className="text-[11px] text-stone-400 pt-1">
              … 还有 {data.knowledge_topics.length - 6} 个
            </div>
          )}
        </div>
      </OverviewCard>

      <OverviewCard
        icon={<Compass size={14} />}
        title="策略"
        subtitle="cross-topic answering methodology"
        empty={!data.strategy_body.trim()}
        emptyHint="对话中验证有效的方法论会沉淀到这里"
        onOpen={() => switchTo('strategy')}
      >
        <PreviewBody body={data.strategy_body} />
      </OverviewCard>

      <OverviewCard
        icon={<Target size={14} />}
        title="习惯"
        subtitle="stable practice & mindset"
        empty={!data.habit_body.trim()}
        emptyHint="稳定的练习节奏 / 心态会沉淀到这里"
        onOpen={() => switchTo('habit')}
      >
        <PreviewBody body={data.habit_body} />
      </OverviewCard>

      <div className="lg:col-span-2 flex items-center justify-end">
        <button
          onClick={refresh}
          className="inline-flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-700 px-2 py-1"
        >
          <RefreshCw size={11} /> 刷新
        </button>
      </div>
    </div>
  );
}

function OverviewCard({
  icon, title, subtitle, empty, emptyHint, onOpen, children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  empty: boolean;
  emptyHint: string;
  onOpen: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border border-stone-200 rounded-lg overflow-hidden bg-white">
      <div className="px-3.5 py-2.5 bg-stone-50 border-b border-stone-200 flex items-center gap-2">
        <span className="text-stone-500">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium text-stone-800">{title}</div>
          <div className="text-[10px] text-stone-400 font-mono">{subtitle}</div>
        </div>
        <button
          onClick={onOpen}
          className="text-[11px] text-primary-600 hover:text-primary-700 inline-flex items-center gap-0.5"
        >
          打开 <ChevronRight size={12} />
        </button>
      </div>
      <div className="p-3.5 text-stone-700 min-h-[100px]">
        {empty ? (
          <div className="text-xs text-stone-400 italic">{emptyHint}</div>
        ) : children}
      </div>
    </div>
  );
}

function PreviewBody({ body }: { body: string }) {
  // First ~8 lines of the body, no heavy markdown rendering — just a peek.
  const lines = body.split('\n').slice(0, 8).join('\n');
  const truncated = body.split('\n').length > 8;
  return (
    <div className="text-[12.5px] leading-relaxed font-mono whitespace-pre-wrap break-words text-stone-700">
      {lines}
      {truncated && <div className="text-stone-400 mt-1">…</div>}
    </div>
  );
}
