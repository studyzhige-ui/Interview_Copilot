import { apiClient } from './client';
import type {
  ExternalPluginOAuthAuthorization,
  ExternalPluginProvider,
  ExternalPluginStatus,
  GmailIntegrationStatus,
  GmailOAuthAuthorization,
} from '@/types/integrations';

export async function getGmailIntegration(): Promise<GmailIntegrationStatus> {
  return (await apiClient.get('/integrations/gmail')).data;
}

export async function authorizeGmailIntegration(): Promise<GmailOAuthAuthorization> {
  return (await apiClient.post('/integrations/gmail/authorize')).data;
}

export async function testGmailIntegration(): Promise<GmailIntegrationStatus> {
  return (await apiClient.post('/integrations/gmail/test')).data;
}

export async function revokeGmailIntegration(): Promise<GmailIntegrationStatus> {
  return (await apiClient.post('/integrations/gmail/revoke')).data;
}

export async function getExternalPluginStatus(
  provider: ExternalPluginProvider,
): Promise<ExternalPluginStatus> {
  return (await apiClient.get(`/integrations/plugins/${provider}`)).data;
}

export async function authorizeExternalPlugin(
  provider: ExternalPluginProvider,
): Promise<ExternalPluginOAuthAuthorization> {
  return (await apiClient.post(`/integrations/plugins/${provider}/authorize`)).data;
}

export async function testExternalPlugin(
  provider: ExternalPluginProvider,
): Promise<ExternalPluginStatus> {
  return (await apiClient.post(`/integrations/plugins/${provider}/test`)).data;
}

export async function revokeExternalPlugin(
  provider: ExternalPluginProvider,
): Promise<ExternalPluginStatus> {
  return (await apiClient.post(`/integrations/plugins/${provider}/revoke`)).data;
}
