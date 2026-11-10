import type { StreamEvent } from "./api";

const TYPES = [
  "queued",
  "sandbox_creating",
  "sandbox_created",
  "code_uploaded",
  "stdout",
  "stderr",
  "exited",
  "sandbox_killed",
  "cleanup_failed",
  "finished",
  "started",
  "step_started",
  "model_text",
  "tool_call",
  "tool_result",
  "failed",
];

const TERMINAL = new Set(["finished", "failed"]);

/**
 * Subscribe to a server-sent event stream. EventSource reconnects on its own and
 * resumes from Last-Event-ID; the server replays anything missed. Returns a closer.
 */
export function openStream(
  url: string,
  onEvent: (ev: StreamEvent) => void,
  onLost: () => void,
): () => void {
  const es = new EventSource(url);
  let done = false;
  const handler = (type: string) => (msg: MessageEvent<string>) => {
    const parsed = JSON.parse(msg.data) as { ts: number; data: Record<string, unknown> };
    onEvent({ seq: Number(msg.lastEventId), type, ts: parsed.ts, data: parsed.data });
    if (TERMINAL.has(type)) {
      done = true;
      es.close();
    }
  };
  for (const t of TYPES) es.addEventListener(t, handler(t) as EventListener);
  es.onerror = () => {
    // CLOSED means the server refused (e.g. stream expired): fall back to a fetch.
    if (!done && es.readyState === EventSource.CLOSED) onLost();
  };
  return () => {
    done = true;
    es.close();
  };
}

/** Replay recorded events with their original relative timing (budget-exhausted mode). */
export function replay(
  events: StreamEvent[],
  onEvent: (ev: StreamEvent) => void,
  speed = 1,
): () => void {
  const timers: number[] = [];
  if (!events.length) return () => {};
  const t0 = events[0].ts;
  for (const ev of events) {
    const delay = Math.min(((ev.ts - t0) * 1000) / speed, 30_000);
    timers.push(window.setTimeout(() => onEvent(ev), delay));
  }
  return () => timers.forEach((t) => window.clearTimeout(t));
}
