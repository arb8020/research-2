/**
 * `panel-cell` state rendering, with vega-embed STUBBED.
 *
 * jsdom has no SVG layout engine, so real Vega produces a chart of NaNs there —
 * a green test that proves nothing. So the stub records what it was asked to do
 * (how many embeds, which changesets) and the real embed is verified in the
 * browser step instead. What is tested here is everything the cell itself owns:
 * badges, in-place failure text, and embed-once-then-change.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Panel, QueryResult, VegaLiteSpec } from "../../core/panel.ts";
import type { QueryOutcome } from "../../core/query.ts";
import type { VegaChangeset, VegaDeps, VegaView } from "./panel-cell.ts";
import { DATASET, createPanelCell } from "./panel-cell.ts";

const VIZ: VegaLiteSpec = {
  mark: "line",
  encoding: {
    x: { field: "step", type: "quantitative" },
    y: { field: "value", type: "quantitative" },
  },
};

const PANEL: Panel = {
  id: "metric:wm_loss",
  title: "wm_loss",
  query: "SELECT step, value FROM events",
  viz: VIZ,
};

function result(rows: readonly unknown[][], over: Partial<QueryResult> = {}): QueryResult {
  return {
    kind: "result",
    columns: [
      { name: "step", type: "BIGINT" },
      { name: "value", type: "DOUBLE" },
    ],
    rows,
    truncated: false,
    limit: 10000,
    ms: 1,
    ...over,
  };
}

interface Recorder {
  readonly deps: VegaDeps;
  readonly embedCalls: { spec: unknown; opts: Record<string, unknown> }[];
  readonly changes: { dataset: string; inserted: readonly unknown[] }[];
  finalized: number;
}

function recorder(): Recorder {
  const embedCalls: Recorder["embedCalls"] = [];
  const changes: Recorder["changes"] = [];
  const rec: Recorder = {
    embedCalls,
    changes,
    finalized: 0,
    deps: {
      embed(host, spec, opts) {
        embedCalls.push({ spec, opts });
        // A plausible stand-in for what Vega leaves behind, so a test can see
        // whether the node survives a refresh.
        const svg = host.ownerDocument.createElement("svg");
        svg.dataset["stub"] = "vega";
        host.append(svg);
        const view: VegaView = {
          change(dataset, changeset) {
            const inserted = changeset.raw;
            changes.push({
              dataset,
              inserted: Array.isArray(inserted) ? inserted : [],
            });
            return view;
          },
          runAsync: () => Promise.resolve(null),
          finalize: () => undefined,
        };
        return Promise.resolve({
          view,
          finalize: () => {
            rec.finalized += 1;
          },
        });
      },
      changeset(): VegaChangeset {
        // The stub's `raw` is just the inserted rows, which is all the test
        // needs to see; the real adapter puts a vega Changeset there.
        const make = (rows: readonly unknown[]): VegaChangeset => ({
          raw: rows,
          remove: () => make(rows),
          insert: (values) => make([...rows, ...values]),
        });
        return make([]);
      },
    },
  };
  return rec;
}

function badge(root: HTMLElement): HTMLElement {
  const node = root.querySelector<HTMLElement>(".panel-badge");
  if (node === null) throw new Error("no badge");
  return node;
}

function failure(root: HTMLElement): HTMLElement {
  const node = root.querySelector<HTMLElement>(".panel-failure");
  if (node === null) throw new Error("no failure element");
  return node;
}

describe("panel cell", () => {
  let rec: Recorder;
  beforeEach(() => {
    rec = recorder();
  });

  it("shows the title and nothing else before a first answer", () => {
    const cell = createPanelCell(PANEL, rec.deps);
    expect(cell.root.querySelector(".panel-title")?.textContent).toBe("wm_loss");
    expect(cell.state()).toEqual({ kind: "idle" });
    expect(badge(cell.root).hidden).toBe(true);
    expect(rec.embedCalls).toHaveLength(0);
  });

  it("badges `loading` while waiting for its first answer", () => {
    const cell = createPanelCell(PANEL, rec.deps);
    cell.setLoading();
    expect(cell.state().kind).toBe("loading");
    expect(badge(cell.root).textContent).toBe("loading");
  });

  it("embeds on the first result and badges the row count", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5], [2, 1.2]]));
    expect(cell.state().kind).toBe("ok");
    expect(badge(cell.root).textContent).toBe("2 rows");
    expect(badge(cell.root).dataset["tone"]).toBe("live");
    expect(cell.embeds()).toBe(1);
    expect(failure(cell.root).hidden).toBe(true);
  });

  it("passes actions:false, svg renderer, the paper theme and the named dataset", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5]]));
    const call = rec.embedCalls[0];
    if (call === undefined) throw new Error("no embed call");
    expect(call.opts["actions"]).toBe(false);
    expect(call.opts["renderer"]).toBe("svg");
    expect(call.opts["config"]).toBeTypeOf("object");
    const spec = call.spec;
    if (typeof spec !== "object" || spec === null || !("data" in spec)) {
      throw new Error("spec has no data");
    }
    expect(spec.data).toEqual({ name: DATASET, values: [{ step: 1, value: 1.5 }] });
  });

  it("does NOT re-embed on a refresh: it changes the live view's data in place", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5]]));
    const svgBefore = cell.root.querySelector("[data-stub='vega']");
    expect(svgBefore).not.toBeNull();

    await cell.render(result([[1, 1.5], [2, 1.2], [3, 1.0]]));

    expect(cell.embeds()).toBe(1);
    expect(rec.changes).toEqual([
      {
        dataset: DATASET,
        inserted: [
          { step: 1, value: 1.5 },
          { step: 2, value: 1.2 },
          { step: 3, value: 1.0 },
        ],
      },
    ]);
    // The exact same node — the DOM was not rebuilt.
    expect(cell.root.querySelector("[data-stub='vega']")).toBe(svgBefore);
    expect(badge(cell.root).textContent).toBe("3 rows");
  });

  it("says in prose how much of a truncated result is showing, and still plots", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5], [2, 1.2]], { truncated: true, limit: 2 }));
    expect(cell.state().kind).toBe("truncated");
    // The badge is an amber word; the SENTENCE is in the header, at reading
    // size. A 10px mono "truncated 2/2" is a thing you scroll past.
    expect(badge(cell.root).textContent).toBe("truncated");
    expect(badge(cell.root).dataset["tone"]).toBe("warn");
    const notice = cell.root.querySelector<HTMLElement>(".panel-notice");
    if (notice === null) throw new Error("no truncation notice");
    expect(notice.hidden).toBe(false);
    expect(notice.textContent).toBe("showing 2 of 2+ rows (limit 2)");
    expect(cell.embeds()).toBe(1);
  });

  it("hides the truncation notice again once a result fits", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5]], { truncated: true, limit: 1 }));
    await cell.render(result([[1, 1.5]]));
    expect(cell.root.querySelector<HTMLElement>(".panel-notice")?.hidden).toBe(true);
  });

  const failures: [string, QueryOutcome, string, string][] = [
    [
      "a DuckDB 400",
      { kind: "query-error", status: 400, message: 'Binder Error: no column "nope"' },
      "error",
      'Binder Error: no column "nope"',
    ],
    [
      "a timeout",
      { kind: "timeout", status: 408, message: "query exceeded 5000ms" },
      "error",
      "query exceeded 5000ms",
    ],
    [
      "a network failure",
      { kind: "network-error", message: "Failed to fetch" },
      "error",
      "network: Failed to fetch",
    ],
    [
      "a malformed body",
      { kind: "malformed-response", reason: "field `limit` expected a finite number" },
      "error",
      "malformed /query response: field `limit` expected a finite number",
    ],
  ];

  it.each(failures)(
    "renders %s in place, loudly",
    async (_label, outcome, tone, text) => {
      const cell = createPanelCell(PANEL, rec.deps);
      await cell.render(outcome);
      expect(cell.state().kind).toBe("query-error");
      expect(badge(cell.root).textContent).toBe("error");
      expect(badge(cell.root).dataset["tone"]).toBe(tone);
      expect(failure(cell.root).hidden).toBe(false);
      expect(failure(cell.root).textContent).toBe(text);
      expect(cell.embeds()).toBe(0);
    },
  );

  it("renders a shape error naming the field, what was expected and what came back", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    // `step` is a VARCHAR, but the spec declares it quantitative.
    await cell.render({
      kind: "result",
      columns: [
        { name: "step", type: "VARCHAR" },
        { name: "value", type: "DOUBLE" },
      ],
      rows: [["a", 1]],
      truncated: false,
      limit: 10000,
      ms: 1,
    });
    expect(cell.state().kind).toBe("shape-error");
    expect(badge(cell.root).textContent).toBe("shape error");
    expect(failure(cell.root).textContent).toBe(
      "field `step`: expected quantitative, got VARCHAR",
    );
    // Crucially: Vega was never asked to draw. That is the whole point of the
    // pre-flight check — an empty chart is a semantic fallback.
    expect(cell.embeds()).toBe(0);
  });

  it("tears down a live chart when a later refresh fails, rather than lying", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5]]));
    expect(cell.root.querySelector("[data-stub='vega']")).not.toBeNull();

    await cell.render({ kind: "query-error", status: 400, message: "boom" });

    expect(rec.finalized).toBe(1);
    expect(cell.root.querySelector("[data-stub='vega']")).toBeNull();
    expect(failure(cell.root).textContent).toBe("boom");
  });

  it("re-embeds after recovering from a failure", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render({ kind: "query-error", status: 400, message: "boom" });
    await cell.render(result([[1, 1.5]]));
    expect(cell.embeds()).toBe(1);
    expect(failure(cell.root).hidden).toBe(true);
    expect(cell.state().kind).toBe("ok");
  });

  it("does not blank a rendered chart when a refresh starts", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render(result([[1, 1.5]]));
    cell.setLoading();
    // Still `ok`: a refresh must not flash the panel back to a loading state.
    expect(cell.state().kind).toBe("ok");
    expect(badge(cell.root).textContent).toBe("1 rows");
  });

  it("finalizes the vega view and removes itself on destroy", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    const host = document.createElement("div");
    host.append(cell.root);
    await cell.render(result([[1, 1.5]]));
    cell.destroy();
    expect(rec.finalized).toBe(1);
    expect(host.children).toHaveLength(0);
  });

  it("survives a stubbed embed that never runs (no unhandled rejection)", async () => {
    const spy = vi.fn();
    const cell = createPanelCell(PANEL, {
      embed: () => Promise.reject(new Error("no canvas in jsdom")),
      changeset: () => rec.deps.changeset(),
    });
    await cell.render(result([[1, 1.5]])).catch(spy);
    expect(spy).toHaveBeenCalledOnce();
  });
});

/**
 * `observe:notify` had no producers: the bus existed and App listened, but no
 * panel ever dispatched, so a broken query was invisible unless you happened to
 * be looking at that cell. These pin the producer side, and pin that it is
 * ONCE PER TRANSITION — a 2s poll against a broken query would otherwise emit
 * 1800 toasts an hour.
 */
describe("panel notifications", () => {
  let rec: Recorder;
  let seen: { kind: unknown; message: unknown }[];
  let stop: () => void;

  beforeEach(() => {
    rec = recorder();
    seen = [];
    function listener(event: Event): void {
      if (!(event instanceof CustomEvent)) return;
      const detail: unknown = event.detail;
      if (typeof detail !== "object" || detail === null) return;
      const record: Record<string, unknown> = { ...detail };
      seen.push({ kind: record["kind"], message: record["message"] });
    }
    window.addEventListener("observe:notify", listener);
    stop = (): void => {
      window.removeEventListener("observe:notify", listener);
    };
  });

  afterEach(() => {
    stop();
  });

  it("notifies once on a query error, not once per poll", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    for (let i = 0; i < 5; i += 1) {
      await cell.render({ kind: "query-error", status: 400, message: "Binder Error: boom" });
    }
    expect(seen).toHaveLength(1);
    expect(seen[0]?.kind).toBe("error");
    expect(seen[0]?.message).toContain("wm_loss");
    expect(seen[0]?.message).toContain("Binder Error: boom");
  });

  it("notifies again after the panel recovers and breaks anew", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render({ kind: "query-error", status: 400, message: "boom" });
    await cell.render(result([[1, 1.5]]));
    await cell.render({ kind: "query-error", status: 400, message: "boom" });
    expect(seen).toHaveLength(2);
  });

  it("notifies on a shape error, naming the field", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    await cell.render({
      kind: "result",
      columns: [
        { name: "step", type: "VARCHAR" },
        { name: "value", type: "DOUBLE" },
      ],
      rows: [["a", 1]],
      truncated: false,
      limit: 10000,
      ms: 1,
    });
    expect(seen).toHaveLength(1);
    expect(seen[0]?.kind).toBe("error");
    expect(seen[0]?.message).toContain("`step`");
    expect(seen[0]?.message).toContain("VARCHAR");
  });

  it("notifies once on truncation, as a warning", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    for (let i = 0; i < 4; i += 1) {
      await cell.render(result([[1, 1.5]], { truncated: true, limit: 1 }));
    }
    expect(seen).toHaveLength(1);
    expect(seen[0]?.kind).toBe("warning");
    expect(seen[0]?.message).toBe("showing 1 of 1+ rows (limit 1)");
  });

  it("says nothing at all about a healthy panel", async () => {
    const cell = createPanelCell(PANEL, rec.deps);
    cell.setLoading();
    await cell.render(result([[1, 1.5]]));
    await cell.render(result([[1, 1.5], [2, 1.2]]));
    expect(seen).toEqual([]);
  });
});
