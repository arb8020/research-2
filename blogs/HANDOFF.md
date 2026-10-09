# Handoff: blogs/ interactive RL series (2026-10-08)

Branch `blogs/flappy`, worktree `worktrees/blogs-flappy`. The page-builder spike is merged in.

## Next session
1. **`<nn-fit>` widget (branch `blogs/nn-fit`, worktree `worktrees/blogs-nnfit`, demo `npm run build:nn-fit`, `web/embeds/nn-fit/demo.html`).** Browser-only TS MLP (hand-written backprop, Adam), playground-style. Done: draw (must span the whole x axis before Train), spiral, presets linear/relu/tanh/sigmoid, gradient check. In progress (subagent round 2): per-layer widths; curve source `wave` = composition of `d` random Fourier series (`K` wiggles, roughness `α`, seeded; no special cases like sawtooth, by the author's choice); a samples slider (the curve is the hidden true function, net sees n points; train error + error vs true curve; spiral train + held-out accuracy); noise σ; compute + wall-clock budgets. Then: adapt it to the embed seam (`web/embeds/<kind>/{embed.py, element.ts, element.css}`) and place it at the prose placeholder "[embed something here that helps the reader believe in neural networks]". Heavy datasets (TinyStories, modular arithmetic, CIFAR): later, require Connect (no recorded runs, no browser fallback).
2. **Modal runtime (spike done: branch `blogs/modal-spike`, `blogs/spike-modal/`, evidence in `.evidence/modal-spike/`).** Design (decided): Jupyter kernel in a Modal sandbox in the reader's own workspace; Python cells + their checks run in the live kernel (tensor-puzzles style); C env cells run check build (asserts, ASan/UBSan) then prod build + budget in subprocesses, then the kernel loads the prod `.so`. Findings: the browser can't call Modal (JS SDK is Node-only; api.modal.com has no CORS/grpc-web), so a stateless relay (Modal web endpoint in our workspace, `/connect` + `/terminate`, ~$0.0001/connect) creates the sandbox with the reader's token; after that the browser talks to Jupyter over the sandbox tunnel directly. Cold connect 3.6 s (first image build 1-3 min), warm C cell ~5 s, Python cell ~70 ms, reload reattaches in 0.2 s, segfault/infinite loop don't kill the kernel, an open websocket keeps the sandbox alive (`idle_timeout` reaps closed tabs), ~$0.19-0.38/h. check.py runs unchanged on Modal Linux. Caveats: checks in the kernel can be faked by the reader (accepted: cheating fools yourself); cross-workspace billing untested (one account); spike committed with `--no-verify`.
   - **Sign-in (decided): paste a token for now.** OAuth ("Sign in with Modal") exists in the SDK (`MODAL_OAUTH_*`) but app registration isn't public; ask Modal later.
   - **Queued: least-privilege setup.** Connect panel walks the reader through: an Environment `blogs`, an Environment budget (e.g. $5/month, Modal-enforced), a service user with Contributor on `blogs` only, paste that token. The relay always uses `environment_name="blogs"` and warns if the token can see other environments. First check which Modal plan has service users/RBAC; if Team-only, fall back to a separate throwaway workspace with a workspace budget. Docs: modal.com/docs/guide/{budgets,service-users,rbac}.
3. **Page work, in this order (decided 2026-10-08):**
   - **Drafts survive reload.** localStorage per cell. On reload the editor shows the draft; a "revert to last passing" button restores the session's last passing source. Downstream cells still use the last passing version only. Fold in: cell order is decided twice (server `cell_order` vs DOM order).
   - **Show solution button.** Read-only view of the solution, select/copy blocked (friction, not security), fetched from the session/runtime on click so the page stays solution-free and `build_page.py`'s leak assert keeps no exceptions.
   - **Small:** ports/session URL in one place (`dev.sh`, `build_page.py`, `session.py`); `light-dark()` to dedupe dark tokens in `page.css`; raw colour in `play.html`; the fixed settings buttons overlap a cell's Run button at narrow widths.
4. **Carousel slide list: inline in `rl/01-flappy.md` (now) or its own file?** Open, the author's call. Media stays runtime-fetched (YouTube on click, hotlinked figures); only the slide text is ours.
5. **check.py split (deferred).** Split along its four jobs: chapter format (`parse`, roles, `HIDDEN`, a reader view vs an author view), C build (`compile_c`, `BUILDS`, sanitizers), runner (`run_cell`, `run_phase`, worker; already returns a `Result` record), thin CLI. Otter-grader spike (borrow: parse once -> two views, checks-on-solutions as part of the build, runner sees only the reader view, result records, show the failing line; don't borrow: notebooks, scoring, hidden tests, single-kernel isolation). Note that `session.py` chains the reader's latest passing code, not the solutions. Revisit after the Modal runtime design lands, since the kernel model changes what the runner is.
6. **`cell=policy`.** Prose slots before it: "can something autonomous play this?" and "a policy network". Order: policy -> sample -> logprob -> loss -> train, each with a check already written. `check=policy` pins `init_policy(obs_dim, n_actions, hidden, seed) -> dict[str, Tensor]` and `policy_probs(params, obs)`. Same mode as `puf_step`: the author drives, Claude asks one line at a time.

## Done 2026-10-08 (late)
- `blogs/lint` merged: page in TypeScript (`web/page.ts`, `web/settings.ts`, `web/dom.ts`), npm + esbuild, `npm run lint` (tsc + eslint + ruff) gate, `blogs/pre-commit` installed as a symlink at `.git/hooks/pre-commit` pointing into this worktree (relink if this worktree is removed). `a11y.py` now fails on light-mode violations too.
- `blogs/result` merged: structured run result (NDJSON `{out}*` then one `{result: {passed, message}}`; `check.run_cell` returns `Result`).
- `blogs/carousel` merged: 8-slide "cool things RL has done" carousel, the first embed (`web/embeds/carousel/`, discovered by `embeds.py`; a fence named after the kind becomes the embed; bad keys fail the build). Move 37 uses a short unofficial clip (`JNrXgpSEEIE`, licence line says so); OpenAI Five Finals game 2 (`-FoZAM9xqS4`). openai.com 403s automated checks, so OpenAI slides were verified via Wayback.
- `dev.sh`: builds the page, runs session :8787 + static :8010 in tmux `blogs`. `verify_page.py` screenshots go to gitignored `.evidence/`.
- `blogs/build-split` merged (971adeba). One conflict in `build_page.py` (kept data-not-typeset/data-lang markup + `HIDDEN`); `verify_page.py` inject point moved to `// increment env by a tick`. check.py, --stub, mutants.sh, build_web.py --diff and verify_page.py all pass. The build-split worktree/branch can be removed.
- **Decided: the reference play wasm (compiled from `solution=flappy`) shipping to readers is fine;** flappy is simple.
- `notes/research/media/` deleted (not needed).

## Page (2026-10-08)
- Prose uses shadcn's `typeset.css` (vendored verbatim, MIT, `web/typeset.css`), driven by `--font-body --font-mono --size --leading --flow --measure`. Cells, the widget and todo boxes opt out with `data-not-typeset`.
- `web/settings.js` holds the corner controls. Light/dark is Lea Verou's two-state toggle (`~/dotfiles/docs/raw/frontend/raw/lea_verou_dark_mode_toggles.md`). The Aa panel (theme classic/paper, fonts, size, leading, flow, measure, Shuffle, Reset) is open to readers on purpose, with no dev/reader split for now. Settings are saved in localStorage and applied before first paint.
- `page.css` tokens are scheme x theme. `paper` is ported from `observe/dashboard/src/theme.css` (loom's skin). A shared personal tokens/components library (shadcn registry) is deferred, with a comment at the top of `page.css`.
- The editor has CSS-variable syntax colours (`.tok-*`) and a per-page vim toggle (`@replit/codemirror-vim`). Locked cells disable Run only. Arrow keys don't scroll the page from the play iframe.
- `uv run --with playwright a11y.py`: axe lint over every theme x scheme. All four are clean.
- Reference: `~/dotfiles/docs/raw/frontend/raw/shadcn_typeset.md`.

## Run it
```
cd worktrees/blogs-flappy/blogs
uv run check.py rl/01-flappy.md [cell] [--stub]     # checks vs hidden solutions (or the stubs)
uv run check.py rl/01-flappy.md flappy --build prod  # check=flappy without asserts/sanitizers
uv run build_web.py rl/01-flappy.md --diff          # wasm play widget + native~wasm behaviour check
uv run build_page.py rl/01-flappy.md                # dist/01-flappy/index.html
uv run session.py rl/01-flappy.md --timeout 20      # local session stand-in, :8787
./dev.sh                                            # build + session :8787 + page :8010 in tmux "blogs"
rm -rf .session && uv run --with playwright verify_page.py   # headless proof, screenshots in .evidence/verify_page/ (gitignored)
uv run --with playwright a11y.py                    # axe accessibility lint, light + dark (page must be served)
(cd web && npm ci)                                  # once: esbuild/tsc/eslint + codemirror (build_page.py bundles web/*.ts)
(cd web && npm run lint)                            # tsc + eslint + ruff; blogs/pre-commit runs it (install line inside)
```
verify_page.py and a11y.py take the page URL as an argument (default `http://localhost:8010/01-flappy/`).
`play.py` is a throwaway terminal player.

## Decisions (made with the author)
- **Roles.** The author writes prose, stubs and solutions. Claude writes checks, widgets, diagrams and the cell machinery. Never write prose.
- **Series.**
  - flappy (2 rows, 0/+1 reward, the agent sees the pipe it is about to face, so it's a contextual bandit) → REINFORCE derived on flappy → pong/cartpole + puffer → RNN detour → breakout → LSTM → breakout + PPO, covering the ICLR "37 PPO details".
  - Catch (bsuite-style) is deferred; it may become the reader-written env.
  - Probes appear only as check fixtures.
- **Chapter = one Markdown file.** Fenced blocks are tagged `given`, `cell=X`, `solution=X` and `check=X`. A `c` cell is a whole PufferLib env header; it is compiled, not exec'd. Solutions live in the file and the repo can be public; the page build strips `solution=` and `check=`.
- **Checks** are plain asserts with pass/fail only, never graded, plus absolute speed/memory budgets on a pinned machine type. Python cells are split into small cells with one check each.
- **Gating.** Cell N is locked until N-1 passes. Locked means Run is disabled and nothing more: the code stays readable and editable, with no fading (2026-10-08). Downstream cells use the reader's latest *passing* version; failing edits don't propagate. Later chapters may run the reader's code or the reference, whichever is easier to build (decided per chapter).
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
- **Hints: no ladder; a "show solution" button only (confirmed 2026-10-08).** See Next session 2.
- **Casts follow puffer.** No redundant casts. Float -> int stays implicit, with a comment saying so. Casts that change meaning (e.g. `(float)` for float division) stay.
- **Logging.** `add_log(Env*)` is a ready-made helper in the stub and the solution. The reader calls it at episode end and keeps `episode_return += reward` themselves. `given` `Flappy.log()` wraps `vec_log`, and `check=flappy` verifies `n`, `episode_length`, `episode_return` and `perf`.
- **Notes.** `notes/research/` holds the distilled research reports (inspiration + infra) and `notes/design-discussion.md` the why behind decisions, both recovered from session a9f505dc. The inspiration sections lack the author's own reasons and need their pass.

## Parked (2026-10-08)
- **Build split (2026-10-08, branch `blogs/build-split`).** `check.py` compiles each C block two ways (`BUILDS`):
  - check: `-O1 -g -fno-omit-frame-pointer -fsanitize=address,undefined,bounds,pointer-overflow -fno-sanitize-recover=all`, asserts on, `-Wall -Wextra -Werror -Wno-unused-parameter` plus upstream's `CLANG_WARN`. Vendor dirs (pufferlib, raylib) are `-isystem`, so only the reader's header and `shim.c` can fail the build. `-O1` rather than upstream's `-O0`: ASan's recommended level, closer to prod codegen, same reports.
  - prod: `-O2 -DNDEBUG` + upstream's `CLANG_WARN`, no `-Werror` (stripping asserts can leave a variable unused). `build_web.py` (emcc play widget and `--diff`) uses it too.
  - Which build a block sees: `check=X` of a C cell X runs against X's check build; a new hidden role `budget=X` runs against prod builds; every other cell and every upstream C cell gets prod. `check=flappy`'s speed loop moved into `budget=flappy`. `check=train` keeps its time/memory asserts, since a Python cell's check already runs on prod in a clean process.
  - Each phase runs in its own Python subprocess (`run_phase`/`worker`). The check phase of a C cell preloads the ASan runtime (`sanitizer_env`: `DYLD_INSERT_LIBRARIES` on macOS, `LD_PRELOAD` + `-shared-libasan` on Linux; `dlopen`ing an ASan .so without it aborts with "interceptors not working"). The budget phase is a clean process because preloaded ASan intercepts `memset`, which slowed even the prod .so by ~30% (346M to 242M steps/s).
  - Crash, sanitizer report (exit 86), abort (failed assert) and timeout messages moved from `session.py` into `check.run_phase`. `session.py` now calls `run_cell` directly.
  - `uv run check.py rl/01-flappy.md flappy --build prod` runs `check=flappy` without asserts/sanitizers, to see what they catch.
  - `assert(a = b)` gave no `-Wparentheses` on macOS because the SDK's `assert(e)` expands to `!(e)`, and the parentheses silence it. glibc's expands to `if (e)` and warns (checked in an Ubuntu container, with both clang and gcc). `include/assert.h` (check build, macOS only) redefines `assert` the glibc way, so the warning (an error under `-Werror`) fires on both. No flag catches other side effects (`assert(x++)`); that is clang-tidy's `bugprone-assert-side-effect`, which isn't installed.
  - Measured (laptop): check build ~80M steps/s, prod ~300M.
  - `verify_page.py`'s segfault and infinite-loop cases had been no-ops since the stub lost `// write stub here` (the paste was the plain stub). They now inject at a stub comment and assert it exists; the segfault now shows as an ASan SEGV report.
  - Untested: the full check.py path on Linux/Modal (x86_64, needs clang's shared ASan runtime installed). The mechanism itself (`-shared-libasan` + `LD_PRELOAD` + ctypes + numpy catching a heap overflow) was run in an arm64 Ubuntu 24.04 container with clang 18.
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
