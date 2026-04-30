# Codex Preferences

## Shell

- On Windows, prefer PowerShell 7 (`pwsh.exe`) for all command execution.
- If the surrounding tool starts in Windows PowerShell 5.1, invoke commands through `pwsh -NoLogo -NoProfile -Command ...` when practical.
- Avoid using Windows PowerShell 5.1 for reading or writing files that may contain Chinese or other non-ASCII text.

## Encoding

- Default to UTF-8 without BOM for source code, Markdown, JSON, YAML, SQL, environment files, and plain text files.
- Never rewrite Chinese text using GBK, CP936, ANSI, OEM, or the Windows system default encoding.
- When reading files from PowerShell, specify UTF-8 explicitly when possible.
- When writing files from PowerShell 7, use `-Encoding utf8NoBOM` or `[System.Text.UTF8Encoding]::new($false)`.
- Before replacing Chinese text, verify it displays correctly and is not mojibake.
