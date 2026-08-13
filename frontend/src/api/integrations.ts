import { apiClient } from './client';
import type {
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
