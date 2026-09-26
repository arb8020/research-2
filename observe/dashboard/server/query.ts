/**
 * `GET /query?sql=` — DuckDB over the store's JSONL files (DESIGN.md
 * "/query wire contract").
 *
 * Stateless like the rest of the server: one in-memory DuckDB per process
 * holds no data, and every request re-creates the `events` view over
 * `<runsDir>/*.jsonl`, so a query always sees the files as they are on disk
 * right now. No cache, no watching, nothing to invalidate.
 *
 * Four things are enforced, because a SQL endpoint with none of them is a
 * remote shell with a row cap:
 *
 *   no files    `SET enable_external_access=false` after the store has been
 *              READ. DuckDB's table functions (`read_text`, `read_csv`,
 *              `read_blob`, `glob`, `parquet_scan`, `FROM 'path'`, ...) are
 *              ordinary SELECT syntax, so the read-only gate below waves them
 *              through; only the engine's own filesystem switch stops them.
 *              See `openRequestSandbox`.
 *
 *   read-only  DuckDB's own parser is the gate: `json_serialize_sql` refuses
 *              anything that is not a SELECT ("Only SELECT statements can be
 *              serialized to json!"), and its `statements` array tells us how
 *              many statements the text held. We never keyword-grep.
 *   limit      the query is wrapped as `SELECT * FROM (<sql>) LIMIT limit+1`,
 *              so a full page is distinguishable from a truncated one instead
 *              of being guessed at.
 *   timeout    `connection.interrupt()` — the query actually stops in the
 *              engine; a raced promise would only abandon the response.
 *
 * Values are coerced for JSON (`toJsonValue`): DuckDB hands back BigInt for
 * BIGINT/HUGEINT and Date for DATE/TIMESTAMP, neither of which JSON.stringify
 * will touch.
 */

import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
// One implementation of the quoting rule, shared with the panel builder. Its
// rationale (why doubling the quote is sufficient for DuckDB) lives there.
import { sqlLiteral } from "../src/core/sql.ts";

/** DESIGN.md: default 10000 rows. */
export const DEFAULT_LIMIT = 10_000;
/** DESIGN.md: default 5000ms. A query past this is a mistake, not a wait. */
export const DEFAULT_TIMEOUT_MS = 5_000;
/**
 * A limit above this is refused rather than clamped — clamping is a semantic
 * fallback, and a million rows is not a chart either way.
 */
export const MAX_LIMIT = 1_000_000;

export interface QueryColumn {
  readonly name: string;
  /** The DuckDB type name, verbatim ("BIGINT", "DECIMAL(18,4)", ...). */
  readonly type: string;
}

/** A 200 body. `rows[i][j]` belongs to `columns[j]`. */
export interface QuerySuccess {
  readonly kind: "ok";
  readonly columns: readonly QueryColumn[];
  readonly rows: readonly (readonly unknown[])[];
  readonly truncated: boolean;
  readonly limit: number;
  readonly ms: number;
}

/**
 * The two ways a query fails as an ANSWER (4xx with a message), as opposed to
 * the server being broken. Anything else is a bug and propagates.
 */
export type QueryFailure =
  /** DuckDB's own message, verbatim: parse, bind, type, or the read-only gate. */
  | { readonly kind: "bad-request"; readonly message: string }
  | { readonly kind: "timeout"; readonly message: string };

export type QueryOutcome = QuerySuccess | QueryFailure;

/* --------------------------------------------------------------- the engine */

/**
 * The DuckDB handle. Deliberately opaque: `server.ts` creates one at startup
 * and passes it to `runQuery`, so nothing above this file knows the store is
 * queried by DuckDB at all.
 *
 * It holds no instance. `enable_external_access` is a DATABASE-global setting
 * (measured: setting it on one connection blocks file reads on every other
 * connection of the same instance), and the sandbox has to be armed AFTER the
 * store is read, so the database itself is per-request. See
 * `openRequestSandbox`.
 */
export interface QueryEngine {
  readonly runsDir: string;
}

/**
 * One connection per query, not one per server. `interrupt()` is
 * connection-wide: on a shared connection, one request hitting its timeout
 * would cancel every other request's query too. A connection is cheap (the
 * database is empty — the `events` view is all there is) and it makes
 * "interrupted" unambiguous: only OUR timer can interrupt OUR connection.
 *
 * Why in-memory and not read-only: DuckDB refuses `access_mode=READ_ONLY` on
 * an in-memory database ("Cannot launch in-memory database in read-only
 * mode!"), and `SET access_mode` after open is refused too. The database holds
 * no data — only the `events` view — so read-only-ness has to be about what
 * the SQL is allowed to SAY, which is `checkReadOnly` below.
 */
export function openEngine(runsDir: string): QueryEngine {
  return { runsDir };
}

/**
 * A database that has read the store and can never read anything else.
 *
 * The order is the whole trick, and it is why this is a fresh database per
 * request rather than a shared one:
 *
 *   1. `CREATE TEMP TABLE events AS SELECT ... read_json_auto(<runs>/*.jsonl)`
 *      — MATERIALIZED, not a view. A view resolves lazily, so with external
 *      access already off the view's own scan is refused too ("file system
 *      operations are disabled by configuration"). Measured at the real runs
 *      dir (5347 lines): ~3ms to open the database, ~17ms to materialize, so
 *      the contract's "reads the files every query" still holds inside the
 *      poll budget.
 *   2. `SET enable_external_access=false` — from here on the connection can
 *      read `events` and nothing on disk. This kills the whole table-function
 *      family at once (`read_text`, `read_csv`, `read_blob`, `read_json*`,
 *      `glob`, `parquet_scan`, `FROM 'file.jsonl'`) without this file keeping
 *      a list of function names DuckDB is free to grow.
 *
 * The setting is global to the database, which is exactly why step 2 cannot
 * happen on a long-lived instance: it would lock out the NEXT request's step 1.
 */
async function openRequestSandbox(runsDir: string): Promise<DuckDBConnection> {
  const instance = await DuckDBInstance.create(":memory:");
  const connection = await instance.connect();
  const glob = sqlLiteral(`${runsDir}/*.jsonl`);
  // `read_json_auto` names the source column `filename` and fills it with the
  // full path; the contract says `file` holding the bare name — the same id
  // `/runs` uses — so it is renamed and reduced here, once.
  await connection.run(
    `CREATE TEMP TABLE events AS
       SELECT * RENAME (filename AS file)
       FROM (
         SELECT * REPLACE (parse_filename(filename) AS filename)
         FROM read_json_auto(${glob}, union_by_name=true, filename=true)
       )`,
  );
  await connection.run("SET enable_external_access=false");
  return connection;
}

/* ------------------------------------------------------- the read-only gate */

/** What DuckDB's parser said about the text. */
type ParseVerdict =
  | { readonly kind: "select"; readonly statements: number }
  | { readonly kind: "rejected"; readonly message: string };

/**
 * Ask DuckDB to serialize the statement. This is a parse with a verdict
 * attached: `json_serialize_sql` implements "only SELECT" itself, and reports
 * parser errors in the same JSON rather than throwing, so one call answers
 * both "is this valid SQL" and "is this read-only".
 */
async function parseStatement(
  connection: DuckDBConnection,
  sql: string,
): Promise<ParseVerdict> {
  const result = await connection.run(
    `SELECT json_serialize_sql(${sqlLiteral(sql)}) AS plan`,
  );
  const rows = await result.getRowsJS();
  const raw = rows[0]?.[0];
  if (typeof raw !== "string") {
    // json_serialize_sql is a scalar over one literal row. No row, or a
    // non-string, means the binding changed shape under us — a bug here, not a
    // bad query.
    throw new Error(`json_serialize_sql returned ${typeof raw}, expected a string`);
  }
  const plan: unknown = JSON.parse(raw);
  if (typeof plan !== "object" || plan === null) {
    throw new Error("json_serialize_sql did not return an object");
  }
  const record: Record<string, unknown> = { ...plan };
  if (record["error"] === true) {
    const raw = record["error_message"];
    const message = typeof raw === "string" ? raw : "DuckDB rejected the statement";
    // DuckDB's own words for "not a SELECT" describe its serializer, not this
    // endpoint, so that one message gets the reason a caller can act on. Every
    // other message (parser, binder) is passed through verbatim.
    return {
      kind: "rejected",
      message: record["error_type"] === "not implemented"
        ? `/query is read-only: only a single SELECT (or WITH ... SELECT) is allowed — DuckDB said: ${message}`
        : message,
    };
  }
  const statements = record["statements"];
  if (!Array.isArray(statements)) {
    throw new Error("json_serialize_sql returned no statements array");
  }
  return { kind: "select", statements: statements.length };
}

/**
 * DuckDB's sandbox error says only which PATH it refused, because the refusal
 * happens in its filesystem layer and by then the table function that asked is
 * gone. A caller who wrote `read_text('/etc/hosts')` would read "Cannot access
 * file" as "the file is missing", so the reason is stated: `/query` reads the
 * store and nothing else. DuckDB's own sentence is kept verbatim after it.
 */
function explainPermission(message: string): string {
  return message.startsWith("Permission Error:")
    ? `/query cannot read files: only the store's own \`events\` table is readable, ` +
        `so table functions over a path (read_text, read_csv, read_blob, read_json, ` +
        `parquet_scan, glob, FROM 'file') are refused — DuckDB said: ${message}`
    : message;
}

/* ---------------------------------------------------------- JSON coercion */

/**
 * The JSON-safe form of one DuckDB value.
 *
 * - BIGINT/HUGEINT arrive as BigInt. Inside IEEE-754's exact range they become
 *   numbers; outside it they become decimal strings, because a silently
 *   rounded step count is worse than a string a caller has to notice.
 * - DATE/TIMESTAMP arrive as Date -> ISO 8601 (UTC).
 * - BLOB arrives as a Buffer/Uint8Array -> base64.
 * - DECIMAL, FLOAT, DOUBLE already arrive as numbers.
 * Documented in DESIGN.md's wire contract.
 */
export function toJsonValue(value: unknown): unknown {
  if (typeof value === "bigint") {
    return value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER)
      ? Number(value)
      : value.toString();
  }
  if (value instanceof Date) return value.toISOString();
  if (value instanceof Uint8Array) return Buffer.from(value).toString("base64");
  if (Array.isArray(value)) return value.map(toJsonValue);
  if (typeof value === "object" && value !== null) {
    return Object.fromEntries(
      Object.entries(value).map(([key, inner]) => [key, toJsonValue(inner)]),
    );
  }
  return value;
}

/* -------------------------------------------------------------- the query */

export interface RunQueryOptions {
  readonly limit?: number;
  readonly timeoutMs?: number;
}

/**
 * Run one SELECT and return rows, or the 4xx answer explaining why not.
 *
 * Never throws for a bad query: a DuckDB error is the point of a query
 * endpoint. It DOES throw when the engine or the store is broken (the view
 * cannot be created, the binding changed shape) — that is a 500's job.
 */
export async function runQuery(
  engine: QueryEngine,
  sql: string,
  options: RunQueryOptions = {},
): Promise<QueryOutcome> {
  const limit = options.limit ?? DEFAULT_LIMIT;
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    return {
      kind: "bad-request",
      message: `limit must be an integer in 1..${String(MAX_LIMIT)}, got ${String(limit)}`,
    };
  }
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

  // The sandbox is built before the statement is even parsed: parsing needs a
  // connection, and the only connection this request gets is a sandboxed one.
  // It is also where a broken store surfaces, so it is outside the try below:
  // it must not be reported as the user's bad SQL.
  const connection = await openRequestSandbox(engine.runsDir);
  const verdict = await parseStatement(connection, sql);
  if (verdict.kind === "rejected") {
    connection.closeSync();
    return { kind: "bad-request", message: verdict.message };
  }
  if (verdict.statements !== 1) {
    connection.closeSync();
    return {
      kind: "bad-request",
      message: `expected a single SELECT statement, got ${String(verdict.statements)}`,
    };
  }

  // limit + 1: one row past the cap is how truncation is DETECTED rather than
  // assumed from `rows.length === limit`.
  const wrapped = `SELECT * FROM (${sql}) LIMIT ${String(limit + 1)}`;
  const started = performance.now();
  // A box, not a `let`: the flag is read in the catch below, and TypeScript
  // would narrow a closure-assigned boolean to its initial value.
  const deadline = { fired: false };
  const timer = setTimeout(() => {
    deadline.fired = true;
    connection.interrupt();
  }, timeoutMs);

  try {
    const result = await connection.run(wrapped);
    const names = result.columnNames();
    const types = result.columnTypes().map((type) => String(type));
    const all = await result.getRowsJS();
    const truncated = all.length > limit;
    const kept = truncated ? all.slice(0, limit) : all;
    return {
      kind: "ok",
      columns: names.map((name, i) => ({ name, type: types[i] ?? "UNKNOWN" })),
      rows: kept.map((row) => row.map(toJsonValue)),
      truncated,
      limit,
      ms: performance.now() - started,
    };
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    if (deadline.fired) {
      return { kind: "timeout", message: `query exceeded ${String(timeoutMs)}ms and was cancelled` };
    }
    return { kind: "bad-request", message: explainPermission(message) };
  } finally {
    clearTimeout(timer);
    connection.closeSync();
  }
}

/* ------------------------------------------------------------ HTTP boundary */

/** `?limit=` — absent is the default; unparseable is an error, never ignored. */
function readLimit(raw: string | null): number | { readonly error: string } {
  if (raw === null) return DEFAULT_LIMIT;
  const parsed = Number(raw);
  if (!Number.isInteger(parsed)) return { error: `limit ${JSON.stringify(raw)} is not an integer` };
  return parsed;
}

function outcomeResponse(outcome: QueryOutcome): Response {
  switch (outcome.kind) {
    case "ok":
      return Response.json(
        {
          columns: outcome.columns,
          rows: outcome.rows,
          truncated: outcome.truncated,
          limit: outcome.limit,
          ms: outcome.ms,
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    case "bad-request":
      return Response.json({ error: outcome.message }, { status: 400 });
    case "timeout":
      return Response.json({ error: outcome.message }, { status: 408 });
  }
}

/**
 * The route. `?sql=` is required — a missing one is a 400 with a message, not
 * an empty result, because "no sql" is a caller bug worth saying out loud.
 */
export async function handleQuery(
  engine: QueryEngine,
  url: URL,
  options: RunQueryOptions = {},
): Promise<Response> {
  const sql = url.searchParams.get("sql");
  if (sql === null || sql.trim() === "") {
    return Response.json({ error: "missing required query parameter: sql" }, { status: 400 });
  }
  const limit = readLimit(url.searchParams.get("limit"));
  if (typeof limit === "object") {
    return Response.json({ error: limit.error }, { status: 400 });
  }
  return outcomeResponse(await runQuery(engine, sql, { ...options, limit }));
}
