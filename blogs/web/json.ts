// The boundary type for JSON we have received but not yet parsed into a domain type (a server reply, a stored
// value, a line of a check's output). Only parsers take or return it; parsed values never carry it onward.

// oxlint-disable-next-line anti-slop/no-unsafe-dictionary-type -- the one named home for an unparsed JSON object; parsers narrow each field before use
export type JsonObject = Record<string, unknown>;

export const isJsonObject = (x: unknown): x is JsonObject => typeof x === "object" && x !== null && !Array.isArray(x);
