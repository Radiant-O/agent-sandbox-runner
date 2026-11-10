# Agent Sandbox Runner: design

Status: approved 2026-11-09. This is the spec the implementation plan follows. The original brief is in [brief.md](brief.md).

## Goal

A FastAPI service that runs untrusted Python inside E2B cloud sandboxes, plus a Claude agent that calls the same execution path as a tool. It is a portfolio piece aimed at E2B, so sandbox lifecycle, cost and concurrency control, failure classification and honest security documentation take priority over features.

## Decisions

1. **Async API.** `POST /api/v1/executions` validates the request, persists a record as `queued`, runs it in a tracked background task and returns `202`. `?wait=true` blocks until the run finishes (bounded by the run's timeout plus a grace period). `GET /api/v1/executions/{id}` returns the record. On startup, records left in `queued`/`running` become `error` with category `interrupted`.
2. **Storage.** SQLite through `aiosqlite`, behind an `ExecutionStore` class. Executions are scoped to the API key that created them; another key gets a 404.
3. **Execution primitive.** The base `e2b` SDK (verified at v2.63.0): `AsyncSandbox.create(timeout=lifetime, allow_internet_access=..., envs={})`, then `files.write("/home/user/main.py", code)`, then `commands.run("python3 /home/user/main.py", timeout=t, on_stdout=..., on_stderr=...)`. This gives a real exit code. Output is streamed into byte-capped buffers, so partial output survives a timeout.
4. **Two timeouts.** The per-run command `timeout`, plus the sandbox lifetime `timeout` set at create as a backstop. `kill()` runs in `finally`. If it fails, we log it and count it; the lifetime limit still destroys the sandbox.
5. **Status and error taxonomy.**
   - status: `queued | running | succeeded | failed | timed_out | error`
   - error_category: `user_code_error | timeout | sandbox_unavailable | upstream_error | auth_error | interrupted | internal_error`
   - A non-zero exit is `failed`/`user_code_error`. `exception_type` is parsed from the last traceback line of stderr.
6. **Retries.** Only sandbox *creation* is retried, and only on transient errors (`RateLimitException`, `ServiceBusyException`, `SandboxUnreachableException`, network errors), with exponential backoff and at most `SANDBOX_CREATE_RETRIES` attempts. Code execution is never retried.
7. **Policy layer (no import blocklists).** Limits on code size, timeout bounds, output byte caps, a concurrency semaphore on live sandboxes, a per-key rate limit, outbound internet off by default (`allow_internet_access=False`), and no secrets in the sandbox's `envs`.
8. **Agent.** Claude through OpenRouter's OpenAI-compatible API, behind an `LLMProvider` protocol. A single `execute_python` tool. Bounds: max steps, max tool calls, wall-clock budget and max tokens. Invalid tool arguments go back to the model as tool errors. The agent calls `ExecutionService` in-process and uses one sandbox session per agent run, killed at the end. The response carries the persisted execution records; whether anything succeeded comes from those records, never from model text.
9. **Auth and rate limiting.** `X-API-Key`, checked against configured keys with `hmac.compare_digest`. Owner id = first 16 hex chars of the key's sha256. An in-memory token bucket per key (single-instance limitation documented).
10. **Observability.** JSON logs with `request_id` / `execution_id` from contextvars. Code is logged as size and sha256 only, never the body; secrets are redacted. `GET /metrics` returns JSON counters.

## Verified E2B SDK facts (e2b 2.63.0, read from installed source and docs.e2b.dev)

- `from e2b import AsyncSandbox, CommandExitException, TimeoutException, SandboxNotRunningException, SandboxUnreachableException, AuthenticationException, RateLimitException, ServiceBusyException, SandboxException`
- `AsyncSandbox.create(template=None, timeout=None, metadata=None, envs=None, allow_internet_access=None, ..., **opts)`. The timeout is in seconds; the class default is 300; the Hobby plan caps it at 3600. The API key comes from `E2B_API_KEY` or `api_key=` in opts.
- `await sandbox.files.write(path, data)`
- `await sandbox.commands.run(cmd, envs=None, cwd=None, on_stdout=None, on_stderr=None, timeout=60, request_timeout=None)` returns `CommandResult(stdout, stderr, exit_code, error)`. A non-zero exit raises `CommandExitException`, which is a `CommandResult`, so it has the same fields. A timeout raises `TimeoutException` (gRPC DEADLINE_EXCEEDED). `SandboxNotRunningException` and `SandboxUnreachableException` subclass `TimeoutException` and must be checked first.
- `await sandbox.kill()` returns a bool. `sandbox.sandbox_id`.
- Unverified: whether `python3` is present in the default `base` template. The live integration test checks this; if it is missing, set `SANDBOX_TEMPLATE`.

## Out of scope for now

React dashboard, demo video, multi-instance deployment (shared rate limit, durable job queue).
