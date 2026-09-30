import { describe, expect, it } from "vitest";
import type { View } from "../core/events.ts";
import { ViewContractError, validateViewModules } from "../core/views.ts";
import { view as panelsView } from "./panels/view.ts";
import { view as rolloutView } from "./rollout/view.ts";

const goodModule: { view: View } = {
  view: {
    name: "fake",
    accepts: ["metric"],
    mount: () => ({}),
    append: () => undefined,
  },
};

describe("view discovery", () => {
  it("finds the panels view through the real glob shape", () => {
    // Mirrors what import.meta.glob('../views/*/view.ts', {eager:true}) returns.
    const discovered = validateViewModules({
      "../views/panels/view.ts": { view: panelsView },
    });
    expect(discovered).toHaveLength(1);
    expect(discovered[0]?.view.name).toBe("panels");
    // `log` is accepted only so the view can see `run_end` and stop polling.
    expect(discovered[0]?.view.accepts).toEqual(["metric", "log"]);
  });

  it("puts the rollout view below panels — the real discovery order", () => {
    // DESIGN.md "Register": the rollout view is a panel-level element in its
    // own slot. Core lays slots out in discovery order, which is path-sorted,
    // and `panels` < `rollout` alphabetically — so the ordering the HUD wants
    // falls out of the folder names rather than needing a layout config.
    const discovered = validateViewModules({
      "../views/rollout/view.ts": { view: rolloutView },
      "../views/panels/view.ts": { view: panelsView },
    });
    expect(discovered.map((d) => d.view.name)).toEqual(["panels", "rollout"]);
    // And it only ever receives artifacts, so no other kind can reach it.
    expect(discovered[1]?.view.accepts).toEqual(["artifact"]);
  });

  it("returns views in stable path-sorted order", () => {
    const discovered = validateViewModules({
      "../views/zeta/view.ts": goodModule,
      "../views/alpha/view.ts": goodModule,
      "../views/panels/view.ts": { view: panelsView },
    });
    expect(discovered.map((d) => d.path)).toEqual([
      "../views/alpha/view.ts",
      "../views/panels/view.ts",
      "../views/zeta/view.ts",
    ]);
  });

  it("throws when a module has no `view` export", () => {
    expect(() =>
      validateViewModules({ "../views/broken/view.ts": { other: 1 } }),
    ).toThrowError(ViewContractError);
    expect(() =>
      validateViewModules({ "../views/broken/view.ts": { other: 1 } }),
    ).toThrowError(/has no `view` export/);
  });

  const noop = (): void => undefined;
  const emptyState = (): object => ({});

  const badViews: [string, unknown][] = [
    ["missing mount", { name: "x", accepts: ["metric"], append: noop }],
    ["missing append", { name: "x", accepts: ["metric"], mount: emptyState }],
    ["empty name", { name: "", accepts: ["metric"], mount: emptyState, append: noop }],
    ["empty accepts", { name: "x", accepts: [], mount: emptyState, append: noop }],
    ["bogus kind", { name: "x", accepts: ["trace"], mount: emptyState, append: noop }],
    ["accepts not an array", { name: "x", accepts: "metric", mount: emptyState, append: noop }],
    ["view is a string", "metrics"],
  ];

  it.each(badViews)("throws on a view with %s", (_label, badView) => {
    expect(() =>
      validateViewModules({ "../views/bad/view.ts": { view: badView } }),
    ).toThrowError(/does not match the View contract/);
  });

  it("names the offending path in the error", () => {
    try {
      validateViewModules({ "../views/oops/view.ts": {} });
      throw new Error("should have thrown");
    } catch (cause) {
      if (!(cause instanceof ViewContractError)) throw cause;
      expect(cause.message).toContain("../views/oops/view.ts");
    }
  });
});
