/**
 * The cross-language contract test. `golden.jsonl` is produced by
 * observe/scripts/golden.py and committed; if Python's on-disk shape drifts
 * from DESIGN.md, this suite is what fails.
 *
 * Also the end-to-end check that a view has real data to render: every line
 * parses, the projections come out right, and the file survives being
 * delivered in arbitrary byte-sized chunks (the tailer's real behaviour).
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Attrs, Event, Kind, Metric } from "./events.ts";
import { parseLine } from "./parse.ts";
import { splitLines } from "./tail.ts";
import { toSeries } from "./series.ts";

const path = fileURLToPath(new URL("./__fixtures__/golden.jsonl", import.meta.url));
const raw = readFileSync(path, "utf8");

/** Fields that exist only on `kind: "log"` (DESIGN.md "On disk"). */
const LOG_ONLY_FIELDS = ["level", "event", "logger"] as const;

function isMetric(event: Event): event is Metric {
  return event.kind === "metric";
}

function parseAll(text: string): Event[] {
  const { lines } = splitLines("", text);
  return lines.map(parseLine);
}

function countKinds(events: Event[]): Record<Kind, number> {
  const counts: Record<Kind, number> = { log: 0, span: 0, metric: 0, artifact: 0 };
  for (const event of events) counts[event.kind] += 1;
  return counts;
}

/** Recursively true if any object in the tree carries `key`. */
function hasKeyAnywhere(value: unknown, key: string): boolean {
  if (Array.isArray(value)) return value.some((item) => hasKeyAnywhere(item, key));
  if (typeof value === "object" && value !== null) {
    const record: Record<string, unknown> = { ...value };
    if (key in record) return true;
    return Object.values(record).some((item) => hasKeyAnywhere(item, key));
  }
  return false;
}

describe("golden.jsonl", () => {
  it("parses every line without throwing", () => {
    expect(() => parseAll(raw)).not.toThrow();
  });

  const events = parseAll(raw);

  it("has the exact kind counts the generator emits", () => {
    expect(countKinds(events)).toEqual({ log: 3, span: 2, metric: 7, artifact: 1 });
  });

  it("opens with run_start and closes with run_end", () => {
    const first = events[0];
    const last = events[events.length - 1];
    expect(first?.kind === "log" && first.event).toBe("run_start");
    expect(last?.kind === "log" && last.event).toBe("run_end");
  });

  it("names both spans and keeps parent_span_id present (null for a root)", () => {
    const spans = events.filter((event) => event.kind === "span");
    expect(spans.map((span) => span.spanName)).toEqual([
      "robots.rollout",
      "robots.eval",
    ]);
    expect(spans[0]?.parentSpanId).toBe("dddddddddddddddd");
    expect(spans[1]?.parentSpanId).toBeNull();
  });

  it("carries the error span's status and error fields as the contract says", () => {
    const failed = events.find(
      (event) => event.kind === "span" && event.status === "error",
    );
    if (failed?.kind !== "span") throw new Error("expected an error span");
    expect(failed.spanName).toBe("robots.eval");
    expect(failed.attrs["error"]).toBe("boom");
    expect(failed.attrs["error_type"]).toBe("ValueError");
  });

  it("never puts level/event/logger on a metric or span, at any depth", () => {
    for (const event of events) {
      if (event.kind === "log") continue;
      for (const field of LOG_ONLY_FIELDS) {
        const attrs: Attrs = event.attrs;
        expect(
          hasKeyAnywhere(attrs, field),
          `${event.kind} carries log-only field \`${field}\``,
        ).toBe(false);
      }
    }
  });

  it("never puts level/event/logger on a raw metric/span line either", () => {
    // parse.ts folds unknown top-level keys into attrs, so check the JSON too:
    // this is the assertion that fails if the Python formatter regresses.
    for (const line of raw.split("\n").filter((text) => text.trim() !== "")) {
      const parsed: unknown = JSON.parse(line);
      if (!(typeof parsed === "object" && parsed !== null)) {
        throw new Error("expected an object per line");
      }
      const obj: Record<string, unknown> = { ...parsed };
      if (obj["kind"] === "log") continue;
      for (const field of LOG_ONLY_FIELDS) {
        expect(field in obj, `${String(obj["kind"])} line carries \`${field}\``).toBe(
          false,
        );
      }
    }
  });

  it("projects to the expected metric series on the step axis", () => {
    const { series, unplottable } = toSeries(events.filter(isMetric), "step");
    expect([...series.keys()].sort()).toEqual(["pi_loss", "wm_loss"]);
    expect(series.get("wm_loss")?.length).toBe(3);
    expect(series.get("pi_loss")?.length).toBe(3);
    // The stepless point has no x value on this axis.
    expect(unplottable.map((entry) => entry.metric.name)).toEqual(["wall_clock_s"]);
  });

  it("survives being delivered in arbitrary byte-sized chunks", () => {
    let remainder = "";
    const streamed: Event[] = [];
    for (let i = 0; i < raw.length; i += 7) {
      const step = splitLines(remainder, raw.slice(i, i + 7));
      remainder = step.remainder;
      streamed.push(...step.lines.map(parseLine));
    }
    expect(streamed).toEqual(events);
  });

  it("carries the artifact's mime and an untyped payload, with step as an attr", () => {
    const artifact = events.find((event) => event.kind === "artifact");
    if (artifact?.kind !== "artifact") throw new Error("expected an artifact");
    expect(artifact.name).toBe("rollout");
    expect(artifact.mime).toBe("application/x-trajectory+json");
    expect(artifact.attrs["step"]).toBe(3);
    // `payload` is not a fixed field's business to type — assert its shape from
    // the outside, the way a renderer will.
    expect(artifact.payload).toEqual({
      env: "CartPole-v1",
      obs: [
        [0, 0, 0, 0],
        [0.01, 0.15, -0.02, -0.21],
        [0.02, 0.34, -0.06, -0.52],
        [0.04, 0.53, -0.11, -0.84],
      ],
      actions: [1, 1, 0],
      rewards: [1, 1, 1],
    });
  });

  it("keeps the artifact's payload out of attrs", () => {
    const artifact = events.find((event) => event.kind === "artifact");
    if (artifact?.kind !== "artifact") throw new Error("expected an artifact");
    expect(artifact.attrs["payload"]).toBeUndefined();
    expect(artifact.attrs["mime"]).toBeUndefined();
  });

  it("keeps run_start config and static fields as attrs", () => {
    const first = events[0];
    if (first?.kind !== "log") throw new Error("expected log");
    expect(first.attrs).toMatchObject({
      env_name: "CartPole-v1",
      num_iters: 3,
      run_id: "goldenrun",
      run_name: "golden",
      git_sha: "0000000",
      git_dirty: false,
    });
  });
});
