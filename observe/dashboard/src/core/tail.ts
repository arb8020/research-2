/**
 * Byte-cursor tailer over an HTTP resource that supports Range.
 *
 * Keeps a byte cursor and a partial-line remainder, so a chunk that splits a
 * line mid-JSON never produces a bad parse: the fragment is held until its
 * newline arrives.
 *
 * The tailer yields raw complete lines and nothing else. It does not parse and
 * it does not decide when a run is over — the caller watches for the `run_end`
 * log event and calls `stop()`.
 *
 * One thing it DOES decide: when the server ignores Range and answers a live
 * cursor with a 200, the body is the whole file, not a suffix. The cursor resets
 * — and so must the consumer's log, or it ends up with the prefix twice. That
 * used to be silent, so a mid-stream 200 duplicated every event seen so far.
 * The tailer now says so: a batch carries `kind: "reset"`, and the consumer is
 * obliged to discard what it has before taking the lines.
 */

export type TailState =
  | { readonly status: "connecting" }
  | { readonly status: "live"; readonly cursor: number }
  | { readonly status: "ended"; readonly cursor: number }
  | { readonly status: "error"; readonly reason: string };

/**
 * One delivery of lines.
 *
 * `append` — the lines continue what the consumer already has.
 * `reset`  — the server resent the file from byte zero (a 200 answering a live
 *            cursor). `lines` is the WHOLE file so far: drop prior state first.
 *
 * `generation` counts resets, so a consumer that prefers a comparison to a
 * switch can just watch the number change. It starts at 0.
 */
export type TailBatch =
  | { readonly kind: "append"; readonly generation: number; readonly lines: string[] }
  | { readonly kind: "reset"; readonly generation: number; readonly lines: string[] };

export interface TailOptions {
  readonly url: string;
  /**
   * Called with complete lines (no trailing newline, blanks dropped).
   * A `reset` batch means: discard everything delivered before it.
   */
  readonly onLines: (batch: TailBatch) => void;
  readonly onState: (state: TailState) => void;
  /** Poll period in ms. Default 100 — the contract's instant-feel budget. */
  readonly intervalMs?: number;
  readonly fetchImpl?: typeof fetch;
  /** Schedules a callback for the next paint. Default requestAnimationFrame. */
  readonly schedule?: (cb: () => void) => void;
}

export interface Tailer {
  start(): void;
  stop(): void;
  readonly state: TailState;
}

/**
 * The byte range a 206's Content-Range advertises, or null if it says nothing
 * parseable. `first` and `last` are inclusive, as in RFC 9110.
 */
function parseContentRange(
  contentRange: string | null,
): { readonly first: number; readonly last: number } | null {
  if (contentRange === null) return null;
  const match = /bytes\s+(\d+)-(\d+)/.exec(contentRange);
  const first = match?.[1];
  const last = match?.[2];
  if (first === undefined || last === undefined) return null;
  return { first: Number.parseInt(first, 10), last: Number.parseInt(last, 10) };
}

/**
 * What of a response body the tailer may consume, and where that leaves the cursor.
 *
 * The subtle case this exists for: the file is APPENDED TO while the request is
 * in flight. The server computed Content-Range against the length it saw, then
 * streamed a body that had grown past it — so the body is LONGER than the range
 * it advertises. Taking the whole body while trusting the header's end byte for
 * the cursor puts the two permanently out of step: the surplus bytes are
 * consumed but not counted, so the next request re-fetches them and the
 * consumer sees those lines twice.
 *
 * The fix is to make the header authoritative for both halves at once — the
 * cursor advances to the advertised end, and the surplus is DROPPED. Nothing is
 * lost: the next poll starts exactly where the cursor is and reads those bytes
 * again, which is the whole point of a byte cursor.
 *
 * Content-Range is also authoritative for a different reason: the byte length of
 * decoded text is not the byte length on the wire for non-ASCII content. Without
 * the header we fall back to the UTF-8 encoded length of what we received.
 */
export function consumeBody(args: {
  readonly cursor: number;
  readonly status: number;
  readonly contentRange: string | null;
  readonly text: string;
}): { readonly cursor: number; readonly text: string } {
  const { cursor, status, contentRange, text } = args;
  const range = status === 206 ? parseContentRange(contentRange) : null;

  if (range !== null) {
    const advertised = range.last - range.first + 1;
    const encoded = new TextEncoder().encode(text);
    // The body may be longer than advertised (an append landed mid-request) or,
    // from a server that miscounts, shorter. Consume exactly the overlap.
    const take = Math.min(advertised, encoded.length);
    const kept = encoded.length === take ? text : decodeUtf8Prefix(encoded, take);
    return { cursor: range.first + take, text: kept };
  }

  const byteLength = new TextEncoder().encode(text).length;
  // A 200 means the server ignored Range and resent everything from zero.
  return {
    cursor: status === 200 ? byteLength : cursor + byteLength,
    text,
  };
}

/**
 * The first `byteCount` bytes of `encoded`, decoded as UTF-8.
 *
 * A truncation can land mid-character; `TextDecoder` without `fatal` renders the
 * partial sequence as U+FFFD. That is correct here and self-healing: a split
 * character is necessarily mid-LINE, so the fragment sits in `remainder` and is
 * discarded when the next poll re-reads those same bytes from the cursor and
 * produces the complete line.
 */
function decodeUtf8Prefix(encoded: Uint8Array, byteCount: number): string {
  return new TextDecoder().decode(encoded.subarray(0, byteCount));
}

/**
 * How many bytes a response body advanced the cursor.
 *
 * Retained as the lower-level reading of the headers alone. `consumeBody` is the
 * one the tailer uses, because a cursor is only half the answer when the body
 * and the advertised range disagree.
 */
export function advanceCursor(args: {
  readonly cursor: number;
  readonly status: number;
  readonly contentRange: string | null;
  readonly text: string;
}): number {
  return consumeBody(args).cursor;
}

/**
 * Split a chunk into complete lines plus the leftover partial line.
 *
 * `remainder` is whatever the previous chunk ended with mid-line.
 */
export function splitLines(
  remainder: string,
  chunk: string,
): { readonly lines: string[]; readonly remainder: string } {
  const combined = remainder + chunk;
  const parts = combined.split("\n");
  const tail = parts.pop() ?? "";
  const lines = parts.filter((line) => line.trim().length > 0);
  return { lines, remainder: tail };
}

export function createTailer(options: TailOptions): Tailer {
  const doFetch = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const schedule =
    options.schedule ??
    ((cb: () => void): void => {
      globalThis.requestAnimationFrame(cb);
    });
  const intervalMs = options.intervalMs ?? 100;

  let state: TailState = { status: "connecting" };
  let cursor = 0;
  let remainder = "";
  let timer: ReturnType<typeof setInterval> | null = null;
  let inFlight = false;
  /** Lines waiting for the next paint, so a burst of polls is one render. */
  let pending: string[] = [];
  let flushScheduled = false;
  let stopped = false;
  /** Bumped on every mid-stream 200. Identifies which file-read the lines are from. */
  let generation = 0;
  /**
   * A reset happened while lines were still queued for paint. The flush must
   * carry the reset flag through, or the consumer appends to a log it should
   * have cleared.
   */
  let pendingReset = false;

  function setState(next: TailState): void {
    state = next;
    options.onState(next);
  }

  function flush(): void {
    flushScheduled = false;
    // A reset with no lines still has to be delivered: an emptied file is a
    // real event, and the consumer's log must follow it to empty.
    if (pending.length === 0 && !pendingReset) return;
    const lines = pending;
    const wasReset = pendingReset;
    pending = [];
    pendingReset = false;
    options.onLines(
      wasReset
        ? { kind: "reset", generation, lines }
        : { kind: "append", generation, lines },
    );
  }

  function enqueue(lines: string[], reset: boolean): void {
    if (reset) {
      // Anything queued came from the previous read of the file and is about to
      // be re-delivered by this whole-file body. Drop it rather than ship it twice.
      pending = [];
      pendingReset = true;
    }
    pending.push(...lines);
    if (pending.length === 0 && !pendingReset) return;
    if (flushScheduled) return;
    flushScheduled = true;
    schedule(flush);
  }

  async function poll(): Promise<void> {
    // One request at a time: a slow server must not stack up polls.
    if (inFlight || stopped) return;
    inFlight = true;
    try {
      const headers: Record<string, string> = { "Cache-Control": "no-store" };
      if (cursor > 0) headers["Range"] = `bytes=${String(cursor)}-`;

      const res = await doFetch(options.url, { headers });

      // 416: the cursor is at EOF. Nothing new, still live.
      if (res.status === 416) return;

      if (res.status !== 200 && res.status !== 206) {
        stop();
        setState({
          status: "error",
          reason: `HTTP ${String(res.status)} ${res.statusText}`,
        });
        return;
      }

      const text = await res.text();
      // A 200 answering `Range: bytes=N-` means the server ignored it and the
      // body is the whole file. The line buffer restarts, the cursor restarts,
      // and the consumer is told so it can drop its duplicate prefix.
      const isReset = res.status === 200 && cursor > 0;
      if (isReset) {
        remainder = "";
        generation += 1;
      }

      // The cursor and the bytes actually consumed must agree exactly, or a
      // mid-request append is delivered twice. `consumeBody` decides both.
      const consumed = consumeBody({
        cursor,
        status: res.status,
        contentRange: res.headers.get("Content-Range"),
        text,
      });
      cursor = consumed.cursor;

      const split = splitLines(remainder, consumed.text);
      remainder = split.remainder;
      enqueue(split.lines, isReset);

      if (state.status === "connecting" || state.status === "live") {
        setState({ status: "live", cursor });
      }
    } catch (cause) {
      stop();
      setState({
        status: "error",
        reason: cause instanceof Error ? cause.message : String(cause),
      });
    } finally {
      inFlight = false;
    }
  }

  function start(): void {
    if (timer !== null || stopped) return;
    setState({ status: "connecting" });
    void poll();
    timer = setInterval(() => void poll(), intervalMs);
  }

  function stop(): void {
    stopped = true;
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
    // Deliver anything already read before going quiet.
    flush();
    if (state.status === "connecting" || state.status === "live") {
      setState({ status: "ended", cursor });
    }
  }

  return {
    start,
    stop,
    get state(): TailState {
      return state;
    },
  };
}

/** True for the log event that marks a finished run. */
export function isRunEnd(event: { kind: string; event?: string }): boolean {
  return event.kind === "log" && event.event === "run_end";
}
