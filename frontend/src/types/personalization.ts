export interface CopilotPreference {
  id: string | null;
  instructions: string[];
  version: number;
  updated_at: string | null;
}
export interface ScopedGuidance {
  owner_id: string;
  guidance: string | null;
  source_message_id: number | null;
  version: number;
  updated_at: string | null;
}

export interface AgentMemorySettings {
  recall_enabled: boolean;
  contribution_enabled: boolean;
  producer_available: boolean;
  version: number;
  updated_at: string | null;
}

export interface ConversationMemoryControls {
  conversation_id: string;
  recall_override: boolean | null;
  contribution_override: boolean | null;
  effective_recall_enabled: boolean;
  effective_contribution_enabled: boolean;
  producer_available: boolean;
  version: number;
  updated_at: string | null;
}

export interface AgentMemorySource {
  source_turn_identity: string;
  source_conversation_identity: string;
  observed_at: string;
  source_deleted_at: string | null;
}

export type AgentMemoryValence = 'effective' | 'ineffective' | 'mixed';
export type AgentMemoryStatus = 'active' | 'invalidated' | 'deleted';

export interface AgentMemory {
  id: string;
  semantic_key: string;
  content: string;
  applicability: string;
  tags: string[];
  valence: AgentMemoryValence;
  confidence: number;
  status: AgentMemoryStatus;
  version: number;
  formed_at: string;
  last_confirmed_at: string;
  last_recalled_at: string | null;
  recall_count: number;
  status_reason: string | null;
  invalidated_at: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
  sources: AgentMemorySource[];
}

export interface AgentMemoryPromotion {
  memory: AgentMemory;
  preference: CopilotPreference;
}
