/**
 * Diff viewer using @pierre/diffs — replaces the CM6-based diff-viewer.tsx.
 *
 * Uses PatchDiff for rendering unified diffs with proper syntax highlighting,
 * side-aware annotations, and built-in dark/light theme support.
 *
 * Annotation positioning follows the plannotator pattern: track mouse position
 * continuously, position popover at the cursor on line click/selection.
 */

import { useRef, useEffect, useMemo, useState, useCallback } from "preact/hooks";
import { PatchDiff } from "@pierre/diffs/react";
import type { SelectedLineRange } from "@pierre/diffs";

interface Props {
  patch: string;
  file?: string;
  onLineSelect?: (file: string, startLine: number, endLine: number, top: number, left: number) => void;
}

/* ── theme ─────────────────────────────────────────────────────── */

function mimirUnsafeCSS(isDark: boolean): string {
  const t = isDark
    ? {
        ground: "#111113",
        surface: "#1a1a1c",
        border: "#2a2a2c",
        ink: "#d4d4d4",
        ink3: "#555555",
        addBg: "rgba(13, 68, 32, 0.7)",
        delBg: "rgba(74, 28, 28, 0.7)",
        hunkBg: "rgba(26, 30, 40, 0.85)",
        hunkColor: "#7a9ec0",
        selBg: "#4a3d10",
        font: '"SF Mono", ui-monospace, "Cascadia Code", "Fira Code", monospace',
      }
    : {
        ground: "#ffffff",
        surface: "#f6f6f6",
        border: "#e2e2e2",
        ink: "#1a1a1a",
        ink3: "#a0a0a0",
        addBg: "#e6f4ea",
        delBg: "#fbe8e8",
        hunkBg: "#f0f3f6",
        hunkColor: "#6b7785",
        selBg: "#e8d88a",
        font: '"SF Mono", ui-monospace, "Cascadia Code", "Fira Code", monospace',
      };

  return `
    :host {
      font-family: ${t.font};
      font-size: 13.5px;
      --diffs-font-family: ${t.font};
      --diffs-font-size: 13.5px;
      --diffs-line-height: 24px;
      --diffs-background: ${t.ground};
      --diffs-gutter-background: ${t.ground};
      --diffs-border-color: ${t.border};
    }

    .diffs-addition-line { background-color: ${t.addBg} !important; }
    .diffs-deletion-line { background-color: ${t.delBg} !important; }
    .diffs-hunk-header { background-color: ${t.hunkBg} !important; color: ${t.hunkColor}; font-style: italic; }

    ::selection { background: ${t.selBg} !important; color: inherit !important; }

    .diffs-gutter { color: ${t.ink3}; font-size: 12px; }

    .diffs-file-header {
      background: ${t.surface};
      border-bottom: 1px solid ${t.border};
      padding: 6px 16px;
      font-size: 12px;
      font-weight: 500;
    }

    .diffs-selected-line {
      background-color: ${t.selBg} !important;
    }
  `;
}

/* ── shared options builder ──────────────────────────────────────── */

function makeDiffOptions(
  isDark: boolean,
  opts?: {
    disableFileHeader?: boolean;
    onLineSelectionEnd?: (range: SelectedLineRange | null) => void;
    onLineClick?: (props: any) => void;
  },
) {
  return {
    diffStyle: "unified" as const,
    theme: isDark
      ? ({ dark: "github-dark", light: "github-light" } as any)
      : ({ dark: "github-dark", light: "github-light" } as any),
    unsafeCSS: mimirUnsafeCSS(isDark),
    disableFileHeader: opts?.disableFileHeader ?? false,
    enableLineSelection: true,
    onLineSelectionEnd: opts?.onLineSelectionEnd,
    onLineClick: opts?.onLineClick,
  };
}

/* ── single-file diff component ──────────────────────────────────── */

export function PierreDiffViewer({ patch, file, onLineSelect }: Props) {
  const isDark = useMemo(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    [],
  );
  const mouseRef = useRef({ x: 0, y: 0 });

  const handleMouseMove = useCallback((e: MouseEvent) => {
    mouseRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  const handleLineSelectionEnd = useCallback(
    (range: SelectedLineRange | null) => {
      if (!onLineSelect || !file || !range) return;
      const { x, y } = mouseRef.current;
      onLineSelect(file, range.start, range.end, y + 10, x);
    },
    [onLineSelect, file],
  );

  const handleLineClick = useCallback(
    (props: any) => {
      if (!onLineSelect || !file) return;
      const event = props.event as PointerEvent | undefined;
      const x = event?.clientX ?? mouseRef.current.x;
      const y = event?.clientY ?? mouseRef.current.y;
      onLineSelect(file, props.lineNumber, props.lineNumber, y + 10, x);
    },
    [onLineSelect, file],
  );

  const options = useMemo(
    () =>
      makeDiffOptions(isDark, {
        onLineSelectionEnd: handleLineSelectionEnd,
        onLineClick: handleLineClick,
      }),
    [isDark, handleLineSelectionEnd, handleLineClick],
  );

  return (
    <div class="pierre-diff-viewer" onMouseMove={handleMouseMove}>
      <PatchDiff patch={patch} options={options} />
    </div>
  );
}

/* ── multi-file diff viewer ──────────────────────────────────────── */

interface FileDiffChunk {
  path: string;
  additions: number;
  deletions: number;
  rawDiff: string;
}

function splitDiffByFile(patch: string): FileDiffChunk[] {
  const lines = patch.split("\n");
  const chunks: FileDiffChunk[] = [];
  let start = -1;
  let path = "";
  let adds = 0;
  let dels = 0;

  function flush(end: number) {
    if (start < 0) return;
    let e = end;
    while (e > start && lines[e - 1] === "") e--;
    chunks.push({
      path,
      additions: adds,
      deletions: dels,
      rawDiff: lines.slice(start, e).join("\n"),
    });
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("diff --git ")) {
      flush(i);
      start = i;
      adds = 0;
      dels = 0;
      const m = line.match(/^diff --git a\/(.+) b\/(.+)$/);
      path = m?.[2] ?? "";
      continue;
    }
    if (start >= 0) {
      if (line.startsWith("+") && !line.startsWith("+++")) adds++;
      if (line.startsWith("-") && !line.startsWith("---")) dels++;
    }
  }
  flush(lines.length);
  return chunks;
}

interface MultiDiffProps {
  patch: string;
  label: string;
  onLineSelect?: Props["onLineSelect"];
  onFileVisible?: (path: string) => void;
}

export function PierreMultiDiffViewer({
  patch,
  label,
  onLineSelect,
}: MultiDiffProps) {
  const chunks = useMemo(() => splitDiffByFile(patch), [patch]);
  const isDark = useMemo(
    () => window.matchMedia("(prefers-color-scheme: dark)").matches,
    [],
  );
  // Shared mouse tracker across all file sections
  const mouseRef = useRef({ x: 0, y: 0 });
  const handleMouseMove = useCallback((e: MouseEvent) => {
    mouseRef.current = { x: e.clientX, y: e.clientY };
  }, []);

  return (
    <div class="multi-diff-scroll" onMouseMove={handleMouseMove}>
      {chunks.map((chunk) => (
        <div
          key={chunk.path}
          class="multi-diff-file"
          id={`diff-file-${chunk.path}`}
        >
          <div class="multi-diff-header">
            <span class="multi-diff-path">{chunk.path}</span>
            <span class="multi-diff-stat">
              <span class="multi-diff-add">+{chunk.additions}</span>{" "}
              <span class="multi-diff-del">-{chunk.deletions}</span>
            </span>
          </div>
          <PierreDiffSection
            chunk={chunk}
            isDark={isDark}
            mouseRef={mouseRef}
            onLineSelect={onLineSelect}
          />
        </div>
      ))}
    </div>
  );
}

/** Single file section — lazy-mounted via IntersectionObserver */
function PierreDiffSection({
  chunk,
  isDark,
  mouseRef,
  onLineSelect,
}: {
  chunk: FileDiffChunk;
  isDark: boolean;
  mouseRef: { current: { x: number; y: number } };
  onLineSelect?: Props["onLineSelect"];
}) {
  const sentinelRef = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!sentinelRef.current) return;
    const obs = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    obs.observe(sentinelRef.current);
    return () => obs.disconnect();
  }, []);

  const handleLineSelectionEnd = useCallback(
    (range: SelectedLineRange | null) => {
      if (!onLineSelect || !range) return;
      const { x, y } = mouseRef.current;
      onLineSelect(chunk.path, range.start, range.end, y + 10, x);
    },
    [onLineSelect, chunk.path, mouseRef],
  );

  const handleLineClick = useCallback(
    (props: any) => {
      if (!onLineSelect) return;
      const event = props.event as PointerEvent | undefined;
      const x = event?.clientX ?? mouseRef.current.x;
      const y = event?.clientY ?? mouseRef.current.y;
      onLineSelect(chunk.path, props.lineNumber, props.lineNumber, y + 10, x);
    },
    [onLineSelect, chunk.path, mouseRef],
  );

  const options = useMemo(
    () =>
      makeDiffOptions(isDark, {
        disableFileHeader: true,
        onLineSelectionEnd: handleLineSelectionEnd,
        onLineClick: handleLineClick,
      }),
    [isDark, handleLineSelectionEnd, handleLineClick],
  );

  const lineCount = chunk.rawDiff.split("\n").length;
  const estimatedHeight = lineCount * 24;

  return (
    <div ref={sentinelRef}>
      {visible ? (
        <div class="diff-file-editor">
          <PatchDiff patch={chunk.rawDiff} options={options} />
        </div>
      ) : (
        <div
          class="diff-file-placeholder"
          style={{ height: `${Math.min(estimatedHeight, 800)}px` }}
        />
      )}
    </div>
  );
}
