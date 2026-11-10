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
      <section aria-label="Sandbox lifecycle" className="rounded-2xl border border-line bg-panel px-5 py-4">
        <Lifeline life={life} />
      </section>

      {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}

      <div className="grid min-h-0 flex-1 gap-5 lg:grid-cols-[14.5rem_minmax(0,1fr)_minmax(0,1fr)] lg:grid-rows-[minmax(0,1fr)]">
        <nav aria-label="Examples" className="scrollbar-thin min-h-0 min-w-0 lg:overflow-y-auto">
          <h2 className="mb-2 px-1 text-sm font-medium text-muted">Try a scenario</h2>
          <ul className="scrollbar-thin flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:gap-0.5 lg:overflow-visible">
            {examples.map((ex) => {
              const on = ex.id === selected;
              return (
                <li key={ex.id} className="shrink-0">
                  <button
                    onClick={() => pick(ex)}
                    aria-pressed={on}
                    className={`group w-full rounded-xl px-3 py-2.5 text-left transition-colors ${
                      on ? "bg-raised" : "hover:bg-panel"
                    }`}
                  >
                    <span className="flex items-center gap-2 text-sm font-medium">
                      <span className={`h-1.5 w-1.5 rounded-full ${EXPECT_DOT[ex.expect] ?? "bg-muted"}`} />
                      {ex.title}
                    </span>
                    <span className="mt-0.5 hidden text-xs leading-snug text-muted lg:block">{ex.blurb}</span>
                  </button>
                </li>
              );
            })}
          </ul>
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
                className="w-20 accent-[rgb(var(--live))]"
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
          <Terminal life={life} maxOutputBytes={status?.limits.max_output_bytes ?? 65536} className="flex-1" />
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
