"use client";

import { useEffect, useRef, useState } from "react";
import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from "@codemirror/autocomplete";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import { json } from "@codemirror/lang-json";
import { python } from "@codemirror/lang-python";
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import { highlightSelectionMatches, searchKeymap } from "@codemirror/search";
import { EditorState } from "@codemirror/state";
import {
  crosshairCursor,
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import styles from "./studio-code-editor.module.css";

type StudioCodeLanguage = "python" | "json";
type StudioCodeStatusTone = "ready" | "error" | "neutral";

interface StudioCodeEditorProps {
  ariaLabel: string;
  filename: string;
  language: StudioCodeLanguage;
  runtimeLabel: string;
  status: string;
  statusTone?: StudioCodeStatusTone;
  value: string;
  onBlur?: (value: string) => void;
  onChange: (value: string) => void;
}

const editorHighlighting = HighlightStyle.define([
  { tag: tags.keyword, color: "#ff7b72" },
  { tag: [tags.typeName, tags.className, tags.function(tags.variableName)], color: "#d2a8ff" },
  { tag: [tags.definition(tags.variableName), tags.variableName], color: "#e6edf3" },
  { tag: [tags.propertyName, tags.attributeName, tags.labelName], color: "#79c0ff" },
  { tag: [tags.string, tags.special(tags.string), tags.docString], color: "#7ee787" },
  { tag: [tags.number, tags.bool, tags.null], color: "#79c0ff" },
  { tag: [tags.operator, tags.punctuation], color: "#a5adb7" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "#8b949e", fontStyle: "italic" },
  { tag: [tags.invalid], color: "#ff7b72", textDecoration: "underline wavy" },
]);

const editorTheme = EditorView.theme(
  {
    "&": {
      height: "100%",
      color: "#e6edf3",
      backgroundColor: "#101010",
      fontSize: "12px",
    },
    ".cm-scroller": {
      overflow: "auto",
      fontFamily: 'var(--codex-font-mono, "SFMono-Regular", "SF Mono", Menlo, Monaco, Consolas, monospace)',
      lineHeight: "1.72",
    },
    ".cm-content": {
      minHeight: "100%",
      padding: "13px 0 28px",
      caretColor: "#58a6ff",
    },
    ".cm-line": {
      padding: "0 18px",
    },
    ".cm-gutters": {
      minWidth: "50px",
      borderRight: "1px solid #2b2b2b",
      color: "#626262",
      backgroundColor: "#141414",
    },
    ".cm-lineNumbers .cm-gutterElement": {
      minWidth: "42px",
      padding: "0 11px 0 7px",
    },
    ".cm-activeLineGutter": {
      color: "#d0d0d0",
      backgroundColor: "#202020",
    },
    ".cm-activeLine": {
      backgroundColor: "rgb(255 255 255 / 3.5%)",
    },
    ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
      backgroundColor: "rgb(51 156 255 / 28%) !important",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "#58a6ff",
    },
    ".cm-foldGutter .cm-gutterElement": {
      color: "#6f6f6f",
    },
    ".cm-matchingBracket": {
      color: "#ffffff",
      backgroundColor: "rgb(88 166 255 / 22%)",
      outline: "1px solid rgb(88 166 255 / 42%)",
    },
    ".cm-searchMatch": {
      backgroundColor: "rgb(230 170 74 / 26%)",
      outline: "1px solid rgb(230 170 74 / 42%)",
    },
    ".cm-searchMatch.cm-searchMatch-selected": {
      backgroundColor: "rgb(51 156 255 / 30%)",
    },
    ".cm-tooltip": {
      border: "1px solid #3a3a3a",
      color: "#d7d7d7",
      backgroundColor: "#202020",
    },
    ".cm-tooltip-autocomplete > ul > li[aria-selected]": {
      color: "#ffffff",
      backgroundColor: "#303030",
    },
  },
  { dark: true },
);

function languageExtension(language: StudioCodeLanguage) {
  return language === "python" ? python() : json();
}

export function StudioCodeEditor({
  ariaLabel,
  filename,
  language,
  runtimeLabel,
  status,
  statusTone = "neutral",
  value,
  onBlur,
  onChange,
}: StudioCodeEditorProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onBlurRef = useRef(onBlur);
  const onChangeRef = useRef(onChange);
  const [copied, setCopied] = useState(false);
  const [cursor, setCursor] = useState({ line: 1, column: 1 });
  const lineCount = Math.max(1, value.split("\n").length);

  useEffect(() => {
    onBlurRef.current = onBlur;
    onChangeRef.current = onChange;
  }, [onBlur, onChange]);

  useEffect(() => {
    if (!hostRef.current) return;
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        foldGutter(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        EditorState.tabSize.of(4),
        indentOnInput(),
        syntaxHighlighting(editorHighlighting),
        bracketMatching(),
        closeBrackets(),
        autocompletion(),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        languageExtension(language),
        editorTheme,
        EditorView.contentAttributes.of({
          "aria-label": ariaLabel,
          "aria-multiline": "true",
          spellcheck: "false",
        }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged) {
            onChangeRef.current(update.state.doc.toString());
          }
          if (update.docChanged || update.selectionSet) {
            const head = update.state.selection.main.head;
            const line = update.state.doc.lineAt(head);
            setCursor({ line: line.number, column: head - line.from + 1 });
          }
        }),
        EditorView.domEventHandlers({
          blur: (_event, view) => {
            onBlurRef.current?.(view.state.doc.toString());
            return false;
          },
        }),
        keymap.of([
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          ...foldKeymap,
          ...completionKeymap,
          indentWithTab,
        ]),
      ],
    });
    const view = new EditorView({ state, parent: hostRef.current });
    viewRef.current = view;
    return () => {
      viewRef.current = null;
      view.destroy();
    };
  }, [ariaLabel, language]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view || view.state.doc.toString() === value) return;
    view.dispatch({
      changes: { from: 0, to: view.state.doc.length, insert: value },
    });
  }, [value]);

  function copySource() {
    void navigator.clipboard.writeText(value).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1_400);
    });
  }

  return (
    <section className={styles.shell} data-language={language}>
      <header className={styles.header}>
        <div className={styles.title}>
          <span className={styles.fileMark}>{language === "python" ? "PY" : "{}"}</span>
          <span>
            <strong>{filename}</strong>
            <small>{runtimeLabel}</small>
          </span>
        </div>
        <div className={styles.headerActions}>
          <span>{lineCount} lines</span>
          <button type="button" onClick={copySource}>
            {copied ? "已复制" : "复制"}
          </button>
        </div>
      </header>
      <div className={styles.editor} ref={hostRef} />
      <footer className={styles.footer}>
        <span>Ln {cursor.line}, Col {cursor.column}</span>
        <span>Spaces: 4</span>
        <span>UTF-8</span>
        <span className={styles.shortcut}>⌘F 查找</span>
        <strong data-tone={statusTone}>{status}</strong>
      </footer>
    </section>
  );
}
