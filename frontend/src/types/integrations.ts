export type GmailAccountStatus = 'active' | 'invalid' | 'revoked';

export interface GmailIntegrationAccount {
  id: string;
  provider: 'gmail';
  account_hint: string;
  scopes: string[];
  status: GmailAccountStatus;
  last_checked_at: string | null;
  last_error_code: string | null;
  history_cursor_updated_at: string | null;
  last_observation_sync_at: string | null;
  last_observation_sync_error_code: string | null;
  revoked_at: string | null;
}

export interface GmailIntegrationStatus {
  provider: 'gmail';
  adapter_available: boolean;
  connection_required: boolean;
  account: GmailIntegrationAccount | null;
}

export interface GmailOAuthAuthorization {
  provider: 'gmail';
  authorization_url: string;
  expires_in_seconds: number;
}
