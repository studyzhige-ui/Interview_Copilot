import { useEffect } from 'react';
import { toast } from '@/store/uiStore';
import { extractErr } from '@/api/client';

/** Toast a query error once per error instance (not on every render). */
export function useToastOnError(error: unknown, fallback: string) {
  useEffect(() => {
    if (error) toast.error(extractErr(error, fallback));
  }, [error, fallback]);
}
