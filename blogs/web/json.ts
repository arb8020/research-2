// oxlint-disable-next-line anti-slop/no-unsafe-dictionary-type -- the one named home for an unparsed JSON object; parsers narrow each field before use
export type JsonObject = Record<string, unknown>;

export const isJsonObject = (x: unknown): x is JsonObject => typeof x === "object" && x !== null && !Array.isArray(x);
