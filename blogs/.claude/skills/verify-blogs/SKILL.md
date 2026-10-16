---
name: verify-blogs
description: Verify the blogs/ interactive textbook (built chapter pages in a browser, checked cells against session.py, Connect against a local Jupyter via connect_dev.py, embeds, [[links]]). Use before claiming a blogs/ change works, or to show it working; launches an isolated local instance on free ports, drives it with Playwright, keeps screenshots and transcripts.
---

# verify-blogs

blogs/ turns one Markdown file per chapter into a reader page (`build_page.py` -> `dist/<stem>/index.html`). The
reader's surface is that page in a browser: checked code cells run against `session.py` (stand-in for the
reader's sandbox), scratch cells and nn-fit's "remote" run on a Jupyter kernel reached through a Connect
gateway (`connect_dev.py` locally; the real relay on Modal), and embeds (carousel, nn-fit, the flappy play
widget). The author's surface is the build itself: it fails loudly on bad chapters.

Every command below runs from `blogs/`. `vb` is `.claude/skills/verify-blogs/vb` (stdlib python3; its
docstring lists every subcommand). The feature map is `features/README.md`: read it, then the feature file for
the area you touched.

## Isolation (read first)

The author keeps long-running servers in tmux: `blogs` (session.py :8787 + page :8010), `reader-path` (relay
:8790 + page :8012), `blogs-nnfit` (:8060), and others. Never drive, bind, or kill those. `vb` picks free ports
(never 8010/8012/8060/8787/8790), starts every process in its own process group, and kills only those groups.
One `vb` run per checkout (state in `.session/verify-blogs/run.json`); a second checkout (worktree) can run its own
side by side. session.py keeps reader progress at the fixed path `.session/01-flappy/`, so `vb launch` refuses
when it already exists (pass `--fresh` to delete it).

## Launch

    .claude/skills/verify-blogs/vb setup            # fresh worktree only: npm ci in web/ (+ Playwright Chromium if missing)
    .claude/skills/verify-blogs/vb launch           # [--fresh]

`launch` builds every chapter with `--session-url`/`--gateway-url` pointing at its own ports, then starts
`uv run session.py rl/01-flappy.md --port P --timeout 20`, `python3 -m http.server Q -d dist --bind 127.0.0.1`
and `uv run connect_dev.py --port G`. Ready = it prints `ready.` and the URLs (also `vb status`):

    flappy (checked cells): http://127.0.0.1:Q/01-flappy/
    neural-nets (Connect):  http://127.0.0.1:Q/neural-nets/?gateway=http://127.0.0.1:G
    engine plan:            http://127.0.0.1:Q/00-plan/

It waits on `GET /state` (session), `GET /01-flappy/` (static), and `GET /sessions/none` -> 404 (gateway; the
first run installs jupyter_server, up to a few minutes). Server logs: `<evidence>/logs/*.log`.

## Doctor

    .claude/skills/verify-blogs/vb doctor           # read-only; exit 1 on any FAIL

Checks: branch and HEAD, `web/node_modules` (a fresh worktree's only symptom is `esbuild: command not found`),
uv, `.venv`, Playwright Chromium, emcc + clang, raylib fetched, no leftover scaffolding, a recorded run launched on
this branch, each process alive and still running the recorded command, each port listened on only by our
process group, run ports avoid the author's, session `/state` answers, the served page's `session-url` meta is our
session, neural-nets' `data-gateway` is our gateway, connect_dev answers, `dist/` newer than the sources. Run it
first, after anything surprising, and before trusting a result. `vb drive` runs it before every feature and
refuses to drive on a FAIL.

## Drive

    .claude/skills/verify-blogs/vb drive <feature> [<feature> ...]     # or: all

| feature | what it drives (harness) |
|---|---|
| `build` | `build_page.py` single + `--all`, built-HTML checks, fixture chapters that must build / must fail (`fixtures/`) |
| `plan` | `engine/00-plan.md` builds alone; the page in Chromium (`pages.py plan`) |
| `cells` | flappy checked cells through the page (`verify_page.py`: stub fails, solution passes, gating, crash, hang, reload) |
| `embeds` | carousel, flappy play widget, nn-fit in the browser (`pages.py embeds`) |
| `links` | `[[page#heading]]` hover card, Escape, click (`pages.py links`) |
| `connect` | bad token (`pages.py bad-token`), then `verify_connect.py --gateway <ours>`: connect, `!nvidia-smi`, Stop, reload reattach, disconnect, sign out, phone/dark, axe |
| `nn-fit-remote` | `web/embeds/nn-fit/remote_e2e.py` (starts its own connect_dev with torch; ~3 min; not in `all`) |

Each drive prints `ok`/`FAIL` lines and ends with `== <feature>: PASS|FAIL`; exit 1 if any feature failed. Real
handles, recipes and gotchas per feature: `features/<feature>.md` (`nn-fit-remote` is in `embeds.md`). To drive by hand, open the launched URLs in a
browser, or write a new case in `pages.py` (Playwright; selectors from the feature files).

Other proofs that are not page drives (run when you touch their area): `uv run check.py rl/01-flappy.md [cell]
[--stub]`, `uv run build_web.py rl/01-flappy.md --diff`, `(cd web && npm run lint)`, `(cd web && npm run
test:nn-fit)`, `uv run --with playwright a11y.py http://127.0.0.1:Q/01-flappy/` (axe over theme x scheme).

Modal (the real Connect) is documented in `features/connect.md` and is not part of `vb`: it costs money and needs
the box relay from another branch. Prefer the local gateway.

## Evidence

Everything lands in `blogs/.evidence/verify-blogs/<run id>/` (gitignored; `vb` never deletes it):
`launch.txt`, `run.json`, `logs/` (build, session, static, gateway), and one dir per feature with
`transcript.txt` (doctor + every command + its output + exit code + verdicts) and the screenshots/video. The repo
harnesses write to shared dirs (`.evidence/verify_page/`, `.evidence/verify_connect/`, `.evidence/nn-fit-remote/`)
that the next run overwrites; `vb` copies what a drive wrote there into the feature dir.

Proof standards: drive the reader's path in the page (click Run, the pill, the card), not session or gateway
endpoints directly; capture the action and the result (before/after screenshots, the status line text); check
side effects next to what's visible (`cells` saves the session's `/state` after the run: `state-after.json`
must list the cells that passed); mocks only where a production boundary already isolates the external system
(connect_dev.py stands in for the Modal relay at the gateway contract; its `nvidia-smi` prints `FAKE`). A pass
from `connect` proves the page against the contract, not Modal.

## Cleanup

    .claude/skills/verify-blogs/vb cleanup

TERMs each recorded process group (KILL after 10 s), skips a PID that now runs something else, reports each port
free, removes this run's `.session/01-flappy/` and `run.json`, any leftover scaffolding
(`verify-blogs-scaffold/`, `dist/vf-*`), then lists the evidence dir it kept. Run it after every run, failed or
not, before the next `vb launch`. It never touches processes it didn't record (never by name). `dist/` stays
built with this run's dead ports; `./dev.sh` or `vb launch` rebuilds it.

## Helpers

- `vb` (setup, launch, doctor, status, drive, cleanup): `.claude/skills/verify-blogs/vb --help`.
- `pages.py`: browser cases the repo's harnesses don't cover (`plan`, `embeds`, `links`, `bad-token`,
  `fixture`); `vb drive` runs them; by hand see its docstring.
- `fixtures/vf-*.md`: chapters `vb drive build` copies one at a time into `verify-blogs-scaffold/`
  (VERIFICATION SCAFFOLDING: build_page only builds chapters in a non-hidden subdirectory of blogs/) and removes.

Keep the map honest with `/maintain-verification-skill`.
