import type { ReactNode } from "react";
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
          <rect width="32" height="32" className="fill-panel" />
          <path d="M5 17h6l3-8 4 15 3-7h6" fill="none" stroke="rgb(var(--live))" strokeWidth="2.6" strokeLinejoin="miter" />
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
          <div
            className="hidden w-44 lg:block"
            title={`Shared by all visitors. Resets at ${new Date(status!.budget.resets_at).toLocaleTimeString()}`}
          >
            <div className="flex justify-between text-xs text-muted">
              <span>Demo runs left today</span>
              <span className="tabular-nums">
                {b.remaining} of {b.total}
              </span>
            </div>
            <div className="mt-1 h-1 overflow-hidden rounded-full bg-line">
              <div className={`h-full rounded-full ${pct > 15 ? "bg-fg/70" : "bg-user"}`} style={{ width: `${pct}%` }} />
            </div>
          </div>
        )}

        <div className="flex items-center gap-1">
          <IconButton label="Run history" onClick={onHistory}>
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <path d="M3 3v5h5M12 7v5l3 2" />
          </IconButton>
          <IconButton label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`} onClick={onTheme}>
            {theme === "dark" ? (
              <>
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
              </>
            ) : (
              <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />
            )}
          </IconButton>
          {status?.repo_url && (
            <IconButton label="Source code" href={status.repo_url}>
              <path d="M8 6l-6 6 6 6M16 6l6 6-6 6" />
            </IconButton>
          )}
        </div>
      </div>
    </header>
  );
}

function IconButton({
  label,
  onClick,
  href,
  children,
}: {
  label: string;
  onClick?: () => void;
  href?: string;
  children: ReactNode;
}) {
  const cls =
    "grid h-9 w-9 place-items-center text-muted transition-colors hover:bg-panel hover:text-fg";
  const icon = (
    <svg
      viewBox="0 0 24 24"
      className="h-[18px] w-[18px]"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden
    >
      {children}
    </svg>
  );
  return href ? (
    <a href={href} target="_blank" rel="noreferrer" aria-label={label} title={label} className={cls}>
      {icon}
    </a>
  ) : (
    <button type="button" onClick={onClick} aria-label={label} title={label} className={cls}>
      {icon}
    </button>
  );
}
