import { ChangeEvent, useState } from 'react';
import { Upload } from 'lucide-react';
import type { UserSkill } from '@/api/capabilities';
import { Btn } from '@/components/ui/Btn';
import { Modal } from '@/components/ui/Modal';

const TEMPLATE = `---
name: my-skill
description: Describe when the agent should use this skill
---

# Instructions

Write the workflow the agent should follow.
`;

interface Props {
  open: boolean;
  skill: UserSkill | null;
  saving: boolean;
  onClose: () => void;
  onSave: (content: string) => void;
}

export function SkillEditorModal({ open, skill, saving, onClose, onSave }: Props) {
  const [content, setContent] = useState(skill?.content ?? TEMPLATE);

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
    </Modal>
  );
}
