// Pure reducers that turn the backend's real lifecycle events into view state.
import type { AgentRun, Execution, StreamEvent } from "./api";

export type Phase = "idle" | "queued" | "creating" | "uploading" | "running" | "killing" | "done";

export interface OutputChunk {
  stream: "stdout" | "stderr";
  text: string;
}

export interface Life {
  phase: Phase;
  executionId: string | null;
  sandboxId: string | null;
  createMs: number | null;
  uploadMs: number | null;
  runMs: number | null;
  killMs: number | null;
  /** client clock (performance.now) when the current phase started, for live growth */
  phaseSince: number;
  output: OutputChunk[];
  outputBytes: number;
  exitCode: number | null;
  timedOut: boolean;
  cleanupFailed: boolean;
  execution: Execution | null;
}

export const emptyLife: Life = {
  phase: "idle",
  executionId: null,
  sandboxId: null,
  createMs: null,
  uploadMs: null,
  runMs: null,
  killMs: null,
  phaseSince: 0,
  output: [],
  outputBytes: 0,
  exitCode: null,
  timedOut: false,
  cleanupFailed: false,
  execution: null,
};

const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

function appendOutput(life: Life, stream: "stdout" | "stderr", text: string): Life {
  const last = life.output[life.output.length - 1];
  const output =
    last && last.stream === stream
      ? [...life.output.slice(0, -1), { stream, text: last.text + text }]
      : [...life.output, { stream, text }];
  return { ...life, output, outputBytes: life.outputBytes + text.length };
}

export function lifeReducer(life: Life, ev: StreamEvent, now: number): Life {
  const d = ev.data;
  switch (ev.type) {
    case "queued":
      return { ...emptyLife, phase: "queued", executionId: String(d.execution_id ?? ""), phaseSince: now };
    case "sandbox_creating":
      return { ...life, phase: "creating", phaseSince: now };
    case "sandbox_created":
      return {
        ...life,
        phase: "uploading",
        sandboxId: String(d.sandbox_id ?? ""),
        createMs: num(d.create_ms),
        phaseSince: now,
      };
    case "code_uploaded":
      return { ...life, phase: "running", uploadMs: num(d.upload_ms), phaseSince: now };
    case "stdout":
    case "stderr":
      return appendOutput(life, ev.type, String(d.data ?? ""));
    case "exited":
      return {
        ...life,
        phase: "killing",
        runMs: num(d.run_ms),
        exitCode: num(d.exit_code),
        timedOut: Boolean(d.timed_out),
        phaseSince: now,
      };
    case "sandbox_killed":
      return { ...life, killMs: num(d.kill_ms) };
    case "cleanup_failed":
      return { ...life, cleanupFailed: true };
    case "finished": {
      const execution = d.execution as Execution;
      return fromExecution(execution, life.output.length ? life.output : undefined);
    }
    default:
      return life;
  }
}

/** Static view of a stored execution (history, or a stream that already expired). */
export function fromExecution(e: Execution, output?: OutputChunk[]): Life {
  const chunks: OutputChunk[] =
    output ??
    [
      ...(e.stdout ? [{ stream: "stdout" as const, text: e.stdout }] : []),
      ...(e.stderr ? [{ stream: "stderr" as const, text: e.stderr }] : []),
    ];
  return {
    ...emptyLife,
    phase: "done",
    executionId: e.id,
    sandboxId: e.sandbox_id,
    createMs: e.create_ms,
    uploadMs: e.upload_ms,
    runMs: e.run_ms,
    killMs: e.kill_ms,
    output: chunks,
    outputBytes: chunks.reduce((n, c) => n + c.text.length, 0),
    exitCode: e.exit_code,
    timedOut: e.status === "timed_out",
    execution: e,
  };
}

// ---- agent transcript -------------------------------------------------------------

export type TranscriptItem =
  | { kind: "step"; step: number }
  | { kind: "thought"; text: string }
  | { kind: "tool"; callId: string; code: string; life: Life; result: Record<string, unknown> | null }
  | { kind: "answer"; text: string };

export interface AgentView {
  runId: string | null;
  task: string;
  items: TranscriptItem[];
  session: { sandboxId: string | null; createMs: number | null; killed: boolean };
  run: AgentRun | null;
  failed: string | null;
  active: boolean;
}

export const emptyAgent: AgentView = {
  runId: null,
  task: "",
  items: [],
  session: { sandboxId: null, createMs: null, killed: false },
  run: null,
  failed: null,
  active: false,
};

const EXEC_EVENTS = new Set(["code_uploaded", "stdout", "stderr", "exited"]);

export function agentReducer(view: AgentView, ev: StreamEvent, now: number): AgentView {
  const d = ev.data;
  switch (ev.type) {
    case "started":
      return { ...emptyAgent, runId: String(d.run_id), task: String(d.task ?? ""), active: true };
    case "step_started":
      return { ...view, items: [...view.items, { kind: "step", step: Number(d.step) }] };
    case "model_text":
      return d.final
        ? { ...view, items: [...view.items, { kind: "answer", text: String(d.text) }] }
        : { ...view, items: [...view.items, { kind: "thought", text: String(d.text) }] };
    case "tool_call": {
      const life: Life = { ...emptyLife, phase: "queued", phaseSince: now };
      return {
        ...view,
        items: [
          ...view.items,
          { kind: "tool", callId: String(d.call_id), code: String(d.code ?? ""), life, result: null },
        ],
      };
    }
    case "sandbox_creating":
      return mapLastTool(view, (t) => ({ ...t, life: lifeReducer(t.life, ev, now) }));
    case "sandbox_created":
      return {
        ...mapLastTool(view, (t) => ({ ...t, life: lifeReducer(t.life, ev, now) })),
        session: { sandboxId: String(d.sandbox_id), createMs: num(d.create_ms), killed: false },
      };
    case "tool_result":
      return mapTool(view, String(d.call_id), (t) => ({
        ...t,
        result: d,
        life: { ...t.life, phase: "done" },
      }));
    case "sandbox_killed":
      return { ...view, session: { ...view.session, killed: true } };
    case "finished":
      return { ...view, run: d.run as AgentRun, active: false };
    case "failed":
      return { ...view, failed: String(d.message ?? "Agent run failed."), active: false };
    default:
      if (EXEC_EVENTS.has(ev.type)) {
        return mapLastTool(view, (t) => {
          // A reused session skips create: start the tool's life at "uploading".
          const base =
            t.life.phase === "queued"
              ? { ...t.life, phase: "uploading" as Phase, sandboxId: view.session.sandboxId }
              : t.life;
          return { ...t, life: lifeReducer(base, ev, now) };
        });
      }
      return view;
  }
}

type ToolItem = Extract<TranscriptItem, { kind: "tool" }>;

function mapLastTool(view: AgentView, f: (t: ToolItem) => ToolItem): AgentView {
  for (let i = view.items.length - 1; i >= 0; i--) {
    const it = view.items[i];
    if (it.kind === "tool") {
      const items = view.items.slice();
      items[i] = f(it);
      return { ...view, items };
    }
  }
  return view;
}

function mapTool(view: AgentView, callId: string, f: (t: ToolItem) => ToolItem): AgentView {
  return {
    ...view,
    items: view.items.map((it) => (it.kind === "tool" && it.callId === callId ? f(it) : it)),
  };
}
