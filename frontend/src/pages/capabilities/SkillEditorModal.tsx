import { ChangeEvent, useState } from 'react';
import { Plus, Trash2, Upload } from 'lucide-react';
import type { SkillResource, SkillResourceKind, UserSkill } from '@/api/capabilities';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';

const TEMPLATE = `---
name: my-skill
description: Describe when the agent should use this skill
profiles: [career]
required-tools: []
allowed-tools: []
---

# Instructions

Write the workflow the agent should follow.
`;

interface Props {
  open: boolean;
  skill: UserSkill | null;
  saving: boolean;
  resources: SkillResource[];
  resourcesLoading: boolean;
  resourcesSaving: boolean;
  onClose: () => void;
  onSave: (content: string) => void;
  onSaveResources: (resources: SkillResource[]) => void;
}

export function SkillEditorModal({
  open, skill, saving, resources, resourcesLoading, resourcesSaving,
  onClose, onSave, onSaveResources,
}: Props) {
  const [content, setContent] = useState(skill?.content ?? TEMPLATE);
  const [resourceDrafts, setResourceDrafts] = useState<SkillResource[]>(resources);

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) setContent(await file.text());
    event.target.value = '';
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={skill ? `编辑 ${skill.name}` : '导入 Skill'}
      width={760}
      footer={
        <>
          <Btn kind="ghost" onClick={onClose} disabled={saving}>取消</Btn>
          <Btn onClick={() => onSave(content)} loading={saving}>保存 Skill</Btn>
        </>
      }
    >
      <div className="flex items-center justify-between gap-4 mb-3">
        <p className="text-xs text-stone-500">
          使用标准 SKILL.md：YAML frontmatter 必须包含 name 和 description。
        </p>
        <label className="inline-flex items-center gap-1.5 text-xs text-primary-700 cursor-pointer hover:text-primary-800">
          <Upload size={14} /> 选择 .md 文件
          <input type="file" accept=".md,text/markdown,text/plain" className="hidden" onChange={importFile} />
        </label>
      </div>
      <textarea
        aria-label="Skill 内容"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        spellCheck={false}
        className="w-full min-h-[430px] resize-y rounded-lg border border-stone-200 bg-stone-950 p-4 font-mono text-[13px] leading-6 text-stone-100 outline-none focus:border-primary-400"
      />
      <div className="mt-5 border-t border-stone-200 pt-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-medium text-stone-800">按需披露的附属资源</h3>
            <p className="mt-1 text-xs text-stone-500">主 Skill 激活后，Agent 仍需按明确路径单独读取这些 reference、script、template 或 asset。</p>
          </div>
          <Btn
            size="sm"
            kind="ghost"
            icon={<Plus size={14} />}
            disabled={!skill}
            onClick={() => setResourceDrafts((items) => [...items, { path: '', kind: 'reference', content: '' }])}
          >添加资源</Btn>
        </div>
        {!skill ? <p className="mt-3 text-xs text-stone-500">先保存主 Skill，再添加附属资源。</p>
          : resourcesLoading ? <p className="mt-3 text-xs text-stone-500">正在读取资源…</p>
            : <div className="mt-3 space-y-3">
              {resourceDrafts.map((resource, index) => (
                <div key={`${resource.path}-${index}`} className="rounded-lg border border-stone-200 bg-stone-50 p-3">
                  <div className="grid gap-2 sm:grid-cols-[1fr_150px_auto]">
                    <input
                      aria-label={`资源 ${index + 1} 路径`}
                      value={resource.path}
                      placeholder="references/rubric.md"
                      onChange={(event) => setResourceDrafts((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, path: event.target.value } : item))}
                      className="rounded-md border border-stone-200 bg-white px-2.5 py-1.5 text-xs"
                    />
                    <select
                      aria-label={`资源 ${index + 1} 类型`}
                      value={resource.kind}
                      onChange={(event) => setResourceDrafts((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, kind: event.target.value as SkillResourceKind } : item))}
                      className="rounded-md border border-stone-200 bg-white px-2.5 py-1.5 text-xs"
                    >
                      <option value="reference">reference</option><option value="script">script</option>
                      <option value="template">template</option><option value="asset">asset</option>
                    </select>
                    <button aria-label={`删除资源 ${index + 1}`} onClick={() => setResourceDrafts((items) => items.filter((_, itemIndex) => itemIndex !== index))} className="p-1.5 text-stone-500 hover:text-danger-600"><Trash2 size={15} /></button>
                  </div>
                  <textarea
                    aria-label={`资源 ${index + 1} 内容`}
                    value={resource.content}
                    onChange={(event) => setResourceDrafts((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, content: event.target.value } : item))}
                    rows={4}
                    className="mt-2 w-full rounded-md border border-stone-200 bg-white p-2 font-mono text-xs"
                  />
                </div>
              ))}
              <div className="flex justify-end"><Btn size="sm" loading={resourcesSaving} onClick={() => onSaveResources(resourceDrafts)}>保存附属资源</Btn></div>
            </div>}
      </div>
    </Modal>
  );
}
