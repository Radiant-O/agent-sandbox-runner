# Console UI + Public Demo: Design

Status: decided 2026-11-10. The owner asked to see the built result rather than approve each section in turn.

## Goals
- A "mission control" web console that makes the system's behaviour *visible*: real sandbox lifecycle events, live output, honest classification, and agent runs checked against backend records.
- A public live demo that E2B reviewers can use without any credentials, where **no secret ever reaches the browser** and spend is capped by a daily budget.

## Architecture (approach A: one deployable)
- The React app (Vite, TypeScript, Tailwind) lives in `web/`. It is built into `app/static/` and served by FastAPI at `/`, from the same origin as the API.
- A new public router at `/demo/*` is enabled by `DEMO_ENABLED`. It calls the services server-side as owner `demo`. The existing `/api/v1` API is unchanged.
- Live updates use Server-Sent Events, fed by an in-process event bus with a per-execution replay buffer.

## Backend additions
- **Event bus.** `ExecutionEvents` handles publish/subscribe per stream id and keeps a replay ring buffer (closed streams are dropped after a TTL).
  - Execution events: `queued`, `sandbox_creating`, `sandbox_created{sandbox_id,create_ms}`, `code_uploaded{upload_ms}`, `stdout{data}`, `stderr{data}`, `exited{exit_code,timed_out}`, `sandbox_killed{kill_ms}`, `cleanup_failed`, `finished{execution}`.
  - Agent events: `step_started{step}`, `model_text{text}`, `tool_call{code}`, `execution` (nested execution events, tagged with `execution_id`), `tool_result{...}`, `finished{run}`.
- **Phase timings.** `create_ms`, `upload_ms`, `run_ms` and `kill_ms` are persisted on the execution record. The sandbox protocol gains an optional `EventSink`.
- **Demo limits.**
  - Per visitor (hashed IP; `X-Forwarded-For` is honoured only when `TRUST_PROXY=true`): `DEMO_RUNS_PER_HOUR=10`, `DEMO_AGENT_RUNS_PER_HOUR=3`.
  - Global per UTC day, persisted in SQLite: `DEMO_DAILY_RUNS=300`, `DEMO_DAILY_AGENT_RUNS=40`.
  - Tighter policy: `DEMO_MAX_TIMEOUT_SECONDS=15`, `DEMO_MAX_CODE_BYTES=10000`, agent capped at 4 steps and 2 tool calls, internet always off.
- **Turnstile.** When `TURNSTILE_SECRET_KEY` is set, every demo POST must carry a token, verified server-side at `challenges.cloudflare.com/turnstile/v0/siteverify` *before* any sandbox or LLM call. `TURNSTILE_SITE_KEY` is public and exposed through `/demo/status`.
- **Endpoints.**
  - `POST /demo/executions`, `GET /demo/executions/{id}`, `GET /demo/executions/{id}/events`
  - `POST /demo/agent/runs`, `GET /demo/agent/runs/{id}/events`
  - `GET /demo/status`, `GET /demo/examples`, `GET /demo/recordings`
- **Budget exhausted.** The API returns 429 `demo_budget_exhausted`, and the UI switches to replaying recorded real runs.

## UI
- **Top bar:** live sandbox count, average create time, today's budget meter, theme toggle, GitHub link.
- **Run mode:** editor with an example picker, a lifecycle timeline driven by real events, a streaming terminal, and a result card that says whether the code or the infrastructure was at fault.
- **Agent mode:** a conversation timeline (step, code written, mini lifecycle, result, answer) with a "verified by backend" badge.
- **Inside mode:** an architecture diagram that highlights the path the last run took, plus live metrics.
- **History slide-over:** this browser's runs, with ids kept in localStorage.
- **Designed edge states:** budget used up (replay), rate limited (countdown), stream dropped (reconnect and replay), backend offline, Turnstile pending.

## Testing
- Backend: unit tests for the event bus, phase events from the fake backend, demo limits and daily budget, Turnstile (stubbed verify), SSE streams, agent events, and static serving.
- UI: type-check plus production build; a Playwright smoke test against the real server for screenshots.

## Deploy
- A multi-stage Dockerfile: a node stage builds the UI, and a python stage serves everything.
- Target host is Fly.io (chosen at deploy time). Deploying requires the owner's go-ahead.
