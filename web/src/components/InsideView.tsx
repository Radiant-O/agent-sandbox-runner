import type { DemoStatus, Status } from "../lib/api";
import { ms } from "../lib/format";

type Outcome = Exclude<Status, "queued" | "running">;

const STAGES: { name: string; does: string[] }[] = [
  { name: "Your browser", does: ["Holds no keys", "Talks only to this server"] },
  {
    name: "Demo gate",
    does: ["Bot check (Turnstile)", "Per-visitor hourly limit", "Daily spend budget"],
  },
  {
    name: "Execution service",
    does: ["Size and timeout policy", "Concurrency cap", "Every run recorded"],
  },
  {
    name: "E2B backend",
    does: ["Create, retried with one idempotency key", "Output capped while streaming", "Always destroyed"],
  },
  { name: "microVM", does: ["No internet", "No server secrets", "Lives for one run"] },
];

const OUTCOMES: { key: Outcome; label: string; who: string; tone: string; ring: string }[] = [
  { key: "succeeded", label: "Succeeded", who: "Exit code 0", tone: "text-ok", ring: "border-ok" },
  { key: "failed", label: "Your code failed", who: "Non-zero exit", tone: "text-user", ring: "border-user" },
  { key: "timed_out", label: "Timed out", who: "Used its full budget", tone: "text-late", ring: "border-late" },
  { key: "error", label: "Platform error", who: "Not your code", tone: "text-infra", ring: "border-infra" },
];

const BAR: Record<Outcome, string> = {
  succeeded: "bg-ok",
  failed: "bg-user",
  timed_out: "bg-late",
  error: "bg-infra",
};

export function InsideView({ status, last }: { status: DemoStatus | null; last: Outcome | null }) {
  const m = status?.metrics;
  const counts = OUTCOMES.map((o) => ({ ...o, n: m?.executions_by_status[o.key] ?? 0 }));
  const total = counts.reduce((a, c) => a + c.n, 0);

  return (
    <div className="space-y-10 px-4 pb-10 sm:px-6 lg:px-8">
      <section aria-labelledby="path-h">
        <h2 id="path-h" className="text-2xl font-semibold tracking-tight">
          The path every line of code takes
        </h2>
        <p className="mt-1 max-w-prose text-sm text-muted">
          {last
            ? "Highlighted: where your last run ended up."
            : "Run something and its outcome lights up here."}
        </p>

        <ol className="mt-6 grid gap-3 md:grid-cols-5 md:gap-6">
          {STAGES.map((s, i) => (
            <li
              key={s.name}
              className={`relative rounded-2xl border bg-panel p-4 transition-colors ${
                last ? "border-fg/30" : "border-line"
              }`}
            >
              <div className="flex items-baseline gap-2">
                <span className="text-xs tabular-nums text-muted">{i + 1}</span>
                <h3 className="font-semibold">{s.name}</h3>
              </div>
              <ul className="mt-2 space-y-1 text-sm text-muted">
                {s.does.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
              {i < STAGES.length - 1 && (
                <svg
                  aria-hidden
                  viewBox="0 0 24 12"
                  className={`absolute -right-[1.3rem] top-1/2 hidden h-3 w-5 -translate-y-1/2 md:block ${
                    last ? "text-fg/60" : "text-line"
                  }`}
                >
                  <path d="M0 6h20M15 1l6 5-6 5" fill="none" stroke="currentColor" strokeWidth="1.5" />
                </svg>
              )}
            </li>
          ))}
        </ol>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 md:grid-cols-4">
          {OUTCOMES.map((o) => {
            const hit = last === o.key;
            return (
              <div
                key={o.key}
                className={`rounded-2xl border px-4 py-3 transition-colors ${hit ? `${o.ring} bg-raised` : "border-line"}`}
              >
                <p className={`font-semibold ${hit ? o.tone : "text-fg"}`}>{o.label}</p>
                <p className="text-sm text-muted">{o.who}</p>
              </div>
            );
          })}
        </div>
      </section>

      <section aria-labelledby="live-h" className="grid gap-8 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div>
          <h2 id="live-h" className="text-2xl font-semibold tracking-tight">
            Live on this server
          </h2>
          <p className="mt-1 text-sm text-muted">Since the server last started. Refreshes every few seconds.</p>

          <div className="mt-5">
            <div className="flex h-3 overflow-hidden rounded-full bg-line/60" role="img" aria-label="Outcome distribution">
              {total > 0 &&
                counts.map((c) =>
                  c.n ? <div key={c.key} className={BAR[c.key]} style={{ width: `${(c.n / total) * 100}%` }} /> : null,
                )}
            </div>
            <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              {counts.map((c) => (
                <li key={c.key} className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${BAR[c.key]}`} />
                  {c.label}
                  <span className="tabular-nums text-muted">{c.n}</span>
                </li>
              ))}
            </ul>
          </div>

          <dl className="mt-8 grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-3">
            <Stat k="Boot a microVM, average" v={ms(m?.sandbox_create_ms_avg)} />
            <Stat k="Run duration, median" v={ms(m?.execution_duration_ms_p50)} />
            <Stat k="Run duration, 95th percentile" v={ms(m?.execution_duration_ms_p95)} />
            <Stat k="Sandboxes alive right now" v={m?.sandboxes_live ?? "—"} />
            <Stat k="Sandboxes created" v={m?.sandboxes_created_total ?? "—"} />
            <Stat k="Failed cleanups" v={m?.cleanup_failures_total ?? "—"} />
          </dl>
        </div>

        <div>
          <h2 className="text-2xl font-semibold tracking-tight">What this does not promise</h2>
          <ul className="mt-4 space-y-3 text-sm leading-relaxed text-muted">
            <li>
              <span className="text-fg">Isolation is E2B's.</span> This service makes sure code only
              ever runs inside the microVM; the microVM is the security boundary.
            </li>
            <li>
              <span className="text-fg">No import blocklists.</span> They're easy to get around.
              Containment comes from the sandbox, not from reading the code.
            </li>
            <li>
              <span className="text-fg">Limits are per server.</span> Rate limits and these numbers
              live in one process.
            </li>
            <li>
              <span className="text-fg">The agent can still be wrong.</span> Its answer comes with the
              real execution records so you can check it.
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}

function Stat({ k, v }: { k: string; v: string | number }) {
  return (
    <div>
      <dt className="text-sm text-muted">{k}</dt>
      <dd className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight">{v}</dd>
    </div>
  );
}
