# Handoff: blogs/ interactive RL series (2026-10-08)

Branch `blogs/flappy`, worktree `worktrees/blogs-flappy`. The page-builder spike is merged in.

## Next session
1. **`puf_step` is done (2026-10-08).** The author translated the draft line by line and the stub now passes `check.py ... flappy --stub`. Concepts it took, in order: `->` vs `.`, `typedef float obs_t` (puffer's header leaves the obs type as a blank the env fills in), `*` in types vs expressions, `&`, copy vs pointer (copying is fine for reads, writes need the pointer), `*p = v`, a `(int)` cast, `assert` + `#include <assert.h>`, `=` vs `==`, `>` vs `>=`, `add_log` placement. Open: should the reference become the author's version? The reference is now the author's version, and the stub is back to a todo.
2. **Hint ladder.** Hints are derived from annotated solutions and shown beside the editor, never replacing it. Markers go only in `solution=` blocks:
   - a whole-line `// hint_i text` is an outline comment revealed at level i;
   - a trailing `// hint_i` on a code line reveals that line at level i;
   - other code shows as `...`;
   - the last level is the full solution;
   - Python uses `# hint_i`.

## Run it
```
cd worktrees/blogs-flappy/blogs
uv run check.py rl/01-flappy.md [cell] [--stub]     # checks vs hidden solutions (or the stubs)
uv run build_web.py rl/01-flappy.md --diff          # wasm play widget + native~wasm behaviour check
uv run build_page.py rl/01-flappy.md                # dist/01-flappy/index.html
uv run session.py rl/01-flappy.md --timeout 20      # local session stand-in, :8787
python3 -m http.server 8010 -d dist                 # open localhost:8010/01-flappy/
rm -rf .session && uv run --with playwright verify_page.py   # headless proof, screenshots/page-builder/
```
`play.py` is a throwaway terminal player.

## Decisions (made with the author)
- **Roles.** The author writes prose, stubs and solutions. Claude writes checks, widgets, diagrams and the cell machinery. Never write prose.
- **Series.**
  - flappy (2 rows, 0/+1 reward, the agent sees the pipe it is about to face, so it's a contextual bandit) → REINFORCE derived on flappy → pong/cartpole + puffer → RNN detour → breakout → LSTM → breakout + PPO, covering the ICLR "37 PPO details".
  - Catch (bsuite-style) is deferred; it may become the reader-written env.
  - Probes appear only as check fixtures.
- **Chapter = one Markdown file.** Fenced blocks are tagged `given`, `cell=X`, `solution=X` and `check=X`. A `c` cell is a whole PufferLib env header; it is compiled, not exec'd. Solutions live in the file and the repo can be public; the page build strips `solution=` and `check=`.
- **Checks** are plain asserts with pass/fail only, never graded, plus absolute speed/memory budgets on a pinned machine type. Python cells are split into small cells with one check each.
- **Gating.** Cell N is locked until N-1 passes. Downstream cells use the reader's latest *passing* version; failing edits don't propagate. Later chapters may run the reader's code or the reference, whichever is easier to build (decided per chapter).
- **Languages.** Envs are C in PufferLib format, following `ocean/squared` and PufferLib `SKILL_ISSUES.md`: `Env` holds only puffer's fields plus `FlappyEnv flappy_env`. Algorithms are Python with torch. The whole env file is one editable C cell (option c).
- **Runtime.**
  - Everything runs in a sandbox for now. The intended sandbox is a Modal sandbox fronted by a Cloudflare Durable Object; for now the stand-in is the local `session.py`. The browser runtime is a later backend.
  - Readers bring their own throwaway Modal workspace with a budget cap.
  - `box` should grow into the remote half of this, with SF autoresearch interop as a goal.
- **Browser.**
  - The env is compiled to wasm (emcc + raylib + puffer's `puf_web_vsync.js`, ASYNCIFY) for play and watch.
  - Human play latches keys at 1 step/s (`FLAPPY_FRAMES 60`).
  - Native vs wasm is compared on *behaviour*, not bits, because `rand_r` differs across libcs and upstream PufferLib accepts that.
- **Standalone.** blogs vendors its own PufferLib (`vendor/pufferlib`: pufferenv.h, ini.h, puf_web_vsync.js @ 6ffa5b1) and `shim.c` (a copy of robots'), and fetches its own raylib. Nothing reads `robots/`. If the two shims diverge enough to hurt, extract then.
- **Format and assistant.** Markdown was chosen over marimo (marimo fought the gating model and needed CSS hacks; its static build was 27 MB). pi-durable is the candidate inline assistant, deferred.

- **Asserts (2026-10-08).**
  - Readers write plain `assert`s, unenforced by checks. They are a testing tool: on in the check build, stripped with `-DNDEBUG` in the prod build (speed budget, training, play widget). This is the `cstyle_cpp.md` model. Upstream PufferLib and TigerBeetle keep cheap asserts on in prod; the prose should say we differ. It replaces the earlier "asserts on in every build" and "stage a `VERIFY` tier later" plans. A second tier only comes back if a later chapter wants cheap always-on asserts.
  - Teach the rule that asserts must only look, never change anything: `assert(a = b)` would behave differently in the two builds.
  - The flappy stub has `assert_invariants(FlappyEnv*)`, called at `puf_step` entry and before both returns: rows in {TOP, BOTTOM}, `0 <= tick < episode_length`, `0 <= episode_return <= tick`, `episode_length > 0`. Derived with the author via matklad's "What is an Invariant?". Mutants: `>` for `>=` and an over-counted reward fire at the broken rule. A `puf_reset` setting `tick = 1` slips past (a valid but wrong state), since only a reset postcondition would catch it; the author hasn't decided on one.
  - Measured (asserts on, noisy laptop): none ~390M, 3 action asserts ~314M, plus invariants ~201M steps/s. Budget 50M. Irrelevant once prod uses `-DNDEBUG`.
  - Research: `notes/research/asserts-tigerbeetle-matklad.md` (TigerBeetle's `constants.verify` tier, its 5% prod / 5x test cost policy, what to assert in hot loops).
- **Flappy stub: readers write logic, we write the checks (2026-10-08).** The stub's `puf_step` pre-fills the entry checks (`assert_invariants(&env->flappy_env)` + 3 action asserts, written with long paths so they don't give away `Agent* agent = &env->agents[0]`). The reader writes the logic under the outline comments, with no exit checks. Deferred: whether this holds series-wide or only for flappy (it conflicts with "readers write asserts" above).
- **Hints: probably no ladder for flappy.** The outline comments are already in the stub, so a ladder would just repeat them. Leaning towards a "show solution" button only, with no marker machinery until readers are seen to stall. Not yet confirmed by the author.
- **Casts follow puffer.** No redundant casts. Float -> int stays implicit, with a comment saying so. Casts that change meaning (e.g. `(float)` for float division) stay.
- **Logging.** `add_log(Env*)` is a ready-made helper in the stub and the solution. The reader calls it at episode end and keeps `episode_return += reward` themselves. `given` `Flappy.log()` wraps `vec_log`, and `check=flappy` verifies `n`, `episode_length`, `episode_return` and `perf`.
- **Notes.** `notes/research/` holds the distilled research reports (inspiration + infra) and `notes/design-discussion.md` the why behind decisions, both recovered from session a9f505dc. The inspiration sections lack the author's own reasons and need their pass.

## Parked (2026-10-08)
- **Build split, not yet implemented.**
  - Check build: `-O2` + asserts + `-fsanitize=address,undefined`, as upstream's debug build.
  - Prod build: `-O2 -DNDEBUG`, for the speed and memory budgets, training, and `build_web.py`.
  - Today `check.py` runs correctness and speed in one build with asserts on.
  - Also: `-Wextra`/`-Werror` on the reader cell only (`-isystem` for vendor headers), and why `-Wparentheses` didn't fire on `assert(a = b)`. `-Wfloat-conversion` is out, since it contradicts puffer casts.
- **Reference done (2026-10-08).** `solution=flappy` is the author's `puf_step` (entry checks at the top, tidied), and the stub's `puf_step` is back to the author's outline comments (the first and last comments are Claude's). Open: whether the reader writes `assert_invariants` themselves (now ready-made, like `add_log`), the `reward`/`is_terminal` aliases, a `puf_reset` postcondition, and the author's notes-to-self comments, which must go before publishing.

## Open questions
- **Page builder.**
  - (5) A reload restores only the last *passing* source, so unpassed edits are lost.
  - (6) When an upstream cell re-passes with different code, should downstream cells be marked stale?
  - It also decided:
    - `given` code is shown collapsed and read-only;
    - todo boxes show on the page, with no draft/publish switch;
    - the reference wasm plays until the reader's env passes;
    - the play widget is an iframe (click it before the arrow keys work).
- **Watching a trained policy in the browser.** Either puffer's `puffercpu.c` + `puffernet.h` (as nanoG1 does) or something smaller.
- **Python stubs and solutions** for policy, sample, logprob, loss and train are placeholders (the author's to write). The checks for them were validated against a throwaway reference: Adam and SGD both pass, and six mutants fail with their messages.
- **Prose.** Pavlov is classical conditioning; RL is closer to operant (Thorndike/Skinner).

## Spike branches (worktrees removed, branches kept)
| branch | what | worth keeping |
|---|---|---|
| `worktree-agent-a82b41125bb9313a2` | `blogs/spike-c-pyodide`: in-browser clang (YoWASP) → wasm side module → Pyodide `ctypes.CDLL`. flappy 58M steps/s at N=1024; compiler ~23 MB; no crash isolation | yes, for a future browser backend |
| `worktree-agent-a29bfb70351ac7455` | `blogs/spike-gpu-session`: Modal sandbox kernel (exec loop with a worker process, fd-level output capture), the browser streaming straight from the sandbox via connect token, `wrangler dev` DO, token paths (i) we hold vs (ii) reader `modal deploy`. CPU cold start ~2s, T4 ~4-5s, replay after a kill 3-8s. Modal's idle timeout ignores open websockets | yes: the starting point for the real session |
| `worktree-agent-a533c4ddd9502f299` | `blogs/spike-markdown`: superseded by `build_page.py` | no |
| `worktree-agent-ae59e61323e4cf011` | `blogs/spike-marimo`: rejected | no |

Research reports (vmux/Modal auth, Colab, SF autoresearch, pi-durable, inspiration blogs) were summarised in the session. Key facts:
- vmux uses its own Modal account and GitHub OAuth.
- Modal OAuth exists but isn't public.
- Modal's JS SDK can't run in Workers.
- GPU sandboxes can't memory-snapshot.
- autoresearch could be a `box` provider (H100 only; it owns the entrypoint).

## Papercuts seen
- Agents running `npm i` or `uv init` walked up into `~` and `research-2/` and polluted them. Since fixed: `~/node_modules` via `npm ci` + `npm audit fix` (20 advisories remain, all through `@oh-my-pi/pi-coding-agent@15`), and the root `pyproject.toml` restored. Brief agents to stay inside their own project dir.
- raylib only sees key presses held at least one frame, so headless tests must hold keys.
- A reboot mid-session killed a background agent; it resumed from its transcript.
