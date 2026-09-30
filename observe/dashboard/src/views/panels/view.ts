/**
 * The panels view — the landing surface (DESIGN.md "Register").
 *
 * It replaces the hand-rolled metrics chart: one panel per metric name, each a
 * SQL query against `/query` fed to a Vega-Lite line mark.
 *
 * ## Why it still accepts events
 *
 * A panel's data comes from `/query`, not from the event stream, so this view
 * does not plot the events it receives. It uses their ARRIVAL as two signals:
 *
 *  - **which panels exist** — a metric name it has not seen gets a panel. The
 *    default panels are derived from the data, nothing is hardcoded.
 *  - **that there is new data** — an append means the file grew, so re-run the
 *    queries. Debounced to >=500ms so a burst of 200 metrics is one refresh.
 *
 * While the run is live it also re-runs on a 2s interval, because a query can
 * see rows that the tailer's own cursor has not reached yet and because a
 * truncated panel should keep advancing. On `run_end` the interval stops: a
 * finished run's rows do not change, and polling a dead run forever is how a
 * dashboard becomes a load generator.
 *
 * ## View-contract extensions this view needed (see core/events.ts)
 *
 *  1. `accepts: ["metric", "log"]`. The View contract hands a view only the
 *     kinds it accepts, so "is the run over" is not knowable from metrics
 *     alone. `run_end` is a `log` event (DESIGN.md: "`run_end` is a `log`
 *     event"), so the smallest honest extension is to accept `log` too and
 *     watch for `event === "run_end"` — no new contract surface at all.
 *  2. `mount(el, ctx)` with `ctx: { file }`. The panel SQL filters on
 *     `file = '<run file>'` and no Event carries the store's file name. `ctx`
 *     is REQUIRED: a view is mounted to look at a run, and when no run is
 *     selected the app renders no slot at all, so this view has no "no run"
 *     state to model.
 */

import * as vega from "vega";
import embed from "vega-embed";
import type { Event, View, ViewContext } from "../../core/events.ts";
import { RUN_END_EVENT } from "../../core/events.ts";
import type { Panel, VegaLiteSpec } from "../../core/panel.ts";
import { sqlLiteral } from "../../core/panel.ts";
import { runQuery } from "../../core/query.ts";
import type { PanelCell, VegaChangeset, VegaDeps, VegaView } from "./panel-cell.ts";
import { createPanelCell } from "./panel-cell.ts";
import "./panels.css";

/**
 * Whatever `setTimeout`/`setInterval` returns here: a `number` in the browser,
 * a `Timeout` object under Node/Bun. Naming it keeps the view runnable in both
 * without an `as` at every call site.
 */
type Timer = ReturnType<typeof globalThis.setTimeout>;

/** A burst of appends is one refresh. 0.5s is below the eye's patience. */
export const DEBOUNCE_MS = 500;
/** The live cadence, independent of appends. */
export const LIVE_POLL_MS = 2000;
/** The name of the hover param in a default panel's spec. */
export const HOVER_PARAM = "hover";

/** The x-axis a metric prefers: its `step` attr, or the wall clock. */
export type XAxis = "step" | "ts";

/**
 * The default panel for one metric name.
 *
 * `step` is not first-class (DESIGN.md) — it is an attr, and a metric that
 * never carries one must still plot, so the caller says which axis it saw.
 */
export function defaultPanel(args: {
  readonly name: string;
  readonly file: string;
  readonly x: XAxis;
}): Panel {
  const { name, file, x } = args;
  const query =
    `SELECT ${x}, value FROM events` +
    ` WHERE kind='metric' AND name=${sqlLiteral(name)} AND file=${sqlLiteral(file)}` +
    ` ORDER BY ${x}`;
  // Single-panel hover. Three layers:
  //
  //   line  — the series itself
  //   rule  — a full-height crosshair at the hovered x
  //   point — a marker on the hovered datum, carrying the tooltip
  //
  // The x/y encodings are declared PER LAYER rather than shared at the top
  // level, because a top-level `encoding` is inherited by every layer and a
  // `rule` that inherits y is a dot, not a crosshair: the rule layer must
  // encode x alone so Vega spans it across the plot height.
  //
  // Three layers rather than `mark: {point: true}`: a point on every datum is
  // noise at 10k rows — the marker should appear only under the cursor, which
  // is what the conditional opacity does.
  const xEnc = { field: x, type: "quantitative", title: x } as const;
  const yEnc = { field: "value", type: "quantitative", title: null } as const;
  /** Fully opaque only while `hover` has a datum; invisible otherwise. */
  const onHoverOnly = {
    condition: { param: HOVER_PARAM, value: 1, empty: false },
    value: 0,
  } as const;
  const viz: VegaLiteSpec = {
    width: "container",
    height: 160,
    layer: [
      { mark: { type: "line" }, encoding: { x: xEnc, y: yEnc } },
      {
        mark: { type: "rule" },
        encoding: { x: xEnc, opacity: onHoverOnly },
      },
      {
        mark: { type: "point", filled: true, size: 44 },
        params: [
          {
            name: HOVER_PARAM,
            // `nearest` on the x field: hovering anywhere in the panel selects
            // the datum whose x is closest, which is how a line chart should
            // read — you aim at a step, not at a 1.5px stroke.
            select: { type: "point", on: "mouseover", nearest: true, fields: [x] },
          },
        ],
        encoding: {
          x: xEnc,
          y: yEnc,
          opacity: onHoverOnly,
          tooltip: [
            { field: x, type: "quantitative", title: x },
            { field: "value", type: "quantitative", title: "value" },
          ],
        },
      },
    ],
  };
  return { id: `metric:${name}`, title: name, query, viz };
}

export interface PanelsState {
  readonly root: HTMLElement;
  readonly grid: HTMLElement;
  readonly notice: HTMLElement;
  readonly file: string;
  /** metric name -> its cell. Insertion order is discovery order. */
  readonly cells: Map<string, PanelCell>;
  /** metric name -> the x-axis its current cell was built for. */
  readonly axes: Map<string, XAxis>;
  readonly vega: VegaDeps;
  /** Everything with a timer or a fetch in flight, so teardown is total. */
  readonly timers: { debounce: Timer | null; poll: Timer | null };
  /**
   * The refresh in flight, if any.
   *
   * `controller` is what a NEW-DATA refresh aborts to supersede an older round.
   * `busy` is what the live poll checks: a tick that fires while a round is
   * still running must SKIP, not abort — aborting on a timer means a query
   * slower than LIVE_POLL_MS is cancelled by the next tick, forever, and the
   * panel never renders a row (poll starvation).
   */
  readonly inflight: { controller: AbortController | null; busy: boolean };
  live: boolean;
  destroyed: boolean;
}

function el(tag: string, className?: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className !== undefined) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/** The real vega-embed/vega pair. Swapped for a stub in tests. */
export function realVegaDeps(): VegaDeps {
  return {
    async embed(host, spec, opts) {
      // `spec` arrives as `unknown` from the cell's dependency interface, which
      // is what lets a test pass a stub. Narrow it to vega-embed's own spec type
      // here — the boundary between our injected seam and the library.
      if (!isEmbedSpec(spec)) {
        throw new TypeError("panel spec is not an object; cannot embed");
      }
      const result = await embed(host, spec, opts);
      const view: VegaView = {
        change(dataset, changeset) {
          // `raw` is the vega Changeset this adapter produced in `changeset()`
          // below; the narrowing is a real check, not a cast.
          const raw = changeset.raw;
          if (!isChangeset(raw)) {
            throw new TypeError("panel change() needs a vega Changeset");
          }
          result.view.change(dataset, raw);
          return view;
        },
        runAsync: () => result.view.runAsync(),
        finalize: () => {
          result.view.finalize();
        },
      };
      return {
        view,
        finalize: () => {
          result.finalize();
        },
      };
    },
    changeset(): VegaChangeset {
      const wrap = (cs: vega.Changeset): VegaChangeset => ({
        raw: cs,
        remove: (predicate) => wrap(cs.remove(predicate)),
        insert: (values) => wrap(cs.insert([...values])),
      });
      return wrap(vega.changeset());
    },
  };
}

type EmbedSpec = Parameters<typeof embed>[1];

function isEmbedSpec(value: unknown): value is EmbedSpec {
  return typeof value === "object" && value !== null;
}

/** A vega Changeset, verified by the two methods `view.change` will call. */
function isChangeset(value: unknown): value is vega.Changeset {
  return (
    typeof value === "object" &&
    value !== null &&
    "insert" in value &&
    typeof value.insert === "function" &&
    "remove" in value &&
    typeof value.remove === "function"
  );
}

/** Which axis a metric's panel should use: `step` when the attr is a number. */
function axisFor(event: Event): XAxis {
  if (event.kind !== "metric") return "ts";
  return typeof event.attrs["step"] === "number" ? "step" : "ts";
}

function isRunEnd(event: Event): boolean {
  return event.kind === "log" && event.event === RUN_END_EVENT;
}

function setNotice(state: PanelsState, text: string | null): void {
  if (text === null) {
    state.notice.hidden = true;
    state.notice.textContent = "";
    return;
  }
  state.notice.hidden = false;
  state.notice.textContent = text;
}

/**
 * Run every panel's query and push the outcome into its cell.
 *
 * Supersedes any round in flight: new data means the older answers are stale.
 * The live poll does NOT call this while a round is running — see
 * `startPolling`.
 */
export async function refresh(state: PanelsState): Promise<void> {
  if (state.destroyed) return;
  state.inflight.controller?.abort();
  state.inflight.busy = true;
  const controller = new AbortController();
  state.inflight.controller = controller;
  const cells = [...state.cells.values()];
  try {
    await Promise.all(
      cells.map(async (cell) => {
        cell.setLoading();
        const outcome = await runQuery(cell.panel.query, { signal: controller.signal });
        if (state.destroyed || controller.signal.aborted) return;
        await cell.render(outcome);
      }),
    );
  } catch (cause) {
    // runQuery rethrows only an abort, which means a newer refresh superseded
    // this one. Nothing to render and nothing to report.
    if (cause instanceof DOMException && cause.name === "AbortError") return;
    throw cause;
  } finally {
    if (state.inflight.controller === controller) {
      state.inflight.controller = null;
      state.inflight.busy = false;
    }
  }
}

function scheduleDebounced(state: PanelsState): void {
  if (state.destroyed) return;
  if (state.timers.debounce !== null) return; // already coalescing a burst
  state.timers.debounce = globalThis.setTimeout(() => {
    state.timers.debounce = null;
    void refresh(state);
  }, DEBOUNCE_MS);
}

function cancelDebounced(state: PanelsState): void {
  if (state.timers.debounce === null) return;
  globalThis.clearTimeout(state.timers.debounce);
  state.timers.debounce = null;
}

function startPolling(state: PanelsState): void {
  if (state.timers.poll !== null || state.destroyed) return;
  state.timers.poll = globalThis.setInterval(() => {
    if (!state.live) {
      stopPolling(state);
      return;
    }
    // Skip, do not abort. A query that takes longer than the interval still
    // gets to finish and render; the next tick after it lands picks up again.
    if (state.inflight.busy) return;
    void refresh(state);
  }, LIVE_POLL_MS);
}

function stopPolling(state: PanelsState): void {
  if (state.timers.poll === null) return;
  globalThis.clearInterval(state.timers.poll);
  state.timers.poll = null;
}

/** Install (or replace) the cell for one metric name, at the end of the grid. */
function putCell(state: PanelsState, name: string, x: XAxis): void {
  const panel = defaultPanel({ name, file: state.file, x });
  const cell = createPanelCell(panel, state.vega);
  const prior = state.cells.get(name);
  if (prior === undefined) {
    state.grid.append(cell.root);
  } else {
    // Replace in place so the grid keeps discovery order across a recreate.
    state.grid.insertBefore(cell.root, prior.root);
    prior.destroy();
  }
  state.cells.set(name, cell);
  state.axes.set(name, x);
}

/**
 * Create panels for metric names not seen before, and RE-EVALUATE the x-axis of
 * ones already on screen. Returns how many cells appeared or changed.
 *
 * The axis used to be pinned by the first event of a name, which is wrong for
 * the common case: `metric("wm_loss", v)` before the training loop starts (no
 * `step`) pinned the panel to `ts`, and every stepped point that followed was
 * plotted against the wall clock for the rest of the run. So a panel on `ts`
 * that later sees a `step` switches — one way only: `step` is strictly more
 * informative, and a metric that sometimes omits it must not flap the axis
 * back and forth every batch.
 */
export function ensurePanels(state: PanelsState, events: readonly Event[]): number {
  let changed = 0;
  for (const event of events) {
    if (event.kind !== "metric") continue;
    const x = axisFor(event);
    const prior = state.cells.get(event.name);
    if (prior === undefined) {
      putCell(state, event.name, x);
      changed += 1;
      continue;
    }
    if (x === "step" && state.axes.get(event.name) === "ts") {
      putCell(state, event.name, x);
      changed += 1;
    }
  }
  if (changed > 0) setNotice(state, null);
  return changed;
}

/** The append half of the contract, exported so a test can drive it directly. */
export function appendTo(state: PanelsState, events: readonly Event[]): void {
  if (state.destroyed) return;
  const changed = ensurePanels(state, events);
  const ended = events.some(isRunEnd);
  if (ended) {
    state.live = false;
    stopPolling(state);
    // A pending debounce from the burst that preceded run_end must go too:
    // otherwise the view fires one more query 500ms after it said it stopped.
    // The final refresh below is the last one, deliberately.
    cancelDebounced(state);
  } else if (state.live) {
    startPolling(state);
  }
  // A new (or recreated) panel has nothing on screen yet, and run_end means the
  // final rows are on disk — both deserve a query now rather than in 500ms.
  // Otherwise coalesce.
  if (changed > 0 || ended) void refresh(state);
  else scheduleDebounced(state);
}

export function createState(
  el_: HTMLElement,
  ctx: ViewContext,
  vegaDeps: VegaDeps,
): PanelsState {
  const root = el("div", "panels-view");
  // A panel-level empty state, INSIDE the view — not landing chrome. It names
  // itself as such (DESIGN.md's enforcement test: every element on the landing
  // surface is a metric panel, the status, or the run picker) and it is gone the
  // moment a panel exists.
  const notice = el("p", "panel-empty");
  const grid = el("div", "panels-grid");
  root.append(notice, grid);
  el_.append(root);

  const state: PanelsState = {
    root,
    grid,
    notice,
    file: ctx.file,
    cells: new Map(),
    axes: new Map(),
    vega: vegaDeps,
    timers: { debounce: null, poll: null },
    inflight: { controller: null, busy: false },
    live: true,
    destroyed: false,
  };
  setNotice(state, "waiting for metrics…");
  return state;
}

export function destroy(state: PanelsState): void {
  state.destroyed = true;
  stopPolling(state);
  cancelDebounced(state);
  state.inflight.controller?.abort();
  for (const cell of state.cells.values()) cell.destroy();
  state.cells.clear();
  state.axes.clear();
  state.root.remove();
}

export const view: View<PanelsState> = {
  name: "panels",
  // `log` is accepted for exactly one reason: `run_end` (see the header).
  accepts: ["metric", "log"],
  mount(el_: HTMLElement, ctx: ViewContext): PanelsState {
    return createState(el_, ctx, realVegaDeps());
  },
  append(state: PanelsState, events: readonly Event[]): void {
    appendTo(state, events);
  },
};
