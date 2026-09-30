# Integration acceptance (2026-09-30)

Acceptance evidence applies to a named commit and execution environment. A
successful synthetic check does not establish real account delivery, installed
desktop behavior, model quality, or deployment readiness.

## Verified integration baseline

Remote `6e006491b623ba27ec9d652dbdc4829e215f104c`, tree
`3a9e26793f381387b129982379cb20285bc2229b`, integrates main and PR #2 and adds
Supabase identity with independent local unlock. Main remains unmerged.

- CI run `36738993976`: every job succeeded. Python 3.11 and 3.13 each ran
  2,423 passing backend tests, including actual PostgreSQL and local IPC
- Fresh PostgreSQL upgrade/check, published-main upgrade, historical PR2
  fingerprint/adoption with rollback, stable owners, and protected transcript
  history downgrade all passed
- Frontend: 348 tests, typecheck, lint, production build and contract generation
- Real HTTP/PostgreSQL browser campaign and deterministic interaction gate passed
- Realtime run `36738993886` passed separately
- Independent review rechecked account switching, both HTTP transports, verified
  recovery, immediate logout, async usage context, live authorization and unlock
  credential rotation

Three backend skips cover the external RAG corpus, real local-model retrieval,
and realtime loopback; the latter is exercised in the separate realtime job.
Python 3.11 reported a non-failing subprocess cleanup warning; 3.13 reported only
a dependency deprecation. No private recording or paid provider was used.

## Acceptance still required

| Area | Current evidence | Remaining acceptance |
| --- | --- | --- |
| Complete web interaction/visual journeys | Existing focused real-browser campaign | Expanded route, form, keyboard, narrow-screen, interruption and account-isolation campaign with screenshots |
| Hosted email/password Auth | Signup and confirmation enabled; exact four development callbacks saved; custom SMTP configured | User-authorized real test account, email receipt, confirmation, login, recovery, logout, and offline-unlock continuation |
| Existing Cloudflare preview | Bot reports failed build; no working preview URL | Obtain actual build logs and identify cause; a static Pages preview alone cannot implement the local FastAPI `/api/v1` service |
| Installed desktop | Existing Electron prototype only | Windows desktop and no Docker are selected; decide native versus WSL2 backend delivery, implement actual product loading/runtime lifecycle, installer and callback flow, then execute installed-app acceptance |

These outstanding areas must not be described as passed or ready to merge.
Hosted security settings, credentials, and password entry still follow their
separate approval/secure-entry requirements.

## Desktop boundary

`desktop/main.cjs` currently opens static prototypes under `career://pages/`.
Its smoke checks a throwaway HTTP page and browser view disposal. The two desktop
policy tests pass, but neither loads the production React app or FastAPI. There
is no package/installer script, dependency lockfile, real stack lifecycle or
Supabase native callback integration. The existing Compose stack keeps
PostgreSQL/pgvector, Redis, MinIO and workers and exposes the product on loopback.
The user selected Windows desktop without Docker. The existing Linux runtime
requires a decision between a managed WSL2 distribution and a substantial native
Windows port; WSL2 is not assumed approved. Celery lacks official Windows support,
and local inference explicitly relies on Linux peer credentials, flock and
process-death/cancellation primitives. An installer alone does not port them.

Any desktop implementation must:

1. Load the actual product and check the intended local runtime identity and
   readiness; reject an occupied/untrusted origin and show actionable errors
2. Preserve stable local data and credential locations; manage only processes
   it owns and keep historical migration/adoption safeguards
3. Keep Node disabled in renderers, context isolation/sandbox/web security
   enabled, navigation allowlisted, and privileged IPC restricted to the trusted
   app's main frame
4. Bind email callbacks to the originating PKCE context. The system browser and
   Electron do not share the verifier. An explicit bridge must validate exact
   callback shape, pending flow, expiry and replay state, then exchange the code
   with that verifier; it must never forward an arbitrary URL or log tokens
5. Exercise installation, restart, service outage/recovery, sign-in/email return,
   wrong-browser/expired links, logout/account switching and local unlock on the
   chosen platform. Development `:5173` callbacks are not installed-app evidence

References: [Electron security](https://www.electronjs.org/docs/latest/tutorial/security),
[Electron deep links](https://www.electronjs.org/docs/latest/tutorial/launch-app-from-url-in-another-app),
[Supabase PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow).
