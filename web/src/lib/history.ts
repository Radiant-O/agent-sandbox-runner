// This browser's own runs. Only ids and small summaries are kept, never code output.
import type { AgentRun, Status, StopReason } from "./api";

export type HistoryEntry =
  | { kind: "exec"; id: string; title: string; status: Status; at: number }
  | { kind: "agent"; id: string; title: string; status: StopReason; at: number; run: AgentRun };

const KEY = "asr.history.v1";
const MAX = 25;

export function loadHistory(): HistoryEntry[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as HistoryEntry[];
  } catch {
    return [];
  }
}

export function pushHistory(entry: HistoryEntry): HistoryEntry[] {
  const next = [entry, ...loadHistory().filter((e) => e.id !== entry.id)].slice(0, MAX);
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage full or blocked: history is a convenience only */
  }
  return next;
}
