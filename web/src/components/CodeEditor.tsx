import { python } from "@codemirror/lang-python";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView, keymap } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo } from "react";

const highlight = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.operatorKeyword], color: "rgb(var(--late))" },
  { tag: [t.string, t.special(t.string)], color: "rgb(var(--ok))" },
  { tag: [t.number, t.bool, t.null], color: "rgb(var(--user))" },
  { tag: [t.comment], color: "rgb(var(--muted))", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: "rgb(var(--live))" },
  { tag: [t.definition(t.variableName), t.className], color: "rgb(var(--fg))", fontWeight: "600" },
]);

export function CodeEditor({
  value,
  onChange,
  onRun,
  readOnly = false,
  ariaLabel = "Python code",
}: {
  value: string;
  onChange?: (v: string) => void;
  onRun?: () => void;
  readOnly?: boolean;
  ariaLabel?: string;
}) {
  const extensions = useMemo(
    () => [
      python(),
      syntaxHighlighting(highlight),
      EditorView.lineWrapping,
      EditorView.contentAttributes.of({ "aria-label": ariaLabel }),
      keymap.of([
        {
          key: "Mod-Enter",
          preventDefault: true,
          run: () => {
            onRun?.();
            return true;
          },
        },
      ]),
    ],
    [onRun, ariaLabel],
  );
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      readOnly={readOnly}
      editable={!readOnly}
      theme="none"
      basicSetup={{ foldGutter: false, highlightActiveLine: !readOnly, autocompletion: false }}
      extensions={extensions}
      height="100%"
      className="h-full"
    />
  );
}
