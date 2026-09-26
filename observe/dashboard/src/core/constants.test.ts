/**
 * Run constants are a property of the DATA, not a list of field names.
 *
 * The golden fixture is the spec here: it is stamped with the four
 * `static_fields` the contract names, so those four — and only those — are what
 * a correct implementation finds in it. The test never mentions them as an
 * input, only as the expected output, which is the whole point of the change.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  createRunConstants,
  extendRunConstants,
  runConstants,
} from "./constants.ts";
import type { Event, Metric } from "./events.ts";
import { parseLine } from "./parse.ts";
import { splitLines } from "./tail.ts";

const path = fileURLToPath(new URL("./__fixtures__/golden.jsonl", import.meta.url));

function goldenEvents(): Event[] {
  const { lines } = splitLines("", readFileSync(path, "utf8"));
  return lines.map((line) => parseLine(line));
}

function metric(name: string, value: number, attrs: Metric["attrs"]): Metric {
  return { kind: "metric", ts: 0, name, value, attrs };
}

function sorted(keys: ReadonlySet<string>): string[] {
  return [...keys].sort();
}

/** The four `static_fields` golden.py stamps — asserted, never supplied. */
const GOLDEN_CONSTANTS = ["git_dirty", "git_sha", "run_id", "run_name"];

describe("runConstants", () => {
  it("finds exactly the static fields in the golden fixture", () => {
    expect(sorted(runConstants(goldenEvents()))).toEqual(GOLDEN_CONSTANTS);
  });

  /**
   * The regression the hardcoded name list could not express: a run whose
   * git_sha changes mid-file (a resume, a rebuild) must SHOW git_sha, because it
   * is now a distinguishing fact about each row.
   */
  it("drops a key that varies — one different git_sha and it leaves", () => {
    const events = goldenEvents();
    const first = events[0];
    if (first === undefined) throw new Error("golden fixture is empty");

    const divergent: Event = {
      ...first,
      attrs: { ...first.attrs, git_sha: "deadbee" },
    };

    const keys = runConstants([...events, divergent]);
    expect(keys.has("git_sha")).toBe(false);
    // The rest are untouched: one varying key does not disqualify its neighbours.
    expect(sorted(keys)).toEqual(
      GOLDEN_CONSTANTS.filter((key) => key !== "git_sha"),
    );
  });

  it("returns nothing for an empty log", () => {
    expect(sorted(runConstants([]))).toEqual([]);
  });

  /**
   * A key carried by only some events is a distinguishing attr, not a run
   * constant — even though every event that has it agrees on the value.
   */
  it("does not call a partially-present key constant", () => {
    const keys = runConstants([
      metric("a", 1, { run_id: "r", step: 1 }),
      metric("a", 2, { run_id: "r" }),
    ]);
    expect(sorted(keys)).toEqual(["run_id"]);
  });

  it("compares structurally, so key order in a nested attr is not a variation", () => {
    const keys = runConstants([
      metric("a", 1, { cfg: { lr: 0.1, bs: 32 } }),
      metric("a", 2, { cfg: { bs: 32, lr: 0.1 } }),
    ]);
    expect(keys.has("cfg")).toBe(true);
  });

  it("sees through to nested differences", () => {
    const keys = runConstants([
      metric("a", 1, { cfg: { lr: 0.1 } }),
      metric("a", 2, { cfg: { lr: 0.2 } }),
    ]);
    expect(keys.has("cfg")).toBe(false);
  });
});

describe("extendRunConstants", () => {
  /**
   * The incremental form is what the UI actually runs as a run streams in. It
   * must agree with the one-shot form for EVERY split of the same log, which is
   * the monotonicity property the module claims.
   */
  it("folding the golden fixture in batches equals the one-shot result", () => {
    const events = goldenEvents();
    const oneShot = sorted(runConstants(events));

    for (const split of [1, 2, 5, events.length - 1]) {
      const state = createRunConstants();
      extendRunConstants(state, events.slice(0, split));
      const keys = extendRunConstants(state, events.slice(split));
      expect(sorted(keys), `split at ${String(split)}`).toEqual(oneShot);
    }
  });

  /** Once a key varies it is gone for good, even if later events agree again. */
  it("a key that varied never comes back", () => {
    const state = createRunConstants();
    extendRunConstants(state, [metric("a", 1, { git_sha: "aaa" })]);
    expect(extendRunConstants(state, [metric("a", 2, { git_sha: "bbb" })]).has("git_sha")).toBe(
      false,
    );
    // Agreeing with the ORIGINAL value again must not resurrect it.
    expect(extendRunConstants(state, [metric("a", 3, { git_sha: "aaa" })]).has("git_sha")).toBe(
      false,
    );
  });
});
