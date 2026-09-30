/**
 * One panel on screen: a header (title + state badge) and a body.
 *
 * Imperative by contract — this is a surface, on the poll path (DESIGN.md
 * "surfaces"). The two behaviours that matter:
 *
 *  - **Embed once, then `change()`.** Re-embedding on every refresh throws away
 *    the SVG and rebuilds it, which at a 2s cadence is a visible flash and a
 *    guaranteed >0.1s frame. So the first successful result embeds, and every
 *    later one pushes rows into the live Vega view with a changeset. `embeds`
 *    counts embeds so a test can assert the DOM was not rebuilt.
 *  - **Failure renders in place.** A query error, a shape error or a malformed
 *    response replaces the body with its own text — a notebook cell with a
 *    traceback, not a blank chart.
 *  - **Failure is also LOUD once.** DESIGN.md's Register says panel errors
 *    surface as toasts; the cell is the only thing that knows a panel just
 *    broke, so it dispatches `observe:notify` (the one sanctioned views -> app
 *    channel, see src/app/notify.ts — views may not import it, so the literal
 *    is duplicated here by design). Once per TRANSITION into a bad state, not
 *    once per poll: a 2s interval against a broken query would otherwise emit
 *    1800 toasts an hour.
 */

import type {
  Panel,
  PanelState,
  QueryColumn,
  QueryResult,
  QueryRow,
} from "../../core/panel.ts";
import { checkShape, rowsToObjects } from "../../core/panel.ts";
import type { QueryOutcome } from "../../core/query.ts";
import { resolveVegaTheme } from "../../core/vega-theme.ts";
import "./panels.css";

/**
 * The slice of vega-embed and vega we use, named so a test can pass a stub.
 * jsdom cannot run Vega's layout (no real SVG metrics), so the state-rendering
 * tests stub this and the real embed is verified in the browser.
 */
export interface VegaView {
  change(dataset: string, changeset: VegaChangeset): VegaView;
  runAsync(): Promise<unknown>;
  finalize(): void;
}

export interface VegaDeps {
  embed(
    el: HTMLElement,
    spec: unknown,
    opts: Record<string, unknown>,
  ): Promise<{ view: VegaView; finalize(): void }>;
  /** vega's `changeset()` factory. Both methods are chainable builders. */
  changeset(): VegaChangeset;
}

/**
 * The chainable subset of vega's Changeset we use, plus the underlying object.
 *
 * `raw` is what gets handed back to `view.change()`. Carrying it on the
 * interface is what lets the real adapter pass vega its own Changeset with no
 * cast, while a test stub supplies whatever it likes as `raw`.
 */
export interface VegaChangeset {
  readonly raw: unknown;
  remove(predicate: (datum: unknown) => boolean): VegaChangeset;
  insert(values: readonly unknown[]): VegaChangeset;
}

/** The dataset the panel's inline `data.values` becomes inside a Vega view. */
export const DATASET = "panel_rows";

export interface PanelCell {
  readonly panel: Panel;
  readonly root: HTMLElement;
  /** Push a fresh outcome in. Returns once the DOM (and Vega) reflect it. */
  render(outcome: QueryOutcome): Promise<void>;
  /** Mark the panel as waiting on its first answer. */
  setLoading(): void;
  state(): PanelState;
  /** How many times vega-embed has been called. Must stay 1 across refreshes. */
  embeds(): number;
  destroy(): void;
}

function el(tag: string, className?: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  if (className !== undefined) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/**
 * The views -> app notify channel, by literal.
 *
 * `views/` must not import `app/` (lint-enforced), so the event name and detail
 * shape are duplicated from src/app/notify.ts. That duplication IS the boundary;
 * see that file's header.
 */
const NOTIFY_EVENT = "observe:notify";

function notify(kind: "info" | "warning" | "error", message: string): void {
  window.dispatchEvent(
    new CustomEvent(NOTIFY_EVENT, { detail: { kind, message } }),
  );
}

/**
 * The notification a state deserves, or null when it deserves none.
 *
 * Keyed by state KIND, not by message: the identity is what "already told them"
 * is measured against, so a query error whose message changes while the panel
 * stays broken does not re-toast.
 */
export function noticeFor(
  panel: Panel,
  state: PanelState,
): { readonly key: string; readonly kind: "warning" | "error"; readonly message: string } | null {
  switch (state.kind) {
    case "query-error":
      return {
        key: "query-error",
        kind: "error",
        message: `panel ${panel.title}: ${state.message}`,
      };
    case "shape-error":
      return {
        key: "shape-error",
        kind: "error",
        message:
          `panel ${panel.title}: field \`${state.error.field}\` ` +
          `expected ${state.error.expected}, got ${state.error.got}`,
      };
    case "truncated":
      return {
        key: "truncated",
        kind: "warning",
        message: truncatedText(state.result.rows.length, state.limit),
      };
    case "idle":
    case "loading":
    case "ok":
      return null;
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}

/** The human sentence a truncated panel puts in its header. */
export function truncatedText(rows: number, limit: number): string {
  // "M+" because `truncated` is measured by fetching limit+1 rows: the store
  // holds at least this many and we do not know how many more.
  return `showing ${String(rows)} of ${String(rows)}+ rows (limit ${String(limit)})`;
}

/** Turn an outcome plus the spec's shape requirements into a PanelState. */
export function toPanelState(panel: Panel, outcome: QueryOutcome): PanelState {
  switch (outcome.kind) {
    case "result": {
      const shape = checkShape(outcome.columns, panel.viz);
      if (shape !== null) return { kind: "shape-error", error: shape };
      if (outcome.truncated) {
        return { kind: "truncated", result: outcome, limit: outcome.limit };
      }
      return { kind: "ok", result: outcome };
    }
    case "query-error":
    case "timeout":
    case "http-error":
      return { kind: "query-error", message: outcome.message };
    case "network-error":
      return { kind: "query-error", message: `network: ${outcome.message}` };
    case "malformed-response":
      return { kind: "query-error", message: `malformed /query response: ${outcome.reason}` };
    default: {
      const exhaustive: never = outcome;
      return exhaustive;
    }
  }
}

/** The badge text for a state, or null when there is nothing worth saying. */
export function badgeFor(state: PanelState): { text: string; tone: string } | null {
  switch (state.kind) {
    case "idle":
      return null;
    case "loading":
      return { text: "loading", tone: "muted" };
    case "ok":
      return { text: `${String(state.result.rows.length)} rows`, tone: "live" };
    case "truncated":
      return { text: "truncated", tone: "warn" };
    case "query-error":
      return { text: "error", tone: "error" };
    case "shape-error":
      return { text: "shape error", tone: "error" };
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}

/** The in-place failure text. Empty for the states that are not failures. */
export function failureText(state: PanelState): string | null {
  switch (state.kind) {
    case "query-error":
      return state.message;
    case "shape-error":
      return `field \`${state.error.field}\`: expected ${state.error.expected}, got ${state.error.got}`;
    case "idle":
    case "loading":
    case "ok":
    case "truncated":
      return null;
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}

/** The spec handed to vega-embed: the panel's viz with rows bound and a name. */
export function specWithData(
  panel: Panel,
  columns: readonly QueryColumn[],
  rows: readonly QueryRow[],
): Record<string, unknown> {
  return {
    ...panel.viz,
    data: { name: DATASET, values: rowsToObjects(columns, rows) },
  };
}

export function createPanelCell(panel: Panel, vega: VegaDeps): PanelCell {
  const root = el("section", "panel");
  root.dataset["panel"] = panel.id;

  const header = el("header", "panel-header");
  const title = el("h3", "panel-title", panel.title);
  const badge = el("span", "panel-badge");
  // The truncation sentence, in the header next to the badge. A 10px mono badge
  // reading "truncated 10000/10000" is a thing you scroll past; "showing 10000
  // of 10000+ rows (limit 10000)" is a thing you read.
  const notice = el("p", "panel-notice");
  notice.hidden = true;
  header.append(title, notice, badge);

  const body = el("div", "panel-body");
  const plot = el("div", "panel-plot");
  const failure = el("pre", "panel-failure");
  failure.hidden = true;
  body.append(plot, failure);
  root.append(header, body);

  let state: PanelState = { kind: "idle" };
  let live: VegaView | null = null;
  let finalizeEmbed: (() => void) | null = null;
  let embedCount = 0;
  /** The notice key already announced, so a transition is told once. */
  let announced: string | null = null;

  /** Toast on a TRANSITION into a notifiable state; stay quiet inside one. */
  function announce(): void {
    const pending = noticeFor(panel, state);
    if (pending === null) {
      announced = null;
      return;
    }
    if (announced === pending.key) return;
    announced = pending.key;
    notify(pending.kind, pending.message);
  }

  function paintNotice(): void {
    if (state.kind !== "truncated") {
      notice.hidden = true;
      notice.textContent = "";
      return;
    }
    notice.hidden = false;
    notice.textContent = truncatedText(state.result.rows.length, state.limit);
  }

  function paintHeader(): void {
    paintNotice();
    const b = badgeFor(state);
    if (b === null) {
      badge.textContent = "";
      badge.removeAttribute("data-tone");
      badge.hidden = true;
      return;
    }
    badge.hidden = false;
    badge.textContent = b.text;
    badge.dataset["tone"] = b.tone;
  }

  function showFailure(text: string): void {
    // Drop the live view: its rows belong to a query that no longer describes
    // the panel, and leaving a stale chart under an error badge is a lie.
    if (finalizeEmbed !== null) {
      finalizeEmbed();
      finalizeEmbed = null;
      live = null;
    }
    plot.replaceChildren();
    plot.hidden = true;
    failure.hidden = false;
    failure.textContent = text;
  }

  function hideFailure(): void {
    failure.hidden = true;
    failure.textContent = "";
    plot.hidden = false;
  }

  async function showRows(result: QueryResult): Promise<void> {
    hideFailure();
    const values = rowsToObjects(result.columns, result.rows);
    if (live !== null) {
      // The whole point: mutate the existing view's data instead of rebuilding.
      // remove(all) + insert(rows) is a full replace without touching the DOM
      // tree Vega already built; only the marks it owns are re-bound.
      const cs = vega
        .changeset()
        .remove(() => true)
        .insert(values);
      live.change(DATASET, cs);
      await live.runAsync();
      return;
    }
    embedCount += 1;
    const embedded = await vega.embed(plot, specWithData(panel, result.columns, result.rows), {
      actions: false,
      renderer: "svg",
      // Resolved from the app's CSS variables at embed time, so the plots follow
      // the chrome's light/dark theme instead of hardcoding one of them.
      config: resolveVegaTheme(plot),
    });
    live = embedded.view;
    finalizeEmbed = (): void => {
      embedded.finalize();
    };
  }

  paintHeader();

  return {
    panel,
    root,
    setLoading(): void {
      // Only from idle: a refresh of a rendered panel must not blank the chart.
      if (state.kind === "idle") {
        state = { kind: "loading" };
        paintHeader();
      }
    },
    async render(outcome: QueryOutcome): Promise<void> {
      state = toPanelState(panel, outcome);
      paintHeader();
      announce();
      const text = failureText(state);
      if (text !== null) {
        showFailure(text);
        return;
      }
      if (state.kind === "ok" || state.kind === "truncated") {
        await showRows(state.result);
      }
    },
    state(): PanelState {
      return state;
    },
    embeds(): number {
      return embedCount;
    },
    destroy(): void {
      if (finalizeEmbed !== null) finalizeEmbed();
      finalizeEmbed = null;
      live = null;
      root.remove();
    },
  };
}
