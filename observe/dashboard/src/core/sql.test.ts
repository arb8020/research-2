import { describe, expect, it } from "vitest";
import { sqlLiteral } from "./sql.ts";

describe("sqlLiteral", () => {
  it("quotes a plain value", () => {
    expect(sqlLiteral("wm_loss")).toBe("'wm_loss'");
  });

  it("doubles a single quote so a name with an apostrophe cannot break out", () => {
    expect(sqlLiteral("o'brien")).toBe("'o''brien'");
    expect(sqlLiteral("x' OR 1=1 --")).toBe("'x'' OR 1=1 --'");
  });

  it("doubles EVERY quote, not just the first", () => {
    expect(sqlLiteral("a'b'c")).toBe("'a''b''c'");
  });

  it("leaves double quotes and backslashes alone (DuckDB does not escape them here)", () => {
    expect(sqlLiteral('say "hi"\\n')).toBe("'say \"hi\"\\n'");
    // A trailing backslash does not escape the closing quote in DuckDB, so the
    // literal below is closed and the backslash is data.
    expect(sqlLiteral("trail\\")).toBe("'trail\\'");
  });

  it("quotes an empty string as an empty literal", () => {
    expect(sqlLiteral("")).toBe("''");
  });
});
