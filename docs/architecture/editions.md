# Edition architecture

Interview Copilot has one application core and two distribution policies.
Edition checks are enforced by the backend and exposed to the frontend through
`GET /api/v1/capabilities/edition`.

## Policy matrix

| Surface | Cloud | Community |
|---|---|---|
| User LLM keys and model selection | Enabled | Enabled |
| Official LLM providers | Enabled | Enabled |
| Custom provider endpoint and headers | Disabled | Enabled |
| User Skills | Enabled | Enabled |
| Remote Streamable HTTP MCP | Enabled | Enabled |
| Local stdio MCP | Disabled | Operator opt-in |
| Embedding, reranker, ASR, diarization | Operator managed | Deployment configurable |
| Advanced model settings UI | Hidden | Visible |

`APP_EDITION` is the only product-edition switch:

```env
APP_EDITION=cloud
APP_EDITION=community
```

Model provider settings remain independent. A Community deployment can use
remote APIs, and a Cloud operator can run managed models on its own servers.

## Capability resolution

The effective tools for a turn are the intersection of:

1. tools implemented by the application;
2. edition policy;
3. deployment availability;
4. user enablement;
5. conversation permissions;
6. the immutable turn snapshot.

User Skills and MCP tools never mutate the process-global registry. MCP runtime
state is keyed by `(user_id, server_id)`, conversation permissions are stored
per user and conversation, and every turn receives its own immutable tool
catalog.

## Source boundaries

- `app/core/edition.py` owns the edition policy.
- API and service layers reject disallowed writes.
- Runtime factories ignore legacy values that are invalid for the active
  edition.
- The frontend consumes the public policy and does not duplicate edition rules.

Adding an edition-specific behavior should extend the policy object and enforce
it at the service/runtime boundary. Avoid scattered environment checks in route
handlers and React components.
