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
| `spike/workspace-cells` | spike of the workspace-cell uncertainties | **running**: see "spike findings" below |

## spike findings

<!-- fill in when the spike lands: contents API / CORS, kernel-image toolchain, check speed, background checks, bundle persistence, error links -->

## next

1. fold the spike findings into 00-plan.md
2. define what "correct" means for a forward pass (chapter 1's check); measurements from the gpt2 forward subagent inform it
3. chapter 1 reference code + checks (gpt2 torch functional forward vs HuggingFace), as the first layered reference folder `engine/ref/ch01/`
4. the smallest workspace-cell slice (a toy 2-file C++ chapter end to end), then chapter 5's engine

## open

- chapter 5 may need splitting; chapter 1 model (gpt2 only vs qwen3-0.6b); "after the core" section; scheduler policy shape; multi-host TPU; local backend (session.py vs connect_dev.py)
- cross-workspace Modal billing untested (Connect with a reader's own token)
