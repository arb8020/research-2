/**
 * The panels view's live behaviour: panel discovery, debounce, the 2s poll, and
 * `run_end` stopping it.
 *
 * `runQuery` is mocked because the point here is WHEN queries run and with what
 * SQL, not what `/query` answers — that boundary has its own test in
 * core/query.test.ts. vega-embed is stubbed for the reason panel-cell.dom.test
 * gives: jsdom has no SVG layout.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Log, Metric } from "../../core/events.ts";
import type { QueryOutcome } from "../../core/query.ts";
import type { VegaChangeset, VegaDeps, VegaView } from "./panel-cell.ts";

const runQuery = vi.hoisted(() => vi.fn<(sql: string, opts?: unknown) => Promise<QueryOutcome>>());
vi.mock("../../core/query.ts", () => ({
  runQuery,
  isQueryError: (o: QueryOutcome): boolean => o.kind !== "result",
}));

const { DEBOUNCE_MS, LIVE_POLL_MS, appendTo, createState, destroy } = await import("./view.ts");

function metric(name: string, step: number | null = 1): Metric {
  return {
    kind: "metric",
    ts: 1_700_000_000,
    name,
    value: 1.5,
    attrs: step === null ? {} : { step },
  };
}

function log(event: string): Log {
  return { kind: "log", ts: 1_700_000_001, level: "INFO", event, logger: "train", attrs: {} };
}

function okResult(): QueryOutcome {
  return {
    kind: "result",
    columns: [
      { name: "step", type: "BIGINT" },
      { name: "value", type: "DOUBLE" },
    ],
    rows: [[1, 1.5]],
    truncated: false,
    limit: 10000,
    ms: 1,
  };
}

function stubVega(): VegaDeps {
  return {
    embed(host) {
      host.append(host.ownerDocument.createElement("svg"));
      const view: VegaView = {
        change: () => view,
        runAsync: () => Promise.resolve(null),
        finalize: () => undefined,
      };
      return Promise.resolve({ view, finalize: () => undefined });
    },
    changeset(): VegaChangeset {
      const cs: VegaChangeset = { raw: [], remove: () => cs, insert: () => cs };
      return cs;
    },
  };
}

/** Mount the view against a run file. `ctx` is required by the View contract. */
function mount(file = "run-1k.jsonl"): {
  state: ReturnType<typeof createState>;
  host: HTMLElement;
} {
  const host = document.createElement("div");
  document.body.append(host);
  const state = createState(host, { file }, stubVega());
  return { state, host };
}

/** Let the microtask queue drain so the awaited renders land. */
async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
}

function sqlSeen(): string[] {
  return runQuery.mock.calls.map((call) => call[0]);
}

describe("panels view", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    runQuery.mockReset();
    runQuery.mockResolvedValue(okResult());
    document.body.replaceChildren();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("creates one panel per NEW metric name, in arrival order", async () => {
    const { state, host } = mount();
    appendTo(state, [metric("wm_loss"), metric("pi_loss"), metric("wm_loss")]);
    await settle();
    const titles = [...host.querySelectorAll(".panel-title")].map((n) => n.textContent);
    expect(titles).toEqual(["wm_loss", "pi_loss"]);
    destroy(state);
  });

  it("queries a new panel immediately rather than waiting out the debounce", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss")]);
    await settle();
    expect(sqlSeen()).toHaveLength(1);
    expect(sqlSeen()[0]).toContain("name='wm_loss'");
    expect(sqlSeen()[0]).toContain("file='run-1k.jsonl'");
    destroy(state);
  });

  it("uses ts for a metric with no step attr", async () => {
    const { state } = mount();
    appendTo(state, [metric("gpu_temp", null)]);
    await settle();
    expect(sqlSeen()[0]).toContain("SELECT ts, value");
    destroy(state);
  });

  it("coalesces a burst of appends into ONE refresh, at >=500ms", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss")]); // creates the panel, refreshes now
    await settle();
    runQuery.mockClear();

    // 200 more metrics of a name already seen: a burst, not new panels.
    for (let i = 0; i < 200; i += 1) appendTo(state, [metric("wm_loss", i + 2)]);
    await settle();
    // Nothing yet — the debounce is still coalescing.
    expect(runQuery).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS - 1);
    expect(runQuery).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(runQuery).toHaveBeenCalledTimes(1);
    destroy(state);
  });

  it("re-runs every panel's query on the 2s live interval", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss"), metric("pi_loss")]);
    await settle();
    runQuery.mockClear();

    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(runQuery).toHaveBeenCalledTimes(2); // one per panel
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(runQuery).toHaveBeenCalledTimes(4);
    destroy(state);
  });

  it("stops polling on run_end and never queries again", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss")]);
    await settle();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    runQuery.mockClear();

    appendTo(state, [log("run_end")]);
    await settle();
    // The run_end append itself is a data signal, so one last refresh is fine —
    // what must not happen is the interval firing forever after.
    runQuery.mockClear();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 5);
    expect(runQuery).not.toHaveBeenCalled();
    destroy(state);
  });

  it("does not stop on an ordinary log event", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss")]);
    await settle();
    appendTo(state, [log("epoch_done")]);
    await vi.advanceTimersByTimeAsync(DEBOUNCE_MS);
    runQuery.mockClear();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(runQuery).toHaveBeenCalledTimes(1);
    destroy(state);
  });

  it("renders a per-panel failure without taking the others down", async () => {
    const { state, host } = mount();
    runQuery.mockImplementation((sql: string) =>
      Promise.resolve(
        sql.includes("pi_loss")
          ? { kind: "query-error", status: 400, message: "Binder Error: boom" }
          : okResult(),
      ),
    );
    appendTo(state, [metric("wm_loss"), metric("pi_loss")]);
    await settle();
    await settle();
    const failures = [...host.querySelectorAll<HTMLElement>(".panel-failure")].filter(
      (n) => !n.hidden,
    );
    expect(failures).toHaveLength(1);
    expect(failures[0]?.textContent).toContain("Binder Error: boom");
    // The healthy panel still has its chart.
    expect(host.querySelectorAll("svg")).toHaveLength(1);
    destroy(state);
  });

  it("stops every timer and removes its DOM on destroy", async () => {
    const { state, host } = mount();
    appendTo(state, [metric("wm_loss")]);
    await settle();
    destroy(state);
    runQuery.mockClear();
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 3 + DEBOUNCE_MS);
    expect(runQuery).not.toHaveBeenCalled();
    expect(host.children).toHaveLength(0);
    expect(state.cells.size).toBe(0);
  });

  // Poll starvation. The interval used to call refresh() unconditionally, and
  // refresh() aborts whatever is in flight — so a query slower than
  // LIVE_POLL_MS was cancelled by the very next tick, forever, and the panel
  // never rendered a row.
  it("lets a query slower than the poll interval finish and render", async () => {
    const { state, host } = mount();
    // Held in a one-slot box rather than a `let`: TS narrows a `let` captured
    // by a closure to its initializer and then calls the null check redundant.
    const slow: { resolve: ((outcome: QueryOutcome) => void) | null } = { resolve: null };
    runQuery.mockImplementation(
      () =>
        new Promise<QueryOutcome>((resolve) => {
          slow.resolve = resolve;
        }),
    );

    appendTo(state, [metric("wm_loss")]);
    await settle();
    expect(runQuery).toHaveBeenCalledTimes(1);

    // Three ticks go by while the one query is still out. Each must SKIP.
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS * 3);
    expect(runQuery).toHaveBeenCalledTimes(1);

    // Now it answers. Nothing aborted it, so the rows land.
    if (slow.resolve === null) throw new Error("query was never started");
    slow.resolve(okResult());
    await settle();
    await settle();
    expect(host.querySelectorAll("svg")).toHaveLength(1);
    expect(state.cells.get("wm_loss")?.state().kind).toBe("ok");

    // And the poll resumes once the round is done.
    runQuery.mockResolvedValue(okResult());
    await vi.advanceTimersByTimeAsync(LIVE_POLL_MS);
    expect(runQuery).toHaveBeenCalledTimes(2);
    destroy(state);
  });

  // Axis pinned from the first event. `metric("wm_loss", v)` logged before the
  // loop starts has no `step`, which pinned the panel to `ts` for the whole run.
  it("switches a ts panel to step when a later point carries one", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss", null)]);
    await settle();
    expect(sqlSeen()[0]).toContain("SELECT ts, value");
    const firstCell = state.cells.get("wm_loss");

    runQuery.mockClear();
    appendTo(state, [metric("wm_loss", 1)]);
    await settle();
    // The cell was recreated (a spec's x is baked in at embed time) and the
    // new query is on step.
    expect(state.cells.get("wm_loss")).not.toBe(firstCell);
    expect(sqlSeen()[0]).toContain("SELECT step, value");
    expect(state.cells.get("wm_loss")?.panel.query).toContain("ORDER BY step");
    destroy(state);
  });

  it("does not flap back to ts when a later point drops step", async () => {
    const { state } = mount();
    appendTo(state, [metric("wm_loss", 1)]);
    await settle();
    const cell = state.cells.get("wm_loss");
    runQuery.mockClear();
    appendTo(state, [metric("wm_loss", null)]);
    await settle();
    // Same cell, still on step: `step` is strictly more informative, and an
    // axis that flips every batch is worse than either choice.
    expect(state.cells.get("wm_loss")).toBe(cell);
    expect(state.cells.get("wm_loss")?.panel.query).toContain("ORDER BY step");
    destroy(state);
  });

  it("ignores appends after destroy", async () => {
    const { state } = mount();
    destroy(state);
    appendTo(state, [metric("late")]);
    await settle();
    expect(runQuery).not.toHaveBeenCalled();
  });
});
