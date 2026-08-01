/**
 * CodeMirror editor component — read-only code viewer with --at gutter.
 */

import { useRef, useEffect } from "preact/hooks";
import { EditorView, lineNumbers, drawSelection, keymap } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { searchKeymap, highlightSelectionMatches } from "@codemirror/search";
import { bracketMatching, foldGutter, indentOnInput } from "@codemirror/language";

import { tokens, mimirEditorTheme, mimirHighlightStyle } from "./theme";
import { atExtension, setAtData, type AtLineData } from "./at-gutter";
import { langForPath } from "./lang";
import { fetchFile, fetchAt } from "./api";

interface Props {
  path: string | null;
}

// Compartment for swapping language support per file
const langCompartment = new Compartment();

export function Editor({ path }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);

  // Create editor on mount
  useEffect(() => {
    if (!containerRef.current) return;

    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const t = isDark ? tokens.dark : tokens.light;

    const view = new EditorView({
      state: EditorState.create({
        doc: "",
        extensions: [
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
          langCompartment.of([]),
          atExtension(),
        ],
      }),
      parent: containerRef.current,
    });

    viewRef.current = view;
    return () => view.destroy();
  }, []);

  // Load file when path changes
  useEffect(() => {
    if (!path || !viewRef.current) return;

    const view = viewRef.current;

    (async () => {
      const [file, at] = await Promise.all([
        fetchFile(path),
        fetchAt(path),
      ]);

      // Replace document content + swap language
      view.dispatch({
        changes: {
          from: 0,
          to: view.state.doc.length,
          insert: file.content,
        },
        effects: langCompartment.reconfigure(langForPath(path)),
      });

      // Set --at data
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
    })();
  }, [path]);

  return (
    <div
      ref={containerRef}
      style={{
        flex: 1,
        overflow: "hidden",
        borderRadius: "6px",
        border: "1px solid var(--border)",
      }}
    />
  );
}
