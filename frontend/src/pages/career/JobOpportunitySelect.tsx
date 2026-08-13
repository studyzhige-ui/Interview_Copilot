import { useQuery } from '@tanstack/react-query';
import { listJobOpportunities } from '@/api/careerProcess';
import { SelectInput } from './CareerFields';
import type { JobOpportunity } from '@/types/career';

export const OPPORTUNITIES_KEY = ['career-process', 'opportunities', true] as const;

export function jobOpportunityLabel(opportunity: JobOpportunity): string {
  const location = opportunity.location ? ` · ${opportunity.location}` : '';
  const archived = opportunity.archived_at ? '（已归档）' : '';
  return `${opportunity.company_name} · ${opportunity.job_title}${location}${archived}`;
}

export function JobOpportunitySelect({
  value,
  onChange,
  disabled,
  ariaLabel = '关联岗位机会',
  emptyLabel = '不关联岗位',
  excludeIds = [],
}: {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel?: string;
  emptyLabel?: string;
  excludeIds?: string[];
}) {
  const opportunitiesQuery = useQuery({
    queryKey: OPPORTUNITIES_KEY,
    queryFn: () => listJobOpportunities(true),
  });
  const excluded = new Set(excludeIds);
  const opportunities = (opportunitiesQuery.data ?? []).filter(
    (opportunity) => opportunity.id === value || !excluded.has(opportunity.id),
  );

  return (
    <div className="space-y-1.5">
      <SelectInput
        aria-label={ariaLabel}
        value={value}
        disabled={disabled || opportunitiesQuery.isLoading}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{opportunitiesQuery.isLoading ? '正在读取岗位…' : emptyLabel}</option>
        {opportunities.map((opportunity) => (
          <option key={opportunity.id} value={opportunity.id}>
            {jobOpportunityLabel(opportunity)}
          </option>
        ))}
      </SelectInput>
      {opportunitiesQuery.isError && (
        <div role="alert" className="text-[11px] text-danger-700">岗位列表暂时无法读取，请稍后重试。</div>
      )}
    </div>
  );
}
