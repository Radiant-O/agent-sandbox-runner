# Agent Sandbox Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI service that runs untrusted Python in E2B sandboxes with full lifecycle control, plus a bounded Claude agent that uses the same execution path.

**Architecture:** API layer (FastAPI routers, auth, rate limit) → `ExecutionService` (policy, concurrency, persistence, classification) → `SandboxBackend` protocol (E2B implementation, fake for tests). `AgentService` drives an `LLMProvider` (OpenAI-compatible client pointed at OpenRouter) and calls `ExecutionService` in-process. SQLite stores execution records.

**Tech Stack:** Python ≥3.11, FastAPI, Pydantic v2 + pydantic-settings, e2b 2.63.x, openai SDK (OpenRouter), aiosqlite, tenacity, pytest + pytest-asyncio + httpx, ruff, mypy, Docker, GitHub Actions.

**Spec:** `docs/design.md`. Read it first; the "Verified E2B SDK facts" section is the only source of truth for SDK calls.

## Global Constraints

- `requires-python = ">=3.11"`. The Docker image uses `python:3.12-slim`.
- Pin `e2b>=2.63,<3`. Do not call any E2B method that isn't listed in `docs/design.md` without first checking the installed source in `.venv/Lib/site-packages/e2b`.
- Code execution is never retried. Only `AsyncSandbox.create` is retried.
- Never log code bodies, API keys, the E2B key or the LLM key. Log `code_size` and `code_sha256`.
- Never pass server secrets into sandbox `envs`. Always pass `envs={}`.
- Every unit test runs without network access or credentials. Live tests are marked `@pytest.mark.integration` and skip when their key env var is missing.
- Error response body is always `{"error": {"code": str, "message": str, "request_id": str}}`.
- Status values: `queued, running, succeeded, failed, timed_out, error`. Category values: `user_code_error, timeout, sandbox_unavailable, upstream_error, auth_error, interrupted, internal_error`.
- Settings defaults: `DEFAULT_TIMEOUT_SECONDS=30`, `MAX_TIMEOUT_SECONDS=120`, `MAX_CODE_BYTES=100000`, `MAX_OUTPUT_BYTES=65536` (per stream), `MAX_CONCURRENT_SANDBOXES=5`, `SANDBOX_ALLOW_INTERNET=false`, `SANDBOX_CREATE_RETRIES=3`, `RATE_LIMIT_PER_MINUTE=30`, `AGENT_MAX_STEPS=6`, `AGENT_MAX_TOOL_CALLS=4`, `AGENT_TIMEOUT_SECONDS=180`, `AGENT_MAX_TOKENS=1024`, `LLM_BASE_URL=https://openrouter.ai/api/v1`, `DATABASE_PATH=data/executions.db`.
- Sandbox lifetime = run timeout + 60 s for API executions, and `AGENT_TIMEOUT_SECONDS + 60` for agent sessions.
- Commit after each task with a conventional-commit message ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Infinite loop or huge print (`while True: print("x"*10**6)`)** must give `timed_out` with output capped at `MAX_OUTPUT_BYTES` and `stdout_truncated=true`, not exhaust memory. → Task 4 (buffer) and Task 5 (backend) tests.
2. **Sandbox dies mid-run** (`SandboxNotRunningException`, which subclasses `TimeoutException`) must give `error/upstream_error`, not `timed_out`. → Task 5 test `test_sandbox_not_running_is_upstream_not_timeout`.
3. **`kill()` raises during cleanup** must not change the result of an otherwise successful run. The failure is counted in metrics. → Task 5 test.
4. **A burst of concurrent submissions** above `MAX_CONCURRENT_SANDBOXES` must queue (status `queued`), not create extra sandboxes. → Task 6 test `test_concurrency_cap_is_respected`.
5. **The model emits malformed tool arguments or loops forever calling the tool** must end with `stop_reason="tool_call_limit"` and no crash, and invalid arguments are fed back as tool errors. → Task 9 tests.

---

### Task 1: Scaffold, config, JSON logging, health

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `app/__init__.py`, `app/core/config.py`, `app/core/logging.py`, `app/main.py`
- Test: `tests/conftest.py`, `tests/unit/test_config.py`, `tests/unit/test_logging.py`, `tests/unit/test_health.py`

**Interfaces:**
- Produces: `Settings` (pydantic-settings, reads `.env`) with every key in Global Constraints plus `E2B_API_KEY: SecretStr | None`, `API_KEYS: SecretStr` (comma-separated; parse it yourself, because pydantic-settings expects JSON for lists), `LLM_API_KEY: SecretStr | None`, `LLM_MODEL: str | None`, `SANDBOX_TEMPLATE: str | None`, `LOG_LEVEL="INFO"`; `Settings.api_key_list() -> list[str]`; `get_settings() -> Settings` (cached).
- Produces: `configure_logging(level: str, secrets: list[str]) -> None`; contextvars `request_id_var`, `execution_id_var`; a JSON formatter that emits `ts, level, logger, msg, request_id, execution_id` plus `extra` fields, and replaces any configured secret substring with `***`.
- Produces: `create_app(settings: Settings | None = None) -> FastAPI` and `GET /health` returning `{"status": "ok", "version": "0.1.0"}`.
- `tests/conftest.py`: fixture `settings` (tmp DB path, `API_KEYS="test-key"`).

- [ ] **Step 1: Write failing tests:** `test_api_keys_parsed_from_comma_list` (`"a, b"` gives `["a","b"]`); `test_timeout_defaults` (30/120); `test_log_line_is_json_with_request_id`; `test_secret_redacted_in_logs` (log `"key=sk-123"` with `secrets=["sk-123"]` and assert `"sk-123"` is absent and `"***"` is present); `test_health_ok` (httpx `AsyncClient` + `ASGITransport` returns 200 with `status == "ok"`).
- [ ] **Step 2:** Run `pytest tests/unit -q`. Expect FAIL (import errors).
- [ ] **Step 3:** Implement. pyproject: deps `fastapi, uvicorn[standard], pydantic>=2, pydantic-settings, e2b>=2.63,<3, openai>=1.40, aiosqlite, tenacity`; dev extras `pytest, pytest-asyncio, httpx, ruff, mypy`; `[tool.pytest.ini_options] asyncio_mode="auto"`, `markers=["integration: needs live credentials"]`, `addopts="-m 'not integration'"`. `.gitignore` covers `.venv/ data/ .env __pycache__/ .mypy_cache/ .ruff_cache/`. `.env.example` lists every setting with a comment and empty secrets.
- [ ] **Step 4:** Run `pip install -e ".[dev]"`, then `pytest -q`. Expect PASS. Run `ruff check .`. Expect clean.
- [ ] **Step 5:** Commit `chore: scaffold app with config, json logging and health check`.

### Task 2: Domain models and API schemas

**Files:**
- Create: `app/domain.py`, `app/schemas/__init__.py`, `app/schemas/executions.py`, `app/schemas/errors.py`
- Test: `tests/unit/test_schemas.py`

**Interfaces:**
- Produces in `app/domain.py`: `ExecutionStatus(StrEnum)`, `ErrorCategory(StrEnum)` (values in Global Constraints); `@dataclass ExecutionRecord` with fields `id: str, owner: str, status: ExecutionStatus, code: str, code_sha256: str, code_size: int, timeout_seconds: int, source: Literal["api","agent"], agent_run_id: str | None, created_at: datetime, started_at: datetime | None, completed_at: datetime | None, duration_ms: int | None, stdout: str, stderr: str, stdout_truncated: bool, stderr_truncated: bool, exit_code: int | None, error_category: ErrorCategory | None, error_message: str | None, exception_type: str | None, sandbox_id: str | None`; `ExecutionRecord.new(code, timeout_seconds, owner, source="api", agent_run_id=None) -> ExecutionRecord` (id = `"exe_" + uuid4().hex`, UTC timestamps, status `queued`, empty output).
- Produces in `app/schemas/executions.py`: `ExecutionCreate(code: str, timeout_seconds: int | None)`. The code must be non-blank. Its size limit (`MAX_CODE_BYTES`) and the timeout bounds `1..MAX_TIMEOUT_SECONDS` are enforced in the service (Task 6) because they depend on settings. `ExecutionOut` is the full record minus `code` and `owner`, built by `ExecutionOut.from_record(rec)`.
- Produces in `app/schemas/errors.py`: `ErrorBody(code, message, request_id)`, `ErrorResponse(error: ErrorBody)`.

- [ ] **Step 1: Write failing tests:** `test_new_record_defaults` (id prefix `exe_`, status `queued`, sha256 matches `hashlib`); `test_blank_code_rejected` (pydantic `ValidationError` for `"   "`); `test_execution_out_hides_code_and_owner`.
- [ ] **Step 2:** Run `pytest tests/unit/test_schemas.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Commit `feat: add execution domain model and api schemas`.

### Task 3: SQLite execution store

**Files:**
- Create: `app/store.py`
- Test: `tests/unit/test_store.py`

**Interfaces:**
- Consumes: `ExecutionRecord`, `ExecutionStatus`, `ErrorCategory`.
- Produces: `class ExecutionStore` with `__init__(path: str)`, `async init() -> None` (creates parent dir and table), `async create(rec) -> None`, `async update(rec) -> None` (full overwrite by id), `async get(execution_id: str, owner: str) -> ExecutionRecord | None`, `async list_by_agent_run(agent_run_id: str) -> list[ExecutionRecord]`, `async mark_interrupted() -> int` (sets every `queued`/`running` row to `error` + `interrupted` + `completed_at=now`, and returns the count), `async close() -> None`. Datetimes are stored as ISO strings and enums as values.

- [ ] **Step 1: Write failing tests** (with `tmp_path`): `test_create_then_get_roundtrip` (all fields equal); `test_get_wrong_owner_returns_none`; `test_update_persists_status_and_output`; `test_mark_interrupted_only_touches_active` (queued + running + succeeded rows give count 2, and the succeeded row is unchanged).
- [ ] **Step 2:** Run `pytest tests/unit/test_store.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement with a single `aiosqlite` connection opened in `init()`.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Commit `feat: add sqlite execution store with crash recovery`.

### Task 4: Sandbox abstraction, capped output buffer, fake backend

**Files:**
- Create: `app/sandbox/__init__.py`, `app/sandbox/base.py`, `app/sandbox/output.py`, `tests/fakes.py`
- Test: `tests/unit/test_output_buffer.py`

**Interfaces:**
- Produces in `base.py`: `@dataclass(frozen=True) RunOutput(stdout: str, stderr: str, stdout_truncated: bool, stderr_truncated: bool, exit_code: int | None, timed_out: bool, duration_ms: int)`; `class SandboxSession(Protocol)` with `sandbox_id: str` and `async run_python(code: str, timeout_seconds: int) -> RunOutput`; `class SandboxBackend(Protocol)` with `def session(lifetime_seconds: int) -> AbstractAsyncContextManager[SandboxSession]`; exceptions `SandboxError(Exception)` with class attribute `category: ErrorCategory`, and subclasses `SandboxUnavailableError` (sandbox_unavailable), `SandboxAuthError` (auth_error) and `SandboxUpstreamError` (upstream_error).
- Contract: a session may raise `SandboxError` subclasses. A user-code timeout is **returned** as `RunOutput(timed_out=True)` with partial output, not raised.
- Produces in `output.py`: `class OutputBuffer(limit_bytes: int)` with `append(chunk: str) -> None`, `text: str` and `truncated: bool`. It stores at most `limit_bytes` UTF-8 bytes, cutting on a character boundary, and drops the rest without accumulating it.
- Produces in `tests/fakes.py`: `FakeSandboxBackend(outputs: list[RunOutput | Exception] | None = None, create_error: Exception | None = None, delay: float = 0)`. It hands out sessions with `sandbox_id="fake-sbx-<n>"`, pops outputs in order (default: success with exit 0), and records `created: int`, `killed: int` and `max_live: int`.

- [ ] **Step 1: Write failing tests:** `test_buffer_under_limit_keeps_all`; `test_buffer_truncates_and_flags` (limit 10, append 25 ASCII chars, so `len(text.encode()) == 10` and `truncated is True`); `test_buffer_never_splits_multibyte_char` (limit 5, append `"ééé"`, so the text decodes cleanly and is ≤ 5 bytes); `test_buffer_ignores_chunks_after_full` (append 10 MB in 1 KB chunks and the stored size stays at the limit).
- [ ] **Step 2:** Run `pytest tests/unit/test_output_buffer.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Commit `feat: add sandbox protocol, capped output buffer and fake backend`.

### Task 5: E2B backend

**Files:**
- Create: `app/sandbox/e2b_backend.py`, `app/core/metrics.py`
- Test: `tests/unit/test_e2b_backend.py`, `tests/unit/test_metrics.py`, `tests/integration/test_e2b_live.py`

**Interfaces:**
- Consumes: `RunOutput`, `SandboxSession`, `SandboxError` subclasses, `OutputBuffer`, `Settings`.
- Produces in `metrics.py`: `class Metrics` with `execution_finished(status: ExecutionStatus, duration_ms: int)`, `sandbox_created(create_ms: int)`, `sandbox_killed()`, `cleanup_failed()`, `create_retried()`, `agent_run_finished(stop_reason: str)`, and `snapshot() -> dict`. The snapshot contains `executions_by_status`, `sandboxes_live`, `sandboxes_created_total`, `cleanup_failures_total`, `create_retries_total`, `sandbox_create_ms_avg`, `execution_duration_ms_p50/p95` (computed over the last 1000), and `agent_runs_by_stop_reason`.
- Produces: `E2BSandboxBackend(settings: Settings, metrics: Metrics, sandbox_cls=AsyncSandbox)`. `sandbox_cls` is the injection point that tests replace.
  - `session(lifetime_seconds)` is an `asynccontextmanager`. It calls `sandbox_cls.create(template=settings.SANDBOX_TEMPLATE, timeout=lifetime_seconds, allow_internet_access=settings.SANDBOX_ALLOW_INTERNET, envs={}, metadata={"app": "agent-sandbox-runner"}, api_key=<E2B key>)`, wrapped in tenacity: retry only on `RateLimitException, ServiceBusyException, SandboxUnreachableException, httpx.TransportError`, `stop_after_attempt(SANDBOX_CREATE_RETRIES)`, exponential wait 0.5–4 s (tests patch the wait to 0). Error mapping: `AuthenticationException` → `SandboxAuthError`; retries exhausted or any other `SandboxException` → `SandboxUnavailableError`. In `finally` it calls `await sbx.kill()`; any exception there is logged with `sandbox_id`, increments `cleanup_failed()` and is swallowed. A missing E2B key raises `SandboxAuthError` before any network call.
  - `run_python`: `files.write("/home/user/main.py", code)`, then `commands.run("python3 /home/user/main.py", timeout=timeout_seconds, on_stdout=buf_out.append, on_stderr=buf_err.append)`. Return-path mapping: `CommandResult` gives `exit_code`; `CommandExitException` gives its `exit_code` (this is a user-code failure, not an exception for us); `SandboxNotRunningException` / `SandboxUnreachableException` give `SandboxUpstreamError`; then `TimeoutException` gives `RunOutput(timed_out=True, exit_code=None)`; `AuthenticationException` gives `SandboxAuthError`; any other `SandboxException` or an `httpx.TransportError` (network drop mid-run) gives `SandboxUpstreamError`. Add the test `test_network_drop_mid_run_is_upstream_error`. stdout/stderr always come from the buffers, not from the result object, so the byte cap holds.

- [ ] **Step 1: Write failing tests** using a hand-written `FakeAsyncSandbox` class in the test file (classmethod `create`, `files.write`, `commands.run` that calls `on_stdout` with scripted chunks and then returns or raises, `kill`, and `sandbox_id`). Build SDK exceptions with their real constructors from `e2b`.
  `test_success_returns_exit_zero_and_output`; `test_nonzero_exit_is_output_not_exception` (raise `CommandExitException(stdout="", stderr="ZeroDivisionError: x", exit_code=1, error=None)` and expect `exit_code == 1`); `test_timeout_returns_timed_out_with_partial_output`; `test_sandbox_not_running_is_upstream_not_timeout`; `test_create_retries_transient_then_succeeds` (2× `RateLimitException`, then OK, so create is called 3 times and `create_retries_total == 2`); `test_create_auth_error_not_retried` (create called once, `SandboxAuthError`); `test_kill_called_on_success_and_on_error`; `test_kill_failure_is_swallowed_and_counted`; `test_output_capped` (5 MB of chunks and limit 1024 gives `stdout_truncated`); `test_sandbox_envs_empty_and_internet_off` (inspect the create kwargs). Metrics: `test_snapshot_percentiles`.
- [ ] **Step 2:** Run `pytest tests/unit/test_e2b_backend.py tests/unit/test_metrics.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Write `tests/integration/test_e2b_live.py` (marked `integration`, skip if `E2B_API_KEY` is unset): `print(2+2)` gives exit 0 and stdout `"4\n"`; `1/0` gives exit 1 and stderr containing `ZeroDivisionError`; `import time; time.sleep(30)` with timeout 3 gives `timed_out`; `import urllib.request; urllib.request.urlopen("https://example.com", timeout=5)` gives a non-zero exit (internet off). Run `pytest -m integration -q` only if the key is present; otherwise record "skipped, no key" in the task report.
- [ ] **Step 6:** Commit `feat: add e2b sandbox backend with retrying create and guaranteed cleanup`.

### Task 6: Execution service

**Files:**
- Create: `app/services/__init__.py`, `app/services/execution_service.py`
- Test: `tests/unit/test_execution_service.py`

**Interfaces:**
- Consumes: `ExecutionStore`, `SandboxBackend`, `Metrics`, `Settings`, `ExecutionRecord`, `RunOutput`, `SandboxError`.
- Produces: `class PolicyViolation(Exception)` with fields `code: str` (`"code_too_large"` | `"timeout_out_of_range"`) and `message: str`.
- Produces: `parse_exception_type(stderr: str) -> str | None`, which takes the last non-empty stderr line matching `^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning))\b`.
- Produces: `apply_output(rec: ExecutionRecord, out: RunOutput) -> None` (pure). It sets `succeeded` when exit is 0; `failed` + `user_code_error` + `exception_type` when exit is non-zero; and `timed_out` + `timeout` when `timed_out`.
- Produces: `ExecutionService(store, backend, metrics, settings)` with:
  - `async submit(code: str, timeout_seconds: int | None, owner: str) -> ExecutionRecord`. It enforces the policy (raising `PolicyViolation`), persists the record as `queued`, starts a tracked `asyncio.Task` (`_run_standalone`) and returns the record.
  - `async wait(execution_id: str, owner: str) -> ExecutionRecord`. It awaits the task with `asyncio.shield`, bounded by `timeout_seconds + 30`, then returns the stored record.
  - `async get(execution_id, owner) -> ExecutionRecord | None`.
  - `open_session(lifetime_seconds: int) -> AbstractAsyncContextManager[SandboxSession]`. It acquires a slot from `asyncio.Semaphore(MAX_CONCURRENT_SANDBOXES)`, then enters `backend.session`.
  - `async run_in_session(session, code, timeout_seconds, owner, agent_run_id: str) -> ExecutionRecord`. Used by the agent: same policy checks, persists with `source="agent"`, runs, applies the output and returns the final record.
  - `async recover() -> int`, which delegates to `store.mark_interrupted()`.
  - `async shutdown()`, which cancels in-flight tasks; their records become `interrupted`.
  - Running sets `running` + `started_at`. Afterwards it sets `completed_at` and `duration_ms` and calls `metrics.execution_finished`. A `SandboxError` sets `error` + `exc.category` + `str(exc)`. Any other exception sets `error/internal_error`, logged with the traceback. The task never raises. Log `code_size`/`code_sha256`, never the code.

- [ ] **Step 1: Write failing tests** with `FakeSandboxBackend` and a tmp store:
  `test_submit_then_wait_succeeds` (status `succeeded`, `sandbox_id` starts with `fake-sbx-`, `duration_ms >= 0`); `test_nonzero_exit_is_failed_user_code_error_with_exception_type`; `test_timeout_maps_to_timed_out`; `test_create_failure_maps_to_error_sandbox_unavailable` (status `error`, never `failed`); `test_code_too_large_raises_policy_violation`; `test_timeout_out_of_range_raises_policy_violation` (0 and 121); `test_default_timeout_applied` (None gives 30); `test_concurrency_cap_is_respected` (cap 2, delay 0.2, 6 submissions, so `max_live <= 2` and all end `succeeded`); `test_recover_marks_interrupted`; `test_parse_exception_type` (`"Traceback...\nValueError: bad"` gives `ValueError`; `"  File x\nSyntaxError: invalid syntax"` gives `SyntaxError`; `"hello"` gives None).
- [ ] **Step 2:** Run `pytest tests/unit/test_execution_service.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Commit `feat: add execution service with policy, concurrency cap and classification`.

### Task 7: Executions API: auth, rate limit, errors, request IDs, metrics

**Files:**
- Create: `app/core/security.py`, `app/dependencies.py`, `app/api/__init__.py`, `app/api/executions.py`, `app/api/system.py`
- Modify: `app/main.py` (lifespan wiring, middleware, exception handlers, routers)
- Test: `tests/unit/test_api_executions.py`

**Interfaces:**
- Consumes: `ExecutionService`, `Metrics`, `ExecutionCreate`, `ExecutionOut`, `ErrorResponse`, `PolicyViolation`.
- Produces in `security.py`: `owner_id(api_key: str) -> str` (first 16 hex chars of the sha256); `class RateLimiter(per_minute: int, clock=time.monotonic)` with `check(key: str) -> float | None` (None if allowed, otherwise the retry-after seconds; token bucket).
- Produces in `dependencies.py`: `require_api_key(request) -> str` (returns the owner id; `hmac.compare_digest` against each configured key; missing or invalid key gives 401 `unauthorized`; then the rate limit gives 429 `rate_limited` with a `Retry-After` header); `get_execution_service(request)` and `get_metrics(request)` read from `app.state`.
- `create_app(settings, *, backend: SandboxBackend | None = None, llm: LLMProvider | None = None)`. The lifespan builds the store, metrics and backend (`E2BSandboxBackend` unless one is injected), runs `recover()` on startup and `shutdown()` + `store.close()` on teardown.
- Middleware: read `X-Request-ID` or generate one, set `request_id_var`, echo it in the response header, and log one access line (`method, path, status, duration_ms`).
- Endpoints:
  - `POST /api/v1/executions?wait=false` → 202 + `ExecutionOut`. With `wait=true` → 200 if the run reached a terminal state, else 202.
  - `GET /api/v1/executions/{id}` → 200, or 404 `not_found` (including another owner's id).
  - `GET /metrics` → `metrics.snapshot()` (requires an API key).
  - `GET /health` unchanged (no auth).
- Exception handlers map `PolicyViolation` → 422 with its code, `RequestValidationError` → 422 `invalid_request`, `HTTPException` → its status, and anything unhandled → 500 `internal_error`. All use the error envelope.

- [ ] **Step 1: Write failing tests** (app built with `FakeSandboxBackend`, `httpx.AsyncClient` + `ASGITransport`, running the lifespan via `asgi-lifespan` or a manual `app.router.lifespan_context`; add `asgi-lifespan` to dev deps if used):
  `test_missing_key_401_envelope` (body has `error.code == "unauthorized"` and `error.request_id`); `test_submit_wait_returns_200_succeeded`; `test_submit_async_returns_202_then_get`; `test_get_other_owner_404` (two keys); `test_code_too_large_422_code_too_large`; `test_rate_limit_429_with_retry_after` (`RATE_LIMIT_PER_MINUTE=2`, third call gives 429); `test_request_id_echoed`; `test_metrics_counts_execution`; `test_openapi_has_execution_paths`.
- [ ] **Step 2:** Run `pytest tests/unit/test_api_executions.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`. Expect all PASS.
- [ ] **Step 5:** Manual check: run `uvicorn app.main:create_app --factory` with a real `.env`, then `curl` a `POST` with `wait=true`. This needs the E2B key; if it's absent, record "skipped".
- [ ] **Step 6:** Commit `feat: add executions api with auth, rate limiting and error envelope`.

### Task 8: LLM provider (OpenRouter, OpenAI-compatible)

**Files:**
- Create: `app/llm/__init__.py`, `app/llm/base.py`, `app/llm/openai_compat.py`
- Modify: `tests/fakes.py` (add `ScriptedLLM`)
- Test: `tests/unit/test_llm_provider.py`

**Interfaces:**
- Produces in `base.py`: `@dataclass ToolCall(id: str, name: str, arguments: str)` (raw JSON string); `@dataclass LLMTurn(text: str | None, tool_calls: list[ToolCall], finish_reason: str, total_tokens: int)`; `class LLMProvider(Protocol)` with `async complete(messages: list[dict], tools: list[dict], max_tokens: int) -> LLMTurn`; `class LLMError(Exception)`.
- Produces: `OpenAICompatibleProvider(api_key: str, base_url: str, model: str, timeout_seconds: float = 60, client: AsyncOpenAI | None = None)`. It calls `client.chat.completions.create(model, messages, tools, tool_choice="auto", max_tokens)` and maps `choices[0].message` to an `LLMTurn`. Any `openai.APIError` or timeout becomes an `LLMError` whose message does not include the key.
- Produces: `tests/fakes.py::ScriptedLLM(turns: list[LLMTurn | Exception])`, which records the `messages` it received on each call.
- Before implementing, verify the OpenRouter Claude model id with `curl -s https://openrouter.ai/api/v1/models` (public, no key) and put a cheap Haiku-class id as the `LLM_MODEL` example in `.env.example`.

- [ ] **Step 1: Write failing tests** with a stub `client` object (no network): `test_maps_tool_calls`; `test_maps_text_only_turn`; `test_api_error_wrapped_without_key` (the stub raises `openai.APIConnectionError(request=httpx.Request("POST","http://x"))`, giving an `LLMError` whose str doesn't contain the key).
- [ ] **Step 2:** Run `pytest tests/unit/test_llm_provider.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run the same command. Expect PASS.
- [ ] **Step 5:** Commit `feat: add openai-compatible llm provider for openrouter`.

### Task 9: Agent service and endpoint

**Files:**
- Create: `app/services/agent_service.py`, `app/schemas/agents.py`, `app/api/agents.py`
- Modify: `app/main.py` (router, build the provider from settings when `LLM_API_KEY` and `LLM_MODEL` are set, otherwise use `llm=None`)
- Test: `tests/unit/test_agent_service.py`, `tests/unit/test_api_agents.py`, `tests/integration/test_agent_live.py`

**Interfaces:**
- Consumes: `LLMProvider`, `LLMTurn`, `ToolCall`, `LLMError`, `ExecutionService.open_session`, `ExecutionService.run_in_session`, `PolicyViolation`, `ExecutionOut`.
- Tool schema (OpenAI function format): name `execute_python`, params `{code: string (required), timeout_seconds: integer (optional)}`. The description says it runs in an isolated sandbox without internet, and that the result is JSON with `status, exit_code, stdout, stderr, exception_type`.
- System prompt (exact intent): decide whether code is needed; use print to show results; base the final answer only on observed tool results; if execution failed or never ran, say so plainly and never claim success.
- Produces: `AgentService(llm: LLMProvider, executions: ExecutionService, metrics: Metrics, settings: Settings)` with `async run(task: str, owner: str) -> AgentRunResult`.
- Produces in `schemas/agents.py`: `AgentRunRequest(task: str, 1..4000 chars)`; `AgentRunResult(id: str ("run_"+hex), stop_reason: Literal["completed","step_limit","tool_call_limit","time_limit","llm_error"], answer: str | None, executions: list[ExecutionOut], steps: int, tool_calls: int, any_execution_succeeded: bool)`.
- Loop rules:
  - The sandbox session is opened lazily on the first tool call, with lifetime `AGENT_TIMEOUT_SECONDS+60`, and closed in `finally`.
  - The whole loop runs under `asyncio.timeout(AGENT_TIMEOUT_SECONDS)`; expiry gives `time_limit`.
  - Each `llm.complete` is one step; more than `AGENT_MAX_STEPS` gives `step_limit`.
  - Each tool call counts, valid or not. A call beyond `AGENT_MAX_TOOL_CALLS` gives `tool_call_limit`, and the loop stops without asking the model again.
  - An unknown tool name, invalid JSON or a missing `code` produces a tool message `{"error": "..."}`, and the loop continues.
  - A `PolicyViolation` produces a tool message with its message.
  - A `SandboxError` ends up in the persisted record (status `error`), and the model sees the record JSON.
  - Tool-result stdout/stderr sent back to the model is trimmed to 4000 chars each.
  - A turn with no tool calls ends the run as `completed` with `answer=text`.
  - `LLMError` gives `llm_error`, keeping the executions so far.
  - `answer` is None for every stop reason except `completed`.
  - `any_execution_succeeded` is computed from the records.
  - Call `metrics.agent_run_finished(stop_reason)`.
- Endpoint: `POST /api/v1/agent/run` (auth + rate limit) → 200 `AgentRunResult`. When `llm` is None → 503 `agent_unavailable`.

- [ ] **Step 1: Write failing tests** with `ScriptedLLM` + `FakeSandboxBackend`:
  `test_answer_without_tool_use` (no sandbox created, `fake.created == 0`); `test_tool_call_then_answer` (one execution, succeeded; the second LLM call's messages include a `role:"tool"` message whose content contains the stdout); `test_invalid_tool_args_fed_back_as_error` (arguments `"not json"`, then a text turn, gives `completed`, zero executions, and a tool message containing `"error"`); `test_tool_call_limit_stops_loop` (the LLM always calls the tool, `AGENT_MAX_TOOL_CALLS=2`, giving `tool_call_limit`, `answer is None`, 2 executions); `test_step_limit`; `test_time_limit` (the fake backend delay exceeds an `AGENT_TIMEOUT_SECONDS` of 0.2); `test_llm_error_keeps_executions`; `test_sandbox_reused_within_run_and_killed` (two tool calls give `created == 1`, `killed == 1`); `test_failed_execution_visible_to_model` (exit 1 gives `any_execution_succeeded is False`). API: `test_agent_endpoint_503_without_llm`; `test_agent_endpoint_runs`.
- [ ] **Step 2:** Run `pytest tests/unit/test_agent_service.py tests/unit/test_api_agents.py -q`. Expect FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run `pytest -q`. Expect all PASS.
- [ ] **Step 5:** Write `tests/integration/test_agent_live.py` (marked `integration`, skip unless both `E2B_API_KEY` and `LLM_API_KEY` are set): the task "What is the 20th Fibonacci number? Compute it." gives `completed`, at least 1 succeeded execution, and `"6765"` in the answer. This costs real OpenRouter credit, so run it once only.
- [ ] **Step 6:** Commit `feat: add bounded tool-calling agent using sandbox execution`.

### Task 10: Docker, CI, docs, examples

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `README.md`, `SECURITY.md`, `examples/requests.http`, `examples/run_examples.py`, `docs/case-study.md` (skeleton with headings: Context, Architecture, Trade-offs, Failure scenarios, Challenges, Lessons. Fill it in from real notes collected during Tasks 1–9; no invented incidents)
- Test: CI run, `docker build`

**Interfaces:**
- Dockerfile: `python:3.12-slim`, a non-root user, `pip install .`, `EXPOSE 8000`, `CMD uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000`, and a `HEALTHCHECK` on `/health` using python urllib (no curl in slim).
- CI: on push/PR, Python 3.11 + 3.12 matrix running `pip install -e ".[dev]"`, `ruff check .`, `ruff format --check .`, `mypy app`, `pytest -q`, plus a `docker build` job. Integration tests are not run in CI (no secrets).
- `examples/run_examples.py`: uses httpx against `BASE_URL` with `API_KEY` and shows success, a runtime error, a syntax error, a timeout, an internet-blocked run and an agent run, printing status and category for each.
- README: what it is, an architecture diagram (mermaid), quickstart (venv and Docker), configuration table, API examples with real responses captured from a live run, the error taxonomy table, how to run unit and integration tests, design decisions (link to `docs/design.md`), and limitations.
- SECURITY.md: the threat model (untrusted code; E2B microVM isolation is the boundary we rely on, not this app); controls in place; explicit non-guarantees (in-memory rate limiting is per-instance, network allowlists are E2B's, output content is not sanitized, the agent can still produce wrong answers); and how to report issues.

- [ ] **Step 1:** Write the files.
- [ ] **Step 2:** Run `docker build -t agent-sandbox-runner .`, then `docker run --rm -p 8000:8000 --env-file .env agent-sandbox-runner`, then `curl localhost:8000/health`. Expect `{"status":"ok",...}`.
- [ ] **Step 3:** Run `ruff check . && ruff format --check . && mypy app && pytest -q`. Expect everything clean.
- [ ] **Step 4:** With live keys, run `python examples/run_examples.py` and paste the real outputs into the README. Without keys, leave a clearly marked TODO in the README and report it.
- [ ] **Step 5:** Commit `docs: add docker, ci, readme, security notes and examples`.
