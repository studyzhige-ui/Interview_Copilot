# Edition architecture

Interview Copilot has one application core and two distribution policies.
Edition checks are enforced by the backend and exposed to the frontend through
`GET /api/v1/capabilities/edition`.

## Product boundary

The original interview-only boundary in this document has been superseded by
the confirmed full-cycle Career Copilot direction. The durable product and
architecture source of truth is
[`full-cycle-career-copilot.md`](./full-cycle-career-copilot.md). Edition policy
still controls deployment availability; it must not redefine the shared
product domain from the current set of implemented pages or tools.

## Policy matrix

| Surface | Cloud | Community |
|---|---|---|
| User answer-model keys and selection | Enabled | Enabled |
| Official LLM providers | Enabled | Enabled |
| Internal router and worker models | Operator managed | Deployment configurable |
| Custom provider endpoint and headers | Disabled | Enabled |
| User Skills | Enabled | Enabled |
| Remote Streamable HTTP MCP | Enabled | Enabled |
| Server-side stdio MCP | Disabled | Trusted operator opt-in |
| Embedding, reranker, ASR, diarization | Operator managed | Deployment configurable |
| Advanced model settings UI | Hidden | Visible |
| Direct `/rag/query` diagnostics | Hidden (404) | Enabled for developer use |

`APP_EDITION` is the only product-edition switch:

```env
APP_EDITION=cloud
APP_EDITION=community
```

Model provider settings remain independent. A Community deployment can use
remote APIs, and a Cloud operator can run managed models on its own servers.
Users never select the internal router/worker model or provide its credential.
Both internal roles currently use `deepseek/deepseek-v4-flash`.

The Community stdio exception means a trusted deployment operator may start a
process on that Community server. It is not a client-side local Agent, does not
expose an end user's computer, browser, files, or shell, and is not part of the
Cloud product target.

## Tool boundary

Edition policy is a deterministic deployment boundary. It can hard-deny a
transport or setting, but it does not choose a business action, group tools, or
create a capability-resolution layer.

The runtime follows the single Tool plane defined by
[`full-cycle-career-copilot.md`](./full-cycle-career-copilot.md): only concrete
ToolDefinitions with real handlers enter discovery, the model calls a concrete
Tool directly, and the Executor checks current connection, scope, and Policy at
the actual call. Turn-local catalogs and caches are implementation details;
they do not form another Tool plane or freeze facts that must be rechecked at
execution time. User Skills and MCP tools must not mutate the process-global
registry.

## Source boundaries

- `app/core/edition.py` owns the edition policy.
- API and service layers reject disallowed writes.
- Runtime factories ignore legacy values that are invalid for the active
  edition.
- The frontend consumes the public policy and does not duplicate edition rules.

Adding an edition-specific behavior should extend the policy object and enforce
it at the service/runtime boundary. Avoid scattered environment checks in route
handlers and React components.
