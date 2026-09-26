/**
 * The raw-table / terminal formatting of each kind.
 *
 * Written when `artifact` was added: the terminal line's KIND column was a
 * hardcoded `padEnd(6)` that fit "METRIC" exactly, so an 8-character kind
 * jagged every row after it. The width is now derived from KINDS, and this is
 * the test that says so.
 */

import { describe, expect, it } from "vitest";
import { KINDS } from "../core/events.ts";
import type { Artifact, Event, Metric } from "../core/events.ts";
import { summarizeAttrs, terminalLine } from "./eventlines.ts";

const NOTHING_CONSTANT: ReadonlySet<string> = new Set<string>();

const ARTIFACT: Artifact = {
  kind: "artifact",
  ts: 1789669024.8,
  name: "rollout",
  mime: "application/x-trajectory+json",
  payload: { env: "CartPole-v1", obs: [[0, 0, 0, 0]], actions: [], rewards: [] },
  attrs: { step: 3 },
};

const METRIC: Metric = {
  kind: "metric",
  ts: 1789669024.8,
  name: "wm_loss",
  value: 1.25,
  attrs: { step: 3 },
};

describe("summarizeAttrs", () => {
  it("shows an artifact's mime, not its payload", () => {
    const summary = summarizeAttrs(ARTIFACT, NOTHING_CONSTANT);
    expect(summary).toContain("application/x-trajectory+json");
    expect(summary).toContain("step=3");
    // A trajectory flattened into a table cell is noise; the renderer owns it.
    expect(summary).not.toContain("obs");
    expect(summary).not.toContain("CartPole");
  });
});

describe("terminalLine", () => {
  it("renders ARTIFACT  name  mime  attrs", () => {
    const line = terminalLine(ARTIFACT, NOTHING_CONSTANT);
    expect(line).toContain("ARTIFACT");
    expect(line).toMatch(
      /ARTIFACT\s+rollout\s+application\/x-trajectory\+json\s+step=3/,
    );
  });

  it("aligns the name column across every kind, including the longest", () => {
    // The regression: with padEnd(6), "ARTIFACT" pushed its name 2 chars right
    // of every other kind's, so the column was no longer a column.
    // Measured, not derived: where does the NAME actually begin in the string?
    // Both events share one `ts`, so the timestamp prefix is the same width and
    // the only thing that can move the name is the KIND column's padding.
    const events: readonly Event[] = [ARTIFACT, METRIC];
    const names = ["rollout", "wm_loss"];
    const nameColumns = events.map((event, index) =>
      terminalLine(event, NOTHING_CONSTANT).indexOf(names[index] ?? ""),
    );
    expect(nameColumns.every((column) => column > 0)).toBe(true);
    expect(new Set(nameColumns).size, `names start at ${nameColumns.join(" vs ")}`).toBe(
      1,
    );
    // And that column is exactly the longest kind plus the two-space gutter.
    const width = Math.max(...KINDS.map((kind) => kind.length));
    const tsWidth = terminalLine(ARTIFACT, NOTHING_CONSTANT).indexOf("ARTIFACT");
    expect(nameColumns[0]).toBe(tsWidth + width + 2);
  });
});
