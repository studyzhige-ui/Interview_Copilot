# Edition architecture

Interview Copilot has one application core and two distribution policies.
Edition checks are enforced by the backend and exposed to the frontend through
`GET /api/v1/capabilities/edition`.

## Product boundary

The product helps a candidate practise and review interviews; it is not an
autonomous recruiting system, an applicant-tracking system, or a guarantee of
an interview outcome. The supported user workflow is deliberately narrow:

1. keep up to two personal resumes and choose a default;
2. add reusable technical, project, or interview-preparation documents to the
   knowledge library;
3. run a resume-and-JD-grounded mock interview with a chosen interviewer style
   and voice;
4. upload a real interview recording for transcription and review;
5. ask follow-up questions in chat or Agent mode, optionally using personal
   Skills and MCP tools;
6. inspect evidence-backed memories and ability trends.

Personal resumes are first-class profile entities and do not silently enter the
general RAG library. A mock-interview JD is single-use context. Knowledge
documents are reusable retrieval sources. Interview recordings and their
snapshots belong to the corresponding interview record. These ownership rules
avoid one upload appearing in several unrelated product areas.

The mock interview exposes choices that change the candidate experience:
resume, JD, interviewer style, and voice. Stage budgets, planner prompts,
retrieval policy, scoring prompts, and internal models remain product policy;
exposing them would make sessions less comparable and would leak operational
complexity into the user interface.

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
