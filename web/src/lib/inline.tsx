import { Fragment, type ReactNode } from "react";

/** Minimal, safe inline formatting for model text: **bold** and `code` only. */
export function inline(text: string): ReactNode {
  return text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4)
      return <strong key={i} className="font-semibold text-fg">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2)
      return <code key={i} className="rounded bg-ink px-1 py-0.5 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}

/** Model text with ```fenced``` code blocks rendered as code; everything else via inline(). */
export function rich(text: string): ReactNode {
  const parts = text.split(/```[^\n`]*\n?([\s\S]*?)(?:```|$)/g);
  return parts.map((part, i) => {
    if (i % 2 === 1)
      return (
        <pre
          key={i}
          className="scrollbar-thin my-3 max-h-72 overflow-auto whitespace-pre rounded-lg bg-ink px-3 py-2.5 font-mono text-[0.8rem] leading-relaxed text-fg/90"
        >
          {part.replace(/\n$/, "")}
        </pre>
      );
    const trimmed = part.replace(/^\n+|\n+$/g, "");
    return trimmed ? <span key={i} className="whitespace-pre-wrap">{inline(trimmed)}</span> : null;
  });
}
