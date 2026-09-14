/**
 * Browse sidebar for annotate mode — "To review" list + lazy-loaded codebase tree.
 */

import { useState, useEffect, useCallback } from "preact/hooks";
import { fetchBrowseChildren, type BrowseEntry } from "./api";

interface Props {
  /** Files the agent asked the user to review */
  reviewPaths: string[];
  /** Currently selected file in the main content area */
  selected: string | null;
  /** Callback when a file is clicked */
  onSelect: (path: string) => void;
  /** Whether the sidebar is collapsed */
  collapsed: boolean;
  /** Toggle collapsed state */
  onToggle: () => void;
}

/** Persistent "read" state in sessionStorage */
function getReadState(): Set<string> {
  try {
    const raw = sessionStorage.getItem("mimir-review-read");
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function saveReadState(s: Set<string>) {
  sessionStorage.setItem("mimir-review-read", JSON.stringify([...s]));
}

/* ── Lazy tree node ─────────────────────────────────────────────── */

function CodebaseDir({ path, name, depth, selected, onSelect }: {
  path: string;
  name: string;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<BrowseEntry[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = useCallback(() => {
    if (!expanded && children === null && !loading) {
      setLoading(true);
      fetchBrowseChildren(path).then((entries) => {
        setChildren(entries);
        setLoading(false);
      }).catch(() => setLoading(false));
    }
    setExpanded((e) => !e);
  }, [expanded, children, loading, path]);

  const indent = depth * 12;

  return (
    <>
      <div
        class="tree-dir"
        style={{ paddingLeft: `${indent}px` }}
        onClick={toggle}
      >
        <span class="tree-arrow">{expanded ? "▾" : "▸"}</span>
        <span class="tree-dir-name">{name}</span>
        {loading && <span class="browse-loading-dot">...</span>}
      </div>
      {expanded && children && children.map((c) =>
        c.is_dir ? (
          <CodebaseDir
            key={c.path}
            path={c.path}
            name={c.name}
            depth={depth + 1}
            selected={selected}
            onSelect={onSelect}
          />
        ) : (
          <div
            key={c.path}
            class={`tree-file${selected === c.path ? " active" : ""}`}
            style={{ paddingLeft: `${(depth + 1) * 12}px` }}
            onClick={() => onSelect(c.path)}
          >
            <span>{c.name}</span>
          </div>
        )
      )}
    </>
  );
}

/* ── Main sidebar ───────────────────────────────────────────────── */

export function BrowseSidebar({ reviewPaths, selected, onSelect, collapsed, onToggle }: Props) {
  const [readSet, setReadSet] = useState<Set<string>>(getReadState);
  const [codebaseRoot, setCodebaseRoot] = useState<BrowseEntry[] | null>(null);
  const [codebaseExpanded, setCodebaseExpanded] = useState(false);

  // Load codebase root on first expand
  useEffect(() => {
    if (codebaseExpanded && codebaseRoot === null) {
      fetchBrowseChildren("").then(setCodebaseRoot);
    }
  }, [codebaseExpanded, codebaseRoot]);

  const toggleRead = useCallback((path: string, e: Event) => {
    e.stopPropagation();
    setReadSet((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      saveReadState(next);
      return next;
    });
  }, []);

  if (collapsed) {
    return (
      <nav class="browse-sidebar browse-sidebar-collapsed" onClick={onToggle}>
        <div class="browse-sidebar-toggle-label">files</div>
      </nav>
    );
  }

  const reviewDone = reviewPaths.filter((p) => readSet.has(p)).length;

  return (
    <nav class="browse-sidebar">
      <div class="browse-sidebar-header">
        <span class="browse-sidebar-title">files</span>
        <button class="ann-sidebar-collapse" onClick={onToggle}>{"‹"}</button>
      </div>

      {/* To review section */}
      <div class="browse-section">
        <div class="browse-section-label">
          to review
          <span class="browse-section-count">{reviewDone}/{reviewPaths.length}</span>
        </div>
        {reviewPaths.map((p) => {
          const name = p.includes("/") ? p.slice(p.lastIndexOf("/") + 1) : p;
          const isRead = readSet.has(p);
          return (
            <div
              key={p}
              class={`browse-review-item${selected === p ? " active" : ""}${isRead ? " browse-review-done" : ""}`}
              onClick={() => onSelect(p)}
              title={p}
            >
              <label
                class="browse-check"
                onClick={(e) => e.stopPropagation()}
              >
                <input
                  type="checkbox"
                  checked={isRead}
                  onChange={(e) => toggleRead(p, e)}
                />
              </label>
              <span class="browse-review-path">{p}</span>
            </div>
          );
        })}
      </div>

      {/* Codebase section */}
      <div class="browse-section browse-section-codebase">
        <div
          class="browse-section-label browse-section-label-toggle"
          onClick={() => setCodebaseExpanded((e) => !e)}
        >
          <span class="tree-arrow">{codebaseExpanded ? "▾" : "▸"}</span>
          codebase
        </div>
        {codebaseExpanded && (
          <div class="browse-codebase-tree">
            {codebaseRoot === null ? (
              <div class="tree-loading" style={{ paddingLeft: "12px" }}>loading...</div>
            ) : (
              codebaseRoot.map((entry) =>
                entry.is_dir ? (
                  <CodebaseDir
                    key={entry.path}
                    path={entry.path}
                    name={entry.name}
                    depth={0}
                    selected={selected}
                    onSelect={onSelect}
                  />
                ) : (
                  <div
                    key={entry.path}
                    class={`tree-file${selected === entry.path ? " active" : ""}`}
                    style={{ paddingLeft: "12px" }}
                    onClick={() => onSelect(entry.path)}
                  >
                    <span>{entry.name}</span>
                  </div>
                )
              )
            )}
          </div>
        )}
      </div>
    </nav>
  );
}
