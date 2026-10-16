# ezyang: Scaling DeepSeek-V3 explainer site

Source: https://deepseek-v3.ezyang.com/ (repo: github.com/ezyang/scaling-deepseek-v3)

## Distillation
- Plain HTML/JS, zero dependencies, no build step. Hosted on GitHub Pages. Widgets are custom HTML tags (`<dsv3-layer>`, `<dsv3-sheet>`, ...), ~30 modules, configured by attributes and linked with `for="id1 id2"`.
- Cache-busting: each page has an import map pointing at content-hashed files; a script regenerates the hashes so pages never run stale JS.
- **Everything computes in the browser** in plain JS (SVG + canvas). No WASM, Pyodide, WebGL, workers or fetch. Real DeepSeek trace numbers are typed in as constants.
- Interactions: knobs on diagrams (hardware, parallelism, ZeRO, recompute, number formats), live memory/trace simulators, a seeded steppable routing sim, a step-through slide deck where the reader can change knobs mid-slide ("detour") and reset, pinnable tooltips.
- **Readers cannot write code.** Closest thing: "cell sheets" in post 03, hand-written HTML tables where each row has name, value and a formula. "The formula column IS the program": compiled to exact BigInt fraction arithmetic. Readers edit only whitelisted input rows, with validation (e.g. "EP must divide GPUs"); dependents recompute and turn amber.
- Numbers in the prose can bind to sheet rows (`data-cellref`) and update live. The page exports to `.xlsx` with live formulas.
- Formula text shown on screen is the exact string evaluated, so prose, tables, tooltips and export cannot drift.
- **State**: per page in the URL hash (shareable, survives refresh); same-named rows share a value. **Nothing carries across pages**; earlier values are re-entered by hand. A floating reset lists what the reader changed.
- Correctness is checked at build time, not on the reader: golden number tests, light/dark screenshot diffs, a diagram layout linter, ~85 headless-Chrome click-through scenarios, a test that fails on stale numbers in the HTML.
- Pedagogy: one model refined step by step (speed-of-light → roofline → 6ND → EP → ZeRO → pipelining → compare to real trace); every assumption is a named input row. Folds for side material. No exercises or quizzes. Phones get scaled previews with "tap to explore".
- **Openly AI-assisted**: graphics "100% vibe coded"; text human-written. `CLAUDE.md` requires AI-drafted prose to be wrapped in `[[AI: ...]]` markers, flag-don't-rewrite for doubtful author text, and AI prose never on a live page.

## Relevance to the series
- "The displayed text is the executed text" is the key idea to steal: our gated cells should show exactly what runs.
- URL-hash state + a reset control listing reader changes is a cheap model for per-page state; but note it does not solve cross-page carry-forward, which we need.
- Build-time verification battery (goldens, screenshot diffs, click-through tests) is a good model for keeping chapters from rotting.
- The `CLAUDE.md` author/agent split (AI prose markers, flag-don't-rewrite) is directly reusable for how we write this series.
- Contrast: zero reader code here; the series goes much further (real C/Python editing), so it needs infra this site avoids.

## Caveats from the report
- Site/tests not run locally; drafts not read. Sibling repo `ezyang/interactive-parallelize-transformer` mentions exercises but wasn't inspected. Human vs AI prose split beyond disclosures is inferred.

source: subagent file agent-a04aa2b4448b62682.jsonl
