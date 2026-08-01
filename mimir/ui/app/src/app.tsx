/**
 * mimir app shell — file browser + code viewer + diff viewer.
 *
 * Modes:
 * - Browse: file tree (full repo) + code editor with --at popover/peek
 * - Diff: file tree (changed files only) + per-file diff viewer
 */

import { useState, useEffect, useCallback, useMemo } from "preact/hooks";
import { FileTree } from "./tree";
import { Editor } from "./editor";
import { DiffViewer } from "./diff-viewer";
import { fetchTree, fetchDiff, type TreeData } from "./api";
import { parseUnifiedDiff, type DiffFile } from "./diff-parse";

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [currentRef, setCurrentRef] = useState<string | null>(null);
  const [peekRef, setPeekRef] = useState<string | null>(null);
  const [peekLine, setPeekLine] = useState<number | null>(null);

  // Diff mode state
  const [diffFiles, setDiffFiles] = useState<DiffFile[] | null>(null);
  const [diffLabel, setDiffLabel] = useState<string>("");

  const isDiffMode = diffFiles !== null;

  useEffect(() => {
    fetchTree().then(setTree);

    // Check URL params for diff mode
    const params = new URLSearchParams(window.location.search);
    const diffRef = params.get("diff");
    const diffRange = params.get("range");
    if (diffRef !== null || diffRange !== null) {
      fetchDiff(diffRef ?? undefined, diffRange ?? undefined).then((data) => {
        const files = parseUnifiedDiff(data.diff);
        setDiffFiles(files);
        setDiffLabel(data.range ?? data.ref ?? "working tree");
        // Auto-select first file
        if (files.length > 0) setSelected(files[0].newPath);
      });
    }
  }, []);

  // In diff mode, build a synthetic tree from changed files
  const diffTree = useMemo<TreeData | null>(() => {
    if (!diffFiles) return null;
    const files = diffFiles.map((f) => f.newPath);
    const touched: Record<string, string[]> = {};
    for (const f of diffFiles) {
      // Use additions/deletions as a rough "activity" signal
      if (f.additions > 0 || f.deletions > 0) {
        touched[f.newPath] = [`+${f.additions} -${f.deletions}`];
      }
    }
    return { files, touched, branch: diffLabel };
  }, [diffFiles, diffLabel]);

  // Find the selected file's raw diff
  const selectedDiff = useMemo(() => {
    if (!diffFiles || !selected) return null;
    return diffFiles.find((f) => f.newPath === selected) ?? null;
  }, [diffFiles, selected]);

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

  const activeTree = isDiffMode ? diffTree : tree;
  const touchedCount = selected && activeTree?.touched[selected]?.length;

  return (
    <div class="app">
      <FileTree
        tree={activeTree}
        selected={selected}
        onSelect={(path) => {
          setSelected(path);
          if (!isDiffMode) {
            setCurrentRef(null);
            setPeekRef(null);
            setPeekLine(null);
          }
        }}
      />
      <div class="main">
        {isDiffMode && selected && selectedDiff ? (
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
              <span class="file-meta">
                +{selectedDiff.additions} −{selectedDiff.deletions}
              </span>
            </div>
            <DiffViewer patch={selectedDiff.rawDiff} />
          </>
        ) : selected && !isDiffMode ? (
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
            {isDiffMode ? "select a changed file" : "pick a file — click gutter marks for who's-here"}
          </div>
        )}
      </div>
    </div>
  );
}
