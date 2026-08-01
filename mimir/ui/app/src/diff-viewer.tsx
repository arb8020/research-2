/**
 * Unified diff viewer using @codemirror/merge.
 * Renders a list of file diffs from a unified patch.
 */

import { useRef, useEffect, useState } from "preact/hooks";
import { EditorView, lineNumbers, drawSelection } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { unifiedMergeView } from "@codemirror/merge";
import { bracketMatching, foldGutter } from "@codemirror/language";

import { tokens, mimirEditorTheme, mimirHighlightStyle, type Tokens } from "./theme";
import { langForPath } from "./lang";
import { parseUnifiedDiff, type DiffFile } from "./diff-parse";

interface Props {
  patch: string;
}

function diffThemeExtension(t: Tokens) {
  return EditorView.theme({
    ".cm-mergeView": {
      fontSize: "13.5px",
      fontFamily: '"SF Mono", ui-monospace, "Cascadia Code", "Fira Code", monospace',
    },
    // Deleted chunks
    ".cm-deletedChunk": {
      backgroundColor: `${t === tokens.dark ? "#37252620" : "#f0d0d020"}`,
    },
    ".cm-deletedChunk .cm-deletedLine": {
      backgroundColor: t === tokens.dark ? "#372526" : "#fbe8e8",
    },
    // Inserted lines (in unified view, these are the "new" lines)
    ".cm-insertedLine": {
      backgroundColor: t === tokens.dark ? "#1f3025" : "#e6f4ea",
    },
    // Gutter marks for changes
    ".cm-changeGutter .cm-gutterElement": {
      color: t.ink3,
      fontSize: "11px",
    },
  }, { dark: t === tokens.dark });
}

function FileDiff({ file }: { file: DiffFile }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (!containerRef.current || collapsed) return;

    const isDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const t = isDark ? tokens.dark : tokens.light;

    const view = new EditorView({
      state: EditorState.create({
        doc: file.newContent,
        extensions: [
          lineNumbers(),
          drawSelection(),
          bracketMatching(),
          foldGutter(),
          EditorState.readOnly.of(true),
          mimirEditorTheme(t),
          mimirHighlightStyle(t),
          diffThemeExtension(t),
          ...langForPath(file.newPath),
          unifiedMergeView({
            original: file.oldContent,
            highlightChanges: true,
            gutter: true,
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
  }, [file, collapsed]);

  return (
    <div class="diff-file">
      <div
        class="diff-file-header"
        onClick={() => setCollapsed(!collapsed)}
      >
        <span class="diff-file-arrow">{collapsed ? "▸" : "▾"}</span>
        <span class="diff-file-path">{file.newPath}</span>
        {file.oldPath !== file.newPath && (
          <span class="diff-file-rename">← {file.oldPath}</span>
        )}
      </div>
      {!collapsed && (
        <div class="diff-file-content" ref={containerRef} />
      )}
    </div>
  );
}

export function DiffViewer({ patch }: Props) {
  const files = parseUnifiedDiff(patch);

  if (files.length === 0) {
    return <div class="diff-empty">no changes</div>;
  }

  return (
    <div class="diff-viewer">
      {files.map((file) => (
        <FileDiff key={`${file.oldPath}:${file.newPath}`} file={file} />
      ))}
    </div>
  );
}
