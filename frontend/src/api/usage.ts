import { apiClient } from './client';

export interface AccountUsage {
  scope: 'account_consumption';
  unit: 'logical_tokens_and_resource_units';
  window_date: string;
  timezone: 'UTC';
  call_limit: number;
  token_limit: number;
  calls_admitted: number;
  tokens_used: number;
  tokens_reserved: number;
  currency: string;
  cost_limit_micros: string | null;
  rated_cost_used_micros: string;
  rated_cost_reserved_micros: string;
  cost_is_vendor_invoice: false;
  unpriced_requests: number;
  unresolved_all_dates: number;
  invoice_reconciled_requests: number;
  units_used: Record<string, number>;
  units_reserved: Record<string, number>;
  unit_limits: Record<string, number>;
  categories: { meter: string; status: string; count: number }[];
  excluded: string[];
}
export interface UsageReceipt {
  id: string;
  revision: number;
  date: string;
  currency: string;
  meter: string;
  provider: string | null;
  model: string | null;
  status: 'reserved' | 'settled' | 'estimated' | 'rejected' | 'unknown';
  cost_basis: 'unpriced' | 'rated_estimate' | 'rated_usage' | 'provider_invoice';
  cost_observed_micros: string | null;
  cost_reserved_micros: string;
  reserved_tokens: number;
  observed_tokens: number;
  reserved_units: Record<string, number>;
  observed_units: Record<string, number> | null;
  price_version: string | null;
  reconciled: boolean;
  created_at: string;
  settled_at: string | null;
}
export async function getAccountUsage(): Promise<AccountUsage> {
  return (await apiClient.get('/usage')).data;
}
export async function getUsageReceipts(before?: string): Promise<{ items: UsageReceipt[]; next_cursor: string | null }> {
  return (await apiClient.get('/usage/receipts', { params: { before, limit: 25 } })).data;
}
