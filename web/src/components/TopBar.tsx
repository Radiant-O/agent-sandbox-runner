import type { DemoStatus } from "../lib/api";
import { ms } from "../lib/format";

export type Mode = "run" | "agent" | "inside";

const MODES: { key: Mode; label: string }[] = [
  { key: "run", label: "Run code" },
  { key: "agent", label: "Agent" },
  { key: "inside", label: "How it works" },
];

export function TopBar({
  mode,
  onMode,
  status,
  offline,
  theme,
  onTheme,
  onHistory,
}: {
  mode: Mode;
  onMode: (m: Mode) => void;
  status: DemoStatus | null;
  offline: boolean;
  theme: "dark" | "light";
  onTheme: () => void;
  onHistory: () => void;
}) {
  const live = status?.metrics.sandboxes_live ?? 0;
  const b = status?.budget.runs;
  const pct = b ? (b.remaining / Math.max(1, b.total)) * 100 : 100;

  return (
    <header className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6 lg:px-8">
      <a href="/" className="flex items-center gap-2.5" aria-label="Agent Sandbox Runner home">
        <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
          <rect width="32" height="32" rx="8" className="fill-panel" />
          <path d="M6 16h5l3-7 4 14 3-7h5" fill="none" stroke="rgb(var(--live))" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <span className="text-[1.05rem] font-semibold tracking-tight">Agent Sandbox Runner</span>
      </a>

      <nav aria-label="Mode" className="order-3 flex w-full rounded-xl bg-panel p-1 sm:order-none sm:w-auto">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => onMode(m.key)}
            aria-current={mode === m.key ? "page" : undefined}
            className={`flex-1 rounded-lg px-3.5 py-1.5 text-sm transition-colors sm:flex-none ${
              mode === m.key ? "bg-raised font-medium text-fg" : "text-muted hover:text-fg"
            }`}
          >
            {m.label}
          </button>
        ))}
      </nav>

      <div className="ml-auto flex items-center gap-5 text-sm">
        {offline ? (
          <span className="flex items-center gap-2 text-infra">
            <span className="h-2 w-2 rounded-full bg-infra" />
            Server unreachable
          </span>
        ) : (
          <span className="hidden items-center gap-2 text-muted md:flex" title="Sandboxes alive right now">
            <span className={`h-2 w-2 rounded-full ${live > 0 ? "animate-beat bg-live" : "bg-muted/50"}`} />
            <span>
              {live} live
              {status?.metrics.sandbox_create_ms_avg != null &&
                `, boots in ${ms(status.metrics.sandbox_create_ms_avg)}`}
            </span>
          </span>
        )}

        {b && (
          <div className="hidden w-40 lg:block" title={`Resets ${new Date(status!.budget.resets_at).toLocaleTimeString()}`}>
            <div className="flex justify-between text-xs text-muted">
              <span>Today's runs</span>
              <span className="tabular-nums">
                {b.remaining}/{b.total}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-line">
              <div className={`h-full rounded-full ${pct > 15 ? "bg-live" : "bg-user"}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        <button onClick={onHistory} className="text-muted hover:text-fg">
          History
        </button>
        <button
          onClick={onTheme}
          className="text-muted hover:text-fg"
          aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? "Light" : "Dark"}
        </button>
        {status?.repo_url && (
          <a href={status.repo_url} className="text-muted hover:text-fg" target="_blank" rel="noreferrer">
            Source
          </a>
        )}
      </div>
    </header>
  );
}
