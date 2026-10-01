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
| Complete web interaction/visual journeys | Seven real HTTP/PostgreSQL cases and 70 desktop/mobile screenshots passed and were visually reviewed on `77f4eb8e` | New storage/avatar, expired-audio renewal and lower plugin content cases on the final storage head |
| Hosted email/password Auth | Signup and confirmation enabled; four development and two exact native callbacks saved; custom SMTP configured | User-authorized real test account, email receipt, confirmation, login, recovery, logout, and offline-unlock continuation |
| Existing Cloudflare preview | Bot reports failed build; no working preview URL | Obtain actual build logs and identify cause; a static Pages preview alone cannot implement the local FastAPI `/api/v1` service |
| Installed desktop | Full NSIS installation and synthetic Windows OS dispatch passed on `a55a6017` | Repeat exact-head packaging; real local-storage Docker campaign, then actual Windows Docker Desktop, live email return and microphone acceptance |

These outstanding areas must not be described as passed or ready to merge.
Hosted security settings, credentials, and password entry still follow their
separate approval/secure-entry requirements.

## Storage and installed-Windows follow-up (2026-10-01)

Windows job `110157469470` on `a55a6017` completed a full NSIS build, integrity
inspection, actual per-user installation/first-launch URI registration, cold and
warm OS dispatch, single-instance routing, stale/duplicate/expired callback
rejection, restart and uninstall cleanup. Its synthetic pending metadata proves
OS delivery only; live Supabase/PKCE, mail, microphone and Windows Docker Desktop
still require their own evidence. The fixture's public Auth configuration is
synthetic and cannot serve as a live-account release.

The same acceptance campaign found the historical MinIO images unavailable from
Docker Hub and the selected server tag unauthorized on the vendor Quay registry.
Vendor advisories also affect the selected community release; a mirror change
does not resolve that security boundary. The user approved default private local
filesystem storage with optional explicitly configured S3. This implementation
keeps old URI dispatch and data intact and adds bounded immutable transfer,
authenticated/capability reads and media ranges, per-owner usage, free-space
guarding, and initial file-directory selection. Existing workspace moves and
actual old-data migration remain separate operations.

The coherent storage batch must run the restored real Docker lifecycle/retention
campaign, four PostgreSQL ordering tests, the browser upload/avatar/download and
usage flow, and the optional S3 HTTP fixture. Local skipped service tests are not
counted as passed. The S3 fixture uses the official SeaweedFS 4.48 linux/amd64
descriptor `sha256:aba492e2a4e4c90bff795745e8e660affa1f09e7650f5981bd7bccd1a06cd931`,
verified against registry bytes; it is disposable test infrastructure only.

## Desktop boundary

The original `desktop/main.cjs` opened static prototypes under `career://pages/`.
That prototype remains available through `npm run prototype`; its smoke did not
load the production React app or FastAPI. The new launcher, pinned dependency
lockfile, NSIS configuration, owned stack lifecycle and pending-flow native bridge
now load the real product after readiness checks. The existing Compose stack keeps
PostgreSQL/pgvector, Redis and workers and exposes the product on loopback.
Private filesystem storage is now the default; explicitly configured S3 is optional.
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

Publication is approved; each changed source tree still requires its own CI result.
The successful Windows OS probe above uses synthetic pending metadata and proves
no Supabase account or password operation. The restored Linux campaign tests real
service readiness, Celery control traffic, database/private-file retention,
authenticated upload/download/ranges, capability-log suppression and unrelated
container isolation, with synthetic data only. Windows Docker Desktop startup,
DPAPI across restart, microphone and user mail flows remain separate installed-host
requirements. The new directory tests inject partial writes and ENOSPC and prove
safe retry; they do not simulate a power loss or establish crash recovery.

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
