/**
 * The pure half of the logs drawer: filtering and formatting, shared by both
 * modes.
 *
 * The drawer shows one Event[] two ways — terminal (one mono line per event)
 * and table (columns). They must never disagree about which events are on
 * screen, so the filter lives here once and both modes call it. No React, no
 * DOM.
 */

import { runConstants } from "../core/constants.ts";
import type { Attrs, Event, Kind } from "../core/events.ts";
import { KINDS, eventLabel } from "../core/events.ts";

/** The two shapes the drawer can render the same events in. */
export const LOG_MODES = ["terminal", "table"] as const;

export type LogMode = (typeof LOG_MODES)[number];

export function formatAttrValue(value: Attrs[string]): string {
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === "string") return value;
  if (value === null) return "null";
  if (typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/**
 * The key attrs: anything identical on every event so far is dropped.
 *
 * `constant` is computed from the data (core/constants.ts), not from a list of
 * field names — see that module for why the old hardcoded set was wrong.
 */
export function summarizeAttrs(
  event: Event,
  constant: ReadonlySet<string>,
): string {
  const parts: string[] = [];
  if (event.kind === "metric") parts.push(`value=${formatAttrValue(event.value)}`);
  if (event.kind === "span") {
    parts.push(`${event.durationMs.toFixed(1)}ms`, event.status);
  }
  if (event.kind === "log") parts.push(event.level);
  // The artifact's type, not its payload: a trajectory summarised into a table
  // cell is noise, and the renderer is where a payload belongs.
  if (event.kind === "artifact") parts.push(event.mime);
  for (const [key, value] of Object.entries(event.attrs)) {
    if (constant.has(key)) continue;
    parts.push(`${key}=${formatAttrValue(value)}`);
  }
  return parts.join("  ");
}

export function formatTs(ts: number): string {
  const date = new Date(ts * 1000);
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  const ms = String(date.getMilliseconds()).padStart(3, "0");
  return `${hh}:${mm}:${ss}.${ms}`;
}

/**
 * The single filter both modes use: published prefix, minus hidden kinds.
 *
 * `revision` is the growth signal for the in-place `events` array, so the
 * prefix — not the array's current length — is what has actually been
 * published.
 */
export function visibleEvents(
  events: readonly Event[],
  revision: number,
  hidden: ReadonlySet<Kind>,
): readonly Event[] {
  const published = events.slice(0, revision);
  if (hidden.size === 0) return published;
  return published.filter((event) => !hidden.has(event.kind));
}

/** Which attr keys are constant across the whole published log. */
export function publishedConstants(
  events: readonly Event[],
  revision: number,
): ReadonlySet<string> {
  // Derived from the PUBLISHED events, not the filtered rows: hiding the
  // metric chip must not change which attrs count as run constants.
  return runConstants(events.slice(0, revision));
}

/**
 * Width of the KIND column, derived from the vocabulary rather than typed in.
 *
 * It was a hardcoded 6, which fit "METRIC" exactly and jagged the moment
 * "ARTIFACT" arrived. Computing it from KINDS means adding a kind cannot
 * silently misalign the column again.
 */
const KIND_WIDTH = Math.max(...KINDS.map((kind) => kind.length));

/** One terminal line: `HH:MM:SS.mmm  KIND  name  attrs…`. */
export function terminalLine(
  event: Event,
  constant: ReadonlySet<string>,
): string {
  const attrs = summarizeAttrs(event, constant);
  const head = `${formatTs(event.ts)}  ${event.kind.toUpperCase().padEnd(KIND_WIDTH)}  ${eventLabel(event)}`;
  return attrs === "" ? head : `${head}  ${attrs}`;
}
