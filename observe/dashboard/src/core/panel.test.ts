import { describe, expect, it } from "vitest";
import type { QueryColumn, VegaLiteSpec } from "./panel.ts";
import { checkShape, rowsToObjects, sqlLiteral } from "./panel.ts";
import { sqlLiteral as sharedSqlLiteral } from "./sql.ts";

function cols(...pairs: [string, string][]): QueryColumn[] {
  return pairs.map(([name, type]) => ({ name, type }));
}

const LINE: VegaLiteSpec = {
  mark: "line",
  encoding: {
    x: { field: "step", type: "quantitative" },
    y: { field: "value", type: "quantitative" },
  },
};

describe("checkShape", () => {
  it("accepts a spec whose fields all exist with compatible types", () => {
    expect(checkShape(cols(["step", "BIGINT"], ["value", "DOUBLE"]), LINE)).toBeNull();
  });

  it("reports the missing field, and names the columns it did have", () => {
    const error = checkShape(cols(["ts", "DOUBLE"], ["value", "DOUBLE"]), LINE);
    expect(error?.field).toBe("step");
    expect(error?.expected).toBe("a column in the query result");
    expect(error?.got).toContain("ts");
  });

  it("reports the FIRST mismatch in spec order", () => {
    // Both channels are wrong; x is declared first.
    const error = checkShape(cols(["step", "VARCHAR"], ["value", "VARCHAR"]), LINE);
    expect(error).toEqual({ field: "step", expected: "quantitative", got: "VARCHAR" });
  });

  type VlType = "quantitative" | "temporal" | "ordinal" | "nominal";
  const typeCases: [string, VlType, string, boolean][] = [
    ["quantitative over DOUBLE", "quantitative", "DOUBLE", true],
    ["quantitative over BIGINT", "quantitative", "BIGINT", true],
    ["quantitative over DECIMAL(18,3)", "quantitative", "DECIMAL(18,3)", true],
    ["quantitative over VARCHAR", "quantitative", "VARCHAR", false],
    ["quantitative over TIMESTAMP", "quantitative", "TIMESTAMP", false],
    ["temporal over TIMESTAMP", "temporal", "TIMESTAMP", true],
    ["temporal over DATE", "temporal", "DATE", true],
    // `ts` is a float unix second on disk, so a number is honestly temporal.
    ["temporal over DOUBLE", "temporal", "DOUBLE", true],
    ["temporal over VARCHAR", "temporal", "VARCHAR", false],
    ["nominal over VARCHAR", "nominal", "VARCHAR", true],
    ["nominal over DOUBLE", "nominal", "DOUBLE", true],
    ["ordinal over BOOLEAN", "ordinal", "BOOLEAN", true],
  ];

  it.each(typeCases)("%s -> %s", (_label, vlType, duckType, expected) => {
    const spec: VegaLiteSpec = {
      mark: "point",
      encoding: { x: { field: "f", type: vlType } },
    };
    const error = checkShape(cols(["f", duckType]), spec);
    expect(error === null).toBe(expected);
  });

  it("checks every layer of a layered spec", () => {
    const layered: VegaLiteSpec = {
      layer: [
        { mark: "line", encoding: { x: { field: "step", type: "quantitative" } } },
        { mark: "point", encoding: { y: { field: "smoothed", type: "quantitative" } } },
      ],
    };
    expect(checkShape(cols(["step", "BIGINT"], ["smoothed", "DOUBLE"]), layered)).toBeNull();
    // The second layer's field is the one missing — it must still be caught.
    expect(checkShape(cols(["step", "BIGINT"]), layered)?.field).toBe("smoothed");
  });

  it("checks color, detail and facet channels", () => {
    const faceted: VegaLiteSpec = {
      mark: "line",
      encoding: {
        x: { field: "step", type: "quantitative" },
        color: { field: "name", type: "nominal" },
        detail: { field: "run_id", type: "nominal" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"], ["name", "VARCHAR"]), faceted)?.field).toBe(
      "run_id",
    );
  });

  it("ignores channels that name no field", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      encoding: {
        x: { field: "step", type: "quantitative" },
        // A constant, and an aggregate count: neither names a column.
        color: { value: "#477bd8" },
        y: { aggregate: "count", type: "quantitative" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"]), spec)).toBeNull();
  });

  it("descends into a repeat/facet body's spec", () => {
    const repeated: VegaLiteSpec = {
      repeat: ["a", "b"],
      spec: {
        mark: "line",
        encoding: { x: { field: "step", type: "quantitative" } },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"]), repeated)).toBeNull();
    expect(checkShape(cols(["ts", "DOUBLE"]), repeated)?.field).toBe("step");
  });

  it("does not check a field declared with no type", () => {
    const untyped: VegaLiteSpec = {
      mark: "line",
      // No `type`: Vega-Lite infers it. The field must exist; we cannot judge it.
      encoding: { x: { field: "step" } },
    };
    expect(checkShape(cols(["step", "VARCHAR"]), untyped)).toBeNull();
    expect(checkShape(cols(["nope", "VARCHAR"]), untyped)?.field).toBe("step");
  });
});

describe("checkShape type modifiers", () => {
  // DuckDB reports a tz timestamp column as "TIMESTAMP WITH TIME ZONE", not
  // the short TIMESTAMPTZ alias. Before the family() fix this read as an
  // unknown family and a valid temporal encoding failed its own data.
  const tzCases: [string, boolean][] = [
    ["TIMESTAMP WITH TIME ZONE", true],
    ["timestamp with time zone", true],
    ["TIMESTAMP(6) WITH TIME ZONE", true],
    ["TIME WITH TIME ZONE", false],
  ];

  it.each(tzCases)("temporal over %s", (duckType, ok) => {
    const spec: VegaLiteSpec = {
      mark: "line",
      encoding: { x: { field: "when", type: "temporal" } },
    };
    expect(checkShape(cols(["when", duckType]), spec) === null).toBe(ok);
  });
});

describe("checkShape and transform-produced fields", () => {
  it("accepts a field a `calculate` transform produces", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [{ calculate: "datum.value * 2", as: "doubled" }],
      encoding: {
        x: { field: "step", type: "quantitative" },
        y: { field: "doubled", type: "quantitative" },
      },
    };
    // `doubled` is in no column and must still pass: it exists after the
    // transform runs, and its type is not the store's to report.
    expect(checkShape(cols(["step", "BIGINT"], ["value", "DOUBLE"]), spec)).toBeNull();
  });

  it("does not type-check a produced field, even against a hostile column", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [{ timeUnit: "yearmonth", field: "ts", as: "month" }],
      encoding: { x: { field: "month", type: "temporal" } },
    };
    // A VARCHAR column of the same name must not make the produced field fail:
    // existence-satisfied, type-unchecked.
    expect(checkShape(cols(["month", "VARCHAR"]), spec)).toBeNull();
  });

  it("accepts both names a `fold` transform produces", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [{ fold: ["a", "b"], as: ["metric", "reading"] }],
      encoding: {
        x: { field: "step", type: "quantitative" },
        y: { field: "reading", type: "quantitative" },
        color: { field: "metric", type: "nominal" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"], ["a", "DOUBLE"], ["b", "DOUBLE"]), spec)).toBeNull();
  });

  it("accepts aggregate/window/joinaggregate `as` names", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [
        { aggregate: [{ op: "mean", field: "value", as: "avg" }], groupby: ["step"] },
        { window: [{ op: "row_number", as: "idx" }] },
        { joinaggregate: [{ op: "max", field: "value", as: "peak" }] },
      ],
      encoding: {
        x: { field: "idx", type: "quantitative" },
        y: { field: "avg", type: "quantitative" },
        size: { field: "peak", type: "quantitative" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"], ["value", "DOUBLE"]), spec)).toBeNull();
  });

  it("stops existence-checking a spec that pivots, since pivot names come from the rows", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [{ pivot: "name", value: "value", groupby: ["step"] }],
      encoding: {
        x: { field: "step", type: "quantitative" },
        y: { field: "wm_loss", type: "quantitative" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"], ["name", "VARCHAR"], ["value", "DOUBLE"]), spec)).toBeNull();
  });

  it("still catches a field that is neither a column nor produced", () => {
    const spec: VegaLiteSpec = {
      mark: "line",
      transform: [{ calculate: "1", as: "one" }],
      encoding: {
        x: { field: "one", type: "quantitative" },
        y: { field: "nope", type: "quantitative" },
      },
    };
    expect(checkShape(cols(["step", "BIGINT"]), spec)?.field).toBe("nope");
  });

  it("sees a transform declared inside a layer", () => {
    const spec: VegaLiteSpec = {
      layer: [
        {
          mark: "line",
          transform: [{ calculate: "datum.value", as: "inner" }],
          encoding: { y: { field: "inner", type: "quantitative" } },
        },
      ],
    };
    expect(checkShape(cols(["value", "DOUBLE"]), spec)).toBeNull();
  });
});

describe("rowsToObjects", () => {
  it("zips columnar-ordered rows against column names", () => {
    expect(
      rowsToObjects(cols(["step", "BIGINT"], ["value", "DOUBLE"]), [
        [1, 1.5],
        [2, 1.2],
      ]),
    ).toEqual([
      { step: 1, value: 1.5 },
      { step: 2, value: 1.2 },
    ]);
  });

  it("preserves nulls rather than dropping the key", () => {
    expect(rowsToObjects(cols(["step", "BIGINT"]), [[null]])).toEqual([{ step: null }]);
  });

  it("returns nothing for no rows", () => {
    expect(rowsToObjects(cols(["step", "BIGINT"]), [])).toEqual([]);
  });
});

describe("sqlLiteral", () => {
  // The rule itself is pinned in core/sql.test.ts — there is one implementation
  // now. What panel.ts owes its callers is that the name is still reachable here.
  it("is the shared core/sql implementation, re-exported", () => {
    expect(sqlLiteral).toBe(sharedSqlLiteral);
    expect(sqlLiteral("o'brien")).toBe("'o''brien'");
  });
});
