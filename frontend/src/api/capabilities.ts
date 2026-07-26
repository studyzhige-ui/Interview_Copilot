import { apiClient } from './client';

export interface UserSkill {
  id: number;
  name: string;
  description: string;
  content: string;
  enabled: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export type MCPTransport = 'streamable_http' | 'stdio';

export interface EditionPolicy {
  edition: 'cloud' | 'community';
  display_name: string;
  managed_ai_roles: string[];
  mcp_transports: MCPTransport[];
  allow_provider_connection_overrides: boolean;
  show_advanced_model_settings: boolean;
}

export interface UserMCPServer {
  id: number;
  name: string;
  transport: MCPTransport;
  url: string | null;
  command: string | null;
  args: string[];
  has_secrets: boolean;
  enabled: boolean;
  last_status: 'unchecked' | 'connected' | 'failed';
  last_error: string | null;
  tool_count: number;
  checked_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  runtime?: {
    status: 'connecting' | 'connected' | 'failed' | 'closed';
    error: string | null;
    revision: string;
    idle_seconds: number;
  };
}

export type CapabilityDecision = 'allow' | 'deny' | 'inherit';

export interface SessionCapabilityState {
  conversation_id: string;
  discovered_skills: string[];
  permissions: Record<string, 'allow' | 'deny'>;
  tool_history: Array<{
    tool_name: string;
    status: string;
    turn_id: string;
    at: string;
  }>;
  updated_at: string | null;
}

export interface MCPServerInput {
  name: string;
  transport: MCPTransport;
  url?: string;
  command?: string;
  args: string[];
  headers?: Record<string, string>;
  env?: Record<string, string>;
  enabled: boolean;
}

export async function getEditionPolicy(): Promise<EditionPolicy> {
  const response = await apiClient.get('/capabilities/edition');
  return response.data;
}

export async function listSkills(): Promise<UserSkill[]> {
  const response = await apiClient.get('/capabilities/skills');
  return response.data?.skills ?? [];
}

export async function createSkill(content: string): Promise<UserSkill> {
  const response = await apiClient.post('/capabilities/skills', { content });
  return response.data;
}

export async function updateSkill(
  id: number,
  patch: { content?: string; enabled?: boolean },
): Promise<UserSkill> {
  const response = await apiClient.patch(`/capabilities/skills/${id}`, patch);
  return response.data;
}

export async function deleteSkill(id: number): Promise<void> {
  await apiClient.delete(`/capabilities/skills/${id}`);
}

export async function listMCPServers(): Promise<UserMCPServer[]> {
  const response = await apiClient.get('/capabilities/mcp-servers');
  return response.data?.servers ?? [];
}

export async function createMCPServer(input: MCPServerInput): Promise<UserMCPServer> {
  const response = await apiClient.post('/capabilities/mcp-servers', input);
  return response.data;
}

export async function updateMCPServer(
  id: number,
  input: MCPServerInput,
): Promise<UserMCPServer> {
  const response = await apiClient.put(`/capabilities/mcp-servers/${id}`, input);
  return response.data;
}

export async function setMCPServerEnabled(id: number, enabled: boolean): Promise<UserMCPServer> {
  const response = await apiClient.patch(`/capabilities/mcp-servers/${id}/enabled`, { enabled });
  return response.data;
}

export async function testMCPServer(id: number): Promise<{
  server: UserMCPServer;
  tools: Array<{ name: string; description: string }>;
}> {
  const response = await apiClient.post(`/capabilities/mcp-servers/${id}/test`, null, {
    timeout: 60_000,
  });
  return response.data;
}

export async function deleteMCPServer(id: number): Promise<void> {
  await apiClient.delete(`/capabilities/mcp-servers/${id}`);
}

export async function getSessionCapabilities(sessionId: string): Promise<SessionCapabilityState> {
  const response = await apiClient.get(`/capabilities/sessions/${encodeURIComponent(sessionId)}`);
  return response.data;
}

export async function setSessionCapabilityPermission(
  sessionId: string,
  capability: string,
  decision: CapabilityDecision,
): Promise<SessionCapabilityState> {
  const response = await apiClient.put(
    `/capabilities/sessions/${encodeURIComponent(sessionId)}/permissions`,
    { capability, decision },
  );
  return response.data;
}
