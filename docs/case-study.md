# Engineering Case Study: Agent Sandbox Runner

> Status: draft. Sections are filled in from real notes taken during the build. Nothing here is invented; anything not yet observed live is marked as pending.

## Context

AI agents increasingly need to *run* the code they write. Running it on the application server is the obvious, dangerous shortcut. This project puts the untrusted code inside E2B sandboxes and treats everything around that boundary as production infrastructure: lifecycle, limits, classification, observability and an agent that cannot bypass any of it.

## Architecture

API layer → `ExecutionService` (policy, concurrency, persistence, classification) → `SandboxBackend` protocol → E2B. The agent is a client of `ExecutionService`, not of E2B directly. See the diagram in the README and the decisions in `docs/design.md`.

## Trade-offs

- **Process execution (`commands.run`) vs a notebook kernel (`run_code`).** I chose real exit codes and process semantics over rich outputs (charts) and in-kernel state.
- **SQLite + in-process background tasks vs a queue (Redis/Celery).** This keeps the project single-binary and easy to run. The cost is that a restart interrupts in-flight work; that is detected and reported as `interrupted`, not hidden.
- **One sandbox per API execution vs pooling.** It maximises isolation, at the price of create latency on every call (visible as `sandbox_create_ms_avg`).
- **One sandbox per agent run.** Files persist between the agent's steps; the sandbox is never shared across runs or callers.
- **OpenAI-compatible client vs the native Anthropic SDK.** This let me use OpenRouter credit and swap providers through configuration; the cost is losing some Anthropic-specific features.

## Failure scenarios and how they surface

| Scenario | Detection | Outcome |
|---|---|---|
| User code raises | `CommandExitException` | `failed / user_code_error`, `exception_type` parsed |
| Infinite loop | SDK `TimeoutException` | `timed_out`, partial output kept |
| Sandbox dies mid-run | `SandboxNotRunningException` (a `TimeoutException` subclass, so caught first) | `error / upstream_error` |
| E2B rate-limits creation | `RateLimitException` | retried with backoff; `create_retries_total` |
| Bad E2B key | `AuthenticationException` | `error / auth_error`, not retried |
| `kill()` fails | exception in `finally` | logged; `cleanup_failures_total`; lifetime timeout backstop |
| Server restarts | records left `queued`/`running` | marked `interrupted` on startup |
| Agent loops on tool calls | tool-call counter | `stop_reason=tool_call_limit`, `answer=null` |
| LLM provider down | `LLMError` | `stop_reason=llm_error`, executions kept |

## Implementation challenges (from the build log)

1. **SDK exception hierarchy.** In e2b 2.63, `SandboxNotRunningException` and `SandboxUnreachableException` subclass `TimeoutException`. A naive `except TimeoutException` would blame the user's code for an infrastructure failure. I verified this from the installed SDK source and pinned it with a test.
2. **Non-zero exit is an exception in the SDK.** `commands.run` raises `CommandExitException` (which is itself a `CommandResult`). The backend converts it back into a normal result, because a failing user script is not a server error.
3. **Cancellation before the first await.** A background task cancelled during shutdown before it ever ran never reached its own error handler, which left records `queued`. A test caught this; the fix is a sweep (`mark_interrupted`) after cancellation.
4. **Agent time budget vs bookkeeping.** When `asyncio.timeout` cancels an in-flight execution, the record must still be finalized (`interrupted`) and the sandbox still killed. Session cleanup lives in an `AsyncExitStack` outside the timeout scope.
5. **Stacked retries.** The E2B SDK already retries control-plane 429/5xx responses. My retry layer adds `SandboxUnreachable` and transport errors and makes retries observable, at the cost of attempts compounding during a sustained outage.

## Live results

Pending: to be filled in from `examples/run_examples.py` and `pytest -m integration` against real E2B, including measured sandbox create latency.

## Lessons learned

Pending: to be written after the live runs.
