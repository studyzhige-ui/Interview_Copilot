import type { QueryClient } from '@tanstack/react-query';

/** Shared read projections affected by career commands, including Agent writes. */
export function invalidateCareerQueries(client: QueryClient) {
  return Promise.all([
    ['career-workspace'], ['career-process'], ['job-opportunities'],
    ['next-action-agenda'], ['next-actions'], ['artifacts'], ['resumes'],
    ['workspace'], ['career-insights'], ['offer'], ['current-offers'],
    ['interview-records'], ['interview', 'records'], ['pending-confirmations'],
    ['career-profile'], ['career-profile-drafts'],
  ].map(queryKey => client.invalidateQueries({ queryKey })));
}
