# Handoff: blogs/ interactive RL series (2026-10-08)

Branch `blogs/flappy`, worktree `worktrees/blogs-flappy`. The page-builder spike is merged in.

## Next session
1. **`puf_step` as the C lesson** (pointers, `&`, `->` vs `.`, arrays as out-parameters). The author's Python-style draft sits in the `cell=flappy` stub; it doesn't compile yet. Translate it line by line, then run `uv run check.py rl/01-flappy.md flappy --stub`. The reference `solution=flappy` passes.
2. **Hint ladder.** Hints are derived from annotated solutions and shown beside the editor, never replacing it. Markers go only in `solution=` blocks:
   - a whole-line `// hint_i text` is an outline comment revealed at level i;
   - a trailing `// hint_i` on a code line reveals that line at level i;
   - other code shows as `...`;
   - the last level is the full solution;
   - Python uses `# hint_i`.
3. **Shared puffer code**: see the open question below.

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
- **Format and assistant.** Markdown was chosen over marimo (marimo fought the gating model and needed CSS hacks; its static build was 27 MB). pi-durable is the candidate inline assistant, deferred.

## Open questions
- **Puffer files.** `blogs` reaches into `robots/envs/puffer/` (shim.c, pufferenv.h, ini.h, build.py, puf_web_vsync.js). Options: a shared top-level `puffer/`, copy into blogs, or keep as is. Moving it touches robots imports and `robots/box_recipe.py`, which uploads robots/.
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
