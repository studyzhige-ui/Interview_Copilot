# Local runtime integration baseline (2026-09-30)

This integration joins published main `812bf76` with draft PR #2 `2803c798`.
It preserves PostgreSQL + pgvector, Redis, Celery, isolated workers, local data
and user-configured model providers. It is not a cloud business-data migration.

## Merge decisions

- Preserve main's active-user gate, durable SQL token revocation, atomic refresh
  consumption, loop-owned clients, durable cancellation, completion-after-commit,
  outbox lease fencing, and memory retention checks.
- Preserve PR #2's domain-module layout, bounded invitation recovery, usage
  accounting, pgvector and local inference/speech/document runtime.
- Generation-tagged event delivery is best-effort; SQL state is authoritative.
- Keep the existing PR #2 activity feed instead of rendering both branches'
  activity components. Include the reviewed chat deletion, review navigation and
  modal accessibility patch.

## Migration history and existing data

Published main migrations through `0052` are unchanged. PR #2-only changes now
follow them as `0060`–`0072`; its schema alignment already exists in main `0052`.
`0060` restores inert nullable compatibility metadata, without recreating values
already retired by published main. No owner IDs or content are reassigned.

Normal main installations: back up the database and files, stop all API/worker
writers, then run `alembic upgrade head` with the intended local DATABASE_URL.

Draft PR #2 installations have conflicting numeric revision identities. Ordinary
Alembic refuses that baseline. For exact PR #2 `0059`, the supported adoption is:

1. Retain a tested backup of the database and files; stop every API/worker process
2. `PYTHONPATH=backend python scripts/upgrade_legacy_pr2.py` performs read-only
   revision and schema-fingerprint validation
3. Review the result, then run the same command with `--apply --backup-confirmed
   --writers-stopped`; security columns, token invalidation and migration identity
   change in one transaction, retaining data and local owner IDs
4. Run `alembic upgrade head` and `alembic check`, then restart processes

Earlier revisions or a column/type/nullability fingerprint mismatch fail closed.
This fingerprint is not a complete constraint/index audit; `alembic check` remains
required after adoption. Finish the original
PR #2 migration chain using its original checkout first, or review a dedicated
migration; never manually stamp a database to bypass a mismatch. A schema match
is not a backup verification. Previous local sessions must sign in again after
PR #2's Redis-to-SQL revocation transition.

## Verification boundary

Frontend typecheck, lint, 319 tests, and production build passed. Ruff and shared
Pydantic contract checks passed. Backend baseline regression, focused seam tests
and PostgreSQL-required tests are retained. Disposable PostgreSQL and pgvector
binaries could be prepared here, but AF_UNIX socket creation is prohibited even
on an elevated retry, so actual PostgreSQL, local IPC and browser gates remain
required in a suitable environment/CI. They are not claimed as passed.

Historical PR #2 migration fixtures are migration source only from `2803c798`;
no private database, audio, credentials, model weights or paid calls are included.
