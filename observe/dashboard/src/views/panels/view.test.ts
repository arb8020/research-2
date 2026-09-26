/**
 * The pure half of the panels view: what the default panels ARE.
 *
 * Runs in node, no DOM — `defaultPanel` is a function from a metric name to a
 * query and a spec, and that is the part worth pinning in isolation. The
 * refresh/debounce/run_end behaviour needs a DOM and lives in `view.dom.test.ts`.
 */

import { describe, expect, it } from "vitest";
import { checkShape } from "../../core/panel.ts";
import { DEBOUNCE_MS, HOVER_PARAM, LIVE_POLL_MS, defaultPanel, view } from "./view.ts";

describe("view contract", () => {
  it("is named panels and accepts metric plus log", () => {
    expect(view.name).toBe("panels");
    // `log` is accepted for one reason only: `run_end` stops the live poll.
    expect(view.accepts).toEqual(["metric", "log"]);
  });

  it("debounces no faster than 500ms and polls live at 2s", () => {
    expect(DEBOUNCE_MS).toBeGreaterThanOrEqual(500);
    expect(LIVE_POLL_MS).toBe(2000);
  });
});

describe("defaultPanel", () => {
  it("queries step and value for one metric in one run", () => {
    const panel = defaultPanel({ name: "wm_loss", file: "run-1k.jsonl", x: "step" });
    expect(panel.id).toBe("metric:wm_loss");
    expect(panel.title).toBe("wm_loss");
    expect(panel.query).toBe(
      "SELECT step, value FROM events" +
        " WHERE kind='metric' AND name='wm_loss' AND file='run-1k.jsonl'" +
        " ORDER BY step",
    );
  });

  it("falls back to ts for a metric that carries no step", () => {
    const panel = defaultPanel({ name: "gpu_temp", file: "run-1k.jsonl", x: "ts" });
    expect(panel.query).toContain("SELECT ts, value");
    expect(panel.query).toContain("ORDER BY ts");
    // Encodings are per-layer now (the crosshair layer must not inherit y).
    expect(layers(panel.viz)[0]?.["encoding"]).toMatchObject({
      x: { field: "ts", type: "quantitative" },
    });
  });

  it("escapes a single quote in the metric name so the SQL cannot break out", () => {
    const panel = defaultPanel({ name: "o'brien' OR 1=1 --", file: "r.jsonl", x: "step" });
    expect(panel.query).toContain("name='o''brien'' OR 1=1 --'");
    // The predicate is still one closed literal: an even number of quotes after
    // `name=` means nothing escaped into SQL.
    const after = panel.query.slice(panel.query.indexOf("name="));
    const quotes = after.match(/'/g)?.length ?? 0;
    expect(quotes % 2).toBe(0);
    // And the title is the raw name, unescaped — escaping is for SQL, not humans.
    expect(panel.title).toBe("o'brien' OR 1=1 --");
  });

  it("escapes a single quote in the file name too", () => {
    const panel = defaultPanel({ name: "loss", file: "it's-a-run.jsonl", x: "step" });
    expect(panel.query).toContain("file='it''s-a-run.jsonl'");
  });

  it("produces a spec whose shape check passes against the columns it selects", () => {
    // The panel's own query selects (step, value); its spec must fit that.
    const panel = defaultPanel({ name: "wm_loss", file: "r.jsonl", x: "step" });
    expect(
      checkShape(
        [
          { name: "step", type: "BIGINT" },
          { name: "value", type: "DOUBLE" },
        ],
        panel.viz,
      ),
    ).toBeNull();
  });

  it("is a layered line sized to its container", () => {
    const panel = defaultPanel({ name: "wm_loss", file: "r.jsonl", x: "step" });
    expect(panel.viz).toMatchObject({ width: "container" });
    expect(layers(panel.viz).map(markType)).toEqual(["line", "rule", "point"]);
  });
});

/** The `layer` array of a layered spec, or a throw — the default panel is one. */
function layers(viz: unknown): Record<string, unknown>[] {
  if (typeof viz !== "object" || viz === null || !("layer" in viz)) {
    throw new Error("spec is not layered");
  }
  const layer: unknown = viz.layer;
  if (!Array.isArray(layer)) throw new Error("`layer` is not an array");
  return layer.map((one: unknown) => {
    if (typeof one !== "object" || one === null) throw new Error("layer is not an object");
    return { ...one };
  });
}

function markType(layer: Record<string, unknown>): unknown {
  const mark = layer["mark"];
  if (typeof mark === "object" && mark !== null && "type" in mark) return mark.type;
  return mark;
}

/**
 * Hover: a chart you cannot read a value off is a picture, not an instrument.
 *
 * Single-panel hover is three layers over one `point` param — crosshair, marker
 * and tooltip — and its shape has to survive `checkShape`, which walks layers.
 */
describe("defaultPanel hover", () => {
  const panel = defaultPanel({ name: "wm_loss", file: "r.jsonl", x: "step" });
  const [lineLayer, ruleLayer, pointLayer] = layers(panel.viz);

  it("declares one `hover` point param, on mouseover, nearest, keyed on x", () => {
    expect(pointLayer?.["params"]).toEqual([
      {
        name: HOVER_PARAM,
        select: { type: "point", on: "mouseover", nearest: true, fields: ["step"] },
      },
    ]);
  });

  it("puts the crosshair rule on x ALONE, so it spans the plot height", () => {
    // A rule that inherits y is a dot. The top level must therefore carry no
    // shared encoding for the layers to inherit.
    expect(ruleLayer?.["encoding"]).toMatchObject({ x: { field: "step" } });
    expect(ruleLayer?.["encoding"]).not.toHaveProperty("y");
    expect(panel.viz).not.toHaveProperty("encoding");
    // The line, by contrast, needs both.
    expect(lineLayer?.["encoding"]).toMatchObject({
      x: { field: "step" },
      y: { field: "value" },
    });
  });

  it("hides the crosshair and the marker until hover", () => {
    for (const layer of [ruleLayer, pointLayer]) {
      expect(layer?.["encoding"]).toMatchObject({
        opacity: {
          condition: { param: HOVER_PARAM, value: 1, empty: false },
          value: 0,
        },
      });
    }
  });

  it("tooltips the x field and the value", () => {
    const encoding = pointLayer?.["encoding"];
    if (typeof encoding !== "object" || encoding === null) throw new Error("no encoding");
    expect(encoding).toMatchObject({
      tooltip: [
        { field: "step", type: "quantitative", title: "step" },
        { field: "value", type: "quantitative", title: "value" },
      ],
    });
  });

  it("uses ts for the param and the tooltip when the metric has no step", () => {
    const byTs = defaultPanel({ name: "gpu_temp", file: "r.jsonl", x: "ts" });
    const [, , pointTs] = layers(byTs.viz);
    expect(pointTs?.["params"]).toMatchObject([
      { select: { fields: ["ts"] } },
    ]);
  });

  it("still passes checkShape against the columns its own query selects", () => {
    // The whole layered spec — params, conditional opacities, tooltips — must
    // survive the pre-flight check, or every panel renders a shape error.
    expect(
      checkShape(
        [
          { name: "step", type: "BIGINT" },
          { name: "value", type: "DOUBLE" },
        ],
        panel.viz,
      ),
    ).toBeNull();
  });

  it("still catches a missing column through the layers", () => {
    expect(checkShape([{ name: "value", type: "DOUBLE" }], panel.viz)?.field).toBe("step");
  });
});
