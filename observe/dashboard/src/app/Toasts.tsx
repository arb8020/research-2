/**
 * The toast stack: bottom-right, newest at the bottom.
 *
 * Everything loud goes here rather than onto the landing surface (DESIGN.md
 * "Register": warnings/errors surface as toasts). Three feeds, one stack:
 *   - `Log` events with level >= WARNING, lifted by App
 *   - parse errors (this replaced an inline banner)
 *   - the views -> app notify bus (see notify.ts)
 *
 * Errors are sticky: a traceback you can scroll past is a traceback you miss,
 * so it stays until clicked. Everything else auto-dismisses after 6s. At most
 * five are on screen; the rest collapse into a "+N" line so a 200-warning run
 * does not become a wall.
 *
 * Two bounds keep the stack from becoming the failure it reports (sticky errors
 * never expire, so without them a broken run grows an unbounded array of React
 * nodes):
 *
 *  - **Dedupe.** The same (kind, message) increments the existing toast's
 *    `count`, shown as `×N`, rather than pushing another row. 1000 identical
 *    parse errors are one line reading `×1000`, which is also the more useful
 *    fact: "this happened a thousand times", not a thousand copies of it.
 *  - **Cap.** At most TOAST_RETAIN are retained at all; the oldest fall off.
 *
 * Both live in `addToast`, so the reducer is testable without React.
 */

import { useEffect } from "react";
import type { NotifyKind } from "./notify.ts";
import "./toasts.css";

export interface Toast {
  readonly id: number;
  readonly kind: NotifyKind;
  readonly message: string;
  /** How many times this exact (kind, message) arrived. 1 for a fresh toast. */
  readonly count: number;
}

/** How long a non-error toast lives. Errors never expire on their own. */
export const TOAST_TTL_MS = 6000;

/** Visible at once; older ones collapse to a count. */
export const TOAST_VISIBLE = 5;

/**
 * Retained at all. Beyond this the OLDEST are dropped: a stack with 50 distinct
 * failures in it has already made its point, and sticky errors would otherwise
 * grow it without limit.
 */
export const TOAST_RETAIN = 50;

/**
 * Fold one notification into the retained toasts.
 *
 * Pure, and exported so the dedupe and the cap are pinned without rendering.
 * `nextId` is only consumed when a genuinely new toast is created, so an id is
 * never burned on a duplicate.
 */
export function addToast(
  current: readonly Toast[],
  incoming: { readonly kind: NotifyKind; readonly message: string },
  nextId: number,
): readonly Toast[] {
  const at = current.findIndex(
    (toast) => toast.kind === incoming.kind && toast.message === incoming.message,
  );
  if (at !== -1) {
    const prior = current[at];
    if (prior !== undefined) {
      // Counted in place: the toast keeps its position and its id, so a
      // duplicate does not shuffle the stack or restart a TTL.
      const bumped: Toast = { ...prior, count: prior.count + 1 };
      return [...current.slice(0, at), bumped, ...current.slice(at + 1)];
    }
  }
  const grown = [
    ...current,
    { id: nextId, kind: incoming.kind, message: incoming.message, count: 1 },
  ];
  return grown.length <= TOAST_RETAIN ? grown : grown.slice(grown.length - TOAST_RETAIN);
}

interface ToastsProps {
  readonly toasts: readonly Toast[];
  readonly onDismiss: (id: number) => void;
}

function ToastRow({
  toast,
  onDismiss,
}: {
  readonly toast: Toast;
  readonly onDismiss: (id: number) => void;
}): React.JSX.Element {
  const sticky = toast.kind === "error";

  useEffect(() => {
    if (sticky) return;
    const timer = window.setTimeout(() => {
      onDismiss(toast.id);
    }, TOAST_TTL_MS);
    return (): void => {
      window.clearTimeout(timer);
    };
  }, [sticky, toast.id, onDismiss]);

  return (
    <button
      type="button"
      className="toast"
      data-kind={toast.kind}
      data-sticky={sticky ? "true" : undefined}
      title={sticky ? "click to dismiss" : undefined}
      onClick={(): void => {
        onDismiss(toast.id);
      }}
    >
      <span className="toast-message">{toast.message}</span>
      {toast.count > 1 && (
        <span className="toast-count tabular">×{toast.count}</span>
      )}
    </button>
  );
}

export function Toasts({ toasts, onDismiss }: ToastsProps): React.JSX.Element | null {
  if (toasts.length === 0) return null;
  // Newest last: the stack grows downward toward the corner, so the freshest
  // toast is the one nearest the cursor.
  const visible = toasts.slice(-TOAST_VISIBLE);
  const collapsed = toasts.length - visible.length;

  return (
    <div className="toast-stack" role="log" aria-live="polite">
      {collapsed > 0 && (
        <span className="toast-collapsed tabular">+{collapsed} more</span>
      )}
      {visible.map((toast) => (
        <ToastRow key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
