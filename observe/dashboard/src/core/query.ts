/**
 * The `/query` client (DESIGN.md "/query wire contract").
 *
 * A 400 (DuckDB parse/bind error) and a 408 (timeout) are ANSWERS, not
 * exceptions: a panel renders them in place as its state. So this returns a sum
 * type and throws only for an aborted request, which is the caller's own doing.
 *
 * The response body is `unknown` and is parsed here with core/fields.ts readers
 * — no `as` — so a server that changes shape produces a named
 * `malformed-response` with a reason instead of a chart of undefineds.
 */

import { FieldError, isRecord, requireBoolean, requireNumber, requireString } from "./fields.ts";
import type { QueryColumn, QueryResult, QueryRow } from "./panel.ts";

/** Every way a query can fail to produce rows. */
export type QueryError =
  | { readonly kind: "query-error"; readonly status: 400; readonly message: string }
  | { readonly kind: "timeout"; readonly status: 408; readonly message: string }
  | {
      readonly kind: "http-error";
      readonly status: number;
      readonly message: string;
    }
  | { readonly kind: "network-error"; readonly message: string }
  | { readonly kind: "malformed-response"; readonly reason: string };

export type QueryOutcome = QueryResult | QueryError;

export interface RunQueryOptions {
  readonly signal?: AbortSignal;
  /** Injected in tests; defaults to the global. */
  readonly fetch?: typeof globalThis.fetch;
  /** Base path for the endpoint. Overridden in tests. */
  readonly endpoint?: string;
}

export function queryUrl(sql: string, endpoint = "/query"): string {
  return `${endpoint}?sql=${encodeURIComponent(sql)}`;
}

/* ------------------------------------------------------------------ parsing */

function parseColumns(value: unknown): readonly QueryColumn[] {
  if (!Array.isArray(value)) {
    throw new FieldError({ key: "columns", expected: "an array", got: value });
  }
  return value.map((entry, i) => {
    if (!isRecord(entry)) {
      throw new FieldError({
        key: `columns[${String(i)}]`,
        expected: "an object",
        got: entry,
      });
    }
    return {
      name: requireString(entry, "name", `columns[${String(i)}]`),
      type: requireString(entry, "type", `columns[${String(i)}]`),
    };
  });
}

function parseRows(value: unknown, width: number): readonly QueryRow[] {
  if (!Array.isArray(value)) {
    throw new FieldError({ key: "rows", expected: "an array", got: value });
  }
  return value.map((row, i) => {
    if (!Array.isArray(row)) {
      throw new FieldError({
        key: `rows[${String(i)}]`,
        expected: "an array (rows are columnar-ordered)",
        got: row,
      });
    }
    if (row.length !== width) {
      throw new FieldError({
        key: `rows[${String(i)}]`,
        expected: `${String(width)} values, one per column`,
        got: `${String(row.length)} values`,
      });
    }
    const values: readonly unknown[] = row;
    return values;
  });
}

/** Parse a 200 body into a QueryResult, or throw FieldError. */
export function parseQueryResult(body: unknown): QueryResult {
  if (!isRecord(body)) {
    throw new FieldError({ key: "<body>", expected: "an object", got: body });
  }
  const columns = parseColumns(body["columns"]);
  return {
    kind: "result",
    columns,
    rows: parseRows(body["rows"], columns.length),
    truncated: requireBoolean(body, "truncated", "/query"),
    limit: requireNumber(body, "limit", "/query"),
    ms: requireNumber(body, "ms", "/query"),
  };
}

/** Parse a 4xx body's `error` string, or throw FieldError. */
function parseErrorBody(body: unknown): string {
  if (!isRecord(body)) {
    throw new FieldError({ key: "<body>", expected: "an object", got: body });
  }
  return requireString(body, "error", "/query error body");
}

function reasonOf(cause: unknown): string {
  if (cause instanceof FieldError) return cause.message;
  if (cause instanceof Error) return cause.message;
  return String(cause);
}

/* ---------------------------------------------------------------- the call */

export async function runQuery(
  sql: string,
  options: RunQueryOptions = {},
): Promise<QueryOutcome> {
  const doFetch = options.fetch ?? globalThis.fetch;
  const url = queryUrl(sql, options.endpoint ?? "/query");

  let response: Response;
  try {
    response = await doFetch(url, {
      ...(options.signal === undefined ? {} : { signal: options.signal }),
    });
  } catch (cause) {
    // An abort is the caller's own instruction, not a query failure: rethrow so
    // a superseded refresh is discarded rather than rendered as an error.
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    return { kind: "network-error", message: reasonOf(cause) };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch (cause) {
    return {
      kind: "malformed-response",
      reason: `status ${String(response.status)}: body is not JSON (${reasonOf(cause)})`,
    };
  }

  if (response.status === 200) {
    try {
      return parseQueryResult(body);
    } catch (cause) {
      return { kind: "malformed-response", reason: reasonOf(cause) };
    }
  }

  let message: string;
  try {
    message = parseErrorBody(body);
  } catch (cause) {
    return {
      kind: "malformed-response",
      reason: `status ${String(response.status)}: ${reasonOf(cause)}`,
    };
  }

  if (response.status === 400) return { kind: "query-error", status: 400, message };
  if (response.status === 408) return { kind: "timeout", status: 408, message };
  return { kind: "http-error", status: response.status, message };
}

/** True for the outcomes that are not rows. Keeps the switch honest at call sites. */
export function isQueryError(outcome: QueryOutcome): outcome is QueryError {
  return outcome.kind !== "result";
}
