import { describe, expect, it, vi } from "vitest";
import { advanceCursor, consumeBody, createTailer, splitLines } from "./tail.ts";
import { at } from "./test-utils.ts";
import { parseLine } from "./parse.ts";

describe("splitLines", () => {
  it("yields complete lines and holds the partial tail", () => {
    const a = splitLines("", '{"a":1}\n{"b":2}\n{"c":');
    expect(a.lines).toEqual(['{"a":1}', '{"b":2}']);
    expect(a.remainder).toBe('{"c":');
  });

  it("stitches a line split mid-JSON across chunks", () => {
    const first = splitLines("", '{"ts": 1, "kind": "metric", "name": "wm');
    expect(first.lines).toEqual([]);
    const second = splitLines(
      first.remainder,
      '_loss", "value": 0.5}\n{"ts": 2, "kind"',
    );
    expect(second.lines).toHaveLength(1);
    const event = parseLine(at(second.lines, 0, "stitched line"));
    expect(event.kind).toBe("metric");
    if (event.kind !== "metric") throw new Error("expected metric");
    expect(event.name).toBe("wm_loss");
    expect(second.remainder).toBe('{"ts": 2, "kind"');
  });

  it("survives a split on the newline boundary itself", () => {
    const a = splitLines("", '{"a":1}');
    expect(a.lines).toEqual([]);
    const b = splitLines(a.remainder, "\n");
    expect(b.lines).toEqual(['{"a":1}']);
    expect(b.remainder).toBe("");
  });

  it("splits one byte at a time without losing content", () => {
    const source = '{"a":1}\n{"b":2}\n{"c":3}\n';
    let remainder = "";
    const all: string[] = [];
    for (const char of source) {
      const step = splitLines(remainder, char);
      remainder = step.remainder;
      all.push(...step.lines);
    }
    expect(all).toEqual(['{"a":1}', '{"b":2}', '{"c":3}']);
    expect(remainder).toBe("");
  });

  it("drops blank and whitespace-only lines", () => {
    const result = splitLines("", '{"a":1}\n\n   \n{"b":2}\n');
    expect(result.lines).toEqual(['{"a":1}', '{"b":2}']);
  });
});

describe("advanceCursor", () => {
  /**
   * Content-Range fixes WHERE the consumed bytes start, and the cursor lands at
   * the end of what was actually consumed.
   *
   * This used to read `.toBe(200)` — the header's end byte, regardless of how
   * much body arrived. That is the bug `consumeBody` fixes: a 7-byte body
   * advanced the cursor 100 bytes, so 93 bytes were skipped unread. The cursor
   * and the bytes taken must agree, so a body shorter than its range advances
   * only by the body.
   */
  it("starts from Content-Range but advances only by the bytes consumed", () => {
    expect(
      advanceCursor({
        cursor: 100,
        status: 206,
        contentRange: "bytes 100-199/500",
        text: "ignored",
      }),
    ).toBe(107);
  });

  /** A full-length body does advance to the advertised end. */
  it("advances to the advertised end when the body fills the range", () => {
    expect(
      advanceCursor({
        cursor: 100,
        status: 206,
        contentRange: "bytes 100-109/500",
        text: "0123456789",
      }),
    ).toBe(110);
  });

  it("falls back to encoded byte length on a 206 without Content-Range", () => {
    expect(
      advanceCursor({ cursor: 10, status: 206, contentRange: null, text: "abcd" }),
    ).toBe(14);
  });

  it("counts UTF-8 bytes, not code units", () => {
    expect(
      advanceCursor({ cursor: 0, status: 200, contentRange: null, text: "é→" }),
    ).toBe(5);
  });

  it("resets to the body length on a 200 (Range ignored)", () => {
    expect(
      advanceCursor({ cursor: 999, status: 200, contentRange: null, text: "abc" }),
    ).toBe(3);
  });
});

/** Reads the Range header out of a plain-object headers bag. */
function readRange(init: RequestInit | undefined): string | null {
  const headers: unknown = init?.headers;
  if (typeof headers !== "object" || headers === null) return null;
  if (Array.isArray(headers)) return null;
  for (const [key, value] of Object.entries(headers)) {
    if (key.toLowerCase() === "range" && typeof value === "string") return value;
  }
  return null;
}

/** A fake server that hands out slices of a growing buffer. */
function fakeServer(chunks: readonly string[]): {
  fetchImpl: typeof fetch;
  advance: () => void;
} {
  let revealed = 0;
  let index = 0;
  const encoder = new TextEncoder();

  function advance(): void {
    if (index < chunks.length) {
      revealed += encoder.encode(chunks[index] ?? "").length;
      index += 1;
    }
  }

  const full = (): string => chunks.slice(0, index).join("");

  const fetchImpl = vi.fn(
    (_url: string | URL | Request, init?: RequestInit): Promise<Response> => {
      const rangeHeader = readRange(init);
      const body = full();
      const bytes = encoder.encode(body);
      let start = 0;
      if (rangeHeader !== null) {
        const match = /bytes=(\d+)-/.exec(rangeHeader);
        if (match?.[1] !== undefined) start = Number.parseInt(match[1], 10);
      }
      if (start >= bytes.length && start > 0) {
        return Promise.resolve(new Response(null, { status: 416 }));
      }
      const slice = bytes.slice(start);
      const text = new TextDecoder().decode(slice);
      const status = start > 0 ? 206 : 200;
      const headers: Record<string, string> = {};
      if (status === 206) {
        headers["Content-Range"] = `bytes ${String(start)}-${String(
          bytes.length - 1,
        )}/${String(bytes.length)}`;
      }
      return Promise.resolve(new Response(text, { status, headers }));
    },
  );

  void revealed;
  return { fetchImpl, advance };
}

/**
 * A 206 whose body is LONGER than its Content-Range says.
 *
 * This is what a real append-while-serving looks like: the server sizes the
 * range against the file it saw, then streams a file that has since grown. The
 * header is authoritative, so the surplus must be dropped — consumed bytes and
 * the cursor have to agree exactly, or the next request re-reads bytes the
 * consumer already took and duplicates those lines.
 */
describe("consumeBody", () => {
  it("drops the surplus when the body overruns the advertised range", () => {
    const advertised = "a".repeat(100);
    const surplus = "b".repeat(20);
    const result = consumeBody({
      cursor: 0,
      status: 206,
      contentRange: "bytes 0-99/100",
      text: advertised + surplus,
    });
    expect(result.text).toBe(advertised);
    expect(result.cursor).toBe(100);
  });

  it("consumes a body that matches its range untouched", () => {
    const result = consumeBody({
      cursor: 50,
      status: 206,
      contentRange: "bytes 50-59/60",
      text: "0123456789",
    });
    expect(result.text).toBe("0123456789");
    expect(result.cursor).toBe(60);
  });

  /** A short body is the server miscounting; consume what actually arrived. */
  it("consumes only what arrived when the body is shorter than advertised", () => {
    const result = consumeBody({
      cursor: 0,
      status: 206,
      contentRange: "bytes 0-99/100",
      text: "short",
    });
    expect(result.text).toBe("short");
    expect(result.cursor).toBe(5);
  });

  /** Counted in BYTES, not code units — the reason the header is preferred. */
  it("truncates on a byte boundary for multi-byte content", () => {
    // "é" is 2 bytes in UTF-8, so 3 of them are 6 bytes.
    const result = consumeBody({
      cursor: 0,
      status: 206,
      contentRange: "bytes 0-3/6",
      text: "ééé",
    });
    expect(result.cursor).toBe(4);
    expect(new TextEncoder().encode(result.text).length).toBe(4);
  });

  it("falls back to the body length with no Content-Range", () => {
    expect(
      consumeBody({ cursor: 10, status: 206, contentRange: null, text: "abcde" }),
    ).toEqual({ cursor: 15, text: "abcde" });
  });

  it("treats a 200 as the whole file from zero", () => {
    expect(
      consumeBody({ cursor: 99, status: 200, contentRange: null, text: "abcde" }),
    ).toEqual({ cursor: 5, text: "abcde" });
  });
});

describe("createTailer", () => {
  it("reads a file incrementally and never emits a partial line", async () => {
    // The second chunk deliberately splits a JSON object.
    const server = fakeServer([
      '{"ts":1,"kind":"metric","name":"a","value":1}\n{"ts":2,"kind":"met',
      'ric","name":"a","value":2}\n',
    ]);
    const received: string[] = [];
    const states: string[] = [];

    const tailer = createTailer({
      url: "/runs/x.jsonl",
      fetchImpl: server.fetchImpl,
      intervalMs: 1,
      schedule: (cb) => {
        cb();
      },
      onLines: (batch) => received.push(...batch.lines),
      onState: (state) => states.push(state.status),
    });

    server.advance();
    tailer.start();
    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    });
    // Only the complete line is out; the fragment is still buffered.
    expect(received[0]).toBe('{"ts":1,"kind":"metric","name":"a","value":1}');

    server.advance();
    await vi.waitFor(() => {
      expect(received).toHaveLength(2);
    });
    expect(parseLine(at(received, 1, "received line")).kind).toBe("metric");

    tailer.stop();
    expect(states).toContain("connecting");
    expect(states).toContain("live");
    expect(tailer.state.status).toBe("ended");
  });

  /**
   * The end-to-end version of the overrun: the tailer must deliver exactly the
   * advertised bytes' lines, leave the cursor at the advertised end, and then
   * pick the rest up on the next poll — with no line delivered twice.
   *
   * Before the fix the tailer took the whole body but set the cursor from the
   * header, so the surplus line was delivered here AND again on the next poll.
   */
  it("drops bytes a 206 over-delivers and re-reads them on the next poll", async () => {
    const first = '{"ts":1,"kind":"metric","name":"a","value":1}\n';
    const second = '{"ts":2,"kind":"metric","name":"a","value":2}\n';
    const firstBytes = new TextEncoder().encode(first).length;
    const total = firstBytes + new TextEncoder().encode(second).length;

    const ranges: (string | null)[] = [];
    let call = 0;
    /**
     * Until released, every poll after the first answers 416 ("nothing new").
     * Without this gate the 1ms poll loop delivers the second line before the
     * first assertion runs, and the test could not tell "dropped and re-read"
     * apart from "delivered twice".
     */
    let releaseRest = false;

    const fetchImpl = vi.fn(
      (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
        const headers = new Headers(init?.headers);
        ranges.push(headers.get("Range"));
        call += 1;

        // Poll 1: the server advertises only the first line but the body has
        // already grown to include the second — the append landed mid-request.
        if (call === 1) {
          return Promise.resolve(
            new Response(first + second, {
              status: 206,
              headers: {
                "Content-Range": `bytes 0-${String(firstBytes - 1)}/${String(firstBytes)}`,
              },
            }),
          );
        }

        if (!releaseRest) {
          return Promise.resolve(new Response(null, { status: 416 }));
        }

        // Then behave like the real server: serve the suffix from the requested
        // offset, and 416 once the cursor has reached EOF. Serving the same
        // suffix unconditionally would re-deliver it on every 1ms poll.
        const from = /bytes=(\d+)-/.exec(headers.get("Range") ?? "")?.[1];
        const offset = from === undefined ? 0 : Number.parseInt(from, 10);
        if (offset >= total) {
          return Promise.resolve(new Response(null, { status: 416 }));
        }
        return Promise.resolve(
          new Response(second, {
            status: 206,
            headers: {
              "Content-Range": `bytes ${String(offset)}-${String(total - 1)}/${String(total)}`,
            },
          }),
        );
      },
    );

    const received: string[] = [];
    const tailer = createTailer({
      url: "/runs/x.jsonl",
      fetchImpl,
      intervalMs: 1,
      schedule: (cb) => {
        cb();
      },
      onLines: (batch) => received.push(...batch.lines),
      onState: () => undefined,
    });

    tailer.start();

    // Exactly the advertised range's one line — the surplus was dropped.
    await vi.waitFor(() => {
      expect(received).toHaveLength(1);
    });
    expect(received[0]).toBe(first.trimEnd());
    expect(tailer.state).toEqual({ status: "live", cursor: firstBytes });

    // The next poll asks from the cursor and gets the line that was dropped.
    releaseRest = true;
    await vi.waitFor(() => {
      expect(received).toHaveLength(2);
    });
    expect(received[1]).toBe(second.trimEnd());
    expect(ranges[1]).toBe(`bytes=${String(firstBytes)}-`);

    tailer.stop();
    // The decisive assertion: no line arrived twice.
    expect(received).toEqual([first.trimEnd(), second.trimEnd()]);
  });

  it("goes to error on a bad HTTP status and stops polling", async () => {
    const fetchImpl = vi.fn(() =>
      Promise.resolve(new Response("nope", { status: 500 })),
    );
    const states: string[] = [];
    const tailer = createTailer({
      url: "/runs/missing.jsonl",
      fetchImpl,
      intervalMs: 1,
      schedule: (cb) => {
        cb();
      },
      onLines: () => undefined,
      onState: (state) => states.push(state.status),
    });
    tailer.start();
    await vi.waitFor(() => {
      expect(tailer.state.status).toBe("error");
    });
    const state = tailer.state;
    if (state.status !== "error") throw new Error("expected error");
    expect(state.reason).toContain("500");
    const callsAtError = fetchImpl.mock.calls.length;
    await vi.waitFor(() => {
      expect(fetchImpl.mock.calls.length).toBe(callsAtError);
    });
  });

  it("treats 416 as 'nothing new' and stays live", async () => {
    const server = fakeServer(['{"ts":1,"kind":"log","level":"INFO","event":"a"}\n']);
    const tailer = createTailer({
      url: "/runs/x.jsonl",
      fetchImpl: server.fetchImpl,
      intervalMs: 1,
      schedule: (cb) => {
        cb();
      },
      onLines: () => undefined,
      onState: () => undefined,
    });
    server.advance();
    tailer.start();
    await vi.waitFor(() => {
      expect(tailer.state.status).toBe("live");
    });
    // Several more polls, all 416 now.
    await vi.waitFor(() => {
      expect(server.fetchImpl).toHaveBeenCalled();
    });
    expect(tailer.state.status).toBe("live");
    tailer.stop();
  });

  /**
   * The mid-stream 200 bug. A server that ignores `Range` (a proxy, a restart,
   * a dev static handler) answers a live cursor with the WHOLE file and a 200.
   * The tailer's cursor correctly restarts at zero, but a consumer that simply
   * appends every batch ends up holding the prefix twice.
   *
   * The fix is that the tailer says so. This test drives 206, 206, then a 200
   * carrying the whole file, and asserts the consumer — replaying the batch
   * protocol the way App does — lands on the exact line set, once.
   */
  it("reports a reset when a mid-stream 200 resends the whole file", async () => {
    const LINE_A = '{"ts":1,"kind":"metric","name":"a","value":1}';
    const LINE_B = '{"ts":2,"kind":"metric","name":"a","value":2}';
    const LINE_C = '{"ts":3,"kind":"metric","name":"a","value":3}';

    // Grows a line at a time. Answers 206 for a Range until `ignoreRange` is
    // set, then answers 200 with the entire file — the server that causes the bug.
    let body = `${LINE_A}\n`;
    let ignoreRange = false;
    const statuses: number[] = [];

    const fetchImpl = vi.fn(
      (_url: string | URL | Request, init?: RequestInit): Promise<Response> => {
        const rangeHeader = readRange(init);
        const bytes = new TextEncoder().encode(body);
        if (rangeHeader === null || ignoreRange) {
          statuses.push(200);
          return Promise.resolve(new Response(body, { status: 200 }));
        }
        const match = /bytes=(\d+)-/.exec(rangeHeader);
        const start =
          match?.[1] === undefined ? 0 : Number.parseInt(match[1], 10);
        if (start >= bytes.length) {
          statuses.push(416);
          return Promise.resolve(new Response(null, { status: 416 }));
        }
        statuses.push(206);
        const slice = new TextDecoder().decode(bytes.slice(start));
        return Promise.resolve(
          new Response(slice, {
            status: 206,
            headers: {
              "Content-Range": `bytes ${String(start)}-${String(
                bytes.length - 1,
              )}/${String(bytes.length)}`,
            },
          }),
        );
      },
    );

    // The consumer, exactly as App.tsx behaves: a reset clears before appending.
    const log: string[] = [];
    const kinds: string[] = [];
    const generations: number[] = [];

    const tailer = createTailer({
      url: "/runs/x.jsonl",
      fetchImpl,
      intervalMs: 1,
      schedule: (cb) => {
        cb();
      },
      onLines: (batch) => {
        kinds.push(batch.kind);
        generations.push(batch.generation);
        if (batch.kind === "reset") log.length = 0;
        log.push(...batch.lines);
      },
      onState: () => undefined,
    });

    // 1st poll: no cursor yet, so a 200 with just line A. Not a reset.
    tailer.start();
    await vi.waitFor(() => {
      expect(log).toEqual([LINE_A]);
    });

    // 2nd poll: a 206 suffix carrying line B.
    body = `${LINE_A}\n${LINE_B}\n`;
    await vi.waitFor(() => {
      expect(log).toEqual([LINE_A, LINE_B]);
    });
    expect(statuses).toContain(206);
    expect(kinds).toEqual(["append", "append"]);

    // 3rd poll: the server stops honouring Range and resends everything,
    // including a new line C, as a 200.
    body = `${LINE_A}\n${LINE_B}\n${LINE_C}\n`;
    ignoreRange = true;
    await vi.waitFor(() => {
      expect(kinds).toContain("reset");
    });
    tailer.stop();

    // The whole line set, exactly once each — no duplicated prefix.
    expect(log).toEqual([LINE_A, LINE_B, LINE_C]);
    expect(new Set(log).size).toBe(log.length);
    // The generation advanced, so view surfaces know to remount. Every later
    // poll is another ignored-Range 200 and so another reset — that is correct,
    // and each one re-delivers the same set, which is why the log stays exact.
    expect(generations[0]).toBe(0);
    expect(Math.max(...generations)).toBeGreaterThanOrEqual(1);
  });
});
