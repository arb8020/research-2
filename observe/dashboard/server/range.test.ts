import { describe, expect, test } from "vitest";

import { parseRange } from "./range.ts";

describe("parseRange", () => {
  test("no header", () => {
    expect(parseRange(null)).toEqual({ kind: "absent" });
  });

  test("open suffix", () => {
    expect(parseRange("bytes=0-")).toEqual({ kind: "suffix-from", start: 0 });
    expect(parseRange("bytes=4096-")).toEqual({ kind: "suffix-from", start: 4096 });
  });

  test.each([
    ["bytes=abc-", "not a number"],
    ["bytes=-500", "suffix-length"],
    ["bytes 0-", "expected"],
    ["bytes=0-100", "closed ranges"],
    ["bytes=0-,10-", "multiple ranges"],
    ["bytes=12", "has no `-`"],
  ])("%s is malformed", (header, fragment) => {
    const parsed = parseRange(header);
    expect(parsed.kind).toBe("malformed");
    if (parsed.kind !== "malformed") throw new Error("unreachable");
    expect(parsed.reason).toContain(fragment);
  });
});
