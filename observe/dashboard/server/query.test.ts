/**
 * `/query`: rows, cross-file columns, honest truncation, the read-only gate,
 * and a timeout that actually stops the engine.
 *
 * The fixture is the golden format (lines lifted from
 * src/core/__fixtures__/golden.jsonl) split across two files, because "which
 * run is this row from" is a question the contract answers with `file`.
 */

import { afterEach, beforeAll, describe, expect, test } from "vitest";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import net from "node:net";

import { isRecord, requireString } from "../src/core/fields.ts";
import { at, must } from "../src/core/test-utils.ts";
import {
  openEngine,
  runQuery,
  toJsonValue,
  type QueryEngine,
  type QuerySuccess,
} from "./query.ts";
import { serve } from "./server.ts";

/** Golden-format lines. alpha: a run_start log, a span, and three metrics. */
const ALPHA = [
  {
    ts: 1789669021.9,
    kind: "log",
    level: "INFO",
    event: "run_start",
    logger: "robots.train",
    run_id: "goldenrun",
    run_name: "alpha",
    git_sha: "0000000",
    git_dirty: false,
    env_name: "CartPole-v1",
  },
  {
    ts: 1789669022.5,
    kind: "span",
    span_name: "robots.rollout",
    trace_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    span_id: "0101010101010101",
    parent_span_id: null,
    start_time_unix_nano: 1789669022200000000,
    end_time_unix_nano: 1789669022300000000,
    duration_ms: 100.0,
    status: "ok",
    run_id: "goldenrun",
    run_name: "alpha",
    step: 1,
  },
  { ts: 1789669023.0, kind: "metric", name: "wm_loss", value: 0.5, run_name: "alpha", step: 1 },
  { ts: 1789669024.0, kind: "metric", name: "wm_loss", value: 0.25, run_name: "alpha", step: 2 },
  { ts: 1789669025.0, kind: "metric", name: "wm_loss", value: 0.125, run_name: "alpha", step: 3 },
];

/** beta: one log and one metric, and an attr alpha does not have (union_by_name). */
const BETA = [
  {
    ts: 1789669030.0,
    kind: "log",
    level: "WARNING",
    event: "slow_iteration",
    logger: "robots.train",
    run_id: "betarun",
    run_name: "beta",
    elapsed_s: 4.2,
  },
  { ts: 1789669031.0, kind: "metric", name: "reward", value: 12.0, run_name: "beta", step: 1 },
  {
    ts: 1789669032.0,
    kind: "artifact",
    name: "rollout",
    mime: "application/x-trajectory+json",
    payload: {
      env: "CartPole-v1",
      obs: [
        [0, 0, 0, 0],
        [0.01, 0.15, -0.02, -0.21],
      ],
      actions: [1],
      rewards: [1.0],
    },
    run_name: "beta",
    step: 1,
  },
];

let runsDir: string;
let engine: QueryEngine;

beforeAll(async () => {
  runsDir = resolve(await mkdtemp(resolve(tmpdir(), "observe-query-")), "runs");
  await mkdir(runsDir);
  const jsonl = (lines: readonly unknown[]): string =>
    lines.map((line) => JSON.stringify(line)).join("\n") + "\n";
  await writeFile(resolve(runsDir, "alpha.jsonl"), jsonl(ALPHA));
  await writeFile(resolve(runsDir, "beta.jsonl"), jsonl(BETA));
  engine = openEngine(runsDir);
});

const running: Bun.Server<undefined>[] = [];

afterEach(async () => {
  while (running.length > 0) await running.pop()?.stop(true);
});

/** A server over the same fixture, so the HTTP statuses are tested too. */
/** A 4xx body's `error`, read with a guard — `as` would hide a shape change. */
async function errorOf(res: Response): Promise<string> {
  const body: unknown = await res.json();
  if (!isRecord(body)) throw new Error(`body is not an object: ${JSON.stringify(body)}`);
  return requireString(body, "error", "/query error body");
}

function fixtureServer(opts: { timeoutMs?: number } = {}): string {
  const server = serve({
    runsDir,
    distDir: resolve(runsDir, "no-dist"),
    port: 0,
    engine,
    ...(opts.timeoutMs === undefined ? {} : { queryTimeoutMs: opts.timeoutMs }),
  });
  running.push(server);
  return `http://127.0.0.1:${String(server.port)}`;
}

function ok(outcome: Awaited<ReturnType<typeof runQuery>>): QuerySuccess {
  if (outcome.kind !== "ok") {
    throw new Error(`expected rows, got ${outcome.kind}: ${outcome.message}`);
  }
  return outcome;
}

// --- artifacts ---

/**
 * A nested `payload` column and `read_json_auto`.
 *
 * The open question was whether an artifact line breaks materialization at all,
 * and whether heterogeneous payloads across files need a JSON-typed column.
 * Measured answer: neither. `union_by_name=true` infers `payload` as a STRUCT
 * whose fields are the UNION of every payload shape in the store (foreign keys
 * NULL per row), and it WIDENS genuinely conflicting field types instead of
 * failing. So no `maximum_object_size`, no `records`, no `columns={payload:
 * 'JSON'}` — which is just as well, because `columns=` replaces the whole
 * schema and disables auto-detect, so it would cost us every other column.
 *
 * The consequence for callers, and why this is documented in DESIGN.md rather
 * than fixed: `payload.<field>` is only meaningful for rows whose mime you also
 * filtered on. `name`/`mime`/attrs are exact, and those are what panels query.
 */
describe("artifacts", () => {
  test("an artifact line indexes, and name/mime come back exactly", async () => {
    const rows = ok(
      await runQuery(engine, "SELECT name, mime FROM events WHERE kind='artifact' ORDER BY name"),
    ).rows;
    expect(rows).toEqual([["rollout", "application/x-trajectory+json"]]);
  });

  test("the artifact's step attr is queryable like any other attr", async () => {
    const rows = ok(
      await runQuery(engine, "SELECT step FROM events WHERE kind='artifact' AND name='rollout'"),
    ).rows;
    expect(rows).toEqual([[1]]);
  });

  test("an artifact does not disturb the other kinds in the same file", async () => {
    const rows = ok(
      await runQuery(engine, "SELECT kind, count(*) FROM events WHERE file='beta.jsonl' GROUP BY kind ORDER BY kind"),
    ).rows;
    expect(rows).toEqual([
      ["artifact", 1],
      ["log", 1],
      ["metric", 1],
    ]);
  });

  test("payloads of different shapes — and conflicting types — still index", async () => {
    // Two artifacts whose payloads share a key name with incompatible types
    // (`env`: string vs number, `obs`: array vs string). This is the case that
    // would have forced a JSON-typed column if DuckDB had refused it.
    const dir = resolve(await mkdtemp(resolve(tmpdir(), "observe-query-art-")), "runs");
    await mkdir(dir);
    const lines = [
      {
        ts: 1,
        kind: "artifact",
        name: "traj",
        mime: "application/x-trajectory+json",
        payload: { env: "CartPole-v1", obs: [[0, 0, 0, 0]], actions: [1], rewards: [1.0] },
      },
      {
        ts: 2,
        kind: "artifact",
        name: "weird",
        mime: "application/x-other+json",
        payload: { env: 42, obs: "not-an-array", extra: { deep: true } },
      },
      { ts: 3, kind: "artifact", name: "scalar", mime: "application/json", payload: 7 },
    ];
    await writeFile(
      resolve(dir, "mixed.jsonl"),
      lines.map((line) => JSON.stringify(line)).join("\n") + "\n",
    );
    const rows = ok(
      await runQuery(openEngine(dir), "SELECT name, mime FROM events WHERE kind='artifact' ORDER BY name"),
    ).rows;
    expect(rows).toEqual([
      ["scalar", "application/json"],
      ["traj", "application/x-trajectory+json"],
      ["weird", "application/x-other+json"],
    ]);
  });
});

// --- rows ---

describe("rows", () => {
  test("metrics come back in step order, exactly", async () => {
    const result = ok(
      await runQuery(
        engine,
        "SELECT name, value, step FROM events WHERE kind='metric' ORDER BY step, name",
      ),
    );
    expect(result.columns.map((c) => c.name)).toEqual(["name", "value", "step"]);
    expect(result.rows).toEqual([
      ["reward", 12.0, 1],
      ["wm_loss", 0.5, 1],
      ["wm_loss", 0.25, 2],
      ["wm_loss", 0.125, 3],
    ]);
    expect(result.truncated).toBe(false);
    expect(result.ms).toBeGreaterThanOrEqual(0);
  });

  test("columns carry DuckDB's own type names", async () => {
    const result = ok(await runQuery(engine, "SELECT kind, value, step FROM events"));
    const types = new Map(result.columns.map((c) => [c.name, c.type]));
    expect(must(types.get("kind"), "kind type")).toBe("VARCHAR");
    expect(must(types.get("value"), "value type")).toBe("DOUBLE");
    expect(must(types.get("step"), "step type")).toBe("BIGINT");
  });

  test("BIGINT, DECIMAL and TIMESTAMP survive JSON", async () => {
    // The wire is JSON: BigInt and Date do not serialize, so they are coerced
    // (numbers / ISO strings) rather than crashing the response.
    const result = ok(
      await runQuery(
        engine,
        "SELECT 9007199254740993::BIGINT AS huge, 7::BIGINT AS small, 2.50::DECIMAL(10,2) AS dec, '2026-09-17T12:00:00Z'::TIMESTAMP AS at",
      ),
    );
    const row = at(result.rows, 0, "coercion row");
    // Past 2^53 a number would be silently wrong, so it is a decimal string.
    expect(row).toEqual([
      "9007199254740993",
      7,
      2.5,
      "2026-09-17T12:00:00.000Z",
    ]);
    expect(() => JSON.stringify(result.rows)).not.toThrow();
  });

  test("toJsonValue leaves plain values alone", () => {
    expect(toJsonValue("x")).toBe("x");
    expect(toJsonValue(1.5)).toBe(1.5);
    expect(toJsonValue(null)).toBe(null);
    expect(toJsonValue(true)).toBe(true);
  });

  test("one view spans every run file, keyed by bare file name", async () => {
    const result = ok(
      await runQuery(engine, "SELECT file, count(*) AS n FROM events GROUP BY file ORDER BY file"),
    );
    expect(result.rows).toEqual([
      ["alpha.jsonl", ALPHA.length],
      ["beta.jsonl", BETA.length],
    ]);
  });

  test("a file's own attrs are visible on it and null elsewhere", async () => {
    // union_by_name: beta's elapsed_s is a column even though alpha lacks it.
    const result = ok(
      await runQuery(
        engine,
        "SELECT file, elapsed_s FROM events WHERE elapsed_s IS NOT NULL",
      ),
    );
    expect(result.rows).toEqual([["beta.jsonl", 4.2]]);
  });

  test("a new file is seen without restarting (no cache, no state)", async () => {
    // Its own runs dir and its own engine: appearing files must not perturb
    // the shared fixture, or the tests become order-dependent.
    const dir = resolve(await mkdtemp(resolve(tmpdir(), "observe-query-new-")), "runs");
    await mkdir(dir);
    const line = JSON.stringify({ ts: 1.0, kind: "metric", name: "g", value: 1.0 }) + "\n";
    await writeFile(resolve(dir, "one.jsonl"), line);
    const fresh = openEngine(dir);
    const before = ok(await runQuery(fresh, "SELECT count(DISTINCT file) AS n FROM events"));
    expect(at(before.rows, 0, "count row")).toEqual([1]);
    await writeFile(resolve(dir, "two.jsonl"), line);
    const after = ok(await runQuery(fresh, "SELECT count(DISTINCT file) AS n FROM events"));
    expect(at(after.rows, 0, "count row")).toEqual([2]);
  });
});

// --- truncation ---

describe("truncation", () => {
  const three = "SELECT step FROM events WHERE name='wm_loss' ORDER BY step";

  test("a capped result says so", async () => {
    const result = ok(await runQuery(engine, three, { limit: 2 }));
    expect(result.rows).toEqual([[1], [2]]);
    expect(result.truncated).toBe(true);
    expect(result.limit).toBe(2);
  });

  test("a result exactly at the limit is NOT truncated", async () => {
    // The limit+1 probe exists for this case: rows.length === limit alone
    // cannot tell a full page from a cut one.
    const result = ok(await runQuery(engine, three, { limit: 3 }));
    expect(result.rows).toHaveLength(3);
    expect(result.truncated).toBe(false);
  });

  test("a nonsense limit is refused, not clamped", async () => {
    const outcome = await runQuery(engine, three, { limit: 0 });
    expect(outcome.kind).toBe("bad-request");
    const res = await fetch(`${fixtureServer()}/query?sql=SELECT%201&limit=abc`);
    expect(res.status).toBe(400);
  });
});

// --- the read-only gate ---

describe("read-only", () => {
  test("bad SQL is a 400 carrying DuckDB's message", async () => {
    const outcome = await runQuery(engine, "SELEC 1");
    expect(outcome.kind).toBe("bad-request");
    if (outcome.kind === "ok") throw new Error("unreachable");
    expect(outcome.message).toContain("syntax error");

    const res = await fetch(`${fixtureServer()}/query?sql=${encodeURIComponent("SELEC 1")}`);
    expect(res.status).toBe(400);
    expect(await errorOf(res)).toContain("syntax error");
  });

  test("an unknown column is a 400, not a crash", async () => {
    const outcome = await runQuery(engine, "SELECT nosuchcolumn FROM events");
    expect(outcome.kind).toBe("bad-request");
    if (outcome.kind === "ok") throw new Error("unreachable");
    expect(outcome.message.toLowerCase()).toContain("nosuchcolumn");
  });

  test.each([
    "DELETE FROM events",
    "CREATE TABLE t (x INTEGER)",
    "INSERT INTO t VALUES (1)",
    "UPDATE t SET x = 1",
    "COPY (SELECT 1) TO '/tmp/observe-pwn.csv'",
    "ATTACH '/tmp/observe-pwn.db'",
    "INSTALL httpfs",
    "PRAGMA disable_verification",
    "SET threads = 1",
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP VIEW events",
  ])("%s is refused", async (sql) => {
    const outcome = await runQuery(engine, sql);
    expect(outcome.kind).toBe("bad-request");
    if (outcome.kind === "ok") throw new Error("unreachable");
    // The message says WHY, not just that DuckDB's serializer declined.
    expect(outcome.message).toMatch(/read-only|single SELECT/);
    // Proof it was refused rather than run: the view is still there.
    const survives = ok(await runQuery(engine, "SELECT count(*) FROM events"));
    expect(at(survives.rows, 0, "count row")).toBeDefined();
  });

  test("WITH is a read, so it is allowed", async () => {
    const result = ok(
      await runQuery(engine, "WITH m AS (SELECT value FROM events WHERE kind='metric') SELECT count(*) FROM m"),
    );
    expect(at(result.rows, 0, "count row")).toEqual([4]);
  });

  test("missing sql is a 400 with a reason", async () => {
    const base = fixtureServer();
    for (const path of ["/query", "/query?sql=", "/query?sql=%20"]) {
      const res = await fetch(base + path);
      expect(res.status).toBe(400);
      expect(await errorOf(res)).toContain("sql");
    }
  });
});

// --- the filesystem sandbox ---

describe("no file reads", () => {
  /**
   * These are all valid single SELECTs, so the read-only gate passes them.
   * Only the engine's own `enable_external_access=false` stops them, which is
   * why the sandbox exists as well as the parser gate. A reviewer read
   * /etc/hosts and /etc/passwd through the first two of these.
   */
  test.each([
    ["read_text", "SELECT * FROM read_text('/etc/hosts')"],
    ["read_csv", "SELECT * FROM read_csv('/etc/passwd', columns={'line': 'VARCHAR'})"],
    ["read_blob", "SELECT * FROM read_blob('/etc/hosts')"],
    ["glob", "SELECT * FROM glob('/etc/*')"],
    ["read_json_auto", "SELECT * FROM read_json_auto('/etc/hosts')"],
    ["parquet_scan", "SELECT * FROM parquet_scan('/etc/hosts')"],
    ["FROM 'file'", "SELECT * FROM '/etc/hosts.jsonl'"],
  ])("%s cannot read a file", async (_name, sql) => {
    const outcome = await runQuery(engine, sql);
    expect(outcome.kind).toBe("bad-request");
    if (outcome.kind === "ok") throw new Error("unreachable");
    // The message names the refused family AND keeps DuckDB's own sentence, so
    // "Cannot access file" never reads as "that file does not exist".
    expect(outcome.message).toContain("/query cannot read files");
    expect(outcome.message).toContain("read_text");
    expect(outcome.message).toContain("file system operations are disabled");

    const res = await fetch(`${fixtureServer()}/query?sql=${encodeURIComponent(sql)}`);
    expect(res.status).toBe(400);
    expect(await errorOf(res)).toContain("/query cannot read files");
  });

  test("the store itself is still readable — the sandbox is armed after the read", async () => {
    const result = ok(await runQuery(engine, "SELECT count(*) FROM events"));
    // 5 alpha lines + 3 beta lines (the third is the artifact).
    expect(at(result.rows, 0, "count row")).toEqual([8]);
  });

  test("a CTE over events still works", async () => {
    const result = ok(
      await runQuery(
        engine,
        "WITH m AS (SELECT step, value FROM events WHERE name='wm_loss') SELECT count(*) FROM m",
      ),
    );
    expect(at(result.rows, 0, "count row")).toEqual([3]);
  });

  test("a subquery over events still works", async () => {
    const result = ok(
      await runQuery(engine, "SELECT max(value) FROM (SELECT value FROM events WHERE kind='metric')"),
    );
    expect(at(result.rows, 0, "max row")).toEqual([12]);
  });

  test("a self-join over events still works", async () => {
    const result = ok(
      await runQuery(engine, "SELECT count(*) FROM events e JOIN events f USING(file)"),
    );
    // 5 alpha lines and 3 beta lines pair within their own file: 25 + 9.
    expect(at(result.rows, 0, "count row")).toEqual([34]);
  });
});

// --- timeout ---

describe("timeout", () => {
  test("a spinning query is cancelled and the engine still works", async () => {
    // 10^13 rows: not "slow", unfinishable. If the response came back without
    // the engine being interrupted, the following query would block behind it.
    const spin = "SELECT count(*) FROM range(10000000000) a, range(1000) b";
    const started = performance.now();
    const outcome = await runQuery(engine, spin, { timeoutMs: 200 });
    const elapsed = performance.now() - started;
    expect(outcome.kind).toBe("timeout");
    expect(elapsed).toBeLessThan(2000);

    const after = performance.now();
    const fast = ok(await runQuery(engine, "SELECT count(*) FROM events"));
    expect(at(fast.rows, 0, "count row")).toBeDefined();
    // The engine was not left wedged: the next query is immediate.
    expect(performance.now() - after).toBeLessThan(2000);
  });

  test("one query's timeout does not cancel another's", async () => {
    // interrupt() is connection-wide, so a connection shared between requests
    // would let a timing-out query kill its neighbour. One per query.
    const spin = runQuery(
      engine,
      "SELECT count(*) FROM range(10000000000) a, range(1000) b",
      { timeoutMs: 200 },
    );
    const neighbour = runQuery(engine, "SELECT count(*) FROM events", { timeoutMs: 5000 });
    const [timedOut, survived] = await Promise.all([spin, neighbour]);
    expect(timedOut.kind).toBe("timeout");
    expect(ok(survived).rows).toHaveLength(1);
  });

  test("a timeout is a 408 over HTTP", async () => {
    const base = fixtureServer({ timeoutMs: 200 });
    const sql = "SELECT count(*) FROM range(10000000000) a, range(1000) b";
    const res = await fetch(`${base}/query?sql=${encodeURIComponent(sql)}`);
    expect(res.status).toBe(408);
    expect(await errorOf(res)).toContain("200ms");

    const next = await fetch(`${base}/query?sql=${encodeURIComponent("SELECT 1")}`);
    expect(next.status).toBe(200);
  });
});

// --- the endpoint does not change the server's shape ---

describe("routing", () => {
  test("/query answers 200 with the wire shape", async () => {
    const res = await fetch(
      `${fixtureServer()}/query?sql=${encodeURIComponent("SELECT name, value FROM events WHERE kind='metric' ORDER BY value")}`,
    );
    expect(res.status).toBe(200);
    expect(res.headers.get("Cache-Control")).toBe("no-store");
    const body: unknown = await res.json();
    expect(body).toMatchObject({
      columns: [
        { name: "name", type: "VARCHAR" },
        { name: "value", type: "DOUBLE" },
      ],
      truncated: false,
      limit: 10000,
    });
  });

  test("an idle keep-alive connection does not block /query", async () => {
    // Same regression as server.test.ts, re-run over the DuckDB path: the
    // query runs on the connection's thread, not the event loop's.
    const base = fixtureServer();
    const port = Number.parseInt(new URL(base).port, 10);
    const parked = net.createConnection({ host: "127.0.0.1", port });
    try {
      await new Promise<void>((done, fail) => {
        parked.once("error", fail);
        parked.once("data", () => {
          done();
        });
        parked.write("GET /runs HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n");
      });
      const t0 = performance.now();
      const res = await fetch(`${base}/query?sql=${encodeURIComponent("SELECT count(*) FROM events")}`, {
        signal: AbortSignal.timeout(2000),
      });
      expect(res.status).toBe(200);
      expect(performance.now() - t0).toBeLessThan(1000);
    } finally {
      parked.destroy();
    }
  });
});
