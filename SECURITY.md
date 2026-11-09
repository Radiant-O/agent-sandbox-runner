# Security

## Threat model

All submitted code is treated as hostile. That includes code written by the AI agent, which can be steered by whoever writes the task. The isolation boundary is **E2B's sandbox (a Firecracker microVM)**, not this application. This service's job is to make sure untrusted code only ever runs *inside* that boundary, with as little reach and as tight limits as practical, and that whatever comes back can't hurt the server.

## Controls in place

| Control | Where |
|---|---|
| Code runs only in E2B sandboxes, never on the API host. There is no `exec`/`eval`/`subprocess` on user input anywhere in `app/`. | `app/sandbox/e2b_backend.py` |
| A fresh sandbox per API execution, and one per agent run. Never shared across callers. | `ExecutionService`, `AgentService` |
| Outbound internet disabled by default (`allow_internet_access=False`). | `SANDBOX_ALLOW_INTERNET` |
| No server secrets in the sandbox: `envs={}` is passed explicitly, and the E2B/LLM keys stay server-side. | `E2BSandboxBackend._create` |
| Per-run timeout, plus a sandbox lifetime timeout as a backstop if `kill()` fails. | `commands.run(timeout=)`, `AsyncSandbox.create(timeout=)` |
| Limits on code size and timeout range. | `MAX_CODE_BYTES`, `MAX_TIMEOUT_SECONDS` |
| Output is byte-capped while streaming (`retain_output=False`, so the SDK keeps no copy). The server holds at most `MAX_OUTPUT_BYTES` per stream per execution. Flooding output still uses network bandwidth until the timeout. | `app/sandbox/output.py` |
| Concurrency cap on live sandboxes, which limits cost and abuse. | `MAX_CONCURRENT_SANDBOXES` |
| API key auth with constant-time comparison. Executions are scoped to the key that created them; other keys get 404. | `app/dependencies.py` |
| Per-key token-bucket rate limit on submissions and agent runs. | `RATE_LIMIT_PER_MINUTE` |
| Agent bounds: max steps, max tool calls, a wall-clock budget, and max tokens per call. | `AGENT_*` settings |
| Logs never contain code bodies (only size and sha256) or configured secrets (redacted). | `app/core/logging.py` |

## What this does **not** guarantee

- **Isolation is E2B's.** A vulnerability in the sandbox or hypervisor is outside this project's control.
- **No static code filtering.** We deliberately don't block imports or keywords. Blocklists are easy to bypass, and they would give false confidence. Containment comes from the sandbox, not from inspecting code.
- **Rate limits and metrics are in-memory and per process.** Behind multiple replicas, each replica enforces its own limit.
- **Output is not sanitized.** stdout/stderr are returned as-is (capped). Clients that render them as HTML must escape them.
- **Agent answers can still be wrong.** The API reports `any_execution_succeeded` and the full execution records so clients can check claims, but the model's prose is not verified.
- **Prompt injection.** Output from code the agent runs is fed back to the model. Hostile output can try to steer the agent; the bounds above limit how much damage that can do, but they don't prevent it.
- **Background executions are in-process.** If the server is restarted, in-flight work is marked `interrupted`; it isn't resumed.
- **API keys are static and come from configuration.** There is no rotation, expiry or per-key quota beyond the rate limit.

## Reporting

Please open a private security advisory on the GitHub repository rather than a public issue.
