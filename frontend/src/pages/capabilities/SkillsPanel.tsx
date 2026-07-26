import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, Sparkles, Trash2 } from 'lucide-react';
import {
  createSkill,
  deleteSkill,
  listSkills,
  updateSkill,
  type UserSkill,
} from '@/api/capabilities';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { ConfirmDialog } from '@/components/ui/ConfirmDialog';
import { EmptyState } from '@/components/ui/EmptyState';
import { Spinner } from '@/components/ui/Spinner';
import { useToastOnError } from '@/hooks/useToastOnError';
import { toast } from '@/store/uiStore';
import { SkillEditorModal } from './SkillEditorModal';

export function SkillsPanel() {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<UserSkill | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [deleting, setDeleting] = useState<UserSkill | null>(null);
  const query = useQuery({ queryKey: ['capabilities', 'skills'], queryFn: listSkills });
  useToastOnError(query.error, 'Skill 加载失败');

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['capabilities', 'skills'] });
  const save = useMutation({
    mutationFn: (content: string) => editing
      ? updateSkill(editing.id, { content })
      : createSkill(content),
    onSuccess: () => {
      refresh();
      setEditorOpen(false);
      toast.success('Skill 已保存');
    },
    onError: (error) => toast.error(extractErr(error, 'Skill 保存失败')),
  });
  const toggle = useMutation({
    mutationFn: (skill: UserSkill) => updateSkill(skill.id, { enabled: !skill.enabled }),
    onSuccess: refresh,
    onError: (error) => toast.error(extractErr(error, 'Skill 状态更新失败')),
  });
  const remove = useMutation({
    mutationFn: (id: number) => deleteSkill(id),
    onSuccess: () => {
      refresh();
      setDeleting(null);
      toast.success('Skill 已删除');
    },
    onError: (error) => toast.error(extractErr(error, 'Skill 删除失败')),
  });

  const openEditor = (skill: UserSkill | null) => {
    setEditing(skill);
    setEditorOpen(true);
  };

  return (
    <section>
      <div className="flex items-start justify-between gap-6 mb-5">
        <div>
          <h2 className="text-lg font-semibold text-stone-800">Skills</h2>
          <p className="mt-1 text-sm text-stone-500">按需为 Agent 提供你自己的工作流指令，完整内容只在调用时加载。</p>
        </div>
        <Btn icon={<Plus size={16} />} onClick={() => openEditor(null)}>导入 Skill</Btn>
      </div>

      {query.isPending ? (
        <div className="py-16 flex justify-center"><Spinner /></div>
      ) : !query.data?.length ? (
        <EmptyState icon={<Sparkles size={28} />} title="还没有 Skill" description="导入一个 SKILL.md，让 Agent 学会你的专属流程。" />
      ) : (
        <div className="grid gap-3">
          {query.data.map((skill) => (
            <article key={skill.id} className="rounded-xl border border-stone-200 bg-white p-4 flex items-center gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium text-stone-800 truncate">{skill.name}</h3>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] ${skill.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-stone-100 text-stone-500'}`}>
                    {skill.enabled ? '已启用' : '已停用'}
                  </span>
                </div>
                <p className="mt-1 text-sm text-stone-500 line-clamp-2">{skill.description}</p>
              </div>
              <Btn size="sm" kind="ghost" onClick={() => toggle.mutate(skill)}>{skill.enabled ? '停用' : '启用'}</Btn>
              <button aria-label={`编辑 ${skill.name}`} onClick={() => openEditor(skill)} className="p-2 text-stone-500 hover:text-primary-700"><Pencil size={16} /></button>
              <button aria-label={`删除 ${skill.name}`} onClick={() => setDeleting(skill)} className="p-2 text-stone-500 hover:text-danger-500"><Trash2 size={16} /></button>
            </article>
          ))}
        </div>
      )}

      {editorOpen && (
        <SkillEditorModal
          key={editing?.id ?? 'new'}
          open
          skill={editing}
          saving={save.isPending}
          onClose={() => setEditorOpen(false)}
          onSave={(content) => save.mutate(content)}
        />
      )}
      <ConfirmDialog
        open={deleting !== null}
        title="删除 Skill"
        description={`确定删除 ${deleting?.name ?? ''}？之后的 Agent 对话将无法再使用它。`}
        confirmText="删除"
        danger
        loading={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </section>
  );
}
