// Typed client for the public /demo API. The browser never holds a credential:
// every request is anonymous and the server applies its own limits.

export type Status = "queued" | "running" | "succeeded" | "failed" | "timed_out" | "error";
export type Category =
  | "user_code_error"
  | "timeout"
  | "sandbox_unavailable"
  | "upstream_error"
  | "auth_error"
  | "interrupted"
  | "internal_error";

export interface Execution {
  id: string;
  status: Status;
  source: "api" | "agent";
  agent_run_id: string | null;
  code_size: number;
  timeout_seconds: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
  exit_code: number | null;
  error_category: Category | null;
  error_message: string | null;
  exception_type: string | null;
  sandbox_id: string | null;
  create_ms: number | null;
  upload_ms: number | null;
  run_ms: number | null;
  kill_ms: number | null;
}

export type StopReason = "completed" | "step_limit" | "tool_call_limit" | "time_limit" | "llm_error";

export interface AgentRun {
  id: string;
  stop_reason: StopReason;
  answer: string | null;
  executions: Execution[];
  any_execution_succeeded: boolean;
  steps: number;
  tool_calls: number;
}

export interface Example {
  id: string;
  group?: string;
  title: string;
  expect: Status;
  blurb: string;
  code: string;
  timeout_seconds: number;
}

export interface Metrics {
  executions_by_status: Partial<Record<Status, number>>;
  execution_duration_ms_p50: number | null;
  execution_duration_ms_p95: number | null;
  sandboxes_live: number;
  sandboxes_created_total: number;
  sandbox_create_ms_avg: number | null;
  cleanup_failures_total: number;
  create_retries_total: number;
  agent_runs_by_stop_reason: Partial<Record<StopReason, number>>;
}

export interface DemoStatus {
  agent_available: boolean;
  turnstile_site_key: string | null;
  repo_url: string | null;
  model: string | null;
  budget: {
    runs: { total: number; remaining: number };
    agent_runs: { total: number; remaining: number };
    resets_at: string;
  };
  limits: {
    max_timeout_seconds: number;
    default_timeout_seconds: number;
    max_code_bytes: number;
    max_output_bytes: number;
    runs_per_hour: number;
    agent_runs_per_hour: number;
    agent_max_steps: number;
    agent_max_tool_calls: number;
    internet: boolean;
  };
  metrics: Metrics;
}

export interface StreamEvent {
  seq: number;
  type: string;
  ts: number;
  data: Record<string, unknown>;
}

export interface Recordings {
  executions: Record<string, { events: StreamEvent[] }>;
  agent_runs: { task: string; events: StreamEvent[] }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public retryAfter: number | null = null,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, "offline", "Can't reach the server. Check your connection and retry.");
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    let message = res.statusText || "Request failed.";
    try {
      const body = await res.json();
      code = body?.error?.code ?? code;
      message = body?.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    const ra = res.headers.get("Retry-After");
    throw new ApiError(res.status, code, message, ra ? Number(ra) : null);
  }
  return (await res.json()) as T;
}

export const api = {
  status: () => request<DemoStatus>("/demo/status"),
  examples: () => request<Example[]>("/demo/examples"),
  agentExamples: () => request<string[]>("/demo/agent/examples"),
  recordings: () => request<Recordings>("/demo/recordings"),
  getExecution: (id: string) => request<Execution>(`/demo/executions/${id}`),
  run: (code: string, timeout_seconds: number | null, turnstile_token: string | null) =>
    request<Execution>("/demo/executions", {
      method: "POST",
      body: JSON.stringify({ code, timeout_seconds, turnstile_token }),
    }),
  startAgent: (task: string, turnstile_token: string | null) =>
    request<{ run_id: string }>("/demo/agent/runs", {
      method: "POST",
      body: JSON.stringify({ task, turnstile_token }),
    }),
};
