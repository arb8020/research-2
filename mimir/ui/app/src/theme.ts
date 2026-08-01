/**
 * mimir design tokens + CodeMirror theme.
 *
 * Light-first, monospace, single accent (gold), inspired by
 * Thinking Machines / Tilde Research / Humans& editorial aesthetic.
 */

import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";

/* ── design tokens ─────────────────────────────────────────────── */

export const tokens = {
  light: {
    ground: "#ffffff",
    surface: "#f6f6f6",
    border: "#e2e2e2",
    ink: "#1a1a1a",
    ink2: "#6b6b6b",
    ink3: "#a0a0a0",
    ink4: "#c8c8c8",
    accent: "#9e7c1a",
    accentBg: "#faf5e6",
    accentBorder: "#e8d8a0",
    // syntax
    keyword: "#1a1a1a",
    string: "#6b6b6b",
    comment: "#a0a0a0",
    number: "#6b6b6b",
    function: "#1a1a1a",
    type: "#4a4a4a",
    decorator: "#9e7c1a",
  },
  dark: {
    ground: "#111113",
    surface: "#1a1a1c",
    border: "#2a2a2c",
    ink: "#d4d4d4",
    ink2: "#8a8a8a",
    ink3: "#555555",
    ink4: "#333333",
    accent: "#c9a23e",
    accentBg: "#1f1c14",
    accentBorder: "#3d3520",
    // syntax
    keyword: "#d4d4d4",
    string: "#8a8a8a",
    comment: "#555555",
    number: "#8a8a8a",
    function: "#d4d4d4",
    type: "#b0b0b0",
    decorator: "#c9a23e",
  },
} as const;

export type Tokens = {
  ground: string;
  surface: string;
  border: string;
  ink: string;
  ink2: string;
  ink3: string;
  ink4: string;
  accent: string;
  accentBg: string;
  accentBorder: string;
  keyword: string;
  string: string;
  comment: string;
  number: string;
  function: string;
  type: string;
  decorator: string;
};

/* ── CodeMirror editor theme ───────────────────────────────────── */

export function mimirEditorTheme(t: Tokens) {
  return EditorView.theme(
    {
      "&": {
        backgroundColor: t.ground,
        color: t.ink,
        fontSize: "13.5px",
        fontFamily: '"SF Mono", ui-monospace, "Cascadia Code", "Fira Code", monospace',
      },
      ".cm-content": {
        lineHeight: "24px",
        padding: "0",
      },
      ".cm-line": {
        padding: "0 16px",
      },
      ".cm-gutters": {
        backgroundColor: t.ground,
        color: t.ink4,
        border: "none",
        borderRight: `1px solid ${t.border}`,
      },
      ".cm-lineNumbers .cm-gutterElement": {
        padding: "0 12px 0 8px",
        minWidth: "40px",
        fontSize: "12px",
        lineHeight: "24px",
      },
      ".cm-activeLine": {
        backgroundColor: t.surface,
      },
      ".cm-activeLineGutter": {
        backgroundColor: t.surface,
      },
      ".cm-selectionBackground": {
        backgroundColor: `${t.accent}22 !important`,
      },
      "&.cm-focused .cm-cursor": {
        borderLeftColor: t.accent,
      },
      ".cm-scroller": {
        overflow: "auto",
      },
      /* ── at-mark gutter ──────────────────────────────────────── */
      ".cm-at-gutter": {
        width: "4px",
        padding: "0",
        marginRight: "2px",
      },
      ".cm-at-mark": {
        width: "4px",
        height: "24px",
        display: "block",
        backgroundColor: t.accent,
        borderRadius: "1px",
        cursor: "pointer",
      },
      /* ── fan-out widget ──────────────────────────────────────── */
      ".mimir-fan": {
        borderTop: `1px solid ${t.border}`,
        borderBottom: `1px solid ${t.border}`,
        backgroundColor: t.surface,
        padding: "12px 16px 12px 56px",
        animation: "mimir-fan-enter 0.15s ease-out",
      },
      ".mimir-fan-header": {
        fontSize: "11px",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        color: t.ink3,
        marginBottom: "10px",
      },
      ".mimir-fan-entry": {
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        gap: "6px 16px",
        alignItems: "baseline",
        padding: "6px 0",
        borderBottom: `1px solid ${t.border}`,
      },
      ".mimir-fan-entry:last-child": {
        borderBottom: "none",
      },
      ".mimir-fan-branch": {
        color: t.accent,
        fontSize: "13px",
      },
      ".mimir-fan-detail": {
        color: t.ink3,
        fontSize: "12px",
      },
      ".mimir-fan-action": {
        fontSize: "12px",
        color: t.ink2,
        textDecoration: "none",
        padding: "2px 8px",
        border: `1px solid ${t.border}`,
        borderRadius: "4px",
        cursor: "pointer",
        backgroundColor: t.ground,
      },
      ".mimir-fan-empty": {
        borderTop: `1px solid ${t.border}`,
        borderBottom: `1px solid ${t.border}`,
        backgroundColor: t.surface,
        padding: "12px 16px 12px 56px",
        color: t.ink3,
        fontSize: "12px",
      },
    },
    { dark: t === tokens.dark }
  );
}

/* ── syntax highlighting ───────────────────────────────────────── */

export function mimirHighlightStyle(t: Tokens) {
  return syntaxHighlighting(
    HighlightStyle.define([
      { tag: tags.keyword, color: t.keyword, fontWeight: "600" },
      { tag: tags.controlKeyword, color: t.keyword, fontWeight: "600" },
      { tag: tags.definitionKeyword, color: t.keyword, fontWeight: "600" },
      { tag: tags.moduleKeyword, color: t.keyword, fontWeight: "600" },
      { tag: tags.operatorKeyword, color: t.keyword, fontWeight: "600" },
      { tag: tags.string, color: t.string },
      { tag: tags.comment, color: t.comment, fontStyle: "italic" },
      { tag: tags.lineComment, color: t.comment, fontStyle: "italic" },
      { tag: tags.blockComment, color: t.comment, fontStyle: "italic" },
      { tag: tags.docComment, color: t.comment, fontStyle: "italic" },
      { tag: tags.number, color: t.number },
      { tag: tags.integer, color: t.number },
      { tag: tags.float, color: t.number },
      { tag: tags.function(tags.variableName), color: t.function },
      { tag: tags.function(tags.definition(tags.variableName)), color: t.function, fontWeight: "600" },
      { tag: tags.typeName, color: t.type },
      { tag: tags.className, color: t.type },
      { tag: tags.meta, color: t.decorator },
      { tag: tags.operator, color: t.ink3 },
      { tag: tags.punctuation, color: t.ink3 },
      { tag: tags.bracket, color: t.ink3 },
      { tag: tags.bool, color: t.keyword, fontWeight: "600" },
      { tag: tags.null, color: t.keyword, fontWeight: "600" },
      { tag: tags.self, color: t.keyword, fontWeight: "600" },
      { tag: tags.variableName, color: t.ink },
      { tag: tags.propertyName, color: t.ink },
    ])
  );
}
