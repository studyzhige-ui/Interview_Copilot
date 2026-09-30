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
| Installed desktop | New Windows Electron launcher and package sources; focused boundary review and unpacked source-integrity checks | Run staged Windows installer/OS dispatch and Linux Docker jobs, then actual Windows Docker Desktop, live email return and microphone acceptance |

These outstanding areas must not be described as passed or ready to merge.
Hosted security settings, credentials, and password entry still follow their
separate approval/secure-entry requirements.

## Desktop boundary

The original `desktop/main.cjs` opened static prototypes under `career://pages/`.
That prototype remains available through `npm run prototype`; its smoke did not
load the production React app or FastAPI. The new launcher, pinned dependency
lockfile, NSIS configuration, owned stack lifecycle and pending-flow native bridge
now load the real product after readiness checks. The existing Compose stack keeps
PostgreSQL/pgvector, Redis, MinIO and workers and exposes the product on loopback.
The user selected Windows desktop and then accepted Docker Desktop for the first
version. The Linux runtime remains inside Docker; the Windows shell must not try
to run Celery or Linux peer-credential/process primitives natively. Docker
installation and Windows feature changes remain user-controlled actions. A draft
launcher and packaging implementation is under acceptance; it has not been
installed or exercised with Docker Desktop on a Windows host.

At the independently reviewed local desktop snapshot `41a9ef8`:

- 362 frontend tests, typecheck, lint and production build passed
- 17 desktop boundary tests and the independent callback, permission, environment
  isolation and partial-start/old-bundle stop probes passed
- A Windows unpacked fixture contains matching application files and all 876
  hashed runtime sources; it uses synthetic public Auth configuration and cannot
  be used for real login
- A Linux NSIS attempt required Wine and was stopped; its partial installer is
  not an acceptance artifact. The staged Windows CI job builds the actual NSIS
  fixture, inspects it, then tests installed OS dispatch and cleans up
- The hosted GoTrue `v2.197.0` health response and matching official source support
  exact native allowlist entries with fragment state; real email delivery and
  browser-to-Windows preservation are not yet observed

The staged Windows fixture and Linux Docker acceptance campaigns are unrun until
publication is approved and exact-head CI finishes. The OS probe uses synthetic
pending metadata and proves no Supabase account or password operation. The Linux
campaign tests real service readiness, Celery control traffic, database/object/file
retention and unrelated-container isolation, with synthetic data only. Windows
Docker Desktop startup, DPAPI across restart, microphone and user mail flows remain
separate installed-host requirements.

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
