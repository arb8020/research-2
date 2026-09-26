/**
 * Panels: a query that feeds a viz (DESIGN.md "Panels").
 *
 * Pure — no DOM, no fetch. Two jobs live here:
 *
 *  1. `checkShape` — Vega-Lite draws an EMPTY chart when an encoding names a
 *     field the data doesn't have. That is a semantic fallback, so we check the
 *     `columns` the server reported against the spec's encodings *before*
 *     handing anything to Vega and fail loudly in place instead.
 *  2. `rowsToObjects` — the wire format is columnar-ordered arrays
 *     (`rows[i][j]` matches `columns[j]`); Vega wants records.
 */

import type { TopLevelSpec } from "vega-lite";
import { isRecord } from "./fields.ts";

/**
 * The viz half of a Panel: vega-lite's own `TopLevelSpec`, minus `data`.
 *
 * `data` is not the panel author's to write — the rows come from the panel's
 * `query`, and `panel-cell` binds them at render time. Omitting it from the type
 * makes "a spec with hardcoded data" unrepresentable rather than merely
 * discouraged. Pinned to vega-lite so a version bump that changes the grammar
 * is a type error here and not a blank chart in the browser.
 */
export type VegaLiteSpec = DistributiveOmit<TopLevelSpec, "data">;

/**
 * `Omit` over a union collapses it to the keys the members share, which turns
 * `TopLevelSpec` (unit | layer | facet | repeat | concat) into a shape where
 * `mark` is not a known property. Distributing keeps each member intact.
 */
type DistributiveOmit<T, K extends keyof never> = T extends unknown
  ? Omit<T, K>
  : never;

export interface Panel {
  readonly id: string;
  readonly title: string;
  readonly query: string;
  readonly viz: VegaLiteSpec;
}

/** One column of a `/query` result: name plus the DuckDB type name. */
export interface QueryColumn {
  readonly name: string;
  readonly type: string;
}

/** A row in wire order: `row[j]` belongs to `columns[j]`. */
export type QueryRow = readonly unknown[];

export interface QueryResult {
  readonly kind: "result";
  readonly columns: readonly QueryColumn[];
  readonly rows: readonly QueryRow[];
  readonly truncated: boolean;
  readonly limit: number;
  readonly ms: number;
}

/** Which encoding channel failed, what the spec asked for, what the store has. */
export interface ShapeError {
  readonly field: string;
  readonly expected: string;
  readonly got: string;
}

/**
 * PanelState, exactly the sum type DESIGN.md names, plus the two states a
 * panel occupies before a first answer exists. `view` is the live Vega view
 * handle and is opaque to core, so it is not modelled here — `panel-cell` owns
 * it; core owns rows and failures.
 */
export type PanelState =
  | { readonly kind: "idle" }
  | { readonly kind: "loading" }
  | { readonly kind: "ok"; readonly result: QueryResult }
  | { readonly kind: "truncated"; readonly result: QueryResult; readonly limit: number }
  | { readonly kind: "query-error"; readonly message: string }
  | { readonly kind: "shape-error"; readonly error: ShapeError };

/* ------------------------------------------------------------------ shapes */

/**
 * DuckDB type name -> the Vega-Lite `type`s it can honestly carry.
 *
 * Matching is on the *family* of the type name (uppercased, parameters
 * stripped: `DECIMAL(18,3)` -> `DECIMAL`), because DuckDB spells widths and
 * precisions into the name and a panel does not care about width.
 */
const NUMERIC_TYPES = new Set([
  "TINYINT",
  "SMALLINT",
  "INTEGER",
  "BIGINT",
  "HUGEINT",
  "UTINYINT",
  "USMALLINT",
  "UINTEGER",
  "UBIGINT",
  "UHUGEINT",
  "FLOAT",
  "DOUBLE",
  "REAL",
  "DECIMAL",
  "NUMERIC",
]);

const TEMPORAL_TYPES = new Set([
  "TIMESTAMP",
  "TIMESTAMP_S",
  "TIMESTAMP_MS",
  "TIMESTAMP_NS",
  "TIMESTAMPTZ",
  "DATE",
  "DATETIME",
]);

/**
 * The type FAMILY: the name with parameters and modifiers stripped.
 *
 * DuckDB spells widths into the name (`DECIMAL(18,3)`) and spells the tz
 * modifier as a suffix (`TIMESTAMP WITH TIME ZONE`, which is what a `?limit`ed
 * `/query` reports for a tz column rather than the short `TIMESTAMPTZ` alias).
 * A panel cares about neither, so both are cut: everything before `(` and
 * everything before ` WITH `.
 */
function family(duckType: string): string {
  const head = duckType.split("(")[0] ?? duckType;
  const upper = head.trim().toUpperCase();
  const withAt = upper.indexOf(" WITH ");
  return (withAt === -1 ? upper : upper.slice(0, withAt)).trim();
}

export function isNumericType(duckType: string): boolean {
  return NUMERIC_TYPES.has(family(duckType));
}

export function isTemporalType(duckType: string): boolean {
  return TEMPORAL_TYPES.has(family(duckType));
}

/** The Vega-Lite measurement types we check. */
const VL_TYPES = ["quantitative", "temporal", "ordinal", "nominal"] as const;
type VlType = (typeof VL_TYPES)[number];

function isVlType(value: unknown): value is VlType {
  return typeof value === "string" && VL_TYPES.some((t) => t === value);
}

/**
 * Can a column of `duckType` carry a channel declared `vlType`?
 *
 * - quantitative needs a number.
 * - temporal accepts a timestamp/date, and also a number: `ts` is a float unix
 *   second on disk (DESIGN.md) and that is the honest temporal column here.
 * - nominal/ordinal accept anything — every type has a string form.
 */
function typeCompatible(vlType: VlType, duckType: string): boolean {
  switch (vlType) {
    case "quantitative":
      return isNumericType(duckType);
    case "temporal":
      return isTemporalType(duckType) || isNumericType(duckType);
    case "nominal":
    case "ordinal":
      return true;
    default: {
      const exhaustive: never = vlType;
      return exhaustive;
    }
  }
}

/**
 * One field reference pulled out of a spec: a field name and, when the spec
 * declared one, the measurement type the channel claims for it.
 */
interface FieldRef {
  readonly field: string;
  readonly type: VlType | null;
}

/**
 * The channels worth checking. `tooltip`/`detail`/`order` are included but only
 * when they are field-based — `tooltip: true` and `tooltip: {value: ...}` name
 * no field, so there is nothing to verify.
 */
const CHECKED_CHANNELS = [
  "x",
  "y",
  "x2",
  "y2",
  "color",
  "detail",
  "facet",
  "row",
  "column",
  "size",
  "shape",
  "opacity",
  "theta",
  "radius",
  "tooltip",
  "order",
  "text",
] as const;

function collectFromEncoding(encoding: unknown, out: FieldRef[]): void {
  if (!isRecord(encoding)) return;
  for (const channel of CHECKED_CHANNELS) {
    const def = encoding[channel];
    // A channel may be a single def or an array of them (tooltip, order).
    const defs: unknown[] = Array.isArray(def) ? def : [def];
    for (const one of defs) {
      if (!isRecord(one)) continue;
      const field = one["field"];
      // No field: a value/datum/aggregate-count channel. Nothing to check.
      if (typeof field !== "string") continue;
      const declared = one["type"];
      out.push({ field, type: isVlType(declared) ? declared : null });
    }
  }
}

/**
 * Walk a spec for every field reference, descending into `layer`, `hconcat`,
 * `vconcat`, `concat` and `spec` (facet/repeat bodies).
 *
 * `repeat` is handled conservatively: a `{repeat: ...}` field reference is
 * resolved per-iteration by Vega-Lite and is not a literal column name, so we
 * skip it rather than report a field named "repeat". Everything else inside a
 * repeat's `spec` is still checked.
 */
export function collectFieldRefs(spec: unknown): FieldRef[] {
  const out: FieldRef[] = [];
  const walk = (node: unknown): void => {
    if (!isRecord(node)) return;
    collectFromEncoding(node["encoding"], out);
    for (const key of ["layer", "hconcat", "vconcat", "concat"] as const) {
      const branch = node[key];
      if (Array.isArray(branch)) for (const child of branch) walk(child);
    }
    walk(node["spec"]);
  };
  walk(spec);
  return out;
}

/**
 * Field names a spec's own `transform` pipeline PRODUCES.
 *
 * A transform invents columns the query never selected — `calculate` emits
 * `as`, `fold` emits a pair, `pivot` emits one column per value of its field,
 * `aggregate`/`window`/`joinaggregate` emit their `as` names, `timeUnit` emits
 * `as`. An encoding that names one of these is correct even though no column
 * of that name exists, so the existence check must know about them.
 *
 * Their TYPE is not knowable from `columns` (it is whatever the transform
 * computes), so a produced field is existence-satisfied and type-unchecked —
 * the honest answer, rather than guessing a type and failing a valid spec.
 */
export function transformOutputs(spec: unknown): Set<string> {
  const out = new Set<string>();
  const addName = (value: unknown): void => {
    if (typeof value === "string") out.add(value);
  };
  /** `as` is a string on most transforms and a [string, string] on `fold`. */
  const addAs = (value: unknown): void => {
    if (Array.isArray(value)) for (const one of value) addName(one);
    else addName(value);
  };
  const walk = (node: unknown): void => {
    if (!isRecord(node)) return;
    const transforms = node["transform"];
    if (Array.isArray(transforms)) {
      for (const t of transforms) {
        if (!isRecord(t)) continue;
        addAs(t["as"]);
        // pivot names its outputs by the DATA, not the spec, so the column
        // names cannot be known here; `pivot` is recorded as producing
        // everything, handled by the caller via `pivots`.
        for (const key of ["aggregate", "window", "joinaggregate"] as const) {
          const inner = t[key];
          if (Array.isArray(inner)) {
            for (const one of inner) if (isRecord(one)) addAs(one["as"]);
          }
        }
      }
    }
    for (const key of ["layer", "hconcat", "vconcat", "concat"] as const) {
      const branch = node[key];
      if (Array.isArray(branch)) for (const child of branch) walk(child);
    }
    walk(node["spec"]);
  };
  walk(spec);
  return out;
}

/**
 * Does the spec contain a `pivot` transform?
 *
 * `pivot` derives its output column names from the row VALUES, so which fields
 * exist afterwards is not a property of the spec. Checking existence against
 * `columns` would reject every valid pivot spec, so existence checking is
 * switched off for a spec that pivots — loudly, here, rather than by accident.
 */
export function hasPivot(spec: unknown): boolean {
  let found = false;
  const walk = (node: unknown): void => {
    if (found || !isRecord(node)) return;
    const transforms = node["transform"];
    if (Array.isArray(transforms)) {
      for (const t of transforms) {
        if (isRecord(t) && "pivot" in t) {
          found = true;
          return;
        }
      }
    }
    for (const key of ["layer", "hconcat", "vconcat", "concat"] as const) {
      const branch = node[key];
      if (Array.isArray(branch)) for (const child of branch) walk(child);
    }
    walk(node["spec"]);
  };
  walk(spec);
  return found;
}

/**
 * Verify every field a spec encodes exists in `columns` with a compatible type.
 * Returns the FIRST mismatch (in spec order) or null when the spec fits.
 *
 * Fields the spec's own `transform` produces count as existing with an unknown
 * type: they are real, but only after the transform runs.
 */
export function checkShape(
  columns: readonly QueryColumn[],
  spec: VegaLiteSpec,
): ShapeError | null {
  const byName = new Map(columns.map((c) => [c.name, c.type]));
  const produced = transformOutputs(spec);
  const pivots = hasPivot(spec);
  for (const ref of collectFieldRefs(spec)) {
    if (produced.has(ref.field) || pivots) continue;
    const duckType = byName.get(ref.field);
    if (duckType === undefined) {
      const known = columns.map((c) => c.name).join(", ");
      return {
        field: ref.field,
        expected: "a column in the query result",
        got: known.length === 0 ? "no columns" : `columns: ${known}`,
      };
    }
    if (ref.type !== null && !typeCompatible(ref.type, duckType)) {
      return { field: ref.field, expected: ref.type, got: duckType };
    }
  }
  return null;
}

/* -------------------------------------------------------------------- rows */

/** Columnar-ordered wire rows -> the records Vega's data API wants. */
export function rowsToObjects(
  columns: readonly QueryColumn[],
  rows: readonly QueryRow[],
): Record<string, unknown>[] {
  const names = columns.map((c) => c.name);
  return rows.map((row) => {
    const obj: Record<string, unknown> = {};
    names.forEach((name, j) => {
      obj[name] = row[j];
    });
    return obj;
  });
}

/* --------------------------------------------------------------------- sql */

/**
 * Panel queries are built from metric names and file names read off the event
 * stream, which are data, not code. The quoting itself lives in `core/sql.ts`
 * so the server shares the one implementation; re-exported here because a
 * panel author reaches for `panel.ts`.
 */
export { sqlLiteral } from "./sql.ts";
