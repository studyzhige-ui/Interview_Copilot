# Transcript correction workbench and source-bound playback

## Implemented in this logical batch

The existing transcript correction application remains the only write owner. The
review page now exposes paged immutable words, confirmed versus suggested roles,
explicit word/speaker edits, reason capture, history, receipt reconciliation, and
an explicit re-extract/reanalyze action. Saving a correction does not call a model.
The page retains the selected review tab across the detail refresh after a save.

Each attempted save freezes the expected transcript ID, a UUID, and the command.
A lost response keeps that command unchanged. Reconciliation performs only GET.
A missing receipt is not proof of non-execution; only a separate explicit user
retry resends the exact original command. Conflicts are not silently rebased.
Only the UUID is retained in sessionStorage, not transcript text. After a page
reload the retained UUID enables GET reconciliation, not an automatic write.
Active drafts cannot be replaced by a background transcript-query refresh.

Historical versions are read-only. A source correction immediately invalidates
visible old QA, scores and reports, while the existing backend invalidation and
publication/version fences remain authoritative. The browser must explicitly
request a new analysis; neither receipt retrieval nor history browsing does so.

## Playback boundary

A new authenticated, rate-limited POST accepts a transcript ID and first/last
word IDs, never a caller-supplied source path, URL, timestamp or model choice.
The application checks record/transcript/asset ownership, source reference,
asset version, checksum, deletion, validation and upload state. It permits at
most 200 consecutive words and 30 seconds. Missing times are not invented.

Database read sessions, including the shared authentication read session, are
closed before storage or FFmpeg work. A second fresh
read rejects ownership, deletion or source-reference changes during that work.
The source is read through the existing immutable snapshot contract and its
complete SHA-256 is verified, including sources using an older asset-only token.
Local files and objects in the configured S3 bucket are supported. Object reads
use fixed-size blocks, size checks, short network timeouts, a finite deadline,
and cleanup on errors. There is no public source URL or cloud model fallback.

The existing PCMStream supplies bounded mono 16 kHz PCM blocks. Only the selected
sample interval is accumulated, then returned as a WAV clip after source checks.
FFmpeg ownership/cleanup is retained after early stop or loss of the HTTP waiter.
The browser verifies the response transcript ID and source hash, then owns and
revokes the bounded blob URL. Selection changes/navigation cancel requests,
pause audio and suppress late results. Audio is never autoplayed.

This is accurate sample selection on a source-verified offline decoder timeline,
not a claim of perfect ASR alignment, instantaneous long-file seeking or realtime
transport. Corrected word times can be estimated and are labelled as such. Each
clip currently verifies the full compressed source and decodes its prefix: this
is a conservative correctness baseline, not a measured long-recording latency
optimization. Storage availability and hardware performance remain unverified.

## Shared contracts and verification boundary

Pydantic correction/page/history/playback models are included in the existing
OpenAPI exporter; the JSON snapshot has passed the official Python --check.
The new TypeScript schema entries were provisionally rendered from that JSON in
this offline workspace and pass TypeScript compilation. The pinned
openapi-typescript 7.13.0 tool was NOT available in the restored dependency bundle;
offline npm installation failed. Before publication, run the repository's normal
locked code generator and --check. Do not disable the gate or claim it passed.
This outstanding gate means the patch is not yet a fully verified remote release.

Validation in the recovered source workspace:
- 373 backend tests passed, zero skipped, across architecture, interview, voice,
  broker, authenticated playback HTTP and process cleanup campaigns.
- All 70 frontend test files / 250 tests passed in four disjoint Vitest shards;
  every shard exited successfully. No tests were deleted or disabled. The final
  timestamp/receipt identity refinements also passed all 19 affected UI tests.
- TypeScript, ESLint, production Vite build, Ruff format/check, compileall,
  Python shared snapshot --check and git diff --check passed.
- Full fixture setup-plan completed; its 3 skips are a dry-run result, NOT a
  full backend test-run result.
- One existing Starlette/AnyIO deprecation warning remains.

The local source artifact is 913932605343d9083e3ec651bfc78c39be4c40e3. A remote
compare through abca9f0bf8f524ee78905819a30daac4f2dd0432 confirmed that every
pre-existing file touched by these patches is unchanged across that interval.
The intervening Qwen long-form files are not in this recovered workspace, so
these results must not be described as a full current-HEAD regression. Apply to
the actual branch, regenerate TypeScript and run the full CI before publication.

No new PostgreSQL/browser-device campaign, real model inference, paid DeepSeek
call, model download, production migration or main merge was performed.
