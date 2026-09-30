/**
 * The dashboard's HTTP surface. Stateless and pull-based: every request is
 * answered from the store as it is on disk right now, nothing is cached and no
 * run is "watched". Producers (python) only append to files.
 *
 *   GET /query?sql=         -> DuckDB SELECT over runs/*.jsonl -> rows
 *   GET /runs               -> JSON index, one row per run, first line only
 *   GET /runs/<file>.jsonl  -> the run file; `Range: bytes=N-` -> 206 suffix
 *   GET /<anything else>    -> static file from dist/ ("/" -> index.html)
 *
 *   bun server/server.ts --runs ../../runs [--port 8384]
 */

import { statSync } from "node:fs";
import { resolve } from "node:path";

import { indexRuns } from "./index.ts";
import { handleQuery, openEngine, type QueryEngine } from "./query.ts";
import { parseRange } from "./range.ts";
import { openRange, openWhole, resolveRun } from "./store.ts";

export const DEFAULT_HOST = "127.0.0.1";
export const DEFAULT_PORT = 8384;

const RUNS_ROUTE = "/runs";
const QUERY_ROUTE = "/query";
const BUILD_HINT =
  "dashboard not built.\n" + "run: cd observe/dashboard && bun install && bun run build\n";

const MIME: Record<string, string> = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".map": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".jsonl": "application/json",
};

function contentType(path: string): string {
  const dot = path.lastIndexOf(".");
  return (dot === -1 ? undefined : MIME[path.slice(dot).toLowerCase()]) ?? "application/octet-stream";
}

function text(status: number, body: string): Response {
  return new Response(body, { status, headers: { "Content-Type": "text/plain" } });
}

export interface ServerConfig {
  readonly runsDir: string;
  readonly distDir: string;
  readonly port?: number;
  readonly host?: string;
  /**
   * The DuckDB handle behind `/query`. Passed in rather than opened here so a
   * test can hand over one with a 200ms timeout, and so a server started
   * without one answers /query 503 instead of crashing.
   */
  readonly engine?: QueryEngine;
  /** Overridden in tests to prove the timeout actually cancels. */
  readonly queryTimeoutMs?: number;
}

async function handleRunFile(
  runsDir: string,
  file: string,
  rangeHeader: string | null,
): Promise<Response> {
  const run = await resolveRun(runsDir, file);
  if (run === null) return text(404, "not found");

  const range = parseRange(rangeHeader);
  if (range.kind === "malformed") {
    return text(400, `bad Range header: ${range.reason}\n`);
  }

  const base = {
    "Content-Type": "application/json",
    "Accept-Ranges": "bytes",
    "Cache-Control": "no-store",
  };

  if (range.kind === "absent") {
    const whole = openWhole(run.path);
    return new Response(whole.body, { status: 200, headers: base });
  }

  const opened = openRange(run.path, range.start);
  if (opened.kind === "unsatisfiable") {
    return new Response(null, {
      status: 416,
      headers: { ...base, "Content-Range": `bytes */${String(opened.size)}` },
    });
  }
  return new Response(opened.body, {
    status: 206,
    headers: {
      ...base,
      "Content-Range": `bytes ${String(opened.start)}-${String(opened.size - 1)}/${String(opened.size)}`,
    },
  });
}

async function handleStatic(distDir: string, path: string): Promise<Response> {
  const dist = Bun.file(resolve(distDir, "index.html"));
  if (!(await dist.exists())) return text(503, BUILD_HINT);

  const relative = path === "/" ? "index.html" : path.replace(/^\/+/, "");
  const candidate = resolve(distDir, relative);
  if (candidate !== distDir && !candidate.startsWith(distDir + "/")) {
    return text(404, "not found");
  }
  const file = Bun.file(candidate);
  if (!(await file.exists())) return text(404, "not found");
  return new Response(file, {
    status: 200,
    headers: { "Content-Type": contentType(candidate) },
  });
}

export function serve(config: ServerConfig): Bun.Server<undefined> {
  const runsDir = resolve(config.runsDir);
  const distDir = resolve(config.distDir);

  // Fail at startup, not on the first request: a typo'd --runs should be a
  // loud error in the terminal, never a dashboard that lists nothing.
  const info = statSync(runsDir, { throwIfNoEntry: false });
  if (!info?.isDirectory()) {
    throw new Error(`runs dir does not exist: ${runsDir}`);
  }

  return Bun.serve({
    hostname: config.host ?? DEFAULT_HOST,
    port: config.port ?? DEFAULT_PORT,
    // Bun.serve is event-driven: an idle keep-alive connection parks on the
    // event loop and blocks nothing. This is the whole reason the Python
    // version needed ThreadingHTTPServer.
    idleTimeout: 60,
    async fetch(req) {
      const url = new URL(req.url);
      const path = url.pathname;
      if (path === RUNS_ROUTE) {
        return Response.json(await indexRuns(runsDir), {
          headers: { "Cache-Control": "no-store" },
        });
      }
      if (path === QUERY_ROUTE) {
        if (config.engine === undefined) {
          return text(503, "query engine not started\n");
        }
        return handleQuery(config.engine, url, {
          ...(config.queryTimeoutMs === undefined ? {} : { timeoutMs: config.queryTimeoutMs }),
        });
      }
      if (path.startsWith(RUNS_ROUTE + "/")) {
        const file = decodeURIComponent(path.slice(RUNS_ROUTE.length + 1));
        return handleRunFile(runsDir, file, req.headers.get("Range"));
      }
      return handleStatic(distDir, path);
    },
  });
}

/** The flags this server takes. A closed set: an unknown flag is an error. */
const FLAGS = ["--runs", "--port", "--dist", "--host"] as const;

type Flag = (typeof FLAGS)[number];

function isFlag(value: string): value is Flag {
  return FLAGS.some((flag) => flag === value);
}

export interface ServerArgs {
  readonly runs: string;
  readonly port: number;
  readonly dist: string;
  readonly host: string;
}

/**
 * argv -> a frozen options object.
 *
 * Two passes rather than one loop that reassigns the result fields: `pairs`
 * turns argv into flag/value pairs (validating arity), and the object is then
 * CONSTRUCTED once from the last value given for each flag. Nothing is
 * assigned twice, so every intermediate is still inspectable and the defaults
 * are visible in one place instead of being overwritten one field at a time.
 */
function pairs(argv: readonly string[]): Map<Flag, string> {
  const found = new Map<Flag, string>();
  for (let i = 0; i < argv.length; i += 2) {
    const flag = argv[i];
    if (flag === undefined) break;
    if (!isFlag(flag)) {
      throw new Error(
        `unknown argument ${JSON.stringify(flag)} (expected one of ${FLAGS.join(", ")})`,
      );
    }
    const value = argv[i + 1];
    if (value === undefined) throw new Error(`${flag} needs a value`);
    // A later occurrence wins, which is what every CLI does.
    found.set(flag, value);
  }
  return found;
}

function parsePort(raw: string): number {
  const port = Number.parseInt(raw, 10);
  if (!Number.isInteger(port)) throw new Error(`--port ${raw} is not a number`);
  return port;
}

export function parseArgs(argv: readonly string[]): ServerArgs {
  const given = pairs(argv);
  const runs = given.get("--runs");
  const dist = given.get("--dist");
  const port = given.get("--port");
  const host = given.get("--host");
  return Object.freeze({
    host: host ?? DEFAULT_HOST,
    runs: runs === undefined ? resolve(import.meta.dir, "..", "..", "..", "runs") : resolve(runs),
    dist: dist === undefined ? resolve(import.meta.dir, "..", "dist") : resolve(dist),
    port: port === undefined ? DEFAULT_PORT : parsePort(port),
  });
}

/**
 * Is this address reachable only from this machine?
 *
 * `/query` is an unauthenticated DuckDB SELECT endpoint. Its sandbox (see
 * query.ts) stops it reading files, but it still exposes every run on the box
 * to anyone who can reach the port, so binding off-loopback is a decision the
 * operator must SEE, not one that happens quietly.
 */
export function isLoopback(host: string): boolean {
  return host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]";
}

if (import.meta.main) {
  const args = parseArgs(Bun.argv.slice(2));
  const engine = openEngine(args.runs);
  const server = serve({
    runsDir: args.runs,
    distDir: args.dist,
    port: args.port,
    host: args.host,
    engine,
  });
  console.log(
    `observe server  http://${server.hostname ?? DEFAULT_HOST}:${String(server.port)}  runs=${args.runs}`,
  );
  if (!isLoopback(args.host)) {
    console.log(
      `  WARNING: bound to ${args.host} (not loopback) — /query is enabled and unauthenticated; anyone who can reach this port can read every run`,
    );
  }
  if (!(await Bun.file(resolve(args.dist, "index.html")).exists())) {
    console.log(`  (no dashboard build at ${args.dist} — / will return 503)`);
  }
}
