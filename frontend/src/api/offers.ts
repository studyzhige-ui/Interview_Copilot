import { AxiosError, isAxiosError } from 'axios';
import { apiClient } from './client';
import type {
  OfferConfirmationRequired,
  OfferCurrent,
  OfferSourceInput,
  OfferTermsInput,
} from '@/types/career';

export class OfferConfirmationError extends Error {
  constructor(public readonly confirmation: OfferConfirmationRequired) {
    super('Offer 条款变化需要用户确认');
  }
}

export async function getCurrentOffer(opportunityId: string): Promise<OfferCurrent | null> {
  try {
    return (
      await apiClient.get(
        `/career-process/opportunities/${encodeURIComponent(opportunityId)}/offer`,
      )
    ).data;
  } catch (error) {
    if (isAxiosError(error) && error.response?.status === 404) return null;
    throw error;
  }
}

export async function recordOffer(input: {
  opportunityId: string;
  operationKey: string;
  terms: OfferTermsInput;
  source: OfferSourceInput;
}): Promise<OfferCurrent> {
  try {
    return (
      await apiClient.post(
        `/career-process/opportunities/${encodeURIComponent(input.opportunityId)}/offer`,
        {
          operation_key: input.operationKey,
          terms: input.terms,
          source: input.source,
        },
      )
    ).data;
  } catch (error) {
    const axiosError = error as AxiosError<{ detail?: OfferConfirmationRequired }>;
    const detail = axiosError.response?.data?.detail;
    if (axiosError.response?.status === 409 && detail?.status === 'confirmation_required') {
      throw new OfferConfirmationError(detail);
    }
    throw error;
  }
}

export async function confirmOfferTerms(input: {
  opportunityId: string;
  offerId: string;
  operationKey: string;
  expectedCurrentToken: string;
  resolution: 'supplement' | 'replace';
  terms: OfferTermsInput;
  candidateSource: OfferSourceInput;
}): Promise<OfferCurrent> {
  return (
    await apiClient.post(
      `/career-process/opportunities/${encodeURIComponent(input.opportunityId)}/offer/confirm-terms`,
      {
        offer_id: input.offerId,
        operation_key: input.operationKey,
        expected_current_token: input.expectedCurrentToken,
        resolution: input.resolution,
        terms: input.terms,
        candidate_source: input.candidateSource,
        ui_confirmation: { kind: 'product_ui' },
      },
    )
  ).data;
}
