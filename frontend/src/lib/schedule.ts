import type { NextAction } from '@/types/career';

/** Offer deadlines are confirmed obligations even before joining a personal plan. */
export function isScheduledAction(action: NextAction): boolean {
  return action.status === 'planned' || (action.status === 'suggested' && action.source_kind === 'offer');
}
