import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, type DemoStatus, type Example, type Recordings } from "../lib/api";
import { pushHistory, type HistoryEntry } from "../lib/history";
import { emptyLife, fromExecution, lifeReducer, type Life } from "../lib/lifecycle";
import { openStream, replay } from "../lib/stream";
import { CodeEditor } from "./CodeEditor";
import { Lifeline } from "./Lifeline";
import { Notice, type NoticeState } from "./Notice";
import { Terminal } from "./Terminal";
import { Verdict } from "./Verdict";

const EXPECT_TEXT: Record<string, string> = {
  succeeded: "exit 0",
  failed: "fails",
  timed_out: "times out",
  error: "errors",
};

const NARRATION: Record<Life["phase"], string> = {
  idle: "",
  queued: "Waiting for a free sandbox slot",
  creating: "Booting a fresh microVM",
  uploading: "Uploading main.py",
  running: "Running main.py",
  killing: "Destroying the microVM",
  done: "",
};

function groupExamples(examples: Example[]): [string, Example[]][] {
  const out = new Map<string, Example[]>();
  for (const ex of examples) {
    const g = ex.group ?? "Examples";
    out.set(g, [...(out.get(g) ?? []), ex]);
  }
  return [...out.entries()];
}

const EXPECT_DOT: Record<string, string> = {
  succeeded: "bg-ok",
  failed: "bg-user",
  timed_out: "bg-late",
  error: "bg-infra",
};

export function RunView({
  status,
  examples,
  recordings,
  takeToken,
  onHistory,
  onFinished,
  openId,
}: {
  status: DemoStatus | null;
  examples: Example[];
  recordings: Recordings | null;
  takeToken: () => Promise<string | null>;
  onHistory: (h: HistoryEntry[]) => void;
  onFinished: (life: Life) => void;
  openId: string | null;
}) {
  const [selected, setSelected] = useState<string>("success");
  const [code, setCode] = useState("");
  const [timeout, setTimeoutS] = useState(10);
  const [life, setLife] = useState<Life>(emptyLife);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const stop = useRef<() => void>(() => {});
  const recorded = useRef(false);

  const example = examples.find((e) => e.id === selected);
  useEffect(() => {
    if (example && !code) {
      setCode(example.code);
      setTimeoutS(example.timeout_seconds);
    }
  }, [example, code]);

  // Re-open a run from history.
  useEffect(() => {
    if (!openId) return;
    stop.current();
    api
      .getExecution(openId)
      .then((e) => setLife(fromExecution(e)))
      .catch(() => setNotice({ tone: "infra", text: "That run is no longer available." }));
  }, [openId]);

  // Record finished runs once.
  useEffect(() => {
    const e = life.execution;
    if (life.phase !== "done" || !e || recorded.current) return;
    recorded.current = true;
    setBusy(false);
    onFinished(life);
    if (!e.id.startsWith("rec_")) {
      onHistory(
        pushHistory({
          kind: "exec",
          id: e.id,
          title: example?.code === code ? example.title : "Custom code",
          status: e.status,
          at: Date.now(),
        }),
      );
    }
  }, [life, onHistory, onFinished, example, code]);

  useEffect(() => () => stop.current(), []);

  const budgetLeft = status?.budget.runs.remaining ?? 1;
  const recording = recordings?.executions[selected];
  const replayMode = budgetLeft === 0;
  const canReplay = replayMode && !!recording && example?.code === code;
  const maxTimeout = status?.limits.max_timeout_seconds ?? 15;

  const pick = (ex: Example) => {
    if (busy) return;
    setSelected(ex.id);
    setCode(ex.code);
    setTimeoutS(Math.min(ex.timeout_seconds, maxTimeout));
    setNotice(null);
  };

  const run = useCallback(async () => {
    if (busy || !code.trim()) return;
    stop.current();
    setNotice(null);
    recorded.current = false;
    setBusy(true);

    if (replayMode) {
      if (!recording || example?.code !== code) {
        setBusy(false);
        setNotice({
          tone: "user",
          text: "Today's live budget is used up. Pick an example to watch a recorded real run.",
        });
        return;
      }
      setNotice({ tone: "muted", text: "Replaying a recorded real run. Live runs resume at midnight UTC." });
      setLife(emptyLife);
      stop.current = replay(recording.events, (ev) => setLife((l) => lifeReducer(l, ev, performance.now())));
      return;
    }

    try {
      const token = await takeToken();
      const rec = await api.run(code, timeout, token);
      setLife({ ...emptyLife, phase: "queued", executionId: rec.id, phaseSince: performance.now() });
      stop.current = openStream(
        `/demo/executions/${rec.id}/events`,
        (ev) => setLife((l) => lifeReducer(l, ev, performance.now())),
        () => api.getExecution(rec.id).then((e) => setLife(fromExecution(e))),
      );
    } catch (err) {
      setBusy(false);
      setNotice(noticeFor(err));
    }
  }, [busy, code, timeout, takeToken, replayMode, recording, example]);

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-5 px-4 pb-5 sm:px-6 lg:px-8">
      <section aria-label="Sandbox lifecycle" className="rounded-2xl border border-line bg-panel px-5 pb-4 pt-5">
        <RunHeadline life={life} bootAvgMs={status?.metrics.sandbox_create_ms_avg ?? null} />
        <div className="mt-4">
          <Lifeline life={life} />
        </div>
      </section>

      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}

      <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[14.5rem_minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
        <nav aria-label="Examples" className="scrollbar-thin min-h-0 min-w-0 lg:overflow-y-auto">
          <div className="scrollbar-thin flex gap-4 overflow-x-auto pb-1 lg:flex-col lg:gap-5 lg:overflow-visible">
            {groupExamples(examples).map(([group, items]) => (
              <div key={group} className="shrink-0">
                <h2 className="mb-1.5 hidden px-3 text-xs font-medium text-muted lg:block">{group}</h2>
                <ul className="flex gap-1 lg:flex-col lg:gap-0.5">
                  {items.map((ex) => {
                    const on = ex.id === selected;
                    return (
                      <li key={ex.id} className="shrink-0">
                        <button
                          onClick={() => pick(ex)}
                          aria-pressed={on}
                          className={`relative w-full rounded-xl px-3 py-2 text-left transition-colors ${
                            on ? "bg-raised" : "hover:bg-panel"
                          }`}
                        >
                          <span className="flex items-center gap-2 whitespace-nowrap text-sm">
                            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${EXPECT_DOT[ex.expect] ?? "bg-muted"}`} />
                            <span className={on ? "font-medium text-fg" : "text-fg/85"}>{ex.title}</span>
                            <span className="ml-auto hidden pl-2 text-[0.7rem] text-muted lg:inline">
                              {EXPECT_TEXT[ex.expect]}
                            </span>
                          </span>
                          {on && (
                            <span className="mt-1 hidden pl-3.5 text-xs leading-snug text-muted lg:block">{ex.blurb}</span>
                          )}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </div>
        </nav>

        <section aria-label="Code" className="flex min-h-[18rem] min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-panel">
          <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
            <span className="font-mono text-xs text-muted">main.py</span>
            <label className="ml-auto flex items-center gap-2 text-xs text-muted">
              Timeout
              <input
                type="range"
                min={1}
                max={maxTimeout}
                value={timeout}
                onChange={(e) => setTimeoutS(Number(e.target.value))}
                className="w-20 accent-[rgb(var(--fg))]"
                aria-valuetext={`${timeout} seconds`}
              />
              <span className="w-7 tabular-nums text-fg">{timeout}s</span>
            </label>
            <button
              onClick={run}
              disabled={busy || (replayMode && !canReplay)}
              className="rounded-lg bg-live px-3.5 py-1.5 text-sm font-semibold text-ink transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "Running…" : canReplay ? "Replay run" : "Run"}
              <kbd className="ml-2 hidden font-sans text-xs font-normal opacity-70 sm:inline">Ctrl ↵</kbd>
            </button>
          </div>
          <div className="min-h-0 flex-1">
            <CodeEditor value={code} onChange={setCode} onRun={run} />
          </div>
        </section>

        <section aria-label="Output" className="flex min-h-[18rem] min-w-0 flex-col overflow-hidden rounded-2xl border border-line bg-[rgb(var(--ink))]">
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5 text-xs text-muted">
            <span>Output</span>
            <span className="flex items-center gap-3">
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-fg/70" />stdout
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-1.5 w-1.5 rounded-full bg-infra" />stderr
              </span>
            </span>
          </div>
          <Terminal life={life} timeoutS={timeout} maxOutputBytes={status?.limits.max_output_bytes ?? 65536} className="flex-1" />
        </section>
      </div>

      <section aria-label="Result" className="rounded-2xl border border-line bg-panel px-5 py-4">
        <Verdict life={life} />
      </section>
    </div>
  );
}

export function noticeFor(err: unknown): NoticeState {
  if (err instanceof ApiError) {
    switch (err.code) {
      case "rate_limited":
        return { tone: "user", text: err.message, retryAfter: err.retryAfter ?? undefined };
      case "demo_budget_exhausted":
        return { tone: "user", text: "Today's live budget is used up. Examples now replay recorded real runs." };
      case "turnstile_required":
      case "turnstile_failed":
        return { tone: "infra", text: "The bot check didn't pass. Wait a moment and run again." };
      case "code_too_large":
      case "timeout_out_of_range":
        return { tone: "user", text: err.message };
      case "offline":
        return { tone: "infra", text: err.message };
    }
    return { tone: "infra", text: err.message };
  }
  return { tone: "infra", text: "Something went wrong. Try again." };
}

function RunHeadline({ life, bootAvgMs }: { life: Life; bootAvgMs: number | null }) {
  const e = life.execution;
  if (life.phase === "idle") {
    return (
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-1">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
          Your code gets its own microVM. It lives for one run.
        </h1>
        <p className="text-sm text-muted">
          {bootAvgMs ? `Boots in about ${Math.round(bootAvgMs)} ms on E2B` : "Isolated by E2B"}
        </p>
      </div>
    );
  }
  const text =
    life.phase === "done"
      ? e?.status === "succeeded"
        ? "Finished. The microVM is gone."
        : e?.status === "error"
          ? "The platform failed this run. Not your code."
          : "Run ended. The microVM is gone."
      : NARRATION[life.phase];
  return (
    <div className="flex items-center gap-3" aria-live="polite">
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${life.phase === "done" ? "bg-muted" : "animate-beat bg-live"}`}
      />
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">
        {text}
        {life.phase !== "done" && <span className="text-muted">…</span>}
      </h1>
    </div>
  );
}
