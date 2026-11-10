import type { Category, Status, StopReason } from "./api";

export const ms = (v: number | null | undefined): string => {
  if (v == null) return "—";
  if (v < 1000) return `${Math.round(v)} ms`;
  return `${(v / 1000).toFixed(v < 10_000 ? 2 : 1)} s`;
};

export const STATUS_TEXT: Record<Status, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Your code failed",
  timed_out: "Timed out",
  error: "Infrastructure error",
};

/** Whose problem is it? The core distinction this system makes. */
export const FAULT: Record<Status, string> = {
  queued: "Waiting for a free sandbox slot",
  running: "Running inside a fresh microVM",
  succeeded: "Exit code 0",
  failed: "The code raised or exited non-zero. The sandbox worked fine.",
  timed_out: "The code used its whole time budget. The sandbox was destroyed.",
  error: "Not your code: the platform failed. Safe to retry.",
};

export const CATEGORY_TEXT: Record<Category, string> = {
  user_code_error: "user code error",
  timeout: "timeout",
  sandbox_unavailable: "sandbox unavailable",
  upstream_error: "upstream error",
  auth_error: "credentials problem",
  interrupted: "interrupted",
  internal_error: "internal error",
};

export const STATUS_TONE: Record<Status, string> = {
  queued: "text-muted",
  running: "text-live",
  succeeded: "text-ok",
  failed: "text-user",
  timed_out: "text-late",
  error: "text-infra",
};

export const STOP_TEXT: Record<StopReason, string> = {
  completed: "Answered",
  step_limit: "Stopped: step limit reached",
  tool_call_limit: "Stopped: tool-call limit reached",
  time_limit: "Stopped: time budget used up",
  llm_error: "Stopped: the model provider failed",
};
