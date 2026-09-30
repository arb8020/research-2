/**
 * The boundary. `unknown` JSON in, honest `Event` out, or a throw.
 *
 * No semantic fallbacks: an unknown `kind` or a missing required field is a
 * loud failure, never a skipped line. Pure — no DOM, no React, no I/O.
 */

import type {
  Artifact,
  AttrValue,
  Attrs,
  Event,
  Kind,
  Log,
  Metric,
  Span,
  SpanStatus,
} from "./events.ts";
import { KINDS } from "./events.ts";
import {
  FieldError,
  isRecord,
  requireNullableString,
  requireNumber,
  requireString,
} from "./fields.ts";

export class ParseError extends Error {
  readonly line: string;
  readonly reason: string;

  constructor(line: string, reason: string) {
    super(`${reason} in line: ${truncate(line)}`);
    this.name = "ParseError";
    this.line = line;
    this.reason = reason;
  }
}

function truncate(text: string): string {
  const limit = 200;
  return text.length <= limit ? text : `${text.slice(0, limit)}…`;
}

function isKind(value: unknown): value is Kind {
  return typeof value === "string" && KINDS.some((k) => k === value);
}

function isSpanStatus(value: unknown): value is SpanStatus {
  return value === "ok" || value === "error";
}

/** True for every JSON value. Recursive so nested objects/arrays are honest AttrValues. */
function isAttrValue(value: unknown): value is AttrValue {
  if (value === null) return true;
  const type = typeof value;
  switch (type) {
    case "string":
    case "number":
    case "boolean":
      return true;
    case "object":
      if (Array.isArray(value)) return value.every(isAttrValue);
      if (isRecord(value)) return Object.values(value).every(isAttrValue);
      return false;
    // JSON.parse never produces these, but the type of `typeof` includes them.
    case "bigint":
    case "symbol":
    case "function":
    case "undefined":
      return false;
    default: {
      const exhaustive: never = type;
      return exhaustive;
    }
  }
}

/**
 * Run a field reader, translating its FieldError into this boundary's error type.
 *
 * The readers live in core/fields.ts (one vocabulary, shared with the server and
 * the /runs index); ParseError is what this boundary's callers already catch,
 * and it carries the offending line. So: shared readers, local error type.
 */
function fields<T>(raw: string, read: () => T): T {
  try {
    return read();
  } catch (cause) {
    if (cause instanceof FieldError) throw new ParseError(raw, cause.message);
    throw cause;
  }
}

function fail(
  raw: string,
  field: string,
  expected: string,
  actual: unknown,
): never {
  const actualDesc =
    actual === undefined ? "absent" : `${typeof actual} ${JSON.stringify(actual)}`;
  throw new ParseError(
    raw,
    `field \`${field}\` expected ${expected}, got ${actualDesc}`,
  );
}

/** Everything not in `fixed` becomes an attr. Extra attrs are always preserved. */
function collectAttrs(
  raw: string,
  obj: Record<string, unknown>,
  fixed: readonly string[],
): Attrs {
  const attrs: Record<string, AttrValue> = {};
  for (const [key, value] of Object.entries(obj)) {
    if (fixed.includes(key)) continue;
    if (value === undefined) continue;
    if (!isAttrValue(value)) {
      throw new ParseError(raw, `attr \`${key}\` is not a JSON value`);
    }
    attrs[key] = value;
  }
  return attrs;
}

const LOG_FIXED = ["ts", "kind", "level", "event", "logger"] as const;
const SPAN_FIXED = [
  "ts",
  "kind",
  "span_name",
  "trace_id",
  "span_id",
  "parent_span_id",
  "start_time_unix_nano",
  "end_time_unix_nano",
  "duration_ms",
  "status",
] as const;
const METRIC_FIXED = ["ts", "kind", "name", "value"] as const;
const ARTIFACT_FIXED = ["ts", "kind", "name", "mime", "payload"] as const;

/**
 * A log line. `logger` is REQUIRED, not optional.
 *
 * DESIGN.md lists it inside the `kind: "log"` shape and the Python formatter
 * always writes it (stdlib logging has no way to emit a record without one), so
 * `string | null` was sludge that let a malformed line through quietly.
 */
function parseLog(raw: string, obj: Record<string, unknown>): Log {
  return fields(raw, () => ({
    kind: "log" as const,
    ts: requireNumber(obj, "ts"),
    level: requireString(obj, "level"),
    event: requireString(obj, "event"),
    logger: requireString(obj, "logger"),
    attrs: collectAttrs(raw, obj, LOG_FIXED),
  }));
}

function parseSpan(raw: string, obj: Record<string, unknown>): Span {
  const status = obj["status"];
  if (!isSpanStatus(status)) {
    return fail(raw, "status", '"ok" or "error"', status);
  }
  return fields(raw, () => ({
    kind: "span" as const,
    ts: requireNumber(obj, "ts"),
    spanName: requireString(obj, "span_name"),
    traceId: requireString(obj, "trace_id"),
    spanId: requireString(obj, "span_id"),
    parentSpanId: requireNullableString(obj, "parent_span_id"),
    startTimeUnixNano: requireNumber(obj, "start_time_unix_nano"),
    endTimeUnixNano: requireNumber(obj, "end_time_unix_nano"),
    durationMs: requireNumber(obj, "duration_ms"),
    status,
    attrs: collectAttrs(raw, obj, SPAN_FIXED),
  }));
}

function parseMetric(raw: string, obj: Record<string, unknown>): Metric {
  return fields(raw, () => ({
    kind: "metric" as const,
    ts: requireNumber(obj, "ts"),
    name: requireString(obj, "name"),
    value: requireNumber(obj, "value"),
    attrs: collectAttrs(raw, obj, METRIC_FIXED),
  }));
}

/**
 * An artifact line. `payload` may be ANY JSON value — including `null`, a
 * number, a string — but it must be PRESENT.
 *
 * So the check is `"payload" in obj`, not a truthiness or type test: there is
 * no honest reader in fields.ts for "any JSON value, required", because every
 * reader there narrows to a type and this field deliberately does not narrow.
 * An absent payload is an artifact that says it has content and does not, which
 * is a producer bug and a loud one.
 *
 * `isAttrValue` still gates it: the payload has to survive a JSON round trip.
 */
function parseArtifact(raw: string, obj: Record<string, unknown>): Artifact {
  if (!("payload" in obj)) {
    return fail(raw, "payload", "any JSON value", undefined);
  }
  const payload = obj["payload"];
  if (!isAttrValue(payload)) {
    throw new ParseError(raw, "field `payload` is not a JSON value");
  }
  return fields(raw, () => ({
    kind: "artifact" as const,
    ts: requireNumber(obj, "ts"),
    name: requireString(obj, "name"),
    mime: requireString(obj, "mime"),
    payload,
    attrs: collectAttrs(raw, obj, ARTIFACT_FIXED),
  }));
}

/**
 * Parse one JSONL line into an Event.
 *
 * @throws ParseError on malformed JSON, a non-object line, a missing or
 *   absent `kind`, an unrecognised `kind`, or a missing/ill-typed required field.
 */
export function parseLine(raw: string): Event {
  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    throw new ParseError(raw, `invalid JSON (${detail})`);
  }

  if (!isRecord(json)) {
    throw new ParseError(raw, "expected a JSON object");
  }

  const kind = json["kind"];
  if (kind === undefined) {
    throw new ParseError(raw, "missing required field `kind`");
  }
  if (!isKind(kind)) {
    throw new ParseError(
      raw,
      `unknown kind ${JSON.stringify(kind)} (expected one of ${KINDS.join(", ")})`,
    );
  }

  switch (kind) {
    case "log":
      return parseLog(raw, json);
    case "span":
      return parseSpan(raw, json);
    case "metric":
      return parseMetric(raw, json);
    case "artifact":
      return parseArtifact(raw, json);
    default: {
      const exhaustive: never = kind;
      return exhaustive;
    }
  }
}
