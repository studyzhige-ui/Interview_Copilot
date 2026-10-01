# HTTP database dependency lifetime

All application `Depends(get_db, scope="function")` declarations use the same
FastAPI cache key. Authentication and its handler therefore share one SQLAlchemy
session. Do not mix request and function scopes: FastAPI creates separate cached
sessions, so an authenticated `User` passed to a profile mutation can be attached
to a different session and fail at `db.add(user)`.

The central contract is documented on `app.db.database.get_db`; an AST regression
checks every application declaration. Token verification and async caller-context
usage attribution are unchanged. A dependency's session is closed after handler
execution/response serialization and **before** streaming response consumption.

Removing auth's existing function scope was rejected: it would hold authentication
transactions through long SSE responses and would still differ from the already
function-scoped chat stream. Detaching or blindly merging the authenticated ORM
row was also unnecessary. The fix is consistent dependency lifetime, not weaker
authentication or ad-hoc mutation handling.

## Complete streaming inventory

The application contains four `StreamingResponse` producers:

| Producer | After the response begins |
| --- | --- |
| `api/file_assets.py::_stream_asset` | Reads provider bytes using a captured URI string. MIME, filename, size, and ownership are resolved before returning; no ORM attribute/session access in the body generator |
| `api/interviews/mock.py::synthesize_speech` | Returns already-produced audio bytes; explicitly closes the shared authentication session before synthesis |
| `api/interviews/records.py::interview_record_events_stream` | Polls dictionary snapshots through `record_admin.poll_record_snapshot`, which owns/closes a separate short-lived session per poll; generator captures only identifiers and counters |
| `api/chat/streaming.py::stream_chat_turn_events` | Already function-scoped. Reads Redis delivery hints and separately owned short-lived SQL status/interaction snapshots; generator captures cursor/turn identifiers, never its admission ORM row |

There are no `FileResponse`, `EventSourceResponse`, or WebSocket routes in
`backend/app`. Realtime signaling endpoints are ordinary HTTP handlers; their
explicit pre-initialization `db.close()` now closes the shared auth session too.
The other yielding application helpers are `api.command_errors` and
`identity.application.user_api_key_service._session`, ordinary context managers,
not nested FastAPI yielding dependencies. There are no request-scoped yielding
parents requiring a longer-lived child database dependency.

## Verification

`test_auth_session_scope.py` builds a file-backed SQL database and uses the real
ASGI `get_current_user` and `get_db` graph, with no overrides for either dependency.
It exercises both legacy access JWTs and real HTTP local-unlock tokens under the
Supabase auth mode, using only synthetic local identities and no cloud call.
It verifies avatar/profile mutation, one shared session, closure before download
bytes/SSE polling/TTS work, persisted JTI revocation, owner token-version changes,
disabled-owner rejection, and caller-context usage attribution.
