/**
 * The toast stack's two bounds.
 *
 * Sticky errors never expire, so without a cap and a dedupe a run that raises
 * the same parse error on every line grows an unbounded array of React nodes —
 * the toast stack becomes the failure it is reporting.
 *
 * `addToast` is pure, so both bounds are pinned here without rendering.
 */

import { describe, expect, it } from "vitest";
import type { Toast } from "./Toasts.tsx";
import { TOAST_RETAIN, addToast } from "./Toasts.tsx";

function fold(
  n: number,
  incoming: { kind: Toast["kind"]; message: string },
): readonly Toast[] {
  let toasts: readonly Toast[] = [];
  for (let i = 0; i < n; i += 1) {
    toasts = addToast(toasts, incoming, i + 1);
  }
  return toasts;
}

describe("addToast", () => {
  it("adds a distinct toast", () => {
    const toasts = addToast([], { kind: "error", message: "boom" }, 1);
    expect(toasts).toEqual([{ id: 1, kind: "error", message: "boom", count: 1 }]);
  });

  it("collapses 1000 identical parse errors into ONE toast counted 1000", () => {
    const toasts = fold(1000, { kind: "error", message: "unknown kind: nope" });
    expect(toasts).toHaveLength(1);
    expect(toasts[0]?.count).toBe(1000);
    // And it keeps the id it was first given, so the row does not remount.
    expect(toasts[0]?.id).toBe(1);
  });

  it("treats the same message at a different severity as a different toast", () => {
    let toasts = addToast([], { kind: "warning", message: "same" }, 1);
    toasts = addToast(toasts, { kind: "error", message: "same" }, 2);
    expect(toasts).toHaveLength(2);
  });

  it("keeps a duplicate in place rather than resurfacing it", () => {
    let toasts = addToast([], { kind: "error", message: "first" }, 1);
    toasts = addToast(toasts, { kind: "error", message: "second" }, 2);
    toasts = addToast(toasts, { kind: "error", message: "first" }, 3);
    expect(toasts.map((t) => t.message)).toEqual(["first", "second"]);
    expect(toasts[0]?.count).toBe(2);
  });

  it("retains at most TOAST_RETAIN, dropping the oldest", () => {
    let toasts: readonly Toast[] = [];
    for (let i = 0; i < TOAST_RETAIN + 10; i += 1) {
      toasts = addToast(toasts, { kind: "error", message: `e${String(i)}` }, i + 1);
    }
    expect(toasts).toHaveLength(TOAST_RETAIN);
    // The newest survived; the first ten fell off the front.
    expect(toasts[toasts.length - 1]?.message).toBe(`e${String(TOAST_RETAIN + 9)}`);
    expect(toasts[0]?.message).toBe("e10");
  });
});
