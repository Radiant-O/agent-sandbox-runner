import { useEffect, useRef } from "react";
import type { Life } from "../lib/lifecycle";

export function Terminal({
  life,
  maxOutputBytes,
  timeoutS,
  className = "",
}: {
  life: Life;
  maxOutputBytes: number;
  timeoutS?: number;
  className?: string;
}) {
  const ref = useRef<HTMLPreElement>(null);
  const stick = useRef(true);

  useEffect(() => {
    const el = ref.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [life.output]);

  const truncated = life.execution?.stdout_truncated || life.execution?.stderr_truncated;
  const empty = life.output.length === 0;
  const running = life.phase !== "idle" && life.phase !== "done";

  return (
    <div className={`relative flex min-h-0 flex-col ${className}`}>
      <pre
        ref={ref}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
        }}
        className="scrollbar-thin min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-[0.8rem] leading-relaxed"
        aria-label="Program output"
        tabIndex={0}
      >
        <span className="select-none text-muted">
          <span className="text-live">sandbox</span>:~$ python main.py{"\n"}
        </span>
        {empty ? (
          <span className="text-muted">
            {life.phase === "idle"
              ? "# Press Run. Output streams here as the sandbox prints it.\n"
              : running
                ? ""
                : "# The program printed nothing.\n"}
          </span>
        ) : (
          life.output.map((c, i) => (
            <span key={i} className={c.stream === "stderr" ? "text-infra/90" : "text-fg/90"}>
              {c.text}
            </span>
          ))
        )}
        {life.phase === "done" && life.execution && (
          <span className="select-none text-muted">
            {"\n"}
            {exitLine(life, timeoutS)}
          </span>
        )}
        {(running || life.phase === "idle") && <span className="ml-0.5 inline-block h-[1em] w-[0.5em] translate-y-[2px] animate-beat bg-live/80" />}
      </pre>
      {truncated && (
        <div className="border-t border-line px-4 py-2 text-xs text-user">
          Output capped at {Math.round(maxOutputBytes / 1024)} KB per stream. The server kept the
          first part and discarded the rest.
        </div>
      )}
    </div>
  );
}

function exitLine(life: Life, timeoutS?: number): string {
  const e = life.execution;
  if (!e) return "";
  if (e.status === "timed_out") return `[killed at the ${timeoutS ?? e.timeout_seconds} s timeout]`;
  if (e.status === "error") return "[platform error: the run never completed]";
  const secs = e.duration_ms != null ? ` in ${(e.duration_ms / 1000).toFixed(2)} s` : "";
  return `[exited with code ${e.exit_code ?? "?"}${secs}]`;
}
