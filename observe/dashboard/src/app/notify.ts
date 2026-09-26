/**
 * The one sanctioned views -> app channel.
 *
 * `views/` must not import `app/` (lint-enforced: see eslint.config.js zones —
 * "a view never sees the chrome"), so a view that wants to raise a toast — a
 * panel whose query failed, a shape check that rejected the rows — cannot call
 * into the toast stack directly. It dispatches a DOM event on `window` instead:
 *
 *     window.dispatchEvent(
 *       new CustomEvent("observe:notify", {
 *         detail: { kind: "error", message: "query failed: …" },
 *       }),
 *     );
 *
 * App listens for it and renders a toast. This is the ONLY channel in that
 * direction; anything else a view needs from the chrome belongs in the View
 * contract in core/events.ts, not here. The event name and the `detail` shape
 * below are the contract — views duplicate the literal rather than importing
 * it, which is the price of the boundary.
 */

import { isRecord } from "../core/fields.ts";

/** Toast severities. `error` is sticky; the rest auto-dismiss. */
export const NOTIFY_KINDS = ["info", "warning", "error"] as const;

export type NotifyKind = (typeof NOTIFY_KINDS)[number];

export const NOTIFY_EVENT = "observe:notify";

export interface NotifyDetail {
  readonly kind: NotifyKind;
  readonly message: string;
}

/**
 * Raise a toast from anywhere. App-side callers can import this; views cannot,
 * so they dispatch the CustomEvent above by hand.
 */
export function notify(kind: NotifyKind, message: string): void {
  window.dispatchEvent(
    new CustomEvent<NotifyDetail>(NOTIFY_EVENT, { detail: { kind, message } }),
  );
}

/** Parse an incoming notify event, or null if the detail is not our shape. */
export function readNotifyEvent(event: Event): NotifyDetail | null {
  if (!(event instanceof CustomEvent)) return null;
  const detail: unknown = event.detail;
  // One `isRecord`, from core/fields.ts — the same gate every other boundary
  // in this app uses before reading a field off unknown JSON.
  if (!isRecord(detail)) return null;
  const kind = detail["kind"];
  const message = detail["message"];
  if (typeof message !== "string") return null;
  const known = NOTIFY_KINDS.find((candidate) => candidate === kind);
  // No semantic fallback on the message; an unknown kind is only a severity
  // hint, so it degrades to `info` rather than dropping the notification.
  return { kind: known ?? "info", message };
}

/**
 * Subscribe to the bus. Returns the unsubscribe function.
 */
export function onNotify(handler: (detail: NotifyDetail) => void): () => void {
  function listener(event: Event): void {
    const detail = readNotifyEvent(event);
    if (detail !== null) handler(detail);
  }
  window.addEventListener(NOTIFY_EVENT, listener);
  return (): void => {
    window.removeEventListener(NOTIFY_EVENT, listener);
  };
}
