// Regression tests for tools/clip. Run: bun test tools/clip.test.ts
//
// Fixtures are local HTML snapshots, so tests don't depend on the live site.
// clip shells out to `npx -y defuddle` (unpinned), so a defuddle release can
// change results; a `test.failing` that starts failing means "this got fixed,
// promote it to a normal test".

import { expect, test } from "bun:test";
import { join } from "node:path";

const CLIP = join(import.meta.dir, "clip");
const FIXTURES = join(import.meta.dir, "clip-fixtures");

async function clip(fixture: string): Promise<string> {
  const proc = Bun.spawn([CLIP, join(FIXTURES, fixture)], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const [out, err, code] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (code !== 0) throw new Error(`clip exited ${code}: ${err}`);
  return out;
}

// Body of the markdown section under `heading`, up to the next heading.
function section(md: string, heading: string): string {
  const start = md.indexOf(`${heading}\n`);
  if (start < 0) throw new Error(`heading not found: ${heading}`);
  const rest = md.slice(start + heading.length + 1);
  const next = rest.search(/^#{1,6} /m);
  return (next < 0 ? rest : rest.slice(0, next)).trim();
}

// Neel Nanda, "How To Become A Mechanistic Interpretability Researcher"
// (alignmentforum.org/posts/jP9KDyMkchuv6tHwm), post HTML from the AF GraphQL
// API (htmlBody), wrapped in <html><article>. Clipping the live page drops the
// same TL;DR.
const NANDA = "af-nanda-mech-interp.html";

// Control: clip runs and the body comes through. Keeps the known-failing test
// below honest (it would also "pass" if clip crashed).
test("nanda: clip extracts the post body", async () => {
  const md = await clip(NANDA);
  expect(section(md, "### High-Level Framing")).toContain(
    "learn the absolute minimal basics as quickly as possible",
  );
});

// KNOWN BUG: defuddle silently drops the TL;DR, a nested <ul> of ~30 bullets
// whose items are mostly #anchor links into the post. We think it treats the
// list as a table of contents and strips it as navigation. clip prints
// `## TL;DR` with nothing under it, and exits 0 with no warning.
test.failing("nanda: TL;DR list survives (known bug: dropped silently)", async () => {
  const md = await clip(NANDA);
  const tldr = section(md, "## TL;DR");
  expect(tldr).toContain("Learn the minimum viable basics, then do research.");
  expect(tldr).toContain("Breadth over depth");
});

// Jacob Steinhardt, "Research as a Stochastic Decision Process"
// (cs.stanford.edu/~jsteinhardt/ResearchasaStochasticDecisionProcess.html),
// curl'd as-is. The page is a bare HTML fragment (no <html>/<body>, opens with
// a long comment), so defuddle extracts nothing and clip falls back to the
// headless browser. Needs agent-browser installed.
const STEINHARDT = "steinhardt-fragment.html";

// Regression: `agent-browser eval` prints its result JSON-encoded, and the
// fallback used to write that string to disk undecoded, so the clip came out
// full of literal `\n`, `\"` and raw <sup> tags.
test("steinhardt: browser fallback decodes eval output", async () => {
  const md = await clip(STEINHARDT);
  expect(md).toContain("reduce uncertainty at the fastest possible rate");
  expect(md).not.toContain("\\n");
  expect(md).not.toContain("<sup");
  expect(md).toContain("[^1]:");
}, 60_000);

// KNOWN BUG: every equation on this page is an <img>, and defuddle drops them
// all without a trace, leaving sentences like "we can compute  for the two
// tasks:". clip exits 0.
test.failing("steinhardt: equation images survive (known bug: dropped silently)", async () => {
  const md = await clip(STEINHARDT);
  expect(md).toContain("Research-as7.png");
}, 60_000);
