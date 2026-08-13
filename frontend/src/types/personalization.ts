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
