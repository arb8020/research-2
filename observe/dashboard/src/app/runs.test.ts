/**
 * The /runs boundary: which run gets opened by default, and what a row may omit.
 */

import { describe, expect, it } from "vitest";
import { RunsError, defaultRun, parseRuns, runLabel } from "./runs.ts";

/** The server's wire shape: newest-started first, unparseable last. */
const NEWEST = {
  file: "newest.jsonl",
  size_bytes: 400,
  started_ts: 300,
  run_id: "r3",
  run_name: "newest",
  git_sha: "ccc",
  git_dirty: false,
};
const OLDER = {
  file: "older.jsonl",
  size_bytes: 200,
  started_ts: 100,
  run_id: "r1",
  run_name: "older",
  git_sha: "aaa",
  git_dirty: true,
};
const BROKEN = {
  file: "broken.jsonl",
  size_bytes: 12,
  error: "bad first line: Unexpected end of JSON input",
};

describe("defaultRun", () => {
  /**
   * The gray-screen bug's back half. The server sorts newest-started first and
   * puts unparseable runs LAST, so `runs[runs.length - 1]` picked either the
   * oldest run or — worse — a run whose header would not parse, which rendered
   * an empty dashboard with the reason invisible.
   */
  it("picks the newest run, which is the first one", () => {
    const runs = parseRuns([NEWEST, OLDER, BROKEN]);
    expect(defaultRun(runs)).toBe("newest.jsonl");
  });

  it("skips a run whose header could not be read", () => {
    const runs = parseRuns([BROKEN, NEWEST, OLDER]);
    expect(defaultRun(runs)).toBe("newest.jsonl");
  });

  it("selects nothing when every run is broken, rather than a blank screen", () => {
    const runs = parseRuns([BROKEN, { ...BROKEN, file: "other.jsonl" }]);
    // null means App shows the error rows instead of tailing an unreadable file.
    expect(defaultRun(runs)).toBeNull();
  });

  it("selects nothing when there are no runs at all", () => {
    expect(defaultRun(parseRuns([]))).toBeNull();
  });
});

describe("parseRuns", () => {
  it("lifts the wire's snake_case into the model", () => {
    const [run] = parseRuns([OLDER]);
    expect(run).toEqual({
      file: "older.jsonl",
      runId: "r1",
      runName: "older",
      gitSha: "aaa",
      gitDirty: true,
      startedTs: 100,
      sizeBytes: 200,
      error: null,
    });
  });

  /**
   * `_git_info` now reports null provenance when there is no git to ask, so the
   * wire carries explicit nulls where it used to carry `"unknown"`/`false`.
   * Both must parse, and neither may become a fake value.
   */
  it("accepts explicit null provenance", () => {
    const [run] = parseRuns([
      { file: "x.jsonl", size_bytes: 1, started_ts: 1, git_sha: null, git_dirty: null },
    ]);
    expect(run?.gitSha).toBeNull();
    expect(run?.gitDirty).toBeNull();
  });

  it("accepts omitted provenance the same way", () => {
    const [run] = parseRuns([{ file: "x.jsonl", size_bytes: 1 }]);
    expect(run?.gitSha).toBeNull();
    expect(run?.gitDirty).toBeNull();
    expect(run?.startedTs).toBeNull();
  });

  it("keeps a broken run's error so the picker can still list it", () => {
    const [run] = parseRuns([BROKEN]);
    expect(run?.error).toContain("bad first line");
  });

  it("throws RunsError when `file` is missing — there is no row without one", () => {
    expect(() => parseRuns([{ size_bytes: 1 }])).toThrowError(RunsError);
  });

  it("throws RunsError on a mistyped field rather than coercing it", () => {
    expect(() => parseRuns([{ file: "x.jsonl", git_sha: 7 }])).toThrowError(
      /git_sha/,
    );
  });

  it("throws RunsError when the payload is not an array", () => {
    expect(() => parseRuns({ runs: [] })).toThrowError(RunsError);
  });
});

describe("runLabel", () => {
  it("omits the sha entirely when provenance is unavailable", () => {
    const [run] = parseRuns([{ file: "x.jsonl", run_name: "n", git_sha: null }]);
    expect(run).toBeDefined();
    if (run === undefined) return;
    // No "· unknown" — an absent sha shows as absent.
    expect(runLabel(run)).toBe("n");
  });

  it("marks a dirty tree with a star", () => {
    const [run] = parseRuns([OLDER]);
    expect(run).toBeDefined();
    if (run === undefined) return;
    expect(runLabel(run)).toBe("older · aaa*");
  });
});
