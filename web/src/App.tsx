import { useCallback, useEffect, useState } from "react";
import { AgentView } from "./components/AgentView";
import { HistoryDrawer } from "./components/HistoryDrawer";
import { InsideView } from "./components/InsideView";
import { RunView } from "./components/RunView";
import { TopBar, type Mode } from "./components/TopBar";
import { api, type AgentRun, type DemoStatus, type Example, type Recordings, type Status } from "./lib/api";
import { loadHistory, type HistoryEntry } from "./lib/history";
import type { Life } from "./lib/lifecycle";
import { useTurnstile } from "./lib/turnstile";

const PATHS: Record<Mode, string> = { run: "/", agent: "/agent", inside: "/inside" };
const modeFromPath = (): Mode =>
  location.pathname.startsWith("/agent") ? "agent" : location.pathname.startsWith("/inside") ? "inside" : "run";

type Outcome = Exclude<Status, "queued" | "running">;

export default function App() {
  const [mode, setModeState] = useState<Mode>(modeFromPath);
  const [status, setStatus] = useState<DemoStatus | null>(null);
  const [offline, setOffline] = useState(false);
  const [examples, setExamples] = useState<Example[]>([]);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [recordings, setRecordings] = useState<Recordings | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory);
  const [drawer, setDrawer] = useState(false);
  const [openExec, setOpenExec] = useState<string | null>(null);
  const [openRun, setOpenRun] = useState<AgentRun | null>(null);
  const [last, setLast] = useState<Outcome | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    try {
      return (localStorage.getItem("asr.theme") as "dark" | "light") ?? "dark";
    } catch {
      return "dark";
    }
  });

  const turnstile = useTurnstile(status?.turnstile_site_key ?? null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("asr.theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  useEffect(() => {
    const onPop = () => setModeState(modeFromPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const setMode = (m: Mode) => {
    setModeState(m);
    if (location.pathname !== PATHS[m]) history_push(PATHS[m]);
  };

  // Status drives live chips, budget and metrics.
  useEffect(() => {
    let alive = true;
    const poll = () =>
      api
        .status()
        .then((s) => {
          if (!alive) return;
          setStatus(s);
          setOffline(false);
        })
        .catch(() => alive && setOffline(true));
    poll();
    const t = window.setInterval(poll, 4000);
    return () => {
      alive = false;
      window.clearInterval(t);
    };
  }, []);

  useEffect(() => {
    api.examples().then(setExamples).catch(() => setOffline(true));
    api.agentExamples().then(setPrompts).catch(() => {});
    api.recordings().then(setRecordings).catch(() => {});
  }, []);

  const onFinished = useCallback((life: Life) => {
    const s = life.execution?.status;
    if (s && s !== "queued" && s !== "running") setLast(s);
  }, []);

  const openEntry = (e: HistoryEntry) => {
    setDrawer(false);
    if (e.kind === "exec") {
      setOpenExec(e.id);
      setMode("run");
    } else {
      setOpenRun(e.run);
      setMode("agent");
    }
  };

  return (
    <div className="mx-auto flex min-h-full max-w-[1600px] flex-col lg:h-full">
      <TopBar
        mode={mode}
        onMode={setMode}
        status={status}
        offline={offline}
        theme={theme}
        onTheme={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
        onHistory={() => setDrawer(true)}
      />

      <main className="flex min-h-0 flex-1 flex-col">
        <div className={mode === "run" ? "flex min-h-0 flex-1 flex-col" : "hidden"}>
          <RunView
            status={status}
            examples={examples}
            recordings={recordings}
            takeToken={turnstile.take}
            onHistory={setHistory}
            onFinished={onFinished}
            openId={openExec}
          />
        </div>
        <div className={mode === "agent" ? "flex min-h-0 flex-1 flex-col overflow-y-auto" : "hidden"}>
          <AgentView
            status={status}
            prompts={prompts}
            recordings={recordings}
            takeToken={turnstile.take}
            onHistory={setHistory}
            openRun={openRun}
          />
        </div>
        {mode === "inside" && (
          <div className="min-h-0 flex-1 overflow-y-auto">
            <InsideView status={status} last={last} />
          </div>
        )}
      </main>

      <HistoryDrawer open={drawer} entries={history} onClose={() => setDrawer(false)} onOpen={openEntry} />
      {/* Turnstile renders here and only becomes visible if Cloudflare needs an interaction. */}
      <div ref={turnstile.container} className="fixed bottom-4 right-4 z-30" />
    </div>
  );
}

function history_push(path: string) {
  window.history.pushState(null, "", path);
}
