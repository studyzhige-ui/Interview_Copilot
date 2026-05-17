/**
 * Frontend Sentry initialization.
 *
 * Reads its config from Vite env vars at build time so the same code
 * runs in dev (no DSN → no-op) and prod (DSN set → events flow).
 *
 *   VITE_SENTRY_DSN              — empty string disables Sentry entirely
 *   VITE_SENTRY_ENVIRONMENT      — "local" / "staging" / "prod"
 *   VITE_SENTRY_TRACES_SAMPLE    — fraction of transactions to trace, 0–1
 *   VITE_SENTRY_RELEASE          — usually the git SHA of the build
 *
 * The dynamic import keeps `@sentry/react` out of the main chunk when DSN
 * is empty (saves ~70KB gzip in dev / OSS builds).
 */
export async function initSentry(): Promise<void> {
  const dsn = (import.meta.env.VITE_SENTRY_DSN as string | undefined)?.trim();
  if (!dsn) return;

  const Sentry = await import('@sentry/react');
  Sentry.init({
    dsn,
    environment: (import.meta.env.VITE_SENTRY_ENVIRONMENT as string) || 'unknown',
    release: (import.meta.env.VITE_SENTRY_RELEASE as string) || undefined,
    tracesSampleRate: Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE ?? '0.1'),
    // Avoid leaking the JWT in network breadcrumbs.
    beforeBreadcrumb(crumb) {
      if (crumb.category === 'fetch' || crumb.category === 'xhr') {
        const headers = (crumb.data as { request_headers?: Record<string, string> } | undefined)
          ?.request_headers;
        if (headers && headers['Authorization']) {
          headers['Authorization'] = '[redacted]';
        }
      }
      return crumb;
    },
  });
}
