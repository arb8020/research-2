/**
 * File tree sidebar — collapsible directories, badge rollup, click to open.
 *
 * When `reviewPaths` is provided (annotate browse mode), a "TO REVIEW" section
 * with checkboxes appears at the top, followed by the normal "CODEBASE" tree.
 */

import { useState, useMemo, useEffect, useCallback } from "preact/hooks";
import type { TreeData } from "./api";

interface Props {
  tree: TreeData | null;
  selected: string | null;
  onSelect: (path: string) => void;
  mode?: "browse" | "diff" | "message";
  /** Files the agent asked the user to review (annotate browse mode) */
  reviewPaths?: string[];
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

interface DirNode {
  name: string;
  path: string;
  files: string[]; // leaf filenames
  dirs: DirNode[];
  badgeCount: number; // total touched branches in this subtree
}

/** Build a nested tree from flat file paths. */
function buildTree(files: string[], touched: Record<string, string[]>): DirNode {
  const root: DirNode = { name: "", path: "", files: [], dirs: [], badgeCount: 0 };

  for (const f of files) {
    const parts = f.split("/");
    let node = root;
    for (let i = 0; i < parts.length - 1; i++) {
      const dirPath = parts.slice(0, i + 1).join("/");
      let child = node.dirs.find((d) => d.path === dirPath);
      if (!child) {
        child = { name: parts[i], path: dirPath, files: [], dirs: [], badgeCount: 0 };
        node.dirs.push(child);
      }
      node = child;
    }
    node.files.push(f);
  }

  // Roll up badge counts
  function countBadges(node: DirNode): number {
    let count = 0;
    for (const f of node.files) count += (touched[f]?.length ?? 0);
    for (const d of node.dirs) count += countBadges(d);
    node.badgeCount = count;
    return count;
  }
  countBadges(root);

  return root;
}

/** Flatten dirs that contain only a single subdir and no files. */
function flatten(node: DirNode): DirNode {
  while (node.dirs.length === 1 && node.files.length === 0) {
    const child = node.dirs[0];
    node = { ...child, name: node.name ? `${node.name}/${child.name}` : child.name };
  }
  return { ...node, dirs: node.dirs.map(flatten) };
}

function fileBadge(t: string[], mode: "browse" | "diff"): string {
  if (mode === "diff") {
    // In diff mode, touched values are "+N −M" strings
    return t[0] ?? "";
  }
  return t.length === 1 ? "1 branch" : `${t.length} branches`;
}

function DirEntry({
  node,
  depth,
  collapsed,
  toggle,
  selected,
  onSelect,
  touched,
  mode,
}: {
  node: DirNode;
  depth: number;
  collapsed: Set<string>;
  toggle: (path: string) => void;
  selected: string | null;
  onSelect: (path: string) => void;
  touched: Record<string, string[]>;
  mode: "browse" | "diff";
}) {
  const isCollapsed = collapsed.has(node.path);
  const indent = depth * 12;

  return (
    <>
      <div
        class="tree-dir"
        style={{ paddingLeft: `${indent}px` }}
        onClick={() => toggle(node.path)}
      >
        <span class="tree-arrow">{isCollapsed ? "▸" : "▾"}</span>
        <span class="tree-dir-name">{node.name}</span>
        {isCollapsed && node.badgeCount > 0 && (
          <span class="tree-badge">
            {mode === "diff" ? `${node.badgeCount} files` : node.badgeCount}
          </span>
        )}
      </div>
      {!isCollapsed && (
        <>
          {node.dirs.map((d) => (
            <DirEntry
              key={d.path}
              node={d}
              depth={depth + 1}
              collapsed={collapsed}
              toggle={toggle}
              selected={selected}
              onSelect={onSelect}
              touched={touched}
              mode={mode}
            />
          ))}
          {node.files.map((f) => {
            const name = f.slice(f.lastIndexOf("/") + 1);
            const t = touched[f];
            return (
              <div
                key={f}
                class={`tree-file${selected === f ? " active" : ""}`}
                style={{ paddingLeft: `${(depth + 1) * 12}px` }}
                onClick={() => onSelect(f)}
              >
                <span>{name}</span>
                {t && (
                  <span class="tree-badge" title={t.join("\n")}>
                    {fileBadge(t, mode)}
                  </span>
                )}
              </div>
            );
          })}
        </>
      )}
    </>
  );
}

export function FileTree({ tree, selected, onSelect, mode = "browse", reviewPaths }: Props) {
  // Start with all dirs collapsed — we'll expand to the selected file
  const [collapsed, setCollapsed] = useState<Set<string> | null>(null);
  const [readSet, setReadSet] = useState<Set<string>>(getReadState);

  const root = useMemo(
    () => (tree ? flatten(buildTree(tree.files, tree.touched)) : null),
    [tree]
  );

  // On first tree load, collapse everything
  useEffect(() => {
    if (root && collapsed === null) {
      const allDirs = new Set<string>();
      function collectDirs(node: DirNode) {
        if (node.path) allDirs.add(node.path);
        node.dirs.forEach(collectDirs);
      }
      collectDirs(root);
      setCollapsed(allDirs);
    }
  }, [root, collapsed]);

  // When a file is selected, expand its ancestor dirs
  useEffect(() => {
    if (!selected || !collapsed) return;
    const parts = selected.split("/");
    const ancestors: string[] = [];
    // Build ancestor paths, but account for flattened dirs
    for (let i = 1; i < parts.length; i++) {
      ancestors.push(parts.slice(0, i).join("/"));
    }
    if (ancestors.length === 0) return;

    setCollapsed((prev) => {
      if (!prev) return prev;
      const next = new Set(prev);
      let changed = false;
      for (const a of ancestors) {
        // Find the flattened dir that contains this ancestor
        for (const key of next) {
          if (a === key || a.startsWith(key + "/") || key.startsWith(a + "/") || key === a) {
            if (next.has(key) && (a === key || key.endsWith("/" + a.split("/").pop()))) {
              next.delete(key);
              changed = true;
            }
          }
        }
        if (next.has(a)) {
          next.delete(a);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [selected]);

  const toggle = (path: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev ?? new Set<string>());
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

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

  const safeCollapsed = collapsed ?? new Set<string>();
  const hasReview = reviewPaths && reviewPaths.length > 0;
  const reviewDone = hasReview ? reviewPaths.filter((p) => readSet.has(p)).length : 0;

  if (mode === "message") {
    // Message mode: flat list of recent messages
    return (
      <nav class="tree">
        <div class="tree-header">messages</div>
        {!tree ? (
          <div class="tree-loading">loading...</div>
        ) : (
          tree.files.map((f) => {
            const t = tree.touched[f];
            const preview = t?.[0] ?? "";
            const idx = parseInt(f.slice(4), 10);
            return (
              <div
                key={f}
                class={`tree-file tree-message${selected === f ? " active" : ""}`}
                onClick={() => onSelect(f)}
              >
                <span class="tree-message-label">{idx === 0 ? "latest" : `${idx + 1} ago`}</span>
                <span class="tree-message-preview">{preview}</span>
              </div>
            );
          })
        )}
      </nav>
    );
  }

  return (
    <nav class="tree">
      {/* TO REVIEW section — only in annotate browse mode */}
      {hasReview && (
        <div class="review-section">
          <div class="review-section-label">
            to review
            <span class="review-section-count">{reviewDone}/{reviewPaths.length}</span>
          </div>
          {reviewPaths.map((p) => {
            const isRead = readSet.has(p);
            return (
              <div
                key={p}
                class={`review-item${selected === p ? " active" : ""}${isRead ? " review-done" : ""}`}
                onClick={() => onSelect(p)}
                title={p}
              >
                <label
                  class="review-check"
                  onClick={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={isRead}
                    onChange={(e) => toggleRead(p, e)}
                  />
                </label>
                <span class="review-path">{p}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* CODEBASE section */}
      <div class="tree-header">{hasReview ? "codebase" : "mimir"}</div>
      {!root ? (
        <div class="tree-loading">loading...</div>
      ) : (
        root.dirs.map((d) => (
          <DirEntry
            key={d.path}
            node={d}
            depth={0}
            collapsed={safeCollapsed}
            toggle={toggle}
            selected={selected}
            onSelect={onSelect}
            touched={tree!.touched}
            mode={mode}
          />
        ))
      )}
      {root?.files.map((f) => {
        const name = f.slice(f.lastIndexOf("/") + 1);
        const t = tree?.touched[f];
        return (
          <div
            key={f}
            class={`tree-file${selected === f ? " active" : ""}`}
            onClick={() => onSelect(f)}
          >
            <span>{name}</span>
            {t && (
              <span class="tree-badge" title={t.join("\n")}>
                {fileBadge(t, mode)}
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
