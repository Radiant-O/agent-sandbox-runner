import { AnimatePresence, motion } from "motion/react";
import { useEffect } from "react";
import { STATUS_TEXT, STATUS_TONE, STOP_TEXT } from "../lib/format";
import type { HistoryEntry } from "../lib/history";

export function HistoryDrawer({
  open,
  entries,
  onClose,
  onOpen,
}: {
  open: boolean;
  entries: HistoryEntry[];
  onClose: () => void;
  onOpen: (e: HistoryEntry) => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            className="fixed inset-0 z-40 bg-ink/60 backdrop-blur-[2px]"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
          />
          <motion.aside
            role="dialog"
            aria-label="Your recent runs"
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-sm flex-col border-l border-line bg-panel"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 34 }}
          >
            <div className="flex items-center justify-between border-b border-line px-5 py-4">
              <h2 className="font-semibold">Your recent runs</h2>
              <button onClick={onClose} className="text-sm text-muted hover:text-fg" autoFocus>
                Close
              </button>
            </div>
            {entries.length === 0 ? (
              <p className="px-5 py-6 text-sm text-muted">
                Runs you start in this browser show up here so you can reopen them.
              </p>
            ) : (
              <ul className="scrollbar-thin flex-1 overflow-y-auto p-2">
                {entries.map((e) => (
                  <li key={e.id}>
                    <button
                      onClick={() => onOpen(e)}
                      className="w-full rounded-xl px-3 py-2.5 text-left hover:bg-raised"
                    >
                      <span className="block truncate text-sm font-medium">{e.title}</span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs">
                        <span className="text-muted">{e.kind === "exec" ? "Code" : "Agent"}</span>
                        <span className={e.kind === "exec" ? STATUS_TONE[e.status] : "text-muted"}>
                          {e.kind === "exec" ? STATUS_TEXT[e.status] : STOP_TEXT[e.status]}
                        </span>
                        <span className="ml-auto text-muted">{new Date(e.at).toLocaleTimeString()}</span>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}
