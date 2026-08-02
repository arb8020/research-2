/**
 * Annotation UI — select lines, write comments, submit to agent.
 *
 * Components:
 * - AnnotationBar: bottom bar with annotation list + submit button
 * - AnnotationInput: inline comment input triggered by line selection
 * - useAnnotations: state management hook
 */

import { useState, useCallback, useRef, useEffect } from "preact/hooks";
import type { AnnotationData } from "./api";
import { submitAnnotations } from "./api";

export interface PendingAnnotation {
  id: string;
  file: string;
  startLine: number;
  endLine: number;
  side?: string | null;
  text: string;
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

  const submit = useCallback(async () => {
    setSubmitting(true);
    try {
      const data: AnnotationData[] = annotations.map((a) => ({
        file: a.file,
        start_line: a.startLine,
        end_line: a.endLine,
        side: a.side,
        text: a.text,
      }));
      await submitAnnotations(data);
      setSubmitted(true);
    } finally {
      setSubmitting(false);
    }
  }, [annotations]);

  return { annotations, add, remove, submit, submitting, submitted };
}

/* ── inline comment input ──────────────────────────────────────── */

interface InputProps {
  file: string;
  startLine: number;
  endLine: number;
  side?: string | null;
  onSubmit: (ann: Omit<PendingAnnotation, "id">) => void;
  onCancel: () => void;
}

export function AnnotationInput({ file, startLine, endLine, side, onSubmit, onCancel }: InputProps) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = () => {
    if (!text.trim()) return;
    onSubmit({ file, startLine, endLine, side, text: text.trim() });
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

  const range = startLine === endLine ? `L${startLine}` : `L${startLine}-${endLine}`;

  return (
    <div class="ann-input">
      <div class="ann-input-header">
        <span class="ann-input-range">{range}</span>
        <span class="ann-input-file">{file}</span>
      </div>
      <textarea
        ref={inputRef}
        class="ann-input-textarea"
        value={text}
        onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
        onKeyDown={handleKeyDown}
        placeholder="comment... (cmd+enter to add, esc to cancel)"
        rows={3}
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

/* ── annotation bar (bottom) ───────────────────────────────────── */

interface BarProps {
  annotations: PendingAnnotation[];
  onRemove: (id: string) => void;
  onSubmit: () => void;
  submitting: boolean;
  submitted: boolean;
}

export function AnnotationBar({ annotations, onRemove, onSubmit, submitting, submitted }: BarProps) {
  if (submitted) {
    return (
      <div class="ann-bar ann-bar-done">
        <span>annotations sent to agent</span>
      </div>
    );
  }

  return (
    <div class="ann-bar">
      <div class="ann-bar-list">
        {annotations.length === 0 ? (
          <span class="ann-bar-empty">select lines to annotate</span>
        ) : (
          annotations.map((a) => (
            <div key={a.id} class="ann-bar-item">
              <span class="ann-bar-item-loc">
                {a.file}:{a.startLine}{a.startLine !== a.endLine ? `-${a.endLine}` : ""}
              </span>
              <span class="ann-bar-item-text">{a.text}</span>
              <button class="ann-bar-item-rm" onClick={() => onRemove(a.id)}>x</button>
            </div>
          ))
        )}
      </div>
      <button
        class="ann-btn ann-btn-submit"
        onClick={onSubmit}
        disabled={annotations.length === 0 || submitting}
      >
        {submitting ? "sending..." : `send ${annotations.length} annotation${annotations.length !== 1 ? "s" : ""}`}
      </button>
    </div>
  );
}
