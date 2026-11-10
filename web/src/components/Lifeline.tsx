// The one bold element: a microVM's actual life, drawn to scale from real backend events.
import { motion } from "motion/react";
import type { Status } from "../lib/api";
import { ms } from "../lib/format";
import type { Life, Phase } from "../lib/lifecycle";
import { useNow } from "../lib/useNow";

type Seg = "create" | "upload" | "run" | "kill";

const ORDER: Seg[] = ["create", "upload", "run", "kill"];
const LABEL: Record<Seg, string> = {
  create: "Boot microVM",
  upload: "Upload code",
  run: "Run",
  kill: "Destroy",
};
const ACTIVE_SEG: Partial<Record<Phase, Seg>> = {
  creating: "create",
  uploading: "upload",
  running: "run",
  killing: "kill",
};
const OUTCOME_BG: Record<Status, string> = {
  queued: "bg-live",
  running: "bg-live",
  succeeded: "bg-ok",
  failed: "bg-user",
  timed_out: "bg-late",
  error: "bg-infra",
};

export function Lifeline({
  life,
  compact = false,
  hideBoot = false,
}: {
  life: Life;
  compact?: boolean;
  /** Agent runs reuse one sandbox: later calls don't boot or destroy. */
  hideBoot?: boolean;
}) {
  const activeSeg = ACTIVE_SEG[life.phase];
  const now = useNow(activeSeg !== undefined);
  const elapsed = Math.max(0, now - life.phaseSince);

  const value: Record<Seg, number | null> = {
    create: life.createMs,
    upload: life.uploadMs,
    run: life.runMs,
    kill: life.killMs,
  };
  if (activeSeg) value[activeSeg] = elapsed;

  const segs = ORDER.filter((s) => !(hideBoot && (s === "create" || s === "kill")));
  const known = segs.map((s) => value[s] ?? 0);
  const total = known.reduce((a, b) => a + b, 0);
  const floor = Math.max(total * 0.05, 1);
  const status = life.execution?.status;
  const runColor = status ? OUTCOME_BG[status] : "bg-live";
  const idle = life.phase === "idle";

  const colorOf = (s: Seg, isActive: boolean) =>
    s === "run" ? (isActive ? "bg-live" : runColor) : s === "create" ? "bg-live/80" : "bg-live/45";

  return (
    <div className={compact ? "space-y-1.5" : "space-y-3"} aria-live="polite">
      {/* The bar is drawn to scale: each segment's width is its real duration. */}
      <div className="flex items-center gap-1">
        {segs.map((s) => {
          const v = value[s];
          const reached = v != null;
          const isActive = s === activeSeg;
          const grow = idle ? 1 : reached ? Math.max(v ?? 0, floor) : floor * 0.6;
          return (
            <motion.div
              key={s}
              layout
              transition={{ type: "spring", stiffness: 220, damping: 30 }}
              style={{ flexGrow: grow, flexBasis: 0 }}
              className={`relative min-w-[6px] ${compact ? "h-1.5" : "h-3"} overflow-hidden rounded-full bg-line/60`}
            >
              {(reached || isActive) && (
                <motion.div
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: 1 }}
                  transition={{ duration: 0.35, ease: "easeOut" }}
                  style={{ originX: 0 }}
                  className={`absolute inset-0 rounded-full ${colorOf(s, isActive)} ${isActive ? "animate-beat" : ""}`}
                />
              )}
            </motion.div>
          );
        })}
      </div>

      {!compact && (
        <>
          {/* Legend in fixed columns so labels never collide, whatever the proportions. */}
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
            {segs.map((s) => {
              const v = value[s];
              const isActive = s === activeSeg;
              const reached = v != null;
              return (
                <div key={s} className="flex items-baseline gap-2 text-sm">
                  <span
                    className={`h-2 w-2 shrink-0 translate-y-[-1px] rounded-full ${
                      reached || isActive ? colorOf(s, isActive) : "bg-line"
                    }`}
                  />
                  <dt className={reached || isActive ? "text-fg" : "text-muted"}>{LABEL[s]}</dt>
                  <dd className={`ml-auto tabular-nums ${isActive ? "text-live" : "text-muted"}`}>
                    {reached ? ms(v) : isActive ? "…" : ""}
                  </dd>
                </div>
              );
            })}
          </dl>
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-t border-line pt-2.5 text-xs text-muted">
            <span>
              {idle ? (
                "Every run gets a fresh E2B microVM that is destroyed when it finishes."
              ) : life.sandboxId ? (
                <>
                  Sandbox <span className="font-mono text-fg/80">{life.sandboxId}</span>
                  {life.cleanupFailed && (
                    <span className="text-infra">. Destroy failed; its lifetime timeout will reclaim it</span>
                  )}
                </>
              ) : life.phase === "queued" ? (
                "Waiting for a free sandbox slot"
              ) : (
                "Booting a microVM"
              )}
            </span>
            {!idle && total > 0 && (
              <span className="tabular-nums">
                {life.phase === "done" ? "Total " : ""}
                {ms(total)}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
