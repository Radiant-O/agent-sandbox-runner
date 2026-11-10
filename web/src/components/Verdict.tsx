import { AnimatePresence, motion } from "motion/react";
import { CATEGORY_TEXT, FAULT, STATUS_TEXT, STATUS_TONE, ms } from "../lib/format";
import type { Life } from "../lib/lifecycle";

const DOT: Record<string, string> = {
  succeeded: "bg-ok",
  failed: "bg-user",
  timed_out: "bg-late",
  error: "bg-infra",
};

export function Verdict({ life }: { life: Life }) {
  const e = life.execution;
  return (
    <AnimatePresence mode="wait">
      {e ? (
        <motion.div
          key={e.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.25 }}
          className="flex flex-wrap items-center gap-x-6 gap-y-2"
        >
          <div className="flex items-center gap-2.5">
            <span className={`h-2.5 w-2.5 rounded-full ${DOT[e.status] ?? "bg-muted"}`} />
            <span className={`text-lg font-semibold tracking-tight ${STATUS_TONE[e.status]}`}>
              {STATUS_TEXT[e.status]}
            </span>
          </div>
          <p className="text-sm text-muted">
            {e.status === "error" && e.error_message ? e.error_message : FAULT[e.status]}
          </p>
          <dl className="ml-auto flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <Fact k="Exit code" v={e.exit_code ?? "—"} />
            {e.exception_type && <Fact k="Exception" v={e.exception_type} mono />}
            {e.error_category && <Fact k="Category" v={CATEGORY_TEXT[e.error_category]} />}
            <Fact k="Duration" v={ms(e.duration_ms)} />
          </dl>
        </motion.div>
      ) : (
        <motion.p key="none" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="text-sm text-muted">
          {life.phase === "idle"
            ? "The verdict says whether a failure was your code or the platform."
            : "Running…"}
        </motion.p>
      )}
    </AnimatePresence>
  );
}

function Fact({ k, v, mono = false }: { k: string; v: string | number; mono?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-muted">{k}</dt>
      <dd className={`tabular-nums text-fg ${mono ? "font-mono text-[0.8rem]" : ""}`}>{v}</dd>
    </div>
  );
}
