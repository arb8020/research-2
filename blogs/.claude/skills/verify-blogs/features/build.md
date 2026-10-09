# Build pages

The author turns a chapter's Markdown into a reader page with `build_page.py`. The build renders cells, given code, scratch cells, embeds, wip banners, prose placeholders, excerpts and `[[links]]`, and fails with a line number on anything that would ship a broken or leaking page.

## Sub-features

- `build-one` builds one chapter: `dist/<stem>/index.html` plus page.js, page.css, the play widget.
- `build-all` builds every chapter under blogs/ (`--all`: `rl/01-flappy.md`, `dl/neural-nets.md`, `engine/00-plan.md`).
- `build-wip` renders `<!-- wip: text -->` as a visible banner (`role="note"`, `aria-label="under construction"`, 🚧); an empty one fails.
- `build-todo` renders any other `<!-- ... -->` on its own line (e.g. `<!-- write: ... -->`) as a muted `.todo` note.
- `build-links` resolves `[[page]]` / `[[page#Heading]]` to `<page-link>` with a build-time preview card; a missing page or heading fails.
- `build-excerpt` renders ```` ```c excerpt=../path ```` as a read-only, line-numbered view; fails unless the body is whole consecutive lines of that file.
- `build-hidden` strips `solution=`, `check=`, `budget=` fences and fails if a hidden block's text still shows on the page.
- `build-scratch` fails a page with a ```` ```python scratch ```` cell but no `<!-- page: connect -->`.

## How to get to it (user POV)

- Run `uv run build_page.py rl/01-flappy.md [more chapters] [--session-url URL] [--gateway-url URL]` in `blogs/`.
- Run `uv run build_page.py --all`.
- Run `./dev.sh` (builds `--all`, then the author's tmux servers: do not use it for verification).

## Driving it with vb

Preconditions:

- `vb launch` finished and `vb doctor` reports ok (the static server serves `dist/`, so built pages are reachable).
- No `verify-blogs-scaffold/` dir exists (doctor WARNs).

- **One chapter.** Build flappy alone. Run `vb drive build` (step 1: `uv run build_page.py rl/01-flappy.md --session-url <ours> --gateway-url <ours>`). Exit 0 and `wrote .../dist/01-flappy/index.html: cells ['flappy', 'policy', 'sample', 'logprob', 'loss', 'train'] ... play widgets ['flappy'], embeds ['carousel'], links 1`.
- **Every chapter.** Same drive, step 2 (`--all`). One `wrote` line each for `01-flappy`, `neural-nets`, `00-plan`.
- **Built HTML.** The drive reads `dist/*/index.html`. 01-flappy has no `solution=`/`check=`/`budget=` and no reference `flappy->tick += 1`, six `<code-cell>`s, `<env-play cell="flappy">`, `.todo` notes, one `<page-link>` to `../neural-nets/#fitting-a-curve`; neural-nets and 00-plan have the wip banner; neural-nets has `<connect-pill data-gateway="<our gateway>">` and a `<scratch-cell>`. Copies land in `build/built/`.
- **Fixtures that build.** `fixtures/vf-page-ok.md` (wip, `<!-- write: -->`, a 3-line excerpt of `vendor/pufferlib/pufferenv.h`, a link) builds; `pages.py fixture` then opens `/vf-page-ok/`: `figure.excerpt .excerpt-src` reads `vendor/pufferlib/pufferenv.h:44–46 · read-only`, a CodeMirror view, the banner, one `.todo`, the link. Screenshot `build/fixture-page.png`.
- **Fixtures that must fail.** Each builds alone and must exit 1 with: `vf-excerpt-bad.md` -> `is not in ../vendor/pufferlib/pufferenv.h verbatim`; `vf-leak.md` -> `leaked into the page`; `vf-bad-link.md` -> `no chapter called vf-no-such-page`; `vf-wip-empty.md` -> `<!-- wip: --> needs text`; `vf-scratch-no-connect.md` -> `scratch cells need <!-- page: connect -->`.
- **Proof.** `build/transcript.txt` (every command, output, exit code, verdict), `build/built/*.html`, `build/fixture-page.png`; the drive ends `== build: PASS` and `ok scaffolding removed`.

## Gotchas

- A fresh worktree without `web/node_modules` fails with only `esbuild: command not found` (exit 127 from `npm run build`). `vb setup`.
- The first build of a chapter with a play widget downloads raylib's wasm build into `vendor/raylib-*` (network).
- Chapters are `.md` files in a non-hidden subdirectory of `blogs/` (not notes/, vendor/, dist/, web/, include/); stems must be unique. That is why fixtures are copied into `verify-blogs-scaffold/` (scaffolding, removed in a `finally` and by `vb cleanup`), and why `--all` would pick them up while they exist.
- A build that names no `--session-url`/`--gateway-url` bakes in the author's `:8787`/`:8790`. Repo harnesses (`verify_connect.py`, `remote_e2e.py`, `demo_tour.py`) rebuild `dist/neural-nets` that way; `vb drive connect`/`nn-fit-remote` rebuild it with ours afterwards, and doctor WARNs if it is stale.
- `build_page.py` re-runs `npm run build` on every call (~0.1 s), so building fixtures one at a time is cheap.
- No chapter on `blogs/engine` uses `excerpt=` yet; only the fixture exercises it.
