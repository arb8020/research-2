/**
 * mimir app shell — tree sidebar + CodeMirror editor.
 */

import { useState, useEffect } from "preact/hooks";
import { FileTree } from "./tree";
import { Editor } from "./editor";
import { fetchTree, type TreeData } from "./api";

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    fetchTree().then(setTree);
  }, []);

  const touchedCount = selected && tree?.touched[selected]?.length;

  return (
    <div class="app">
      <FileTree tree={tree} selected={selected} onSelect={setSelected} />
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
                  {touchedCount} branch{touchedCount > 1 ? "es" : ""} touch
                  this file
                </span>
              ) : null}
            </div>
            <Editor path={selected} />
          </>
        ) : (
          <div class="empty-state">
            pick a file — <kbd>j</kbd>/<kbd>k</kbd> tree,{" "}
            <kbd>enter</kbd> open, click gutter marks for who's-here
          </div>
        )}
      </div>
    </div>
  );
}
