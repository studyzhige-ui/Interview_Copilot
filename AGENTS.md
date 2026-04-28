# Encoding Rules

- Treat source code, Markdown, JSON, YAML, SQL, environment files, and plain text files as UTF-8.
- Never rewrite Chinese text using GBK, CP936, ANSI, or the Windows system default encoding.
- When reading files from PowerShell, use explicit UTF-8 encoding where possible.
- When writing files, preserve the original encoding if known; otherwise write UTF-8 without BOM.
- Before replacing Chinese text, verify it displays correctly and is not mojibake.
- Prefer PowerShell 7 for local Codex work on Windows. Windows PowerShell 5.1 can default to legacy code pages such as GB2312/CP936.
