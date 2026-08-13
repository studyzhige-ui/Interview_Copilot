export type HistorySearchKind = 'message' | 'tool_call';

export type HistorySearchRole = 'user' | 'assistant' | 'tool' | 'system';

export interface HistorySearchResult {
  kind: HistorySearchKind;
  identity: string;
  conversation_id: string;
  conversation_title: string;
  conversation_type: string;
  turn_id: string | null;
  message_id: number | null;
  seq: number | null;
  role: string | null;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_status: string | null;
  occurred_at: string;
  excerpt: string;
}

export interface HistorySearchResponse {
  query: string;
  count: number;
  results: HistorySearchResult[];
}

export interface HistoryRecordDetail extends Omit<HistorySearchResult, 'excerpt'> {
  content: string | null;
  content_blocks: Record<string, unknown>[];
  arguments: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface HistorySearchInput {
  query: string;
  conversationId?: string;
  kinds?: HistorySearchKind[];
  roles?: HistorySearchRole[];
  limit?: number;
}
