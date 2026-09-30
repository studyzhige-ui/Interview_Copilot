# Unified Auth with local-first product data

## Scope

Supabase Auth supplies registration, email confirmation, password recovery and
cloud sessions. PostgreSQL + pgvector, Redis, Celery, worker processes, files,
recordings, user model credentials and all business ownership stay on the
existing installation. No business tables, Storage buckets, RLS policies, Edge
Functions, service-role credentials or synchronization service are created in
Supabase. Signing in on another device does not copy local data or run its jobs.

`AUTH_PROVIDER=local` preserves the existing self-managed login protocol until
this installation is explicitly configured. To use unified Auth, set:

- `AUTH_PROVIDER=supabase`
- `SUPABASE_URL` to the existing project's HTTPS origin
- `SUPABASE_PUBLISHABLE_KEY` to an existing `sb_publishable_...` key
- A unique, stable local `SECRET_KEY` (at least 32 characters) for existing local
  encryption and the independent unlock capability; back it up securely with the
  local installation, never commit it or bundle it in frontend assets

The frontend obtains only the public URL and publishable key from `/auth/config`.
Do not use a service-role key, `sb_secret_...`, or the Supabase JWT signing secret
in a downloadable application. The pinned browser SDK is 2.117.2.

## Identity and migration

`external_identities` maps the verified `(issuer, Supabase UUID)` to the existing
integer `users.id`. All old business `user_id` values keep their meaning.
A matching email never grants access to an existing local profile.

To associate existing data, choose “关联已有本地账号的资料”, sign in to the cloud
account and supply the old local username/password. The API requires an online
confirmed cloud user and password authentication within five minutes, plus the
existing local password. It binds the UUID without copying password hashes or
changing owner IDs. Old local-login tokens are invalidated at this transition.
A profile already bound to another UUID cannot be reassigned by this flow.

Fresh accounts get a distinct local owner after online verification. Cloud email
changes do not reassign ownership. Existing profile/contact fields remain local.
Migration `0073` adds mapping and local-credential tables only. Follow the separate
integration migration guide first if this is an old PR #2 database.

## Offline-first access

After online onboarding, the user can explicitly set a separate local-unlock
password. An Argon2 hash, durable failed-attempt counter and lockout remain in
local PostgreSQL. A successful unlock issues an eight-hour locally signed token
with its own issuer, audience and `local_business` scope; it cannot be used as a
Supabase identity or for identity binding/unlock enrollment. There is no default
password and no acceptance of expired cloud JWTs.

The local token reuses the same stable owner, `is_active`, token-version and SQL
revocation checks. Rotating the unlock credential invalidates old local tokens.
It permits existing owner-scoped local reads, edits, processing and task work.
Existing BYOK requests retain their provider, credentials and permission checks;
network-dependent providers naturally still require connectivity. Signing out
clears/revokes sessions without deleting local data.

This is application access control, not disk/database/file encryption. A machine
administrator or someone with direct database/file access is outside this unlock
boundary. A cloud account revocation cannot instantly reach an offline device.
Local unlock remains valid under local policy until locally revoked/rotated or
expired. Supabase asymmetric access JWTs are cryptographically verified against
bounded-cache JWKS; they are not advertised as instantly remotely revocable.
Legacy HS256 projects verify with the Auth server rather than distributing its
signing secret. Binding and unlock enrollment also recheck the cloud user online.

## Email and callback setup

Keep email/password and email confirmation enabled. The existing project was
observed with these settings already enabled; code changes do not alter them.
The SDK uses PKCE and exact same-origin callbacks. For the current Vite development
server, verify only the actual origins used by the installation:

- `http://localhost:5173/auth`
- `http://localhost:5173/auth?flow=recovery`
- `http://127.0.0.1:5173/auth`
- `http://127.0.0.1:5173/auth?flow=recovery`

Add only the necessary exact URLs after reviewing the project's existing
allowlist. Production origins and desktop callback/deep-link handling must be
validated against the real packaged application. The current desktop shell is
still a prototype; these development callbacks do not make it release-ready.
Email recovery links must be opened in the browser that began the PKCE flow.

The default Supabase SMTP service sends only to project organization team-member
addresses and is not intended for production registration. Verify existing SMTP;
public registration needs an authorized delivery setup.
`SUPABASE_EMAIL_DELIVERY=team_only` displays the current testing limitation in
the Auth screen. Set it to `custom_smtp` only after delivery is actually verified;
this display setting does not configure or bypass the cloud email service. Do not disable email
confirmation to work around email delivery. This implementation creates no SMTP
account, credential, project key, paid service, deployment or hosted setting.

## Verification and remaining gates

Synthetic tests cover valid/forged/wrong-project/expired/anonymous/service tokens,
JWKS outages, symmetric-key remote verification, stable mapping, failed email
matching, existing-owner linking, account isolation, durable revocation, local
unlock without network, rotation, lockout, and recent password proof. Frontend
cases cover signup confirmation, recovery, old-profile linking, duplicate clicks,
late login after logout, local unlock and account-switch cache isolation.

Actual cloud email delivery, real signup/confirmation/recovery, callback allowlist,
real PostgreSQL upgrades from both histories, IPC and packaged desktop/browser
flows remain deployment gates. No real passwords, accounts, private audio or paid
model calls were used during synthetic validation. See the integration guide for
the current execution environment's socket restriction and CI requirements.

Official references:
- https://supabase.com/docs/guides/auth/signing-keys
- https://supabase.com/docs/guides/auth/jwt-fields
- https://supabase.com/docs/reference/javascript/auth-signup
- https://supabase.com/docs/reference/javascript/auth-resetpasswordforemail
- https://supabase.com/docs/guides/auth/auth-smtp
