/**
 * mimir app shell — file browser + code viewer + diff viewer.
 *
 * Modes:
 * - Browse: file tree (full repo) + code editor with --at popover/peek
 * - Diff: file tree (changed files only) + per-file diff viewer
 */

import { useState, useEffect, useCallback, useMemo, useRef } from "preact/hooks";
import { FileTree } from "./tree";
import { Editor } from "./editor";
import { PierreMultiDiffViewer } from "./pierre-diff-viewer";
import { fetchTree, fetchDiff, fetchAnnotateTarget, fetchMessage, type TreeData, type AnnotateTarget } from "./api";
import { parseUnifiedDiff, type DiffFile } from "./diff-parse";
import { useAnnotations, AnnotationInput, AnnotationBar, AnnotationSidebar, type PendingAnnotation } from "./annotate";
import { MessageViewer } from "./message-viewer";

/** Popover that tracks its anchor element on scroll/resize */
function AnnotationPopover({ showingInput, onSubmit, onCancel }: {
  showingInput: {
    file: string;
    startLine?: number;
    endLine?: number;
    originalText: string;
    top: number;
    left: number;
    anchorEl?: Element | null;
  };
  onSubmit: (ann: Omit<PendingAnnotation, "id">) => void;
  onCancel: () => void;
}) {
  const [pos, setPos] = useState({ top: showingInput.top, left: showingInput.left });

  const clickLeft = showingInput.left;
  const offsetRef = useRef(0);

  useEffect(() => {
    const anchor = showingInput.anchorEl;
    if (!anchor) {
      setPos({
        top: Math.min(showingInput.top + 4, window.innerHeight - 260),
        left: Math.min(clickLeft, window.innerWidth - 340),
      });
      return;
    }

    const anchorRect = anchor.getBoundingClientRect();
    offsetRef.current = showingInput.top - anchorRect.bottom;

    function update() {
      const rect = anchor!.getBoundingClientRect();
      const top = Math.min(rect.bottom + 4, window.innerHeight - 260);
      setPos({ top, left: Math.min(clickLeft, window.innerWidth - 340) });
    }
    update();

    document.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [showingInput.anchorEl, clickLeft]);

  return (
    <div style={{
      position: "fixed",
      top: `${pos.top}px`,
      left: `${pos.left}px`,
      zIndex: 100,
    }}>
      <AnnotationInput
        file={showingInput.file}
        originalText={showingInput.originalText}
        startLine={showingInput.startLine}
        endLine={showingInput.endLine}
        onSubmit={onSubmit}
        onCancel={onCancel}
      />
    </div>
  );
}

export function App() {
  const [tree, setTree] = useState<TreeData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [currentRef, setCurrentRef] = useState<string | null>(null);
  const [peekRef, setPeekRef] = useState<string | null>(null);
  const [peekLine, setPeekLine] = useState<number | null>(null);

  // Diff mode state
  const [diffFiles, setDiffFiles] = useState<DiffFile[] | null>(null);
  const [diffLabel, setDiffLabel] = useState<string>("");
  const [fullDiff, setFullDiff] = useState<string>("");

  // Annotate mode state
  const [annotateMode, setAnnotateMode] = useState(false);
  const [annotateTarget, setAnnotateTarget] = useState<AnnotateTarget | null>(null);
  const [showingInput, setShowingInput] = useState<{
    file: string;
    startLine?: number;
    endLine?: number;
    originalText: string;
    top: number;
    left: number;
    anchorEl?: Element | null;
  } | null>(null);
  // Message mode state
  const [messageText, setMessageText] = useState<string | null>(null);
  const [selectedMsgIdx, setSelectedMsgIdx] = useState<number | null>(null);
  // Sidebar state
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const annState = useAnnotations();

  const isDiffMode = diffFiles !== null;
  const isMessageMode = annotateTarget?.mode === "message" && messageText !== null;


  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const isAnnotate = params.get("annotate") === "1";

    if (isAnnotate) {
      setAnnotateMode(true);
      fetchAnnotateTarget().then((target) => {
        setAnnotateTarget(target);
        if (target.mode === "message" && target.message_text) {
          setMessageText(target.message_text);
          setSelectedMsgIdx(0);
          setSelected("msg:0");
          return;
        }
        fetchTree().then(setTree);
        if (target.mode === "diff") {
          // Fetch diff — works for both git ref diffs and stdin diffs
          const ref = target.diff_ref;
          const isRange = ref?.includes("..") ?? false;
          fetchDiff(
            isRange ? undefined : (ref ?? undefined),
            isRange ? ref! : undefined,
          ).then((data) => {
            const files = parseUnifiedDiff(data.diff);
            setDiffFiles(files);
            setDiffLabel(target.label);
            setFullDiff(data.diff);
            if (files.length > 0) setSelected(files[0].newPath);
          });
        }
      });
    } else {
      fetchTree().then(setTree);
      const diffRef = params.get("diff");
      const diffRange = params.get("range");
      if (diffRef !== null || diffRange !== null) {
        fetchDiff(diffRef ?? undefined, diffRange ?? undefined).then((data) => {
          const files = parseUnifiedDiff(data.diff);
          setDiffFiles(files);
          setDiffLabel(data.range ?? data.ref ?? "working tree");
          setFullDiff(data.diff);
          if (files.length > 0) setSelected(files[0].newPath);
        });
      }
    }
  }, []);

  const diffTree = useMemo<TreeData | null>(() => {
    if (!diffFiles) return null;
    const files = diffFiles.map((f) => f.newPath);
    const touched: Record<string, string[]> = {};
    for (const f of diffFiles) {
      if (f.additions > 0 || f.deletions > 0) {
        touched[f.newPath] = [`+${f.additions} -${f.deletions}`];
      }
    }
    return { files, touched, branch: diffLabel };
  }, [diffFiles, diffLabel]);

  const messageTree = useMemo<TreeData | null>(() => {
    if (!annotateTarget?.messages) return null;
    const files = annotateTarget.messages.map((m) => `msg:${m.index}`);
    const touched: Record<string, string[]> = {};
    for (const m of annotateTarget.messages) {
      touched[`msg:${m.index}`] = [m.preview];
    }
    return { files, touched, branch: "messages" };
  }, [annotateTarget]);

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

  const activeTree = isMessageMode ? messageTree : isDiffMode ? diffTree : tree;
  const touchedCount = selected && activeTree?.touched[selected]?.length;

  // Handle line selection for annotation (file/diff mode — legacy)
  const handleLineSelect = useCallback((file: string, startLine: number, endLine: number, top: number, left: number, anchorEl?: Element | null) => {
    if (!annotateMode) return;
    setShowingInput({ file, startLine, endLine, originalText: "", top, left, anchorEl });
  }, [annotateMode]);

  // Handle text selection for annotation (message mode)
  const handleTextSelect = useCallback((file: string, originalText: string, top: number, left: number) => {
    if (!annotateMode) return;
    setShowingInput({ file, originalText, top, left });
  }, [annotateMode]);

  const handleAnnotationAdd = useCallback((ann: Omit<PendingAnnotation, "id">) => {
    annState.add(ann);
    setShowingInput(null);
  }, [annState.add]);

  return (
    <div class={`app ${annotateMode ? "app-annotate app-with-sidebar" : ""}`}>
      <FileTree
        tree={activeTree}
        selected={selected}
        mode={isMessageMode ? "message" : isDiffMode ? "diff" : "browse"}
        onSelect={(path) => {
          setSelected(path);
          if (isMessageMode && path.startsWith("msg:")) {
            const idx = parseInt(path.slice(4), 10);
            setSelectedMsgIdx(idx);
            fetchMessage(idx).then((msg) => setMessageText(msg.text));
          } else if (isDiffMode) {
            // Scroll to file section in multi-diff viewer
            const el = document.getElementById(`diff-file-${path}`);
            if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
          } else {
            setCurrentRef(null);
            setPeekRef(null);
            setPeekLine(null);
          }
        }}
      />
      <div class="main">
        {isDiffMode && fullDiff ? (
          <>
            <div class="file-header">
              <span class="file-name">{diffLabel}</span>
              <span class="file-meta">
                {diffFiles?.length ?? 0} file{(diffFiles?.length ?? 0) !== 1 ? "s" : ""} changed
              </span>
            </div>
            <PierreMultiDiffViewer
              patch={fullDiff}
              label={diffLabel}
              onLineSelect={annotateMode ? handleLineSelect : undefined}
            />
          </>
        ) : isMessageMode ? (
          <>
            <div class="file-header">
              <span class="file-name">
                {selectedMsgIdx === 0 ? "last assistant message" : `message ${selectedMsgIdx! + 1} ago`}
              </span>
            </div>
            <MessageViewer
              text={messageText!}
              messageIndex={selectedMsgIdx ?? 0}
              onTextSelect={annotateMode ? handleTextSelect : undefined}
            />
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
          <AnnotationPopover
            showingInput={showingInput}
            onSubmit={handleAnnotationAdd}
            onCancel={() => setShowingInput(null)}
          />
        )}
      </div>

      {/* Annotation sidebar */}
      {annotateMode && (
        <AnnotationSidebar
          annotations={annState.annotations}
          onRemove={annState.remove}
          onUpdate={annState.update}
          collapsed={sidebarCollapsed}
          onToggle={() => setSidebarCollapsed(!sidebarCollapsed)}
        />
      )}

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
