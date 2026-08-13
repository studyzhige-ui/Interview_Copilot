import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { updateInterviewRecord } from '@/api/interview';
import { extractErr } from '@/api/client';
import { Btn } from '@/components/ui/Btn';
import { JobOpportunitySelect } from '@/pages/career/JobOpportunitySelect';
import { toast } from '@/store/uiStore';

export function InterviewOpportunityControl({
  interviewId,
  initialJobOpportunityId,
}: {
  interviewId: string;
  initialJobOpportunityId?: string | null;
}) {
  const queryClient = useQueryClient();
  const initialValue = initialJobOpportunityId ?? '';
  const [value, setValue] = useState(initialValue);
  const [savedValue, setSavedValue] = useState(initialValue);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await updateInterviewRecord(interviewId, {
        job_opportunity_id: value || null,
      });
      setSavedValue(value);
      await queryClient.invalidateQueries({ queryKey: ['interview', 'records'] });
      toast.success(value ? '面试记录已关联岗位' : '已清除面试记录的岗位关联');
    } catch (error) {
      toast.error(extractErr(error, '岗位关联保存失败'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-3 flex flex-wrap items-end gap-2 rounded-lg border border-stone-200 bg-stone-50 p-3">
      <div className="min-w-[240px] flex-1">
        <div className="mb-1 text-[11px] font-medium text-stone-500">本次面试对应岗位</div>
        <JobOpportunitySelect
          value={value}
          onChange={setValue}
          disabled={saving}
          ariaLabel="本次面试对应岗位"
          emptyLabel="不关联岗位"
        />
      </div>
      <Btn
        kind="outline"
        size="sm"
        loading={saving}
        disabled={value === savedValue}
        onClick={() => { void save(); }}
      >
        {value ? '保存关联' : '清除关联'}
      </Btn>
    </div>
  );
}
