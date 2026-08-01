/**
 * mimir app shell — file browser + code viewer + diff viewer.
 *
 * Modes:
 * - Default: file tree + code editor with --at popover/peek
 * - Diff: unified diff viewer (triggered by ?diff or ?diff=branch)
 */

import { useState, useEffect, useCallback } from "preact/hooks";
import { FileTree } from "./tree";
import { Editor } from "./editor";
import { DiffViewer } from "./diff-viewer";
import { fetchTree, fetchDiff, type TreeData } from "./api";

type Mode = { kind: "browse" } | { kind: "diff"; patch: string; label: string };

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [currentRef, setCurrentRef] = useState<string | null>(null);
  const [peekRef, setPeekRef] = useState<string | null>(null);
  const [peekLine, setPeekLine] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "browse" });

  useEffect(() => {
    fetchTree().then(setTree);

    // Check URL params for diff mode
    const params = new URLSearchParams(window.location.search);
    const diffRef = params.get("diff");
    const diffRange = params.get("range");
    if (diffRef !== null || diffRange !== null) {
      fetchDiff(diffRef ?? undefined, diffRange ?? undefined).then((data) => {
        setMode({
          kind: "diff",
          patch: data.diff,
          label: data.range ?? data.ref ?? "working tree",
        });
      });
    }
  }, []);

  const handlePeek = useCallback((branch: string, line: number) => {
    if (branch === "__close__") {
      setPeekRef(null);
      setPeekLine(null);
    } else {
      setPeekRef(branch);
      setPeekLine(line);
    }
  }, []);

  const handleEnter = useCallback((branch: string) => {
    const oldRef = currentRef;
    setCurrentRef(branch);
    setPeekRef(oldRef);
  }, [currentRef]);

  const touchedCount = selected && tree?.touched[selected]?.length;

  return (
    <div class="app">
      <FileTree
        tree={tree}
        selected={selected}
        onSelect={(path) => {
          setSelected(path);
          setCurrentRef(null);
          setPeekRef(null);
          setPeekLine(null);
          setMode({ kind: "browse" });
        }}
      />
      <div class="main">
        {mode.kind === "diff" ? (
          <>
            <div class="file-header">
              <span class="file-name">diff</span>
              <span class="file-meta">{mode.label}</span>
            </div>
            <DiffViewer patch={mode.patch} />
          </>
        ) : selected ? (
          <>
            <div class="file-header">
              <span class="file-path">
                {selected.includes("/")
                  ? selected.slice(0, selected.lastIndexOf("/") + 1)
                  : ""}
              </span>
              <span class="file-name">
                {selected.includes("/")
                  ? selected.slice(selected.lastIndexOf("/") + 1)
                  : selected}
              </span>
              {touchedCount ? (
                <span class="file-meta">
                  {touchedCount} branch{touchedCount > 1 ? "es" : ""}
                </span>
              ) : null}
            </div>
            <Editor
              path={selected}
              currentRef={currentRef}
              peekRef={peekRef}
              peekLine={peekLine}
              onPeek={handlePeek}
              onEnter={handleEnter}
            />
          </>
        ) : (
          <div class="empty-state">
            pick a file — click gutter marks for who's-here
          </div>
        )}
      </div>
    </div>
  );
}
