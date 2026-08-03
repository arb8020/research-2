/**
 * CodeMirror editor component — read-only code viewer with --at popover.
 * Supports a peek panel (second editor) for viewing branch versions.
 */

import { useRef, useEffect, useCallback, useState } from "preact/hooks";
import { EditorView, lineNumbers, drawSelection, keymap } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { bracketMatching, foldGutter, indentOnInput } from "@codemirror/language";

import { tokens, mimirEditorTheme, mimirHighlightStyle } from "./theme";
import { atExtension, setAtData, setAtCallbacks, type AtLineData } from "./at-gutter";
import { langForPath } from "./lang";
import { fetchFile, fetchAt } from "./api";

interface Props {
  path: string | null;
  currentRef: string | null; // null = working tree
  peekRef: string | null;
  peekLine: number | null;
  onPeek: (branch: string, line: number) => void;
  onEnter: (branch: string) => void;
  onLineSelect?: (file: string, startLine: number, endLine: number, top: number, left: number) => void;
}

const langCompartment = new Compartment();

function createExtensions(isDark: boolean, path: string | null) {
  const t = isDark ? tokens.dark : tokens.light;
  return [
    lineNumbers(),
    drawSelection(),
    bracketMatching(),
    highlightSelectionMatches(),
    foldGutter(),
    history(),
    indentOnInput(),
    keymap.of([...defaultKeymap, ...historyKeymap, ...searchKeymap]),
    EditorState.readOnly.of(true),
    mimirEditorTheme(t),
    mimirHighlightStyle(t),
    langCompartment.of(path ? langForPath(path) : []),
    atExtension(),
  ];
}

function EditorSkeleton() {
  // Varying widths to mimic code lines
  const widths = [72, 45, 88, 60, 35, 80, 55, 42, 90, 68, 50, 75, 38, 85, 48];
  return (
    <div class="editor-skeleton">
      {widths.map((w, i) => (
        <div key={i} class="editor-skeleton-line" style={{ width: `${w}%`, animationDelay: `${i * 60}ms` }} />
      ))}
    </div>
  );
}

export function Editor({ path, currentRef, peekRef, peekLine, onPeek, onEnter, onLineSelect }: Props) {
  const mainRef = useRef<HTMLDivElement>(null);
  const peekContainerRef = useRef<HTMLDivElement>(null);
  const mainViewRef = useRef<EditorView | null>(null);
  const peekViewRef = useRef<EditorView | null>(null);
  const [loading, setLoading] = useState(false);
  // Wire up callbacks for the popover
  useEffect(() => {
    setAtCallbacks({ onPeek, onEnter });
  }, [onPeek, onEnter]);

  // Create main editor
  useEffect(() => {
    if (!mainRef.current) return;
    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const exts = createExtensions(isDark, null);

    // On mouseup after selection, fire annotation popover immediately
    if (onLineSelect) {
      exts.push(EditorView.domEventHandlers({
        mouseup: (e, view) => {
          if (!path) return false;
          setTimeout(() => {
            const sel = view.state.selection.main;
            if (sel.from === sel.to) return;
            const startLine = view.state.doc.lineAt(sel.from).number;
            const endLine = view.state.doc.lineAt(sel.to).number;
            const rect = view.dom.getBoundingClientRect();
            const endCoords = view.coordsAtPos(sel.to);
            onLineSelect(path, startLine, endLine,
              endCoords ? endCoords.bottom : e.clientY,
              endCoords ? endCoords.left : e.clientX);
          }, 10);
          return false;
        },
      }));
    }

    const view = new EditorView({
      state: EditorState.create({
        doc: "",
        extensions: exts,
      }),
      parent: mainRef.current,
    });
    mainViewRef.current = view;

    return () => {
      view.destroy();
    };
  }, []);

  // Load file when path or ref changes
  useEffect(() => {
    if (!path || !mainViewRef.current) return;
    const view = mainViewRef.current;
    setLoading(true);

    (async () => {
      const [file, at] = await Promise.all([
        fetchFile(path, currentRef ?? undefined),
        fetchAt(path),
      ]);

      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: file.content },
        effects: langCompartment.reconfigure(langForPath(path)),
      });

      if (at?.hits) {
        const lineData: AtLineData[] = [];
        const seen = new Map<number, AtLineData>();
        for (const hit of at.hits) {
          for (const [start, end] of hit.ranges) {
            for (let ln = start; ln <= end; ln++) {
              let entry = seen.get(ln);
              if (!entry) {
                entry = { line: ln, hits: [] };
                seen.set(ln, entry);
                lineData.push(entry);
              }
              entry.hits.push(hit);
            }
          }
        }
        view.dispatch({ effects: setAtData.of(lineData) });
      }
      setLoading(false);
    })();
  }, [path, currentRef]);

  // Create/update peek editor when peekRef changes
  useEffect(() => {
    if (!peekRef || !path || !peekContainerRef.current) {
      // Destroy peek if no longer needed
      if (peekViewRef.current) {
        peekViewRef.current.destroy();
        peekViewRef.current = null;
      }
      return;
    }

    (async () => {
      const file = await fetchFile(path, peekRef);
      const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const t = isDark ? tokens.dark : tokens.light;

      if (peekViewRef.current) {
        peekViewRef.current.destroy();
      }

      const peekLangCompartment = new Compartment();
      const view = new EditorView({
        state: EditorState.create({
          doc: file.content,
          extensions: [
            lineNumbers(),
            drawSelection(),
            bracketMatching(),
            highlightSelectionMatches(),
            foldGutter(),
            EditorState.readOnly.of(true),
            mimirEditorTheme(t),
            mimirHighlightStyle(t),
            peekLangCompartment.of(langForPath(path)),
          ],
        }),
        parent: peekContainerRef.current!,
      });

      peekViewRef.current = view;

      // Scroll to the relevant line
      if (peekLine && peekLine <= view.state.doc.lines) {
        const line = view.state.doc.line(peekLine);
        view.dispatch({
          effects: EditorView.scrollIntoView(line.from, { y: "center" }),
        });
      }
    })();

    return () => {
      if (peekViewRef.current) {
        peekViewRef.current.destroy();
        peekViewRef.current = null;
      }
    };
  }, [peekRef, path, peekLine]);

  const refLabel = currentRef ?? "working tree";

  return (
    <div class="editor-container">
      <div class="editor-pane" style={{ flex: peekRef ? "1 1 50%" : "1 1 100%" }}>
        <div class="editor-pane-header">
          <span class="editor-pane-ref">{refLabel}</span>
          {peekRef && <span class="editor-pane-label">current</span>}
        </div>
        <div class="editor-pane-body" ref={mainRef}>
          {loading && <EditorSkeleton />}
        </div>
      </div>
      {peekRef && (
        <div class="editor-pane editor-peek">
          <div class="editor-pane-header">
            <span class="editor-pane-ref">{peekRef}</span>
            <span class="editor-pane-label">peek</span>
            <button
              class="editor-peek-enter"
              onClick={() => onEnter(peekRef)}
            >
              enter →
            </button>
            <button
              class="editor-peek-close"
              onClick={() => onPeek("__close__", 0)}
            >
              ×
            </button>
          </div>
          <div class="editor-pane-body" ref={peekContainerRef} />
        </div>
      )}
    </div>
  );
}
