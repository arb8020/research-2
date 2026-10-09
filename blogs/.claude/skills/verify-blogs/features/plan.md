# Engine plan page

`engine/00-plan.md` is the inference-engine series' curriculum plan: a prose-only chapter under a wip banner, with no cells, no Connect and no play widget. It builds like any chapter and must not talk to the session.

## Sub-features

- `plan-build` builds `engine/00-plan.md` alone and under `--all` (stem `00-plan`, page `dist/00-plan/`).
- `plan-wip` shows the banner `plan only. no prose yet`.
- `plan-outline` gives every heading a GitHub-style id (`## chapters` -> `#chapters`, one `###` per chapter), so `[[00-plan#...]]` links can target them.
- `plan-quiet` loads no cells and sends no request to the session URL.

## How to get to it (user POV)

- Run `uv run build_page.py engine/00-plan.md` (or `--all`), then open `http://127.0.0.1:<static>/00-plan/`.
- Link to it from another chapter with `[[00-plan]]` or `[[00-plan#chapters]]`.

## Driving it with vb

Preconditions:

- `vb doctor` reports ok.

- **Build alone.** Run `vb drive plan` (step 1: `uv run build_page.py engine/00-plan.md --session-url <ours> --gateway-url <ours>`). Exit 0 and `dist/00-plan/index.html: cells [], scratch 0, connect False`.
- **Open the page.** Same drive, `pages.py plan` opens `/00-plan/`. `h1` reads `inference engine: curriculum plan`; `get_by_role("note", name="under construction")` contains `plan only. no prose yet`.
- **Outline.** `h2#chapters` exists and at least five `h3[id]` chapter headings.
- **Quiet page.** No `code-cell, scratch-cell, connect-pill, env-play`; after `networkidle` no request URL starts with the page's `meta[name=session-url]`; no page errors.
- **Proof.** `plan/plan-page.png` (full page), `plan/plan-wip.png`, `plan/transcript.txt` ending `== plan: PASS`.

## Gotchas

- The plan is edited often (it is the author's working plan); assert the title, banner and structure, not chapter text or counts beyond the `>= 5` floor.
- `engine/` is a chapter directory only because links.py treats every non-hidden subdirectory as chapters; a second `00-plan.md` anywhere would fail every build on the duplicate stem.
