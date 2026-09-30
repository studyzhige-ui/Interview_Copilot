const ACCESS = 'access_token';
const REFRESH = 'refresh_token';
export const SESSION_SYNC_KEY = 'interview_copilot_auth_session';
const LOCKED = 'interview_copilot_auth_locked';
const AUTHORITY_EPOCH = 'interview_copilot_authority_epoch';

/** Unverified routing identity only; the backend still verifies every JWT. */
export function tokenAuthority(token: string | null): string | null {
  if (!token) return null;
  const claims = decodeJwtPayload<Record<string, unknown>>(token);
  if (typeof claims?.sub !== 'string') return `opaque:${token}`;
  return JSON.stringify([claims.iss ?? 'local', claims.aud ?? null, claims.sub,
    claims.type ?? 'cloud', claims.session_id ?? null, claims.token_version ?? null,
    claims.credential_version ?? null]);
}

export interface AuthoritySnapshot { epoch: string | null; identity: string | null }

export const tokenStore = {
  snapshot: (): AuthoritySnapshot => ({ epoch: localStorage.getItem(AUTHORITY_EPOCH), identity: tokenAuthority(localStorage.getItem(ACCESS)) }),
  matches: (snapshot: AuthoritySnapshot) => snapshot.epoch === localStorage.getItem(AUTHORITY_EPOCH)
    && snapshot.identity === tokenAuthority(localStorage.getItem(ACCESS)),
  isLocked: () => localStorage.getItem(LOCKED) === '1',
  getAccess: () => localStorage.getItem(ACCESS),
  getRefresh: () => localStorage.getItem(REFRESH),
  set: (access: string, refresh: string) => {
    if (tokenAuthority(localStorage.getItem(ACCESS)) !== tokenAuthority(access) || !localStorage.getItem(AUTHORITY_EPOCH)) {
      localStorage.setItem(AUTHORITY_EPOCH, crypto.randomUUID());
    }
    localStorage.removeItem(LOCKED);
    localStorage.setItem(ACCESS, access);
    localStorage.setItem(REFRESH, refresh);
    localStorage.setItem(SESSION_SYNC_KEY, JSON.stringify({ access, refresh }));
  },
  clear: () => {
    localStorage.setItem(AUTHORITY_EPOCH, crypto.randomUUID());
    localStorage.setItem(LOCKED, '1');
    localStorage.removeItem(ACCESS);
    localStorage.removeItem(REFRESH);
    localStorage.removeItem(SESSION_SYNC_KEY);
  },
};

export function decodeJwtPayload<T = Record<string, unknown>>(token: string): T | null {
  try {
    const part = token.split('.')[1];
    if (!part) return null;
    const json = atob(part.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(json) as T;
  } catch {
    return null;
  }
}
