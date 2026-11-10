// Cloudflare Turnstile: invisible unless Cloudflare wants an interaction.
// Tokens are single-use, so we reset the widget after each one is consumed.
import { useCallback, useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: Record<string, unknown>) => string;
      reset: (id: string) => void;
      remove: (id: string) => void;
    };
  }
}

const SCRIPT = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
let loading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.turnstile) return Promise.resolve();
  loading ??= new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = SCRIPT;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("turnstile failed to load"));
    document.head.appendChild(s);
  });
  return loading;
}

export function useTurnstile(siteKey: string | null) {
  const container = useRef<HTMLDivElement | null>(null);
  const widget = useRef<string | null>(null);
  const token = useRef<string | null>(null);
  const waiters = useRef<((t: string | null) => void)[]>([]);
  const [ready, setReady] = useState(siteKey === null);

  useEffect(() => {
    if (!siteKey || !container.current) return;
    let cancelled = false;
    loadScript()
      .then(() => {
        if (cancelled || !container.current || !window.turnstile) return;
        widget.current = window.turnstile.render(container.current, {
          sitekey: siteKey,
          appearance: "interaction-only",
          theme: "auto",
          callback: (t: string) => {
            token.current = t;
            setReady(true);
            waiters.current.splice(0).forEach((w) => w(t));
          },
          "expired-callback": () => {
            token.current = null;
            setReady(false);
          },
        });
      })
      .catch(() => setReady(false));
    return () => {
      cancelled = true;
      if (widget.current && window.turnstile) window.turnstile.remove(widget.current);
    };
  }, [siteKey]);

  /** Get a fresh token (waits for the widget if needed), consuming it. */
  const take = useCallback(async (): Promise<string | null> => {
    if (!siteKey) return null;
    const t =
      token.current ??
      (await new Promise<string | null>((resolve) => {
        waiters.current.push(resolve);
        window.setTimeout(() => resolve(null), 15_000);
      }));
    token.current = null;
    setReady(false);
    if (widget.current && window.turnstile) window.turnstile.reset(widget.current);
    return t;
  }, [siteKey]);

  return { container, ready, take };
}
