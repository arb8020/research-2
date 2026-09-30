import { describe, expect, it } from "vitest";
import { ParseError, parseLine } from "./parse.ts";

const LOG =
  '{"ts": 1789669021.7, "kind": "log", "level": "INFO", "event": "run_start", "logger": "robots.train", "run_id": "bb62023f", "run_name": "smooth-test", "git_sha": "d8153f6", "git_dirty": true, "env_name": "CartPole-v1", "num_iters": 500}';
const METRIC =
  '{"ts": 1789669022.5, "kind": "metric", "name": "wm_loss", "value": 1.595812, "step": 1, "run_id": "bb62023f", "run_name": "smooth-test", "git_sha": "d8153f6", "git_dirty": true}';
const SPAN =
  '{"ts": 1789669022.5, "kind": "span", "span_name": "rollout", "trace_id": "abc", "span_id": "def", "parent_span_id": null, "start_time_unix_nano": 1789669022000000000, "end_time_unix_nano": 1789669022500000000, "duration_ms": 500.0, "status": "ok", "step": 1, "run_id": "bb62023f"}';

describe("parseLine", () => {
  it("parses a log event and lifts its fixed fields", () => {
    const event = parseLine(LOG);
    expect(event.kind).toBe("log");
    if (event.kind !== "log") throw new Error("expected log");
    expect(event.ts).toBe(1789669021.7);
    expect(event.level).toBe("INFO");
    expect(event.event).toBe("run_start");
    expect(event.logger).toBe("robots.train");
  });

  it("parses a metric event", () => {
    const event = parseLine(METRIC);
    if (event.kind !== "metric") throw new Error("expected metric");
    expect(event.name).toBe("wm_loss");
    expect(event.value).toBeCloseTo(1.595812);
    expect(event.attrs["step"]).toBe(1);
  });

  it("parses a span event, including a null parent", () => {
    const event = parseLine(SPAN);
    if (event.kind !== "span") throw new Error("expected span");
    expect(event.spanName).toBe("rollout");
    expect(event.traceId).toBe("abc");
    expect(event.parentSpanId).toBeNull();
    expect(event.durationMs).toBe(500);
    expect(event.status).toBe("ok");
    expect(event.startTimeUnixNano).toBe(1789669022000000000);
  });

  it("preserves extra attrs, including static fields", () => {
    const event = parseLine(LOG);
    expect(event.attrs).toMatchObject({
      run_id: "bb62023f",
      run_name: "smooth-test",
      git_sha: "d8153f6",
      git_dirty: true,
      env_name: "CartPole-v1",
      num_iters: 500,
    });
  });

  /**
   * `git_sha`/`git_dirty` are static_fields, so they land in `attrs` — and a
   * producer with no git now writes them as JSON null rather than the old
   * `"unknown"`/`false` lie. A null attr must survive parsing as null, not be
   * dropped or coerced, because "provenance unavailable" is the fact being
   * recorded. The golden fixture has real values, so this is its null twin.
   */
  it("keeps null provenance attrs as null, on every kind", () => {
    const lines = [
      '{"ts": 1, "kind": "log", "level": "INFO", "event": "run_start", "logger": "robots.train", "run_id": "r1", "run_name": "n", "git_sha": null, "git_dirty": null}',
      '{"ts": 2, "kind": "metric", "name": "wm_loss", "value": 0.5, "step": 1, "git_sha": null, "git_dirty": null}',
      '{"ts": 3, "kind": "span", "span_name": "rollout", "trace_id": "a", "span_id": "b", "parent_span_id": null, "start_time_unix_nano": 1, "end_time_unix_nano": 2, "duration_ms": 1, "status": "ok", "git_sha": null, "git_dirty": null}',
    ];
    for (const line of lines) {
      const event = parseLine(line);
      expect(event.attrs["git_sha"], line).toBeNull();
      expect(event.attrs["git_dirty"], line).toBeNull();
      // Present-and-null, not absent: the keys must still be there.
      expect(Object.keys(event.attrs), line).toContain("git_sha");
      expect(Object.keys(event.attrs), line).toContain("git_dirty");
    }
  });

  it("keeps nested attr objects and arrays", () => {
    const event = parseLine(
      '{"ts": 1, "kind": "log", "level": "INFO", "event": "cfg", "logger": "x", "cfg": {"a": [1, 2, null]}}',
    );
    expect(event.attrs["cfg"]).toEqual({ a: [1, 2, null] });
  });

  it("does not put fixed fields into attrs", () => {
    const event = parseLine(METRIC);
    expect(event.attrs["name"]).toBeUndefined();
    expect(event.attrs["value"]).toBeUndefined();
    expect(event.attrs["ts"]).toBeUndefined();
    expect(event.attrs["kind"]).toBeUndefined();
  });

  it("throws on an unknown kind", () => {
    expect(() => parseLine('{"ts": 1, "kind": "trace"}')).toThrowError(
      ParseError,
    );
    expect(() => parseLine('{"ts": 1, "kind": "trace"}')).toThrowError(
      /unknown kind "trace"/,
    );
  });

  it("throws when kind is absent", () => {
    expect(() => parseLine('{"ts": 1, "level": "INFO"}')).toThrowError(
      /missing required field `kind`/,
    );
  });

  it.each([
    ["log missing event", '{"ts": 1, "kind": "log", "level": "INFO"}', "event"],
    ["log missing level", '{"ts": 1, "kind": "log", "event": "x"}', "level"],
    // `logger` is REQUIRED on a log line: DESIGN.md lists it in the log shape
    // and stdlib logging cannot emit a record without one. It used to be read
    // as optional, which let a malformed line through as `logger: null`.
    [
      "log missing logger",
      '{"ts": 1, "kind": "log", "level": "INFO", "event": "x"}',
      "logger",
    ],
    [
      "log with a null logger",
      '{"ts": 1, "kind": "log", "level": "INFO", "event": "x", "logger": null}',
      "logger",
    ],
    ["metric missing value", '{"ts": 1, "kind": "metric", "name": "a"}', "value"],
    ["metric missing name", '{"ts": 1, "kind": "metric", "value": 1}', "name"],
    ["metric missing ts", '{"kind": "metric", "name": "a", "value": 1}', "ts"],
    [
      "span missing span_id",
      '{"ts": 1, "kind": "span", "span_name": "r", "trace_id": "a", "parent_span_id": null, "start_time_unix_nano": 1, "end_time_unix_nano": 2, "duration_ms": 1, "status": "ok"}',
      "span_id",
    ],
    [
      "span missing parent_span_id",
      '{"ts": 1, "kind": "span", "span_name": "r", "trace_id": "a", "span_id": "d", "start_time_unix_nano": 1, "end_time_unix_nano": 2, "duration_ms": 1, "status": "ok"}',
      "parent_span_id",
    ],
  ])("throws on %s", (_label, line, field) => {
    expect(() => parseLine(line)).toThrowError(ParseError);
    expect(() => parseLine(line)).toThrowError(new RegExp(`\`${field}\``));
  });

  it("throws on a bad span status rather than defaulting", () => {
    const line = SPAN.replace('"status": "ok"', '"status": "OK"');
    expect(() => parseLine(line)).toThrowError(/`status`/);
  });

  it("throws on a wrongly-typed field", () => {
    expect(() =>
      parseLine('{"ts": 1, "kind": "metric", "name": "a", "value": "1.0"}'),
    ).toThrowError(/expected a finite number, got string/);
  });

  it("throws on invalid JSON and on a non-object line", () => {
    expect(() => parseLine("{not json")).toThrowError(/invalid JSON/);
    expect(() => parseLine("[1,2]")).toThrowError(/expected a JSON object/);
  });

  it("reports the offending line on the error", () => {
    try {
      parseLine('{"ts": 1, "kind": "nope"}');
      throw new Error("should have thrown");
    } catch (cause) {
      if (!(cause instanceof ParseError)) throw cause;
      expect(cause.line).toBe('{"ts": 1, "kind": "nope"}');
      expect(cause.reason).toMatch(/unknown kind/);
    }
  });
});

describe("parseLine — artifacts", () => {
  const ARTIFACT =
    '{"ts": 1789669024.8, "kind": "artifact", "name": "rollout", "mime": "application/x-trajectory+json", "payload": {"env": "CartPole-v1", "obs": [[0, 0, 0, 0]], "actions": [], "rewards": []}, "run_id": "r1", "step": 3}';

  it("lifts name and mime and keeps the payload untyped", () => {
    const event = parseLine(ARTIFACT);
    if (event.kind !== "artifact") throw new Error("expected artifact");
    expect(event.ts).toBe(1789669024.8);
    expect(event.name).toBe("rollout");
    expect(event.mime).toBe("application/x-trajectory+json");
    expect(event.payload).toEqual({
      env: "CartPole-v1",
      obs: [[0, 0, 0, 0]],
      actions: [],
      rewards: [],
    });
    // step and static fields are attrs, exactly as on every other kind.
    expect(event.attrs).toEqual({ run_id: "r1", step: 3 });
  });

  it("accepts any JSON value as a payload, null included", () => {
    for (const raw of ["null", "0", '"text"', "[1,2]", "false"]) {
      const line = `{"ts": 1, "kind": "artifact", "name": "a", "mime": "application/json", "payload": ${raw}}`;
      const event = parseLine(line);
      if (event.kind !== "artifact") throw new Error("expected artifact");
      expect(event.payload).toEqual(JSON.parse(raw));
    }
  });

  it.each([
    ["absent payload", '{"ts": 1, "kind": "artifact", "name": "a", "mime": "application/json"}', "payload"],
    ["missing name", '{"ts": 1, "kind": "artifact", "mime": "application/json", "payload": {}}', "name"],
    ["missing mime", '{"ts": 1, "kind": "artifact", "name": "a", "payload": {}}', "mime"],
    ["missing ts", '{"kind": "artifact", "name": "a", "mime": "application/json", "payload": {}}', "ts"],
    [
      "non-string mime",
      '{"ts": 1, "kind": "artifact", "name": "a", "mime": 7, "payload": {}}',
      "mime",
    ],
  ])("throws on %s", (_label, line, field) => {
    expect(() => parseLine(line)).toThrowError(ParseError);
    expect(() => parseLine(line)).toThrowError(new RegExp(`\`${field}\``));
  });
});
