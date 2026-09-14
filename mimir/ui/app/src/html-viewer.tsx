/**
 * HtmlViewer — same-origin iframe of a working-tree HTML file.
 *
 * Selection in the rendered document opens the annotate popover.
 * Existing annotations are re-applied as <mark> highlights via text-quote
 * matching so they survive iframe reloads without a sidecar store.
 */

import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { fetchFile, previewUrl } from "./api";
import type { PendingAnnotation } from "./annotate";
import { locateQuote, unwrapMarks, wrapQuote } from "./html-quote";

const MARK_STYLE = `
mark.mimir-ann {
  background: rgba(201, 162, 62, 0.38);
  color: inherit;
  padding: 0 1px;
  border-radius: 2px;
  cursor: pointer;
}
mark.mimir-ann[data-focused="1"] {
  outline: 2px solid rgba(201, 162, 62, 0.9);
  outline-offset: 1px;
}
`;

interface Props {
  path: string;
  annotations: PendingAnnotation[];
  focusId?: string | null;
  onTextSelect?: (
    file: string,
    originalText: string,
    top: number,
    left: number,
    extra?: {
      startLine?: number;
      endLine?: number;
      prefix?: string;
      suffix?: string;
    },
  ) => void;
}

function injectMarkStyle(doc: Document): void {
  if (doc.getElementById("mimir-ann-style")) return;
  const style = doc.createElement("style");
  style.id = "mimir-ann-style";
  style.textContent = MARK_STYLE;
  (doc.head || doc.documentElement).appendChild(style);
}

function applyMarks(doc: Document, annotations: PendingAnnotation[]): void {
  if (!doc.body) return;
  unwrapMarks(doc.body);
  // later annotations first so earlier offsets stay valid if wraps split nodes
  for (const a of [...annotations].reverse()) {
    if (!a.originalText) continue;
    wrapQuote(doc.body, a.originalText, a.id, a.prefix);
  }
}

export function HtmlViewer({ path, annotations, focusId, onTextSelect }: Props) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const sourceRef = useRef("");
  const [toolbar, setToolbar] = useState<{
    top: number;
    left: number;
    text: string;
    prefix?: string;
    suffix?: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    sourceRef.current = "";
    fetchFile(path).then((f) => {
      if (!cancelled) sourceRef.current = f.content;
    });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const lastFocusRef = useRef<string | null>(null);

  const paint = useCallback(() => {
    const doc = frameRef.current?.contentDocument;
    if (!doc) return;
    injectMarkStyle(doc);
    applyMarks(doc, annotations);
    if (focusId) {
      const el = doc.querySelector(`[data-ann-id="${CSS.escape(focusId)}"]`);
      if (el) {
        el.setAttribute("data-focused", "1");
        if (lastFocusRef.current !== focusId) {
          lastFocusRef.current = focusId;
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      }
    }
  }, [annotations, focusId]);

  useEffect(() => {
    paint();
  }, [paint]);

  const handleMouseUp = useCallback(() => {
    if (!onTextSelect) return;
    const iframe = frameRef.current;
    const doc = iframe?.contentDocument;
    if (!iframe || !doc) return;

    const sel = doc.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setToolbar(null);
      return;
    }
    const range = sel.getRangeAt(0);
    const raw = sel.toString();
    const lead = raw.length - raw.trimStart().length;
    const trail = raw.length - raw.trimEnd().length;
    const quote = raw.trim();
    if (!quote) {
      setToolbar(null);
      return;
    }

    const pre = doc.createRange();
    pre.setStart(doc.body, 0);
    pre.setEnd(range.startContainer, range.startOffset);
    const prefix = (pre.toString() + raw.slice(0, lead)).slice(-32);
    const post = doc.createRange();
    post.setStart(range.endContainer, range.endOffset);
    post.setEnd(doc.body, doc.body.childNodes.length);
    const suffix = (raw.slice(raw.length - trail) + post.toString()).slice(0, 32);

    const rect = range.getBoundingClientRect();
    const frameRect = iframe.getBoundingClientRect();
    setToolbar({
      top: frameRect.top + rect.top - 36,
      left: frameRect.left + rect.left + rect.width / 2 - 40,
      text: quote,
      prefix,
      suffix,
    });
  }, [onTextSelect]);

  const handleLoad = useCallback(() => {
    const doc = frameRef.current?.contentDocument;
    if (!doc) return;
    injectMarkStyle(doc);
    doc.addEventListener("mouseup", handleMouseUp);
    paint();
  }, [handleMouseUp, paint]);

  useEffect(() => {
    return () => {
      frameRef.current?.contentDocument?.removeEventListener("mouseup", handleMouseUp);
    };
  }, [handleMouseUp, path]);

  useEffect(() => {
    const dismiss = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".md-sel-toolbar")) return;
      setTimeout(() => {
        const sel = frameRef.current?.contentDocument?.getSelection();
        if (!sel || sel.isCollapsed) setToolbar(null);
      }, 10);
    };
    document.addEventListener("mousedown", dismiss);
    return () => document.removeEventListener("mousedown", dismiss);
  }, []);

  const handleComment = useCallback(() => {
    if (!toolbar || !onTextSelect) return;
    const loc = locateQuote(sourceRef.current, toolbar.text);
    onTextSelect(path, toolbar.text, toolbar.top + 40, toolbar.left, {
      startLine: loc?.startLine,
      endLine: loc?.endLine,
      prefix: toolbar.prefix,
      suffix: toolbar.suffix,
    });
    setToolbar(null);
    frameRef.current?.contentDocument?.getSelection()?.removeAllRanges();
  }, [toolbar, onTextSelect, path]);

  return (
    <div class="html-preview">
      <iframe
        ref={frameRef}
        class="html-preview-frame"
        src={previewUrl(path)}
        sandbox="allow-same-origin"
        title={path}
        onLoad={handleLoad}
      />
      {toolbar && (
        <div
          class="md-sel-toolbar"
          style={{
            position: "fixed",
            top: `${toolbar.top}px`,
            left: `${toolbar.left}px`,
          }}
        >
          <button class="md-sel-btn" onClick={handleComment}>
            comment
          </button>
        </div>
      )}
    </div>
  );
}
