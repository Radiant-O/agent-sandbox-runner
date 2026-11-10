# Agent Sandbox Runner

Secure Python execution for AI agents, built on [E2B](https://e2b.dev) cloud sandboxes.

**Live demo: [agent-sandbox-runner.onrender.com](https://agent-sandbox-runner.onrender.com)**. No sign-up needed. Runs real E2B microVMs, with per-visitor and daily limits.

**Engineering case study: [docs/case-study.md](docs/case-study.md)**. The trade-offs, the failures found on real E2B sandboxes, and how the public demo was secured.

A FastAPI service that takes untrusted Python, from a developer or from an LLM agent, and runs it inside isolated E2B sandboxes. It manages the whole sandbox lifecycle and returns structured, classified results. A bounded, tool-calling Claude agent uses **the same** execution path, so agent-generated code gets the same policy, limits and audit trail as direct API calls.

It also ships a **live console**: a public demo where anyone can run code or the agent and watch each microVM boot, run and get destroyed, timed from real backend events. The browser never holds a credential.

![Console: a failing run, with the lifecycle drawn to scale and the verdict blaming the code, not the platform](docs/images/console-run-error.png)

```mermaid
flowchart LR
    C[Client] -->|X-API-Key| API[FastAPI<br/>auth · rate limit · validation]
    U[User task] --> AG[AgentService<br/>Claude via OpenRouter<br/>step/tool/time limits]
    API --> ES
    AG -->|execute_python tool| ES[ExecutionService<br/>policy · concurrency cap<br/>classification · persistence]
    ES --> DB[(SQLite)]
    ES --> SB[E2BSandboxBackend<br/>retrying create · capped output<br/>guaranteed kill]
    SB -->|AsyncSandbox| E2B[[E2B microVM]]
```

## What it does

- **`POST /api/v1/executions`** runs code in a fresh sandbox. It is asynchronous by default (`202` plus a `Location` header); add `?wait=true` to block until the result is ready. If it isn't ready within the timeout plus 30 seconds (for example, while queued behind the concurrency cap), you get `202` with the current state, so poll from there.
- **`GET /api/v1/executions/{id}`** returns status, stdout/stderr, exit code, duration, sandbox id and error classification.
- **`POST /api/v1/agent/run`** takes a natural-language task. The agent decides whether code is needed, writes it, runs it through the sandbox tool, reads the result and answers. The response includes every execution record, so claims can be checked.
- **`GET /metrics`** reports execution counts by status, p50/p95 duration, live and created sandboxes, average create time, cleanup failures, create retries and agent stop reasons.
- **`GET /health`** is a liveness check. Interactive API docs are at **`/docs`** (OpenAPI).

## The console

| Run code | Agent | How it works |
|---|---|---|
| ![Streaming output live](docs/images/console-streaming.png) | ![Agent writes, runs and verifies](docs/images/console-agent.png) | ![Request path and live metrics](docs/images/console-inside.png) |

- **The lifeline** shows a microVM's actual life (boot, upload, run, destroy), drawn to scale from the backend's phase events and growing live while the code runs. Each phase timing is also stored on the execution record.
- **Output streams** to the terminal chunk by chunk over Server-Sent Events, under the same 64 KB-per-stream cap as the API.
- **The verdict** says whose fault a failure was: your code (`failed`, `timed_out`) or the platform (`error`).
- **Agent mode** shows each model step, the exact code Claude wrote, a lifeline for every sandbox run, and an answer marked **"Backed by the backend's records"** or **"Unverified"**, computed from stored executions rather than model text.
- **How it works** lights up the path the last run took and shows live metrics, plus what the system does *not* promise.
- When the day's demo budget is spent, examples **replay recorded real runs** (`app/demo/recordings.json`, captured by `scripts/record_demo.py`) instead of failing.
- Works on phones, has dark and light themes, keyboard focus states and respects reduced motion.

### How the public demo protects the keys

The console talks only to `/demo/*` on the same origin. Those endpoints run code **server-side** as a fixed `demo` owner, so there is no API key in the browser to steal. Every request that spends money passes these checks in order, and nothing is spent until all of them pass:

1. **Policy check** (free): code ≤ 10 KB, timeout ≤ 15 s. Rejected requests cost nothing, and the agent checks policy *before* booting a sandbox.
2. **Cloudflare Turnstile** (when `TURNSTILE_SECRET_KEY` is set): verified server-side, and fails closed.
3. **Per-visitor limit**: 10 runs and 3 agent runs an hour, keyed on a hashed IP. `X-Forwarded-For` is honoured only with `TRUST_PROXY=true`, and only the entry the platform proxy appended is used, so a spoofed header cannot mint new visitors.
4. **Global daily budget**: 300 runs and 40 agent runs per UTC day, persisted in SQLite so restarts don't reset it.

The server refuses to start if the demo is enabled with sandbox internet on. Every cap is configurable; see [`.env.example`](.env.example).

## Quickstart

```bash
git clone <this repo> && cd agent-sandbox-runner
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env    # then set API_KEYS, E2B_API_KEY and (for the agent) LLM_API_KEY
uvicorn app.main:create_app --factory --reload
```

```bash
curl -s -X POST "localhost:8000/api/v1/executions?wait=true" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"code": "print(sum(range(10)))"}'
```

With Docker:

```bash
docker build -t agent-sandbox-runner .
docker run --rm -p 8000:8000 --env-file .env -v asr-data:/data agent-sandbox-runner
```

To run the console locally, enable `DEMO_ENABLED=true` and build the UI once (Node 20+):

```bash
cd web && npm ci && npm run build && cd ..   # emits app/static, served at http://localhost:8000/
# or for UI development with hot reload: (cd web && npm run dev)  -> http://localhost:5173
```

The Docker image builds the UI itself (multi-stage), so `docker build` needs no local Node.

Then run every outcome end to end: `API_KEY=... python examples/run_examples.py` (add `--agent` to include one agent run).

## Results and error taxonomy

Every execution ends in exactly one terminal status. The core distinction is **"your code failed"** versus **"our infrastructure failed"**:

| status | error_category | meaning | who's at fault |
|---|---|---|---|
| `succeeded` | — | exit code 0 | — |
| `failed` | `user_code_error` | non-zero exit (syntax error, exception, `sys.exit(1)`); `exception_type` is parsed from the traceback | user code |
| `timed_out` | `timeout` | exceeded `timeout_seconds`; partial output kept | user code |
| `error` | `sandbox_unavailable` | sandbox couldn't be created (after retries) | infrastructure |
| `error` | `upstream_error` | sandbox died or the network dropped mid-run | infrastructure |
| `error` | `auth_error` | E2B rejected or is missing credentials | configuration |
| `error` | `interrupted` | server restarted or the agent budget ran out mid-run | infrastructure |
| `error` | `internal_error` | bug in this service | us |

API errors share one envelope: `{"error": {"code", "message", "request_id"}}`. The codes are `unauthorized` (401), `not_found` (404), `invalid_request`, `code_too_large` and `timeout_out_of_range` (422), `rate_limited` (429, with `Retry-After`) and `agent_unavailable` (503).

## Live results

These are real outputs from `examples/run_examples.py` against E2B on 2026-11-10 (`base` template, one fresh sandbox per execution):

| case | status | category | exit | exception_type | duration |
|---|---|---|---|---|---|
| `math.factorial(20)` | `succeeded` | — | 0 | — | 1.2 s |
| `data['missing']` | `failed` | `user_code_error` | 1 | `KeyError` | 0.6 s |
| `def broken(:` | `failed` | `user_code_error` | 1 | `SyntaxError` | 0.6 s |
| `while True: pass` (3 s timeout) | `timed_out` | `timeout` | — | — | 3.3 s |
| `urlopen('https://example.com')` | `failed` | `user_code_error` | 1 | `urllib.error.URLError` (name resolution) | 20.8 s |
| `print('x' * 1_000_000)` | `succeeded`, `stdout_truncated: true` | — | 0 | — | 3.2 s |
| `timeout_seconds: 9999` | HTTP 422 `timeout_out_of_range` | — | — | — | — |

Metrics afterwards: 6 sandboxes created and 6 killed (`sandboxes_live: 0`), `sandbox_create_ms_avg: 600`, no cleanup failures and no create retries.

## Design decisions

The full rationale is in [`docs/design.md`](docs/design.md). The highlights:

- **`commands.run` instead of a notebook kernel.** Each execution writes `/home/user/main.py` and runs `python3` on it, which gives real process semantics and a real exit code. The SDK raises `CommandExitException` for non-zero exits, and we turn that back into a *result*, not an error.
- **Two timeouts.** One per command (the user's limit) and one for the sandbox's lifetime (a backstop). `kill()` always runs in `finally`; if it fails, the lifetime timeout still destroys the VM, and `cleanup_failures_total` records it.
- **Retry creation, never execution.** Transient create failures (rate limit, 503, unreachable, transport) are retried with backoff. Every attempt reuses one `idempotency_key`, so a retry after a lost response returns the sandbox E2B already made instead of creating an orphan. Code execution can have side effects, so it is never retried.
- **Classify carefully.** In the SDK, `SandboxNotRunningException` is a *subclass* of `TimeoutException`, and a plain `TimeoutException` is also raised when E2B cancels the stream (for example, the sandbox was shut down). A run is reported as `timed_out` only if the user's time budget was actually used up; anything earlier is `upstream_error`.
- **Stream output into byte-capped buffers.** Output is streamed with `retain_output=False`, so the SDK keeps no second, uncapped copy. A `print` in a loop can't exhaust server memory, and partial output survives timeouts.
- **Concurrency is capped by a semaphore around sandbox sessions.** Excess work waits as `queued` instead of opening more VMs, which keeps cost bounded.
- **The agent can't "claim" success.** Its tool returns the backend's record as JSON. The run result carries `any_execution_succeeded`, computed from stored records rather than model text, and `answer` is `null` unless the run completed.
- **No import blocklists.** They're security theater. Containment is the sandbox's job; this service limits reach (no internet, no secrets) and blast radius (time, output, concurrency). See [`SECURITY.md`](SECURITY.md).

## Configuration

All settings are environment variables; see [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `API_KEYS` | — | Comma-separated client keys (`X-API-Key`) |
| `E2B_API_KEY` | — | E2B credentials |
| `SANDBOX_ALLOW_INTERNET` | `false` | Outbound network from sandboxes |
| `MAX_CONCURRENT_SANDBOXES` | `5` | Live sandbox cap (E2B Hobby allows 10) |
| `DEFAULT_TIMEOUT_SECONDS` / `MAX_TIMEOUT_SECONDS` | `30` / `120` | Execution timeouts |
| `MAX_CODE_BYTES` / `MAX_OUTPUT_BYTES` | `100000` / `65536` | Input and output caps (output cap is per stream) |
| `SANDBOX_CREATE_RETRIES` | `3` | Attempts for transient create failures |
| `RATE_LIMIT_PER_MINUTE` | `30` | Per API key, on submissions and agent runs (polling reads are not charged) |
| `LLM_API_KEY` / `LLM_MODEL` | — / — | OpenRouter key and model (e.g. `anthropic/claude-haiku-5.5`) |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS` / `AGENT_TIMEOUT_SECONDS` | `6` / `4` / `180` | Agent bounds |

## Tests

```bash
pytest -q                     # unit tests: no network, no credentials (fake E2B + scripted LLM)
pytest -m integration -q      # live E2B (+ OpenRouter for the agent test); needs .env keys
ruff check . && mypy app      # lint + strict typing
```

Unit tests cover:
- the classification of every outcome
- retry-then-succeed, retries exhausted, and auth errors that must not be retried
- `kill()` on every path, including when `kill()` itself fails
- output capping
- the concurrency cap
- crash recovery
- the auth, rate-limit, ownership and error envelopes
- every agent stop reason: invalid tool arguments, tool-call loops, the step limit, the time limit, and LLM failure

CI (GitHub Actions) runs lint, format, mypy and unit tests on Python 3.11 and 3.12, and builds the Docker image.

## Project layout

```
app/
  api/            executions.py, agents.py, system.py (health, metrics)
  core/           config, JSON logging, metrics, security (owner id, rate limiter)
  sandbox/        base.py (protocol), e2b_backend.py, output.py (capped buffers)
  services/       execution_service.py, agent_service.py
  llm/            base.py (provider protocol), openai_compat.py (OpenRouter)
  schemas/        request/response models
  demo/           public demo API: guard (limits, daily budget), turnstile, SSE, examples, recordings
  domain.py       ExecutionRecord, statuses, error categories
  store.py        SQLite persistence
tests/unit/       fast, deterministic
tests/integration/ live E2B / LLM, opt-in
web/              console UI: Vite + React + TypeScript + Tailwind (builds into app/static)
scripts/          record_demo.py (captures real runs for replay mode)
examples/         run_examples.py, requests.http
docs/             design.md, case-study.md
```

## Limitations

These are listed honestly in [`SECURITY.md`](SECURITY.md). In short: isolation is provided by E2B, not this service. Rate limits and metrics are per process. Background executions are in-process, so a restart marks them `interrupted` rather than resuming them. Agent prose is not verified; check it against the execution records.
