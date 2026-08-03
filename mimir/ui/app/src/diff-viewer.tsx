/**
 * Diff viewer — renders unified diff as a CM6 document with line decorations.
 *
 * Same approach as diff-syntax.nvim:
 * - Raw unified diff is the document text
 * - Lines classified by prefix (+/-/space/@@/diff --git)
 * - Background decorations for add/delete/context/header
 * - Fold by file (level 1) and hunk (level 2)
 */

import { useRef, useEffect, useMemo, useState } from "preact/hooks";
import { EditorView, lineNumbers, drawSelection, keymap, Decoration, type DecorationSet, ViewPlugin, type ViewUpdate } from "@codemirror/view";
import { EditorState, StateField, RangeSetBuilder } from "@codemirror/state";
import { defaultKeymap } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { foldGutter, foldService, syntaxHighlighting, HighlightStyle } from "@codemirror/language";
import { tags } from "@lezer/highlight";

import { tokens, type Tokens } from "./theme";

interface Props {
  patch: string;
  file?: string;
  onLineSelect?: (file: string, startLine: number, endLine: number, top: number, left: number) => void;
}

/* ── line classification ───────────────────────────────────────── */

type LineKind = "file_hdr" | "hunk_hdr" | "meta" | "add" | "delete" | "context";

function classifyLine(text: string): LineKind {
  if (text.startsWith("diff --git ") || text.startsWith("--- ") || text.startsWith("+++ ")) return "file_hdr";
  if (text.startsWith("@@ ")) return "hunk_hdr";
  if (text.startsWith("index ") || text.startsWith("new file") || text.startsWith("deleted file") ||
      text.startsWith("rename ") || text.startsWith("similarity ") || text.startsWith("Binary ")) return "meta";
  if (text.startsWith("+")) return "add";
  if (text.startsWith("-")) return "delete";
  return "context";
}

/* ── line decorations ──────────────────────────────────────────── */

function makeDiffDecorations(t: Tokens) {
  const addLine = Decoration.line({ class: "diff-line-add" });
  const delLine = Decoration.line({ class: "diff-line-del" });
  const ctxLine = Decoration.line({ class: "diff-line-ctx" });
  const hunkLine = Decoration.line({ class: "diff-line-hunk" });
  const fileLine = Decoration.line({ class: "diff-line-file" });
  const metaLine = Decoration.line({ class: "diff-line-meta" });

  return StateField.define<DecorationSet>({
    create(state) { return buildDecorations(state); },
    update(decos, tr) {
      if (tr.docChanged) return buildDecorations(tr.state);
      return decos;
    },
    provide: (field) => EditorView.decorations.from(field),
  });

  function buildDecorations(state: EditorState): DecorationSet {
    const builder = new RangeSetBuilder<Decoration>();
    for (let i = 1; i <= state.doc.lines; i++) {
      const line = state.doc.line(i);
      const kind = classifyLine(line.text);
      const deco =
        kind === "add" ? addLine :
        kind === "delete" ? delLine :
        kind === "hunk_hdr" ? hunkLine :
        kind === "file_hdr" ? fileLine :
        kind === "meta" ? metaLine :
        ctxLine;
      builder.add(line.from, line.from, deco);
    }
    return builder.finish();
  }
}

/* ── DOM-based diff highlighting (fallback for CM6 decoration issues) ── */

function diffDomHighlighter() {
  function applyClasses(view: EditorView) {
    const lines = view.dom.querySelectorAll(".cm-line");
    lines.forEach((el) => {
      const text = el.textContent || "";
      // Remove old classes
      el.classList.remove("diff-line-add", "diff-line-del", "diff-line-ctx", "diff-line-hunk", "diff-line-file", "diff-line-meta");
      const kind = classifyLine(text);
      switch (kind) {
        case "add": el.classList.add("diff-line-add"); break;
        case "delete": el.classList.add("diff-line-del"); break;
        case "hunk_hdr": el.classList.add("diff-line-hunk"); break;
        case "file_hdr": el.classList.add("diff-line-file"); break;
        case "meta": el.classList.add("diff-line-meta"); break;
        default: el.classList.add("diff-line-ctx"); break;
      }
    });
  }

  return ViewPlugin.fromClass(class {
    constructor(view: EditorView) {
      // Multiple passes to catch lazy-mounted editors
      requestAnimationFrame(() => applyClasses(view));
      setTimeout(() => applyClasses(view), 100);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        requestAnimationFrame(() => applyClasses(update.view));
      }
    }
  });
}

/* ── fold by file/hunk ─────────────────────────────────────────── */

const diffFoldService = foldService.of((state, lineStart, lineEnd) => {
  const line = state.doc.lineAt(lineStart);
  const text = line.text;

  // File headers fold to next file header
  if (text.startsWith("diff --git ")) {
    for (let i = line.number + 1; i <= state.doc.lines; i++) {
      const nextLine = state.doc.line(i);
      if (nextLine.text.startsWith("diff --git ")) {
        return { from: line.to, to: state.doc.line(i - 1).to };
      }
    }
    // Last file — fold to end
    return { from: line.to, to: state.doc.line(state.doc.lines).to };
  }

  // Hunk headers fold to next hunk or file header
  if (text.startsWith("@@ ")) {
    for (let i = line.number + 1; i <= state.doc.lines; i++) {
      const nextLine = state.doc.line(i);
      if (nextLine.text.startsWith("@@ ") || nextLine.text.startsWith("diff --git ")) {
        return { from: line.to, to: state.doc.line(i - 1).to };
      }
    }
    return { from: line.to, to: state.doc.line(state.doc.lines).to };
  }

  return null;
});

/* ── diff-aware syntax highlighting (lightweight) ──────────────── */
// Highlight diff structure — keywords in headers, paths, line ranges

function diffHighlighting(t: Tokens) {
  return syntaxHighlighting(HighlightStyle.define([
    // We use CM6's generic tags to color diff-specific elements
    // but since we're not parsing with a grammar, we rely on line decorations
    // for the main coloring. This just ensures base text is readable.
    { tag: tags.content, color: t.ink },
  ]));
}

/* ── theme ─────────────────────────────────────────────────────── */

function diffLineColors(isDark: boolean) {
  return EditorView.baseTheme({
    "&dark .diff-line-add, &light .diff-line-add": {},
    ".diff-line-add": { backgroundColor: isDark ? "#1a2e1f" : "#e6f4ea" },
    ".diff-line-del": { backgroundColor: isDark ? "#2e1a1a" : "#fbe8e8" },
    ".diff-line-ctx": { backgroundColor: isDark ? "#141618" : "#fafafa" },
    ".diff-line-hunk": { backgroundColor: isDark ? "#171a1d" : "#f0f3f6", color: isDark ? "#9aa4af" : "#6b7785", fontStyle: "italic" },
    ".diff-line-file": { backgroundColor: isDark ? "#171a1d" : "#f0f3f6", color: isDark ? "#d5e0ea" : "#24292e", fontWeight: "bold" },
    ".diff-line-meta": { backgroundColor: isDark ? "#141618" : "#fafafa", color: isDark ? "#555" : "#a0a0a0" },
  });
}

function diffTheme(t: Tokens) {
  const isDark = t === tokens.dark;
  return EditorView.theme({
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
    ".cm-scroller": {
      overflow: "auto",
    },
    ".cm-foldGutter .cm-gutterElement": {
      padding: "0 4px",
      cursor: "pointer",
    },
    // Sign column — first character coloring
    ".diff-sign-add": {
      color: isDark ? "#88d39b" : "#2a6f3b",
    },
    ".diff-sign-del": {
      color: isDark ? "#f0a0a0" : "#b33030",
    },
    // Selection highlight — must override CM6 defaults
    "& .cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
      background: isDark ? "#4a3d10 !important" : "#e8d88a !important",
    },
    "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground": {
      background: isDark ? "#5a4a15 !important" : "#dcc86a !important",
    },
  }, { dark: isDark });
}

/* ── sign gutter (+ / - marks) ─────────────────────────────────── */

import { gutter, GutterMarker } from "@codemirror/view";

class DiffSignMarker extends GutterMarker {
  constructor(readonly sign: string, readonly className: string) { super(); }
  toDOM() {
    const el = document.createElement("span");
    el.textContent = this.sign;
    el.className = this.className;
    return el;
  }
}

const addMarker = new DiffSignMarker("+", "diff-sign-add");
const delMarker = new DiffSignMarker("−", "diff-sign-del");

const diffSignGutter = gutter({
  class: "cm-diff-sign-gutter",
  lineMarker(view, line) {
    const text = view.state.doc.lineAt(line.from).text;
    if (text.startsWith("+") && !text.startsWith("+++")) return addMarker;
    if (text.startsWith("-") && !text.startsWith("---")) return delMarker;
    return null;
  },
});

/* ── component ─────────────────────────────────────────────────── */

export function DiffViewer({ patch, file, onLineSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  useEffect(() => {
    if (!containerRef.current) return;

    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const t = isDark ? tokens.dark : tokens.light;

    const view = new EditorView({
      state: EditorState.create({
        doc: patch,
        extensions: [
          lineNumbers(),
          drawSelection(),
          highlightSelectionMatches(),
          foldGutter(),
          diffFoldService,
          keymap.of([...defaultKeymap, ...searchKeymap]),
          EditorState.readOnly.of(true),
          diffTheme(t),
          diffLineColors(isDark),
          diffHighlighting(t),
          makeDiffDecorations(t),
          diffDomHighlighter(),
          // On mouseup after selection, fire annotation immediately
          EditorView.domEventHandlers({
            mouseup: (e, view) => {
              if (!onLineSelect || !file) return false;
              // Small delay so CM6 finishes updating selection
              setTimeout(() => {
                const sel = view.state.selection.main;
                if (sel.from === sel.to) return;
                const startLine = view.state.doc.lineAt(sel.from).number;
                const endLine = view.state.doc.lineAt(sel.to).number;
                const endCoords = view.coordsAtPos(sel.to);
                onLineSelect(file, startLine, endLine,
                  endCoords ? endCoords.bottom : e.clientY,
                  endCoords ? endCoords.left : e.clientX);
              }, 10);
              return false;
            },
          }),
        ],
      }),
      parent: containerRef.current,
    });

    viewRef.current = view;

    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [patch, file, onLineSelect]);

  return (
    <div ref={containerRef} class="diff-viewer-cm" />
  );
}

/* ── multi-file diff viewer (scrollable with sticky headers) ──── */

interface FileDiffChunk {
  path: string;
  additions: number;
  deletions: number;
  rawDiff: string;
}

function splitDiffByFile(patch: string): FileDiffChunk[] {
  const lines = patch.split("\n");
  const chunks: FileDiffChunk[] = [];
  let start = -1;
  let path = "";
  let adds = 0;
  let dels = 0;

  function flush(end: number) {
    if (start < 0) return;
    let e = end;
    while (e > start && lines[e - 1] === "") e--;
    chunks.push({ path, additions: adds, deletions: dels, rawDiff: lines.slice(start, e).join("\n") });
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("diff --git ")) {
      flush(i);
      start = i;
      adds = 0;
      dels = 0;
      const m = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      path = m?.[2] ?? "";
      continue;
    }
    if (start >= 0) {
      if (line.startsWith("+") && !line.startsWith("+++")) adds++;
      if (line.startsWith("-") && !line.startsWith("---")) dels++;
    }
  }
  flush(lines.length);
  return chunks;
}

/** Single file section within the multi-diff viewer — lazy-mounted via IntersectionObserver */
function DiffFileSection({ chunk, onLineSelect }: { chunk: FileDiffChunk; onLineSelect?: Props["onLineSelect"] }) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const [visible, setVisible] = useState(false);

  // Lazy mount: only create CM6 when scrolled into view
  useEffect(() => {
    if (!sentinelRef.current) return;
    const obs = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) { setVisible(true); obs.disconnect(); } },
      { rootMargin: "200px" } // load slightly before visible
    );
    obs.observe(sentinelRef.current);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !editorRef.current) return;
    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const t = isDark ? tokens.dark : tokens.light;

    const view = new EditorView({
      state: EditorState.create({
        doc: chunk.rawDiff,
        extensions: [
          lineNumbers(),
          drawSelection(),
          highlightSelectionMatches(),
          keymap.of([...defaultKeymap, ...searchKeymap]),
          EditorState.readOnly.of(true),
          diffTheme(t),
          diffLineColors(isDark),
          diffHighlighting(t),
          makeDiffDecorations(t),
          diffDomHighlighter(),
          EditorView.domEventHandlers({
            mouseup: (e, view) => {
              if (!onLineSelect) return false;
              setTimeout(() => {
                const sel = view.state.selection.main;
                if (sel.from === sel.to) return;
                const startLine = view.state.doc.lineAt(sel.from).number;
                const endLine = view.state.doc.lineAt(sel.to).number;
                const endCoords = view.coordsAtPos(sel.to);
                onLineSelect(chunk.path, startLine, endLine,
                  endCoords ? endCoords.bottom : e.clientY,
                  endCoords ? endCoords.left : e.clientX);
              }, 10);
              return false;
            },
          }),
        ],
      }),
      parent: editorRef.current,
    });
    viewRef.current = view;


    return () => { view.destroy(); viewRef.current = null; };
  }, [chunk.rawDiff, visible]);

  // Estimate height from line count for placeholder
  const lineCount = chunk.rawDiff.split("\n").length;
  const estimatedHeight = lineCount * 24; // ~24px per line

  return (
    <div ref={sentinelRef}>
      {visible ? (
        <div ref={editorRef} class="diff-file-editor" />
      ) : (
        <div class="diff-file-placeholder" style={{ height: `${Math.min(estimatedHeight, 800)}px` }} />
      )}
    </div>
  );
}

interface MultiDiffProps {
  patch: string;
  label: string;
  onLineSelect?: Props["onLineSelect"];
  onFileVisible?: (path: string) => void;
}

export function MultiDiffViewer({ patch, label, onLineSelect, onFileVisible }: MultiDiffProps) {
  const chunks = useMemo(() => splitDiffByFile(patch), [patch]);
  console.log(`[MultiDiffViewer] ${chunks.length} files, patch ${patch.length} chars`);

  return (
    <div class="multi-diff-scroll">
      {chunks.map((chunk) => (
        <div key={chunk.path} class="multi-diff-file" id={`diff-file-${chunk.path}`}>
          <div class="multi-diff-header">
            <span class="multi-diff-path">{chunk.path}</span>
            <span class="multi-diff-stat">
              <span class="multi-diff-add">+{chunk.additions}</span>
              {" "}
              <span class="multi-diff-del">−{chunk.deletions}</span>
            </span>
          </div>
          <DiffFileSection chunk={chunk} onLineSelect={onLineSelect} />
        </div>
      ))}
    </div>
  );
}
