# Original Project Brief (summary)

The full brief was provided by the project owner on 2026-11-09. Key requirements:

- REST API: `POST /api/v1/executions`, `GET /api/v1/executions/{id}`, `POST /api/v1/agent/run`, `GET /health`.
- Execute untrusted Python only inside E2B sandboxes. Manage the full lifecycle: create, execute, timeout, cleanup.
- Structured results: output, errors, status, duration. Distinguish user-code errors from infrastructure failures.
- Retry only transient infrastructure operations, never code execution.
- An AI agent with structured tool calling, execution limits, loop protection, and no unverified success claims.
- Per-execution records: id, status, timestamps, duration, stdout/stderr, exit code, error category, sandbox id. No secrets in logs.
- Tests: unit tests with mocked E2B, plus optional live integration tests.
- Developer experience: `.env.example`, OpenAPI, examples, Dockerfile, GitHub Actions, README.
- Security: auth, rate limiting, output limits, no credentials exposed, limitations documented honestly.
- Deliverables: working backend and agent, tests, docs, Docker and CI, an engineering case study.
