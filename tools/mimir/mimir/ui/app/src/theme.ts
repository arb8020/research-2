/**
 * mimir design tokens + CodeMirror theme.
 *
 * Light-first, monospace, single accent (gold), inspired by
 * Thinking Machines / Tilde Research / Humans& editorial aesthetic.
 *
 * Syntax colors are derived from the design tokens via OKLCH mixing —
 * each syntax role gets a hue tint of the ink color at low chroma,
 * so they feel governed by the palette rather than pasted from VS Code.
 */

import { EditorView } from "@codemirror/view";
import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { tags } from "@lezer/highlight";
import { deriveSyntaxPalette, type SyntaxColors } from "./palette";

/* ── design tokens ─────────────────────────────────────────────── */

export interface Tokens {
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
  syntax: SyntaxColors;
}

function makeTokens(
  base: {
    ground: string; surface: string; border: string;
    ink: string; ink2: string; ink3: string; ink4: string;
    accent: string; accentBg: string; accentBorder: string;
  },
  isDark: boolean,
): Tokens {
  return {
    ...base,
    syntax: deriveSyntaxPalette(base.ink, base.ink3, base.accent, isDark),
  };
}

export const tokens = {
  light: makeTokens({
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
  }, false),
  dark: makeTokens({
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
  }, true),
} as const;

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
        backgroundColor: `${t.accent}33 !important`,
      },
      "&.cm-focused .cm-selectionBackground": {
        backgroundColor: `${t.accent}44 !important`,
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
      /* ── popover ────────────────────────────────────────────── */
      ".cm-tooltip": {
        border: "none",
        backgroundColor: "transparent",
      },
      ".mimir-popover": {
        backgroundColor: t.ground,
        border: `1px solid ${t.border}`,
        borderRadius: "6px",
        boxShadow: `0 4px 16px ${t === tokens.dark ? "rgba(0,0,0,0.5)" : "rgba(0,0,0,0.1)"}`,
        minWidth: "240px",
        maxWidth: "360px",
        overflow: "hidden",
        animation: "mimir-popover-enter 0.12s ease-out",
      },
      ".mimir-popover-empty": {
        padding: "12px 16px",
        color: t.ink3,
        fontSize: "12px",
      },
      ".mimir-popover-list": {
        maxHeight: "200px",
        overflowY: "auto",
      },
      ".mimir-popover-row": {
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        gap: "12px",
        padding: "8px 16px",
        cursor: "pointer",
        transition: "background 0.08s",
      },
      ".mimir-popover-row:hover": {
        backgroundColor: t.surface,
      },
      ".mimir-popover-row.active": {
        backgroundColor: t.accentBg,
      },
      ".mimir-popover-branch": {
        color: t.accent,
        fontSize: "13px",
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      },
      ".mimir-popover-meta": {
        color: t.ink3,
        fontSize: "11px",
        flexShrink: "0",
        whiteSpace: "nowrap",
      },
    },
    { dark: t === tokens.dark }
  );
}

/* ── syntax highlighting ───────────────────────────────────────── */

export function mimirHighlightStyle(t: Tokens) {
  const s = t.syntax;
  return syntaxHighlighting(
    HighlightStyle.define([
      { tag: tags.keyword, color: s.keyword, fontWeight: "600" },
      { tag: tags.controlKeyword, color: s.keyword, fontWeight: "600" },
      { tag: tags.definitionKeyword, color: s.keyword, fontWeight: "600" },
      { tag: tags.moduleKeyword, color: s.keyword, fontWeight: "600" },
      { tag: tags.operatorKeyword, color: s.keyword, fontWeight: "600" },
      { tag: tags.string, color: s.string },
      { tag: tags.comment, color: s.comment, fontStyle: "italic" },
      { tag: tags.lineComment, color: s.comment, fontStyle: "italic" },
      { tag: tags.blockComment, color: s.comment, fontStyle: "italic" },
      { tag: tags.docComment, color: s.comment, fontStyle: "italic" },
      { tag: tags.number, color: s.number },
      { tag: tags.integer, color: s.number },
      { tag: tags.float, color: s.number },
      { tag: tags.function(tags.variableName), color: s.function },
      { tag: tags.function(tags.definition(tags.variableName)), color: s.function, fontWeight: "600" },
      { tag: tags.typeName, color: s.type },
      { tag: tags.className, color: s.type },
      { tag: tags.meta, color: s.decorator },
      { tag: tags.operator, color: t.ink3 },
      { tag: tags.punctuation, color: t.ink3 },
      { tag: tags.bracket, color: t.ink3 },
      { tag: tags.bool, color: s.keyword, fontWeight: "600" },
      { tag: tags.null, color: s.keyword, fontWeight: "600" },
      { tag: tags.self, color: s.keyword, fontWeight: "600" },
      { tag: tags.variableName, color: t.ink },
      { tag: tags.propertyName, color: t.ink },
    ])
  );
}
