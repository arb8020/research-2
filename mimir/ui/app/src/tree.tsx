/**
 * File tree sidebar — collapsible directories, badge rollup, click to open.
 */

import { useState, useMemo } from "preact/hooks";
import type { TreeData } from "./api";

interface Props {
  tree: TreeData | null;
  selected: string | null;
  onSelect: (path: string) => void;
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

function DirEntry({
  node,
  depth,
  collapsed,
  toggle,
  selected,
  onSelect,
  touched,
}: {
  node: DirNode;
  depth: number;
  collapsed: Set<string>;
  toggle: (path: string) => void;
  selected: string | null;
  onSelect: (path: string) => void;
  touched: Record<string, string[]>;
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
          <span class="tree-badge">⚑ {node.badgeCount}</span>
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
                    ⚑{t.length > 1 ? ` ${t.length}` : ""}
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

export function FileTree({ tree, selected, onSelect }: Props) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const root = useMemo(
    () => (tree ? flatten(buildTree(tree.files, tree.touched)) : null),
    [tree]
  );

  const toggle = (path: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  return (
    <nav class="tree">
      <div class="tree-header">mimir</div>
      {!root ? (
        <div class="tree-loading">loading...</div>
      ) : (
        root.dirs.map((d) => (
          <DirEntry
            key={d.path}
            node={d}
            depth={0}
            collapsed={collapsed}
            toggle={toggle}
            selected={selected}
            onSelect={onSelect}
            touched={tree!.touched}
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
                ⚑{t.length > 1 ? ` ${t.length}` : ""}
              </span>
            )}
          </div>
        );
      })}
    </nav>
  );
}
