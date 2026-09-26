/**
 * The shared boundary vocabulary: one set of field readers for every place
 * `unknown` JSON becomes a typed value.
 *
 * Three boundaries existed with three copies of `isRecord` + str/num/bool and
 * three different answers to "what does a missing field mean" — `null` in
 * src/app/runs.ts, `undefined` in server/index.ts, a throw in src/core/parse.ts.
 * The drift was the bug surface, so the readers are unified here and the
 * convention is stated once:
 *
 *   require*   — must be present and well-typed, else throw
 *   nullable*  — must be PRESENT, may be JSON null (e.g. `parent_span_id`)
 *   optional*  — may be absent or null; both read as `null`
 *
 * Callers keep their own error *types* (ParseError, RunsError) by catching
 * FieldError and rewrapping. They do not keep their own readers.
 *
 * Pure: no DOM, no Bun, no I/O. Imported by src/** and server/** alike.
 */

/** What a reader wanted, what it found, and where. `ctx` names the call site. */
export class FieldError extends Error {
  readonly key: string;
  readonly expected: string;
  readonly got: string;
  readonly ctx: string | undefined;

  constructor(args: {
    readonly key: string;
    readonly expected: string;
    readonly got: unknown;
    readonly ctx?: string;
  }) {
    const got = describe(args.got);
    const where = args.ctx === undefined ? "" : ` (${args.ctx})`;
    super(`field \`${args.key}\` expected ${args.expected}, got ${got}${where}`);
    this.name = "FieldError";
    this.key = args.key;
    this.expected = args.expected;
    this.got = got;
    this.ctx = args.ctx;
  }
}

/** How a wrong value is reported: "absent", or its type and JSON form. */
function describe(value: unknown): string {
  if (value === undefined) return "absent";
  return `${typeof value} ${JSON.stringify(value)}`;
}

function fail(
  key: string,
  expected: string,
  got: unknown,
  ctx: string | undefined,
): never {
  throw new FieldError({ key, expected, got, ...(ctx === undefined ? {} : { ctx }) });
}

/** A JSON object — not an array, not null. The gate before any reader. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function requireString(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): string {
  const value = obj[key];
  if (typeof value !== "string") return fail(key, "a string", value, ctx);
  return value;
}

/** Finite only: NaN and Infinity do not survive a JSON round trip honestly. */
export function requireNumber(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): number {
  const value = obj[key];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail(key, "a finite number", value, ctx);
  }
  return value;
}

export function requireBoolean(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): boolean {
  const value = obj[key];
  if (typeof value !== "boolean") return fail(key, "a boolean", value, ctx);
  return value;
}

/**
 * Present-but-nullable. The key MUST exist; JSON null is a legal value.
 *
 * This is the reader for a field whose null carries meaning — `parent_span_id`
 * null means "root span", and `git_sha` null means "provenance unavailable".
 * An absent key is a different fact and is a throw.
 */
export function requireNullableString(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): string | null {
  if (!(key in obj)) return fail(key, "a string or null", undefined, ctx);
  const value = obj[key];
  if (value === null) return null;
  if (typeof value !== "string") return fail(key, "a string or null", value, ctx);
  return value;
}

export function requireNullableBoolean(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): boolean | null {
  if (!(key in obj)) return fail(key, "a boolean or null", undefined, ctx);
  const value = obj[key];
  if (value === null) return null;
  if (typeof value !== "boolean") return fail(key, "a boolean or null", value, ctx);
  return value;
}

/**
 * May be absent or null; both read as `null`.
 *
 * Use ONLY where DESIGN.md says the field is optional. Reaching for this
 * because a field is inconvenient is how a required field becomes optional
 * sludge.
 */
export function optionalString(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): string | null {
  const value = obj[key];
  if (value === undefined || value === null) return null;
  if (typeof value !== "string") return fail(key, "a string or null", value, ctx);
  return value;
}

export function optionalNumber(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): number | null {
  const value = obj[key];
  if (value === undefined || value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return fail(key, "a finite number or null", value, ctx);
  }
  return value;
}

export function optionalBoolean(
  obj: Record<string, unknown>,
  key: string,
  ctx?: string,
): boolean | null {
  const value = obj[key];
  if (value === undefined || value === null) return null;
  if (typeof value !== "boolean") return fail(key, "a boolean or null", value, ctx);
  return value;
}
