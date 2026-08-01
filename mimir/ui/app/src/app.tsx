/**
 * mimir app shell — tree + editor with peek flow.
 *
 * Flow:
 * - Click gutter pip → popover lists branches
 * - Click branch → peek panel slides in showing that branch's code
 * - Click "enter" → main swaps to that branch, peek shows old branch
 */

import { useState, useEffect, useCallback } from "preact/hooks";
import { FileTree } from "./tree";
import { Editor } from "./editor";
import { fetchTree, type TreeData } from "./api";

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [currentRef, setCurrentRef] = useState<string | null>(null); // null = working tree
  const [peekRef, setPeekRef] = useState<string | null>(null);
  const [peekLine, setPeekLine] = useState<number | null>(null);

  useEffect(() => {
    fetchTree().then(setTree);
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
    const oldRef = currentRef; // might be null (working tree)
    setCurrentRef(branch);
    // Peek now shows what we were looking at before
    setPeekRef(oldRef);
  }, [currentRef]);

  const touchedCount = selected && tree?.touched[selected]?.length;

  return (
    <div class="app">
      <FileTree tree={tree} selected={selected} onSelect={(path) => {
        setSelected(path);
        setCurrentRef(null);
        setPeekRef(null);
        setPeekLine(null);
      }} />
      <div class="main">
        {selected ? (
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
