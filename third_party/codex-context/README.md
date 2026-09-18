# Codex context migration source baseline

Upstream: https://github.com/openai/codex

Pinned revision: `83dc7d11e873f43533dc898d50fae71cf4d55dc5`.

- `prompt.md`: `codex-rs/prompts/templates/compact/prompt.md`
- `summary_prefix.md`: `codex-rs/prompts/templates/compact/summary_prefix.md`
- `LICENSE` and `NOTICE`: upstream root files, retained with the source copies.

Prompt wording is unmodified. Byte-identical copies, including LICENSE and NOTICE, live in `backend/app/conversation/context_templates` and are loaded by the production context window module. Tests verify both copies. The old worker/JSON summarizer has been removed.

Runtime source mapping, product adaptations and boundaries: `docs/implementation/codex-context-source-migration.md`.
