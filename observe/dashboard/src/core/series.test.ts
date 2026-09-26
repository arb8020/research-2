import { describe, expect, it } from "vitest";
import type { Metric } from "./events.ts";
import { toSeries } from "./series.ts";

function metric(name: string, value: number, attrs: Metric["attrs"], ts = 0): Metric {
  return { kind: "metric", ts, name, value, attrs };
}

describe("toSeries", () => {
  it("groups by metric name on the step axis", () => {
    const result = toSeries(
      [
        metric("wm_loss", 1.5, { step: 1 }),
        metric("pi_loss", 0.9, { step: 1 }),
        metric("wm_loss", 1.2, { step: 2 }),
      ],
      "step",
    );
    expect([...result.series.keys()].sort()).toEqual(["pi_loss", "wm_loss"]);
    expect(result.series.get("wm_loss")).toEqual([
      { x: 1, y: 1.5 },
      { x: 2, y: 1.2 },
    ]);
    expect(result.unplottable).toEqual([]);
  });

  it("uses ts when the axis is 'ts'", () => {
    const result = toSeries([metric("a", 3, {}, 1789669021.7)], "ts");
    expect(result.series.get("a")).toEqual([{ x: 1789669021.7, y: 3 }]);
  });

  it("reports metrics lacking the x attr instead of dropping them", () => {
    const orphan = metric("eval_reward", 20, {});
    const result = toSeries([metric("wm_loss", 1, { step: 1 }), orphan], "step");
    expect(result.series.has("eval_reward")).toBe(false);
    expect(result.unplottable).toHaveLength(1);
    expect(result.unplottable[0]?.metric).toBe(orphan);
    expect(result.unplottable[0]?.reason).toMatch(/missing attr `step`/);
  });

  it("reports a non-numeric x attr", () => {
    const result = toSeries([metric("a", 1, { step: "one" })], "step");
    expect(result.unplottable[0]?.reason).toMatch(/not a number/);
  });

  it("sorts points ascending in x even when events arrive out of order", () => {
    const result = toSeries(
      [
        metric("a", 3, { step: 3 }),
        metric("a", 1, { step: 1 }),
        metric("a", 2, { step: 2 }),
      ],
      "step",
    );
    expect(result.series.get("a")?.map((p) => p.x)).toEqual([1, 2, 3]);
  });

  it("returns an empty result for no metrics", () => {
    const result = toSeries([], "step");
    expect(result.series.size).toBe(0);
    expect(result.unplottable).toEqual([]);
  });
});
