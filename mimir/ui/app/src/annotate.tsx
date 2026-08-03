/**
 * Annotation UI — text-selection comments + sidebar + bottom bar.
 *
 * Components:
 * - AnnotationBar: bottom bar with count, copy, send, format toggle
 * - AnnotationInput: inline comment input triggered by text selection
 * - AnnotationSidebar: right panel showing all annotations
 * - useAnnotations: state management hook
 */

import { useState, useCallback, useRef, useEffect } from "preact/hooks";
import type { AnnotationData } from "./api";
import { submitAnnotations } from "./api";

export interface PendingAnnotation {
  id: string;
  file: string;          // "__message__" for message mode
  originalText: string;  // the selected text
  text: string;          // the comment
  // Legacy fields for file/diff mode
  startLine?: number;
  endLine?: number;
  side?: string | null;
}

let _nextId = 0;
function nextId(): string {
  return `ann-${++_nextId}`;
}

/* ── state hook ────────────────────────────────────────────────── */

export function useAnnotations() {
  const [annotations, setAnnotations] = useState<PendingAnnotation[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const add = useCallback((ann: Omit<PendingAnnotation, "id">) => {
    setAnnotations((prev) => [...prev, { ...ann, id: nextId() }]);
  }, []);

  const remove = useCallback((id: string) => {
    setAnnotations((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const update = useCallback((id: string, text: string) => {
    setAnnotations((prev) =>
      prev.map((a) => (a.id === id ? { ...a, text } : a))
    );
  }, []);

  const submit = useCallback(async (format: "json" | "markdown" = "json") => {
    setSubmitting(true);
    try {
      const data: AnnotationData[] = annotations.map((a) => ({
        file: a.file,
        start_line: a.startLine ?? 0,
        end_line: a.endLine ?? 0,
        side: a.side,
        text: a.text,
        original_text: a.originalText || undefined,
      }));
      await submitAnnotations(data);
      setSubmitted(true);
    } finally {
      setSubmitting(false);
    }
  }, [annotations]);

  return { annotations, add, remove, update, submit, submitting, submitted };
}

/* ── format helpers ───────────────────────────────────────────── */

function annotationsToMarkdown(annotations: PendingAnnotation[]): string {
  return annotations.map((a, i) => {
    const quote = a.originalText
      ? a.originalText.split("\n").map((l) => `> ${l}`).join("\n")
      : "";
    return `### Comment ${i + 1}\n\n${quote}\n\n${a.text}\n`;
  }).join("\n---\n\n");
}

function annotationsToJson(annotations: PendingAnnotation[]): string {
  return JSON.stringify(
    annotations.map((a) => ({
      file: a.file,
      originalText: a.originalText,
      comment: a.text,
    })),
    null,
    2
  );
}

/* ── inline comment input ──────────────────────────────────────── */

interface InputProps {
  file: string;
  originalText: string;
  startLine?: number;
  endLine?: number;
  side?: string | null;
  onSubmit: (ann: Omit<PendingAnnotation, "id">) => void;
  onCancel: () => void;
}

export function AnnotationInput({ file, originalText, startLine, endLine, side, onSubmit, onCancel }: InputProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const t = setTimeout(() => inputRef.current?.focus(), 50);
    return () => clearTimeout(t);
  }, []);

  const handleSubmit = () => {
    if (!text.trim()) return;
    onSubmit({ file, originalText, text: text.trim(), startLine, endLine, side });
    setText("");
  };

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      onCancel();
    }
  };

  const preview = originalText.length > 60
    ? originalText.slice(0, 57) + "..."
    : originalText;

  return (
    <div class="ann-input">
      <div class="ann-input-header">
        <span class="ann-input-range" title={originalText}>"{preview}"</span>
      </div>
      <textarea
        ref={inputRef}
        class="ann-input-textarea"
        value={text}
        onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
        onKeyDown={handleKeyDown}
        placeholder="comment... (⌘↵ to add, esc to cancel)"
        rows={2}
      />
      <div class="ann-input-actions">
        <button class="ann-btn ann-btn-secondary" onClick={onCancel}>cancel</button>
        <button class="ann-btn ann-btn-primary" onClick={handleSubmit} disabled={!text.trim()}>
          add
        </button>
      </div>
    </div>
  );
}

/* ── annotation sidebar (right panel) ─────────────────────────── */

interface SidebarProps {
  annotations: PendingAnnotation[];
  onRemove: (id: string) => void;
  onUpdate: (id: string, text: string) => void;
  onScrollTo?: (ann: PendingAnnotation) => void;
  collapsed: boolean;
  onToggle: () => void;
}

export function AnnotationSidebar({ annotations, onRemove, onUpdate, onScrollTo, collapsed, onToggle }: SidebarProps) {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState("");

  const startEdit = (ann: PendingAnnotation) => {
    setEditingId(ann.id);
    setEditText(ann.text);
  };

  const saveEdit = () => {
    if (editingId && editText.trim()) {
      onUpdate(editingId, editText.trim());
    }
    setEditingId(null);
  };

  if (collapsed) {
    return (
      <div class="ann-sidebar ann-sidebar-collapsed" onClick={onToggle}>
        <div class="ann-sidebar-toggle">{annotations.length}</div>
      </div>
    );
  }

  return (
    <div class="ann-sidebar">
      <div class="ann-sidebar-header">
        <span class="ann-sidebar-title">annotations ({annotations.length})</span>
        <button class="ann-sidebar-collapse" onClick={onToggle}>‹</button>
      </div>
      <div class="ann-sidebar-list">
        {annotations.length === 0 ? (
          <div class="ann-sidebar-empty">select text to annotate</div>
        ) : (
          annotations.map((a) => (
            <div
              key={a.id}
              class="ann-sidebar-item"
              onClick={() => onScrollTo?.(a)}
            >
              <div class="ann-sidebar-item-quote">
                {a.originalText.length > 80
                  ? a.originalText.slice(0, 77) + "..."
                  : a.originalText}
              </div>
              {editingId === a.id ? (
                <div class="ann-sidebar-item-edit">
                  <textarea
                    class="ann-input-textarea"
                    value={editText}
                    onInput={(e) => setEditText((e.target as HTMLTextAreaElement).value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault();
                        saveEdit();
                      }
                      if (e.key === "Escape") {
                        e.preventDefault();
                        setEditingId(null);
                      }
                    }}
                    rows={2}
                  />
                  <div class="ann-input-actions">
                    <button class="ann-btn ann-btn-secondary" onClick={() => setEditingId(null)}>cancel</button>
                    <button class="ann-btn ann-btn-primary" onClick={saveEdit}>save</button>
                  </div>
                </div>
              ) : (
                <div class="ann-sidebar-item-comment">{a.text}</div>
              )}
              <div class="ann-sidebar-item-actions">
                <button
                  class="ann-sidebar-item-btn"
                  onClick={(e) => { e.stopPropagation(); startEdit(a); }}
                  title="edit"
                >edit</button>
                <button
                  class="ann-sidebar-item-btn ann-sidebar-item-btn-del"
                  onClick={(e) => { e.stopPropagation(); onRemove(a.id); }}
                  title="delete"
                >del</button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

/* ── annotation bar (bottom) ───────────────────────────────────── */

interface BarProps {
  annotations: PendingAnnotation[];
  onRemove: (id: string) => void;
  onSubmit: (format?: "json" | "markdown") => void;
  submitting: boolean;
  submitted: boolean;
}

export function AnnotationBar({ annotations, onRemove, onSubmit, submitting, submitted }: BarProps) {
  const [format, setFormat] = useState<"json" | "markdown">("markdown");

  if (submitted) {
    return (
      <div class="ann-bar ann-bar-done">
        <span>annotations sent to agent</span>
      </div>
    );
  }

  const handleCopy = () => {
    const text = format === "markdown"
      ? annotationsToMarkdown(annotations)
      : annotationsToJson(annotations);
    navigator.clipboard.writeText(text);
  };

  return (
    <div class="ann-bar">
      <div class="ann-bar-list">
        <span class="ann-bar-count">
          {annotations.length} annotation{annotations.length !== 1 ? "s" : ""}
        </span>
      </div>
      <div class="ann-bar-actions">
        <button
          class={`ann-btn ann-btn-format ${format === "markdown" ? "active" : ""}`}
          onClick={() => setFormat(format === "json" ? "markdown" : "json")}
          title="toggle format"
        >
          {format === "markdown" ? "md" : "json"}
        </button>
        <button
          class="ann-btn ann-btn-secondary"
          onClick={handleCopy}
          disabled={annotations.length === 0}
        >
          copy
        </button>
        <button
          class="ann-btn ann-btn-submit"
          onClick={() => onSubmit(format)}
          disabled={submitting}
        >
          {submitting ? "sending..." : annotations.length === 0 ? "submit (no comments)" : `send ${annotations.length}`}
        </button>
      </div>
    </div>
  );
}
