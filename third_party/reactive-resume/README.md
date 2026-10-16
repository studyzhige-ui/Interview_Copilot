# Reactive Resume attribution

Source: https://github.com/reactive-resume/reactive-resume
Pinned revision: 19e0518eb5ea1b2c84d785bc5ea2b6d6c9d7b043 (6.0.3).
License: MIT; full notice in LICENSE.

`frontend/src/pages/career/transfer.ts` adapts the CSV parser and iCalendar
serializer from `apps/web/src/features/applications/csv.ts` and `ics.ts`.
Local changes: Chinese field mappings, strict unclosed-quote validation,
UTF-8 byte-aware ICS folding, application-specific identifiers, and formula
guarding. Workspace layout, document drafts and next-step presentation are
informed by the application and resume features; backend ownership, events,
document schema, validation and UI components are implemented for this project.
