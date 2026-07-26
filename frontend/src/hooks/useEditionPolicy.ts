import { useQuery } from '@tanstack/react-query';
import { getEditionPolicy } from '@/api/capabilities';


export function useEditionPolicy() {
  return useQuery({
    queryKey: ['edition-policy'],
    queryFn: getEditionPolicy,
    staleTime: Infinity,
  });
}
