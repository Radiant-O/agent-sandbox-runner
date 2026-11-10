import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AgentRun, type DemoStatus, type Recordings } from "../lib/api";
import { STATUS_TEXT, STATUS_TONE, STOP_TEXT, ms } from "../lib/format";
import { pushHistory, type HistoryEntry } from "../lib/history";
import { agentReducer, emptyAgent, type AgentView as AV, type TranscriptItem } from "../lib/lifecycle";
import { openStream, replay } from "../lib/stream";
import { Lifeline } from "./Lifeline";
import { Notice, type NoticeState } from "./Notice";
import { noticeFor } from "./RunView";
import { rich } from "../lib/inline";

export function AgentView({
  status,
  prompts,
  recordings,
  takeToken,
  onHistory,
  openRun,
}: {
  status: DemoStatus | null;
  prompts: string[];
  recordings: Recordings | null;
  takeToken: () => Promise<string | null>;
  onHistory: (h: HistoryEntry[]) => void;
  openRun: AgentRun | null;
}) {
  const [task, setTask] = useState("");
  const [view, setView] = useState<AV>(emptyAgent);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const stop = useRef<() => void>(() => {});
  const end = useRef<HTMLDivElement>(null);
  const saved = useRef<string | null>(null);

  const available = status?.agent_available ?? false;
  const left = status?.budget.agent_runs.remaining ?? 1;
  const replayMode = available && left === 0;
  const recorded = recordings?.agent_runs ?? [];

  useEffect(() => () => stop.current(), []);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [view.items.length, view.run]);

  useEffect(() => {
    if (!openRun) return;
    stop.current();
    setView({ ...emptyAgent, runId: openRun.id, run: openRun, task: "Earlier run" });
  }, [openRun]);

  useEffect(() => {
    const run = view.run;
    if (!run || saved.current === run.id || run.id.startsWith("rec_")) return;
    saved.current = run.id;
    onHistory(
      pushHistory({
        kind: "agent",
        id: run.id,
        title: view.task.slice(0, 60) || "Agent run",
        status: run.stop_reason,
        at: Date.now(),
        run,
      }),
    );
  }, [view.run, view.task, onHistory]);

  const start = useCallback(
    async (text: string) => {
      const t = text.trim();
      if (!t || view.active) return;
      stop.current();
      setNotice(null);
      if (replayMode || !available) {
        const rec = recorded.find((r) => r.task === t) ?? recorded[0];
        if (!rec) {
          setNotice({ tone: "user", text: available ? "Today's agent budget is used up." : "The agent isn't configured on this server." });
          return;
        }
        setTask(rec.task);
        setNotice({ tone: "muted", text: "Replaying a recorded real agent run." });
        setView(emptyAgent);
        stop.current = replay(rec.events, (ev) => setView((v) => agentReducer(v, ev, performance.now())));
        return;
      }
      setView({ ...emptyAgent, task: t, active: true });
      try {
        const token = await takeToken();
        const { run_id } = await api.startAgent(t, token);
        stop.current = openStream(
          `/demo/agent/runs/${run_id}/events`,
          (ev) => setView((v) => agentReducer(v, ev, performance.now())),
          () => setView((v) => ({ ...v, active: false, failed: "Lost the live stream for this run." })),
        );
      } catch (err) {
        setView(emptyAgent);
        setNotice(noticeFor(err));
      }
    },
    [view.active, replayMode, available, recorded, takeToken],
  );

  const run = view.run;
  const tools = run?.executions.length ?? view.items.filter((i) => i.kind === "tool").length;

  return (
    <div className="grid min-h-0 flex-1 gap-6 px-4 pb-6 sm:px-6 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)] lg:px-8">
      <aside className="space-y-5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void start(task);
          }}
          className="rounded-2xl border border-line bg-panel p-4"
        >
          <label htmlFor="task" className="text-sm font-medium">
            Give Claude a task
          </label>
          <p className="mt-1 text-sm text-muted">
            It decides whether it needs code, writes it, and runs it in a sandbox through the same
            limits as everyone else.
          </p>
          <textarea
            id="task"
            value={task}
            onChange={(e) => setTask(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start(task);
            }}
            rows={4}
            maxLength={1000}
            placeholder="How many primes are there below 100,000?"
            className="mt-3 w-full resize-none rounded-xl border border-line bg-ink px-3 py-2.5 text-sm placeholder:text-muted/70 focus:border-fg/50 focus:outline-none"
          />
          <button
            type="submit"
            disabled={view.active || !task.trim()}
            className="mt-3 w-full rounded-lg bg-live px-3.5 py-2 text-sm font-semibold text-ink transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {view.active ? "Working…" : replayMode || !available ? "Watch a recorded run" : "Run agent"}
          </button>
        </form>

        {notice && <Notice notice={notice} onClose={() => setNotice(null)} />}

        <div>
          <h2 className="mb-2 px-1 text-sm font-medium text-muted">Or try one of these</h2>
          <ul className="space-y-0.5">
            {prompts.map((p) => (
              <li key={p}>
                <button
                  onClick={() => {
                    setTask(p);
                    void start(p);
                  }}
                  disabled={view.active}
                  className="w-full rounded-xl px-3 py-2 text-left text-sm transition-colors hover:bg-panel disabled:opacity-50"
                >
                  {p}
                </button>
              </li>
            ))}
          </ul>
        </div>

        {status && (
          <p className="px-1 text-xs leading-relaxed text-muted">
            Bounded to {status.limits.agent_max_steps} model steps and{" "}
            {status.limits.agent_max_tool_calls} code runs. {status.model && <>Model: {status.model}. </>}
            {left} agent runs left today.
          </p>
        )}
      </aside>

      <section aria-label="Agent transcript" aria-live="polite" className="min-w-0">
        {view.items.length === 0 && !run && !view.active ? (
          <EmptyTranscript />
        ) : (
          <ol className="space-y-4">
            {view.task && (
              <li className="text-xl font-semibold tracking-tight">{view.task}</li>
            )}
            <AnimatePresence initial={false}>
              {view.items.map((it, i) => (
                <motion.li
                  key={i}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25 }}
                >
                  <Item item={it} run={run} />
                </motion.li>
              ))}
            </AnimatePresence>
            {view.active && view.items.length === 0 && (
              <li className="text-sm text-muted">Asking the model…</li>
            )}
            {run && <Outcome run={run} tools={tools} />}
            {view.failed && <li className="text-sm text-infra">{view.failed}</li>}
          </ol>
        )}
        <div ref={end} />
      </section>
    </div>
  );
}

function Item({ item, run }: { item: TranscriptItem; run: AgentRun | null }) {
  switch (item.kind) {
    case "step":
      return <div className="pt-2 text-xs text-muted">Model step {item.step}</div>;
    case "thought":
      return <div className="max-w-prose text-[0.95rem] leading-relaxed text-fg/90">{rich(item.text)}</div>;
    case "answer":
      return (
        <div className="max-w-prose rounded-2xl border border-line bg-panel px-5 py-4">
          <div className="text-[0.97rem] leading-relaxed">{rich(item.text)}</div>
          {run && <Verification run={run} />}
        </div>
      );
    case "tool": {
      const r = item.result;
      const status = typeof r?.status === "string" ? (r.status as keyof typeof STATUS_TEXT) : null;
      const out = typeof r?.stdout === "string" ? r.stdout : "";
      const err = typeof r?.error === "string" ? r.error : null;
      return (
        <div className="overflow-hidden rounded-2xl border border-line bg-panel">
          <div className="flex items-center justify-between border-b border-line px-4 py-2 text-xs text-muted">
            <span>Claude wrote and ran</span>
            {item.life.sandboxId && <span className="font-mono">{item.life.sandboxId}</span>}
          </div>
          <pre className="scrollbar-thin max-h-64 overflow-auto px-4 py-3 font-mono text-[0.8rem] leading-relaxed text-fg/90">
            {item.code}
          </pre>
          <div className="border-t border-line px-4 py-3">
            <Lifeline life={item.life} outcome={status} compact hideBoot={item.life.createMs == null} />
            <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
              {status ? (
                <span className={`font-medium ${STATUS_TONE[status]}`}>{STATUS_TEXT[status]}</span>
              ) : err ? (
                <span className="font-medium text-user">Rejected before running</span>
              ) : (
                <span className="text-live">Running…</span>
              )}
              {typeof r?.exception_type === "string" && (
                <span className="font-mono text-xs text-muted">{r.exception_type}</span>
              )}
              {typeof r?.duration_ms === "number" && (
                <span className="text-xs text-muted">{ms(r.duration_ms)}</span>
              )}
            </div>
            {(out || err) && (
              <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-ink px-3 py-2 font-mono text-xs text-fg/85">
                {err ?? out}
              </pre>
            )}
          </div>
        </div>
      );
    }
  }
}

function Verification({ run }: { run: AgentRun }) {
  const ok = run.executions.filter((e) => e.status === "succeeded").length;
  const n = run.executions.length;
  if (n === 0)
    return (
      <p className="mt-3 border-t border-line pt-3 text-xs text-muted">
        Answered without running code. Nothing for the backend to verify.
      </p>
    );
  return (
    <p className={`mt-3 border-t border-line pt-3 text-xs ${run.any_execution_succeeded ? "text-ok" : "text-user"}`}>
      {run.any_execution_succeeded
        ? `Backed by the backend's records: ${ok} of ${n} sandbox runs succeeded.`
        : `Unverified: none of the ${n} sandbox runs succeeded, so treat this answer with care.`}
    </p>
  );
}

function Outcome({ run, tools }: { run: AgentRun; tools: number }) {
  if (run.stop_reason === "completed") {
    return (
      <li className="text-xs text-muted">
        {run.steps} model {run.steps === 1 ? "step" : "steps"}, {tools} code {tools === 1 ? "run" : "runs"}.
      </li>
    );
  }
  return (
    <li className="rounded-xl border border-user/40 px-4 py-3 text-sm text-user">
      {STOP_TEXT[run.stop_reason]}. The agent gives no answer when it stops early, rather than
      guessing.
    </li>
  );
}

function EmptyTranscript() {
  return (
    <div className="flex h-full min-h-[20rem] flex-col justify-center rounded-2xl border border-dashed border-line px-8 py-10">
      <p className="max-w-md text-xl font-semibold tracking-tight">
        Watch an agent think, write code, and prove its answer.
      </p>
      <p className="mt-2 max-w-md text-sm text-muted">
        Each piece of code it writes runs in an isolated microVM. The answer is checked against what
        the sandbox actually returned, not what the model claims.
      </p>
    </div>
  );
}
