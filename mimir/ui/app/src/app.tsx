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
import { fetchTree, fetchDiff, fetchAnnotateTarget, type TreeData, type AnnotateTarget } from "./api";
import { parseUnifiedDiff, type DiffFile } from "./diff-parse";
import { useAnnotations, AnnotationInput, AnnotationBar, type PendingAnnotation } from "./annotate";

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [currentRef, setCurrentRef] = useState<string | null>(null);
  const [peekRef, setPeekRef] = useState<string | null>(null);
  const [peekLine, setPeekLine] = useState<number | null>(null);

  // Diff mode state
  const [diffFiles, setDiffFiles] = useState<DiffFile[] | null>(null);
  const [diffLabel, setDiffLabel] = useState<string>("");

  // Annotate mode state
  const [annotateMode, setAnnotateMode] = useState(false);
  const [annotateTarget, setAnnotateTarget] = useState<AnnotateTarget | null>(null);
  const [showingInput, setShowingInput] = useState<{
    file: string;
    startLine: number;
    endLine: number;
    top: number;
  } | null>(null);
  const annState = useAnnotations();

  const isDiffMode = diffFiles !== null;

  useEffect(() => {
    fetchTree().then(setTree);

    // Check URL params for diff/annotate mode
    const params = new URLSearchParams(window.location.search);
    const isAnnotate = params.get("annotate") === "1";

    if (isAnnotate) {
      setAnnotateMode(true);
      fetchAnnotateTarget().then((target) => {
        setAnnotateTarget(target);
        if (target.mode === "diff" && target.diff_ref) {
          const isRange = target.diff_ref.includes("..");
          fetchDiff(
            isRange ? undefined : target.diff_ref,
            isRange ? target.diff_ref : undefined,
          ).then((data) => {
            const files = parseUnifiedDiff(data.diff);
            setDiffFiles(files);
            setDiffLabel(target.label);
            if (files.length > 0) setSelected(files[0].newPath);
          });
        }
      });
    } else {
      const diffRef = params.get("diff");
      const diffRange = params.get("range");
      if (diffRef !== null || diffRange !== null) {
        fetchDiff(diffRef ?? undefined, diffRange ?? undefined).then((data) => {
          const files = parseUnifiedDiff(data.diff);
          setDiffFiles(files);
          setDiffLabel(data.range ?? data.ref ?? "working tree");
          if (files.length > 0) setSelected(files[0].newPath);
        });
      }
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

  // Handle line selection for annotation — triggered by double-click on gutter
  const handleLineSelect = useCallback((file: string, startLine: number, endLine: number, top: number) => {
    if (!annotateMode) return;
    setShowingInput({ file, startLine, endLine, top });
  }, [annotateMode]);

  const handleAnnotationAdd = useCallback((ann: Omit<PendingAnnotation, "id">) => {
    annState.add(ann);
    setShowingInput(null);
  }, [annState.add]);

  return (
    <div class={`app ${annotateMode ? "app-annotate" : ""}`}>
      <FileTree
        tree={activeTree}
        selected={selected}
        mode={isDiffMode ? "diff" : "browse"}
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
              onLineSelect={annotateMode ? handleLineSelect : undefined}
            />
          </>
        ) : (
          <div class="empty-state">
            {isDiffMode
              ? "select a changed file"
              : annotateMode
                ? "pick a file to annotate"
                : "pick a file — click gutter marks for who's-here"}
          </div>
        )}

        {/* Annotation input popover */}
        {showingInput && (
          <AnnotationInput
            file={showingInput.file}
            startLine={showingInput.startLine}
            endLine={showingInput.endLine}
            onSubmit={handleAnnotationAdd}
            onCancel={() => setShowingInput(null)}
          />
        )}
      </div>

      {/* Annotation bar */}
      {annotateMode && (
        <AnnotationBar
          annotations={annState.annotations}
          onRemove={annState.remove}
          onSubmit={annState.submit}
          submitting={annState.submitting}
          submitted={annState.submitted}
        />
      )}
    </div>
  );
}
