import { useEffect, useState } from "react";

export interface NoticeState {
  tone: "user" | "infra" | "muted";
  text: string;
  retryAfter?: number;
}

const TONE = {
  user: "border-user/40 text-user",
  infra: "border-infra/40 text-infra",
  muted: "border-line text-muted",
};

export function Notice({ notice, onClose }: { notice: NoticeState; onClose: () => void }) {
  const [left, setLeft] = useState(notice.retryAfter ?? 0);
  useEffect(() => {
    setLeft(notice.retryAfter ?? 0);
    if (!notice.retryAfter) return;
    const t = window.setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(t);
  }, [notice]);
  const mins = Math.floor(left / 60);
  return (
    <div role="status" className={`flex items-center gap-3 rounded-xl border bg-panel px-4 py-2.5 text-sm ${TONE[notice.tone]}`}>
      <span className="flex-1">
        {notice.text}
        {left > 0 && (
          <span className="tabular-nums text-muted">
            {" "}Try again in {mins > 0 ? `${mins} min ` : ""}
            {left % 60} s.
          </span>
        )}
      </span>
      <button onClick={onClose} className="text-muted hover:text-fg" aria-label="Dismiss">
        Dismiss
      </button>
    </div>
  );
}
