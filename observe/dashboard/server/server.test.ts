/**
 * The HTTP surface: /runs index, Range on jsonl, traversal guard, dist fallback.
 * Ported from observe/tests/test_serve.py, assertion for assertion.
 */

import { afterEach, describe, expect, test } from "vitest";
import { mkdtemp, mkdir, writeFile, appendFile, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import net from "node:net";

import { at, must } from "../src/core/test-utils.ts";
import { indexRuns } from "./index.ts";
import { DEFAULT_HOST, isLoopback, parseArgs, serve } from "./server.ts";

const HEADER = {
  ts: 1789667548.3,
  kind: "log",
  event: "run_start",
  run_id: "27ea56a8",
  run_name: "alpha",
  git_sha: "89e9235",
  git_dirty: true,
};

const running: Bun.Server<undefined>[] = [];

afterEach(async () => {
  while (running.length > 0) await running.pop()?.stop(true);
});

async function tmp(): Promise<string> {
  return mkdtemp(resolve(tmpdir(), "observe-serve-"));
}

/** A runs/ directory plus a server on an ephemeral port. */
async function fixture(opts: { dist?: string } = {}): Promise<{ runsDir: string; base: string; root: string }> {
  const root = await tmp();
  const runsDir = resolve(root, "runs");
  await mkdir(runsDir);
  const server = serve({
    runsDir,
    distDir: opts.dist ?? resolve(root, "no-dist"),
    port: 0,
  });
  running.push(server);
  return { runsDir, root, base: `http://127.0.0.1:${String(server.port)}` };
}

async function writeRun(
  runsDir: string,
  name: string,
  opts: { header?: unknown; tail?: string } = {},
): Promise<string> {
  const path = resolve(runsDir, `${name}.jsonl`);
  const header = "header" in opts ? opts.header : HEADER;
  await writeFile(path, JSON.stringify(header) + "\n" + (opts.tail ?? ""));
  return path;
}

async function sizeOf(path: string): Promise<number> {
  return (await stat(path)).size;
}

// --- /runs index ---

describe("/runs index", () => {
  test("reads only the first line", async () => {
    // A corrupt SECOND line must not affect the index — proof we never read past line 1.
    const { runsDir } = await fixture();
    await writeRun(runsDir, "alpha", { tail: "{not json at all\n".repeat(5) });
    const rows = await indexRuns(runsDir);
    expect(rows).toHaveLength(1);
    const entry = at(rows, 0, "indexed run");
    expect(entry.run_name).toBe("alpha");
    expect(entry.run_id).toBe("27ea56a8");
    expect(entry.git_sha).toBe("89e9235");
    expect(entry.git_dirty).toBe(true);
    expect(entry.started_ts).toBe(HEADER.ts);
    expect(entry.file).toBe("alpha.jsonl");
    expect(entry.error).toBeUndefined();
  });

  test("reports a bad first line instead of skipping it", async () => {
    const { runsDir } = await fixture();
    await writeFile(resolve(runsDir, "broken.jsonl"), "this is not json\n");
    await writeRun(runsDir, "alpha");
    const byFile = new Map((await indexRuns(runsDir)).map((r) => [r.file, r]));
    expect([...byFile.keys()].sort()).toEqual(["alpha.jsonl", "broken.jsonl"]);
    expect(must(byFile.get("broken.jsonl"), "broken.jsonl row").error).toContain(
      "bad first line",
    );
  });

  test("reports an empty file", async () => {
    const { runsDir } = await fixture();
    await writeFile(resolve(runsDir, "empty.jsonl"), "");
    const rows = await indexRuns(runsDir);
    expect(rows).toHaveLength(1);
    expect(at(rows, 0, "indexed run").error).toBe("empty file");
    expect(at(rows, 0, "indexed run").size_bytes).toBe(0);
  });

  test("/runs serves the index", async () => {
    const { runsDir, base } = await fixture();
    const path = await writeRun(runsDir, "alpha");
    const res = await fetch(`${base}/runs`);
    expect(res.status).toBe(200);
    const rows: unknown = await res.json();
    if (!Array.isArray(rows)) throw new Error("/runs did not return an array");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ run_name: "alpha", size_bytes: await sizeOf(path) });
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  test("newest-started first, unparseable last", async () => {
    const { runsDir } = await fixture();
    await writeRun(runsDir, "old", { header: { ...HEADER, ts: 1000 } });
    await writeRun(runsDir, "new", { header: { ...HEADER, ts: 2000 } });
    await writeFile(resolve(runsDir, "broken.jsonl"), "nope\n");
    expect((await indexRuns(runsDir)).map((r) => r.file)).toEqual([
      "new.jsonl",
      "old.jsonl",
      "broken.jsonl",
    ]);
  });
});

// --- Range serving ---

describe("Range", () => {
  test("full GET returns the whole file", async () => {
    const { runsDir, base } = await fixture();
    const path = await writeRun(runsDir, "alpha", { tail: '{"ts": 2.0, "kind": "log"}\n' });
    const res = await fetch(`${base}/runs/alpha.jsonl`);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe(await Bun.file(path).text());
    expect(res.headers.get("Accept-Ranges")).toBe("bytes");
  });

  test("returns exact suffix bytes", async () => {
    const { runsDir, base } = await fixture();
    const path = await writeRun(runsDir, "alpha", { tail: '{"ts": 2.0, "kind": "log"}\n' });
    const raw = await Bun.file(path).text();
    const offset = JSON.stringify(HEADER).length + 1; // just past the first line
    const res = await fetch(`${base}/runs/alpha.jsonl`, { headers: { Range: `bytes=${String(offset)}-` } });
    expect(res.status).toBe(206);
    expect(await res.text()).toBe(raw.slice(offset));
    expect(res.headers.get("Content-Range")).toBe(
      `bytes ${String(offset)}-${String(raw.length - 1)}/${String(raw.length)}`,
    );
    expect(res.headers.get("Cache-Control")).toBe("no-store");
  });

  test("at or past EOF is 416", async () => {
    const { runsDir, base } = await fixture();
    const path = await writeRun(runsDir, "alpha");
    const size = await sizeOf(path);
    const res = await fetch(`${base}/runs/alpha.jsonl`, { headers: { Range: `bytes=${String(size)}-` } });
    expect(res.status).toBe(416);
    expect(res.headers.get("Content-Range")).toBe(`bytes */${String(size)}`);

    const beyond = await fetch(`${base}/runs/alpha.jsonl`, {
      headers: { Range: `bytes=${String(size + 100)}-` },
    });
    expect(beyond.status).toBe(416);
  });

  test("sees appended bytes", async () => {
    // The tail loop's contract: append, re-request from the old size, get the new bytes.
    const { runsDir, base } = await fixture();
    const path = await writeRun(runsDir, "alpha");
    const firstSize = await sizeOf(path);
    await appendFile(path, '{"ts": 3.0, "kind": "metric", "name": "x", "value": 1.0}\n');
    const res = await fetch(`${base}/runs/alpha.jsonl`, {
      headers: { Range: `bytes=${String(firstSize)}-` },
    });
    expect(res.status).toBe(206);
    const parsed: unknown = JSON.parse(await res.text());
    expect(parsed).toMatchObject({ name: "x" });
  });

  test.each(["bytes=abc-", "bytes=-500", "bytes 0-", "bytes=0-100"])(
    "malformed Range %s is 400, not silently ignored",
    async (header) => {
      const { runsDir, base } = await fixture();
      await writeRun(runsDir, "alpha");
      const res = await fetch(`${base}/runs/alpha.jsonl`, { headers: { Range: header } });
      expect(res.status).toBe(400);
    },
  );
});

// --- guards ---

describe("guards", () => {
  test("path traversal is 404 and leaks nothing", async () => {
    const { root, base } = await fixture();
    await writeFile(resolve(root, "secret.jsonl"), '{"ts": 1.0, "kind": "log", "event": "secret"}\n');
    const res = await fetch(`${base}/runs/..%2Fsecret.jsonl`);
    expect(res.status).toBe(404);
    expect(await res.text()).not.toContain("secret");
  });

  test("missing run is 404", async () => {
    const { base } = await fixture();
    expect((await fetch(`${base}/runs/nope.jsonl`)).status).toBe(404);
  });

  test("root without dist is 503 with the build hint", async () => {
    const { base } = await fixture();
    const res = await fetch(`${base}/`);
    expect(res.status).toBe(503);
    expect(res.headers.get("Content-Type")).toContain("text/plain");
    expect(await res.text()).toContain("bun run build");
  });

  test("static file is served from dist", async () => {
    const root = await tmp();
    const dist = resolve(root, "dist");
    await mkdir(dist);
    await writeFile(resolve(dist, "index.html"), "<h1>observe</h1>");
    const { base } = await fixture({ dist });
    const res = await fetch(`${base}/`);
    expect(res.status).toBe(200);
    expect(await res.text()).toBe("<h1>observe</h1>");
    expect(res.headers.get("Content-Type")).toContain("text/html");
  });

  test("serve() refuses a missing runs dir", async () => {
    const root = await tmp();
    expect(() =>
      serve({ runsDir: resolve(root, "nope"), distDir: resolve(root, "dist"), port: 0 }),
    ).toThrow(/does not exist/);
  });
});

// --- concurrency ---

describe("concurrency", () => {
  test("an idle keep-alive connection does not block other clients", async () => {
    // Regression: gray dashboard. Browsers park an idle HTTP/1.1 keep-alive
    // connection and fetch assets on others; a single-threaded server serves
    // nothing until the idle one closes.
    const { base } = await fixture();
    const port = Number.parseInt(new URL(base).port, 10);
    const parked = net.createConnection({ host: "127.0.0.1", port });
    try {
      const firstLine = await new Promise<string>((ok, fail) => {
        parked.once("error", fail);
        parked.once("data", (chunk: Buffer) => {
          ok(chunk.toString("utf8"));
        });
        parked.write("GET /runs HTTP/1.1\r\nHost: x\r\nConnection: keep-alive\r\n\r\n");
      });
      expect(firstLine.startsWith("HTTP/1.1 200")).toBe(true);

      const t0 = performance.now();
      const res = await fetch(`${base}/runs`, { signal: AbortSignal.timeout(2000) });
      const body = await res.text();
      const elapsed = performance.now() - t0;
      expect(res.status).toBe(200);
      expect(body).toBe("[]");
      expect(elapsed).toBeLessThan(500);
    } finally {
      parked.destroy();
    }
  });
});

// --- flags ---

describe("--host", () => {
  test("defaults to loopback: /query is unauthenticated, so off-box is opt-in", async () => {
    const root = await tmp();
    expect(parseArgs(["--runs", root]).host).toBe(DEFAULT_HOST);
    expect(isLoopback(DEFAULT_HOST)).toBe(true);
  });

  test("--host is accepted and used verbatim", async () => {
    const root = await tmp();
    expect(parseArgs(["--runs", root, "--host", "0.0.0.0"]).host).toBe("0.0.0.0");
    // ...and it is the case that gets the startup warning.
    expect(isLoopback("0.0.0.0")).toBe(false);
  });

  test("--host with no value is an error, not a silent default", async () => {
    const root = await tmp();
    expect(() => parseArgs(["--runs", root, "--host"])).toThrow("--host needs a value");
  });

  test("the server actually binds the requested host", async () => {
    const root = await tmp();
    const runsDir = resolve(root, "runs");
    await mkdir(runsDir);
    const server = serve({ runsDir, distDir: resolve(root, "dist"), port: 0, host: "127.0.0.1" });
    running.push(server);
    expect(server.hostname).toBe("127.0.0.1");
  });

  test("loopback spellings are recognised; a routable address is not", () => {
    for (const host of ["127.0.0.1", "localhost", "::1", "[::1]"]) {
      expect(isLoopback(host)).toBe(true);
    }
    for (const host of ["0.0.0.0", "192.168.1.5", "::"]) {
      expect(isLoopback(host)).toBe(false);
    }
  });
});
