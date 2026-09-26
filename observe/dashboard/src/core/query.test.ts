import { describe, expect, it } from "vitest";
import { isQueryError, queryUrl, runQuery } from "./query.ts";

/** A fetch that answers every call with one canned response. */
function stubFetch(
  status: number,
  body: unknown,
  opts: { readonly bodyIsNotJson?: boolean } = {},
): typeof globalThis.fetch & { calls: string[] } {
  const calls: string[] = [];
  const fn = (input: RequestInfo | URL): Promise<Response> => {
    calls.push(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    const text = opts.bodyIsNotJson === true ? "<html>not json</html>" : JSON.stringify(body);
    return Promise.resolve(
      new Response(text, { status, headers: { "content-type": "application/json" } }),
    );
  };
  return Object.assign(fn, { calls });
}

const OK_BODY = {
  columns: [
    { name: "step", type: "BIGINT" },
    { name: "value", type: "DOUBLE" },
  ],
  rows: [
    [1, 1.5],
    [2, 1.2],
  ],
  truncated: false,
  limit: 10000,
  ms: 3,
};

describe("queryUrl", () => {
  it("url-encodes the sql", () => {
    expect(queryUrl("SELECT 1 FROM events WHERE name='a'")).toBe(
      "/query?sql=SELECT%201%20FROM%20events%20WHERE%20name%3D'a'",
    );
  });
});

describe("runQuery", () => {
  it("parses a 200 into a QueryResult", async () => {
    const fetch = stubFetch(200, OK_BODY);
    const out = await runQuery("SELECT step, value FROM events", { fetch });
    expect(out.kind).toBe("result");
    if (out.kind !== "result") throw new Error("expected a result");
    expect(out.columns).toEqual(OK_BODY.columns);
    expect(out.rows).toEqual(OK_BODY.rows);
    expect(out.truncated).toBe(false);
    expect(out.limit).toBe(10000);
    expect(out.ms).toBe(3);
    expect(fetch.calls[0]).toContain("/query?sql=");
  });

  it("carries `truncated` through rather than hiding a capped result", async () => {
    const out = await runQuery("SELECT 1", {
      fetch: stubFetch(200, { ...OK_BODY, truncated: true, limit: 2 }),
    });
    if (out.kind !== "result") throw new Error("expected a result");
    expect(out.truncated).toBe(true);
    expect(out.limit).toBe(2);
  });

  it("returns a query-error for 400 with DuckDB's message, and does not throw", async () => {
    const out = await runQuery("SELECT nope", {
      fetch: stubFetch(400, { error: 'Binder Error: column "nope" not found' }),
    });
    expect(out).toEqual({
      kind: "query-error",
      status: 400,
      message: 'Binder Error: column "nope" not found',
    });
    expect(isQueryError(out)).toBe(true);
  });

  it("returns a timeout for 408", async () => {
    const out = await runQuery("SELECT slow", {
      fetch: stubFetch(408, { error: "query exceeded 5000ms" }),
    });
    expect(out).toEqual({ kind: "timeout", status: 408, message: "query exceeded 5000ms" });
  });

  it("returns an http-error for an unexpected status", async () => {
    const out = await runQuery("SELECT 1", { fetch: stubFetch(503, { error: "no store" }) });
    expect(out).toEqual({ kind: "http-error", status: 503, message: "no store" });
  });

  const malformed: [string, unknown][] = [
    ["body is not an object", [1, 2, 3]],
    ["columns missing", { rows: [], truncated: false, limit: 1, ms: 1 }],
    ["a column has no name", { ...OK_BODY, columns: [{ type: "BIGINT" }] }],
    ["rows is not an array", { ...OK_BODY, rows: "nope" }],
    ["a row is not an array", { ...OK_BODY, rows: [{ step: 1, value: 2 }] }],
    ["truncated is not a boolean", { ...OK_BODY, truncated: "no" }],
    ["limit missing", { columns: OK_BODY.columns, rows: [], truncated: false, ms: 1 }],
  ];

  it.each(malformed)("names %s as a malformed-response with a reason", async (_label, body) => {
    const out = await runQuery("SELECT 1", { fetch: stubFetch(200, body) });
    expect(out.kind).toBe("malformed-response");
    if (out.kind !== "malformed-response") throw new Error("expected malformed-response");
    expect(out.reason.length).toBeGreaterThan(0);
  });

  it("reports a row whose width does not match the columns", async () => {
    const out = await runQuery("SELECT 1", {
      // Two columns, a row of one value: the columnar zip would silently
      // produce `value: undefined`, which is exactly the fallback we refuse.
      fetch: stubFetch(200, { ...OK_BODY, rows: [[1]] }),
    });
    if (out.kind !== "malformed-response") throw new Error("expected malformed-response");
    expect(out.reason).toContain("2 values, one per column");
  });

  it("reports a non-JSON body rather than throwing", async () => {
    const out = await runQuery("SELECT 1", {
      fetch: stubFetch(200, null, { bodyIsNotJson: true }),
    });
    if (out.kind !== "malformed-response") throw new Error("expected malformed-response");
    expect(out.reason).toContain("not JSON");
  });

  it("reports a 400 whose body has no `error` string as malformed", async () => {
    const out = await runQuery("SELECT 1", { fetch: stubFetch(400, { oops: 1 }) });
    if (out.kind !== "malformed-response") throw new Error("expected malformed-response");
    expect(out.reason).toContain("status 400");
  });

  it("returns a network-error when fetch itself rejects", async () => {
    const out = await runQuery("SELECT 1", {
      fetch: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    expect(out).toEqual({ kind: "network-error", message: "Failed to fetch" });
  });

  it("rethrows an abort, because a superseded refresh is not a query failure", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(
      runQuery("SELECT 1", {
        signal: controller.signal,
        fetch: () => Promise.reject(new DOMException("aborted", "AbortError")),
      }),
    ).rejects.toThrow(/aborted/);
  });
});
