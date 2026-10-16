import { useQueryClient } from '@tanstack/react-query';
import { extractErr } from '@/api/client';
import { toast } from '@/store/uiStore';
import { invalidateCareerQueries } from '@/lib/productQueries';

export function useRefreshCareer() {
  const client = useQueryClient();
  return () => invalidateCareerQueries(client);
}
export function careerError(error: unknown) { toast.error(extractErr(error)); }
