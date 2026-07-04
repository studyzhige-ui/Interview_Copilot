/** 个人资料 — user_profile_doc body (read-only; no PUT endpoint backend-side). */
import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';
import { EmptyState } from '@/components/ui/EmptyState';
import { MarkdownBody } from '@/components/ui/MarkdownBody';
import { getUserProfileDoc } from '@/api/memory';
import { useToastOnError } from '@/hooks/useToastOnError';
import { LoadingBlock } from './shared';

export function ProfileSection() {
  const { data: body, isPending, error } = useQuery({
    queryKey: ['memory', 'profile'],
    queryFn: ({ signal }) => getUserProfileDoc({ signal }),
  });
  useToastOnError(error, '个人资料加载失败');

  if (isPending) return <LoadingBlock />;
  if (!body?.trim()) {
    return (
      <EmptyState
        icon={<FileText size={28} />}
        title="个人资料文档为空"
        description="在「个人中心」填写昵称 / 简介，或者在对话中提及你的目标公司 / 技术栈 / 当前职级，系统会自动沉淀到这里。"
      />
    );
  }
  return (
    <div className="bg-stone-50 border border-stone-200 rounded-lg p-4">
      <div className="text-[11px] text-stone-400 font-mono mb-2 uppercase tracking-wider">
        user_profile_doc · 只读
      </div>
      <MarkdownBody source={body} />
    </div>
  );
}
