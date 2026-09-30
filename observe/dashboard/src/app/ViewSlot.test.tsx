/**
 * ViewSlot's mount key.
 *
 * A surface cannot be rewound, so anything that changes what it should be
 * showing has to be a REMOUNT. Two of those were bugs:
 *
 *  - `file` was read inside the mount effect but not depended on, with an
 *    `eslint-disable` for `exhaustive-deps` and a comment claiming `resetKey`
 *    encodes it. With `?url=` it does not — the url is pinned while `file`
 *    follows the run picker — so the panels view kept querying the first run.
 *  - `theme` did not exist. The Vega config is baked from the computed CSS
 *    variables at embed time, so flipping the theme left every chart drawn in
 *    the old palette until something else happened to remount it.
 */

// @vitest-environment jsdom

import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Event, View, ViewContext } from "../core/events.ts";
import { ViewSlot } from "./ViewSlot.tsx";

interface Mounted {
  readonly ctx: ViewContext;
}

function spyView(): {
  view: View<Mounted>;
  mounts: ViewContext[];
  appends: (readonly Event[])[];
} {
  const mounts: ViewContext[] = [];
  const appends: (readonly Event[])[] = [];
  const view: View<Mounted> = {
    name: "spy",
    accepts: ["metric"],
    mount(_el, ctx): Mounted {
      mounts.push(ctx);
      return { ctx };
    },
    append(_state, events): void {
      appends.push([...events]);
    },
  };
  return { view, mounts, appends };
}

function metric(step: number): Event {
  return { kind: "metric", ts: 1_700_000_000, name: "wm_loss", value: 1, attrs: { step } };
}

const NO_EVENTS: readonly Event[] = [];

afterEach(() => {
  cleanup();
});

describe("ViewSlot", () => {
  it("mounts once and passes the file as the view's ctx", () => {
    const { view, mounts } = spyView();
    const { rerender } = render(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    expect(mounts).toEqual([{ file: "run.jsonl" }]);
    // A re-render that changes nothing in the key does not remount.
    rerender(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    expect(mounts).toHaveLength(1);
  });

  it("remounts when `file` changes even though the resetKey does not", () => {
    const { view, mounts } = spyView();
    const { rerender } = render(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="pinned" file="a.jsonl" theme="paper" />,
    );
    rerender(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="pinned" file="b.jsonl" theme="paper" />,
    );
    // Two mounts, and the second one was told about the new run.
    expect(mounts).toEqual([{ file: "a.jsonl" }, { file: "b.jsonl" }]);
  });

  it("remounts when the resolved theme changes", () => {
    const { view, mounts } = spyView();
    const { rerender } = render(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    rerender(
      <ViewSlot view={view} events={NO_EVENTS} revision={0} resetKey="a" file="run.jsonl" theme="paper-dark" />,
    );
    expect(mounts).toHaveLength(2);
  });

  /**
   * The remount's other half. A remount resets the cursor to zero, but the log
   * did not change — so without `mountKey` in the append effect the fresh
   * surface is handed nothing at all. A FINISHED run makes that permanent: no
   * further batch ever arrives to bump `revision`, so flipping the theme on a
   * completed run left every panel reading "waiting for metrics…" forever.
   * Found in the browser, on run-1k.
   */
  it("replays the whole log into the surface after a remount", () => {
    const { view, mounts, appends } = spyView();
    const events: readonly Event[] = [metric(1), metric(2), metric(3)];
    const { rerender } = render(
      <ViewSlot view={view} events={events} revision={3} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    expect(appends).toEqual([events]);

    // The theme flips. `events` and `revision` are untouched — the run is over.
    rerender(
      <ViewSlot view={view} events={events} revision={3} resetKey="a" file="run.jsonl" theme="paper-dark" />,
    );
    expect(mounts).toHaveLength(2);
    // The new surface got the log, not an empty view.
    expect(appends).toEqual([events, events]);
  });

  it("does not replay when nothing remounted", () => {
    const { view, appends } = spyView();
    const events: readonly Event[] = [metric(1)];
    const { rerender } = render(
      <ViewSlot view={view} events={events} revision={1} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    rerender(
      <ViewSlot view={view} events={events} revision={1} resetKey="a" file="run.jsonl" theme="paper" />,
    );
    expect(appends).toHaveLength(1);
  });
});
