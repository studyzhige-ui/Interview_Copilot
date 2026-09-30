# Windows desktop acceptance build

This is a Windows x64 Electron launcher for the existing local Docker runtime.
It keeps PostgreSQL/pgvector, Redis, Celery workers, MinIO, local files and BYOK.
Supabase handles identity only. The prior static-page prototype is retained as
`npm run prototype` and is not the production workspace.

## End-user runtime contract

The user installs and starts Docker Desktop themselves, accepts any applicable
Docker terms, and selects Linux containers. The launcher links to the official
[Windows installation instructions](https://docs.docker.com/desktop/setup/install/windows-install/);
it does not install Docker, enable Windows features, accept terms or expose an
unauthenticated TCP Docker daemon.

The installed app carries the build sources needed by the canonical Compose
stack. Users do not need a repository checkout, Git, Python or Node. First start
requires network access to fetch the pinned base images and dependencies and
build the app images; it is not a fully offline installer. Large local model
weights are not included or downloaded automatically.

The launcher always targets the local Windows Docker named pipe, ignores an
ambient remote Docker context, and restricts Compose interpolation to its own
configuration. It labels its containers and uses an installation-specific project
and image names. Database and Redis ports are not exposed to the host; product
and object URLs are bound to loopback only. Start rejects a port or ownership
collision. Stop operates only on verified owned container IDs and never deletes
volumes. It remains available after partial startup or a version mismatch.

Application data and protected runtime settings live under Electron's per-user
`userData/local-workspace`; Docker database/object volumes retain the project
identity. Windows protects the runtime settings using Electron safeStorage
(DPAPI). This does not encrypt PostgreSQL/object volumes, recordings, or all
browser session storage. Preserve both the data and original protected settings;
copying the encrypted settings to a different Windows user/machine is not a
supported migration method. The app refuses to silently replace unreadable keys.

This initial launcher refuses automatic runtime-bundle upgrades for an existing
workspace. A version change needs a separately verified backup/migration path;
it does not stamp or adopt historical PR #2 data automatically. Existing external
Compose installations are never adopted implicitly.

## Build and inspect

Use Node and the pinned `desktop/package-lock.json` in a build environment:

```sh
npm ci --prefix desktop
npm test --prefix desktop
```

The release operator supplies only the approved public Supabase project origin
and publishable key through `IC_SUPABASE_URL` and
`IC_SUPABASE_PUBLISHABLE_KEY`. Never use service-role/secret keys. The staging
script rejects a non-HTTPS origin or non-publishable key, excludes `.env`, user
data, caches and dependencies, and records hashes of the bundled runtime sources.
Keep `IC_SUPABASE_EMAIL_DELIVERY=team_only` until real delivery is verified.

```sh
npm run package:win --prefix desktop
```

This creates a per-user NSIS installer and performs no publication. Signing is
not configured; unsigned acceptance artifacts are not signed release evidence.
A package built with `https://fixture.supabase.co` and a synthetic publishable key
is a packaging fixture, unsuitable for real login and not a release artifact.
The packaged app registers its native return scheme on first launch. Uninstall
removes that per-user association only if it still names this exact installed
executable; a handler subsequently assigned to another application is preserved.

## Native account return and acceptance gates

The OS callback uses only the `interview-copilot` scheme, `auth` host and
`/confirm` or `/recovery` path, with a bounded per-flow `#state=UUID` fragment. The current Supabase Auth
implementation excludes fragments from redirect allowlist matching and preserves
them on a successful PKCE return, so the proposed hosted entries remain exactly
`interview-copilot://auth/confirm` and `interview-copilot://auth/recovery`. No host,
path or query wildcard is required. Error returns without state are notices only
and do not consume an active flow. The hosted project's health endpoint reports
GoTrue `v2.197.0`; the matching official source confirms fragment stripping in
[allowlist matching](https://github.com/supabase/auth/blob/v2.197.0/internal/utilities/request.go)
and preservation on [successful PKCE redirects](https://github.com/supabase/auth/blob/v2.197.0/internal/api/verify.go).
Real-mail and installed OS transport verification are still required before
treating this flow as accepted. The native bridge
only routes a one-time authorization code to the initiating Electron partition.
The actual pinned Supabase SDK exchanges it with that partition's PKCE verifier;
only a verified SDK recovery event enables password submission. An expired,
replaced, cancelled or replayed intent must not consume a newer flow. No callback
URL is logged and no access/refresh token is accepted through it.

Hosted redirect configuration is a separate, explicitly approved action. Native
registration, closed-app/warm-app return, real email delivery, microphone consent,
Docker lifecycle and screenshots must be exercised on an actual Windows host.
Unit tests, an unpacked build, a Linux browser campaign and a source review do not
pass those gates. See the repository acceptance ledger for exact evidence.

The staged desktop CI separates three kinds of evidence. The Windows job builds
and inspects the NSIS fixture, then installs it on a disposable hosted runner and
uses OS ShellExecute with synthetic pending metadata to check closed/warm launch,
single-instance delivery, fragment preservation, stale/duplicate/expired rejection,
and uninstall cleanup. It never calls Supabase or starts Docker Desktop. A Linux
Docker job starts the real bundled services, pings every Celery lane, writes
synthetic PostgreSQL/object/file fixtures, and verifies retention and ownership on
stop/restart. Its temporary settings codec is explicitly a test fixture; it does
not prove Windows DPAPI. These jobs must run successfully on the exact PR head
before their checks can be claimed as passed. Neither substitutes for live email,
Windows Docker Desktop lifecycle, microphone, or a signed release.
