/**
 * `Range` header parsing. Pull-based tailing only ever asks for a suffix
 * (`bytes=N-`), so that is the only form this server implements.
 *
 * No semantic fallbacks: a header we do not understand is a 400, not a silent
 * "serve the whole thing". Silently ignoring a Range is how a tailer ends up
 * re-parsing the file from byte zero every poll without anyone noticing.
 */

export type ParsedRange =
  | { readonly kind: "absent" }
  | { readonly kind: "suffix-from"; readonly start: number }
  | { readonly kind: "malformed"; readonly reason: string };

const PREFIX = "bytes=";

export function parseRange(header: string | null): ParsedRange {
  if (header === null) return { kind: "absent" };
  if (!header.startsWith(PREFIX)) {
    return { kind: "malformed", reason: `expected \`${PREFIX}N-\`, got ${JSON.stringify(header)}` };
  }
  const spec = header.slice(PREFIX.length).trim();
  if (spec.includes(",")) {
    return { kind: "malformed", reason: "multiple ranges are not supported" };
  }
  const dash = spec.indexOf("-");
  if (dash === -1) {
    return { kind: "malformed", reason: `range ${JSON.stringify(spec)} has no \`-\`` };
  }
  const startText = spec.slice(0, dash);
  const endText = spec.slice(dash + 1);
  if (startText === "") {
    // `bytes=-500` means "the last 500 bytes" — a different request than the
    // tailer ever makes, and answering it as byte 0 would be a lie.
    return { kind: "malformed", reason: "suffix-length ranges (`bytes=-N`) are not supported" };
  }
  if (!/^\d+$/.test(startText)) {
    return { kind: "malformed", reason: `range start ${JSON.stringify(startText)} is not a number` };
  }
  if (endText !== "") {
    return { kind: "malformed", reason: "closed ranges (`bytes=N-M`) are not supported" };
  }
  return { kind: "suffix-from", start: Number.parseInt(startText, 10) };
}
