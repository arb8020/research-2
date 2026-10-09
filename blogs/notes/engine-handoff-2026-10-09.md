# engine curriculum: handoff (2026-10-09)

Start here for the next session. The plan of record is `blogs/engine/00-plan.md` (branch `blogs/engine`).

## what was decided

- **series:** a "build the inference engine with me" curriculum in blogs/; the reader rewrites kelpie, and the last chapter's reference code *is* the new kelpie
- **architecture:** frontend (Python: HTTP, chat template, tokenizer, detokenize) <-> engine (C-style C++, single-threaded, central scheduler, token ids only) <-> worker(s) (Python torch: forward, sampling, grammar masks)
- **central scheduler, not replicated.** Kelpie's replicated design was never weighed properly or run multi-GPU. Door-open rules for multi-host later: deterministic sans-IO core, ordered ops log, plan as a wire format, swappable transport
- **overlap deleted** (it only hid ~42 µs of planning); see `kelpie/docs/decisions/overlap-removed.md` on `kelpie/core-compress`
- **transport:** Heinrich pattern (spawn + socketpair + memfd); binary framing; shared-memory ring for the plan in chapter 12
- **language rules:** `~/dotfiles/docs/raw/cstyle_cpp.md` (merged to dotfiles main, `0aae5e6`). C++20, always-on `ASSERT` + `DEBUG_ASSERT`, one owner + one teardown + four cleanup layers, Linux only, grammar (xgrammar) stays in the worker
- **workspace + cells:** see the 00-plan.md section of that name

## branches

| branch | what | state |
|---|---|---|
| `blogs/engine` | 00-plan.md (20 chapters), this handoff | live |
| `kelpie/core-compress` (`worktrees/kelpie-core-compress`) | Zig core cleanup + overlap removal + step loop on `*Engine` | done; now reference only (the engine moves to C++) |
| `worktree-agent-a7fdb11404b864483` | `box dev` (held Modal A100, git sync, streamed runs, ports) | done, verified live; someone else is merging the box work |
| `worktree-agent-aad0b243b3c6f22cd` | `box --provider colab` | done; needs the user's live smoke run (`box/tests/smoke_colab`) |
| `spike/workspace-cells` | spike of the workspace-cell uncertainties | done: see "spike findings" below |
| `engine/ch01-forward` | gpt2 torch functional forward + HF measurement harness (planted bugs) | running at time of writing |

## spike findings

Spike branch `spike/workspace-cells` (worktree `.claude/worktrees/agent-ab43b3645de8cdea6`, evidence in `spike/workspace-cells/evidence/`). All six uncertainties work; nothing breaks the design. Cost about $0.01; nothing left running.

1. **Page -> sandbox file writes:** cross-origin `PUT /api/contents` works with the relay's Jupyter flags, no config change (a deliberately wrong `allow_origin` does block it, so the test is real). Modal: 13-18 ms per 1-50 KB read/write. The kernel fallback works but is ~4x slower -> use the Contents API.
2. **Toolchain:** the Connect kernel image (pytorch 2.5.1 runtime, Ubuntu 22.04) has no git / gcc / clang / make. Fix: one line in `kernel.Dockerfile`: `apt-get install -y --no-install-recommends git clang make ccache g++ libc6-dev` (+35 s build once, ~400 MB).
3. **Check speed:** far under target. Edit-one-file rebuild + trace check on Modal CPU: 0.18 s (g++) / 0.42 s (clang); end to end from page save to streamed verdict: **~190 ms** median. g++ ~2x faster than clang 14 here; ccache barely matters at this size; the risk at kelpie scale is files pulling in heavy STL headers (~0.7 s each). Add `-fno-sanitize-recover=all` or UBSan reports don't fail the check.
4. **Background checks:** work; kernel free within ~50 ms; scratch cells run concurrently; kill in ~6-56 ms. Required: the check runs in its own process group (`start_new_session=True`; otherwise a scratch-cell interrupt kills it), and its output is sent explicitly to the cell that started it; `kernel.ts` needs a "job" mode that keeps the output handler after the cell replies. Alternative that also works: a second kernel just for checks (undecided).
5. **Persistence:** git bundle to a Volume works: 8k-line repo -> 79 KiB bundle; whole pass commit (commit + tag + bundle + copy + sync) 0.6-0.9 s; restore 0.33 s. Git directly on a Volume is slow and showed a broken repo without explicit `sync` -> keep the bundle; write temp + rename, keep the previous bundle, `git bundle verify` before restore.
6. **Error links:** `path:line:col` -> jump-to-line works for gcc / clang / UBSan / ASan / trace output, streamed in random chunks. Linkify complete lines only; match paths by suffix (absolute sandbox paths).

## next

1. fold the spike findings into 00-plan.md
2. define what "correct" means for a forward pass (chapter 1's check); measurements from the gpt2 forward subagent inform it
3. chapter 1 reference code + checks (gpt2 torch functional forward vs HuggingFace), as the first layered reference folder `engine/ref/ch01/`
4. the smallest workspace-cell slice (a toy 2-file C++ chapter end to end), then chapter 5's engine

## open

- chapter 5 may need splitting; chapter 1 model (gpt2 only vs qwen3-0.6b); "after the core" section; scheduler policy shape; multi-host TPU; local backend (session.py vs connect_dev.py)
- cross-workspace Modal billing untested (Connect with a reader's own token)
