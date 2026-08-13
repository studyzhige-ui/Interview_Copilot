import { beforeEach, describe, expect, it, vi } from 'vitest';

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('./client', () => ({ apiClient: { get, post } }));

import {
  authorizeGmailIntegration,
  getGmailIntegration,
  revokeGmailIntegration,
  testGmailIntegration,
} from './integrations';

describe('Gmail integration API', () => {
  beforeEach(() => { get.mockReset(); post.mockReset(); });

  it('uses only the concrete Gmail status and command endpoints', async () => {
    get.mockResolvedValue({ data: { provider: 'gmail', adapter_available: true, connection_required: true, account: null } });
    post
      .mockResolvedValueOnce({ data: { provider: 'gmail', authorization_url: 'https://accounts.google.com/auth', expires_in_seconds: 600 } })
      .mockResolvedValueOnce({ data: { provider: 'gmail', adapter_available: true, connection_required: false, account: {} } })
      .mockResolvedValueOnce({ data: { provider: 'gmail', adapter_available: true, connection_required: true, account: {} } });

    await getGmailIntegration();
    await authorizeGmailIntegration();
    await testGmailIntegration();
    await revokeGmailIntegration();

    expect(get).toHaveBeenCalledWith('/integrations/gmail');
    expect(post.mock.calls.map((call) => call[0])).toEqual([
      '/integrations/gmail/authorize',
      '/integrations/gmail/test',
      '/integrations/gmail/revoke',
    ]);
  });
});
