# Architecture

## Product runtime

AQA ships as a Tauri desktop application. Its embedded FastAPI backend serves the built React UI and same-origin API to the native window; discussions stream through Server-Sent Events. The browser path supports source development and automated testing.

```text
Browser
  └─ React / Vite: frontend/src → frontend/dist
       └─ HTTP + Server-Sent Events
            └─ FastAPI composition root: src/service/api_app.py:create_app
                 └─ app-local AppContext (lazy, shared by this app)
                      ├─ DiscussionService
                      ├─ PromptRepository
                      ├─ LLMManager
                      └─ DiscussionStorage
```

`src/api_server.py` creates the production application and is the Uvicorn entrypoint. `create_app()` is the sole FastAPI composition root: it owns the lifespan, structured error envelopes, request activity middleware, routers, and static-asset serving.

## Frontend

`frontend/src/components/Layout.tsx` composes controller hooks and renders the application views. It owns view, modal, disclosure, focus, and presentation state. The controllers own their respective asynchronous boundaries:

- `useDiscussionStreaming`: typed SSE lifecycle, current discussion state, and discussion mutations;
- `useSessionHydration`: fresh drafts, saved-session snapshots, title editing, and setup state;
- `useWorkbenchCatalogs`: perspectives, roles, session types, quick actions, hosts, and the selected AI source;
- `useApplicationActivity`, `useDiscussionMaterialPane`, and `useDiscussionMaterialPresentation`: activity polling and material-view behavior.

`frontend/src/api/` contains the shared HTTP client, generated wire contracts, and the typed SSE adapter. `frontend/src/api.ts` groups the current domain calls; it is not a compatibility layer. UI-only types live beside components, while generated request and response contracts are the sole source of truth for HTTP payloads.

## Backend

`src/service/discussion.py` owns multi-agent discussion orchestration, prompt assembly, persisted rounds, and follow-up requests. Shared prompt assembly is also used by preview.

`src/service/routers/` groups HTTP endpoints by domain: application, defaults, discussions, globals, Local AI, preview, quick actions, roles, session types, and sessions. `src/service/host_routes.py` provides the host catalogue router. `create_app()` installs the context factory, lock, and app-local context slot. The ordinary FastAPI context dependency initializes that slot once, on the first request that needs an `AppContext`, and every later request served by that app reuses the same context. Health, static assets, and module import do not trigger mutable user-data bootstrap. Tests replace the dependency through `app.dependency_overrides`; there is no process-global context or request-local context variable.

`/api/discussions/start` and `/api/discussions/continue` emit typed SSE events for discussion startup, chunks, agent completion, synthesis, and terminal state. Request generation and abort guards on both sides prevent stale stream events from changing a newer discussion or hydrated snapshot.

## Prompts, persistence, and local data

`PromptRepository` loads active POML source from `data/prompts/`. Immutable distribution defaults live in `data/prompt_defaults/`; restoring a shipped role copies its default without deleting user-created roles.

Saved discussions are complete current-schema snapshots. The store performs atomic writes and never reconstructs a snapshot from mutable prompt files. Tauri places mutable settings, conversations, editable prompts, and Integrated-AI files under the platform-managed AQA data directory. Packaged resources remain read-only.

## Distribution

`desktop/` is a Tauri shell for the same loopback FastAPI application. It starts the packaged Python backend on a loopback port, waits for `/api/health`, and loads that origin in the native window. The only desktop build entrypoint is `packaging/desktop/build_target.sh <target>`; it prepares staging, invokes Tauri, and writes architecture-explicit artifacts.

## Development boundaries

- `requirements.txt` is the local web runtime set.
- `requirements-dev.txt` adds test and quality tools.
- `requirements-runtime.in` and its hash-locked `.txt` file define the embedded desktop runtime dependencies.
- `frontend/package-lock.json` is the frontend dependency lock; use `npm ci`.
- `pyproject.toml` contains shared Pytest, Ruff, and Coverage configuration.
