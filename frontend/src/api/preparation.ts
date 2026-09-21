import { apiClient } from './client';
import type { components } from '@/types/generated/shared-protocols';

export type PreparationBrief = components['schemas']['PreparationBriefResponseContract'];
export type PreparationCommand = components['schemas']['MockPreparationRequestRequestContract'];

export async function prepareInterview(command: PreparationCommand, signal: AbortSignal): Promise<PreparationBrief> {
  const response = await apiClient.post<PreparationBrief>('/mock-interviews/preparation', command, { signal });
  return response.data;
}
