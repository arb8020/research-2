# NOTES-doctor

`kelpie doctor` (branch cli/doctor). The code is the truth; this file is the judgement calls,
the open questions and the papercuts found along the way.

## Shape

```
kelpie (console script)
  kelpie_http.cli.main                 # NEW: {serve, build, cache, check, doctor} -> "module:function"
    kelpie_http.sdk.serve.main         # ~ serve's flags only; no longer dispatches
    kelpie_http.doctor.main            # NEW: argparse, $KELPIE_LIB/cache env read here, print, exit 1 on FAIL
      kelpie_http.doctor.run -> list[Check]
        kelpie_engine.doctor.run       # NEW: xgrammar shim, libkelpie fresh, libkelpie ABI
        disk_free / lockfiles_clean / torch_devices / kernel_backends
        remote_checks                  # only with --remote: modal CLI subprocesses + tmux
scripts/check_core_loop.py             # ~ calls kelpie_engine.doctor.libkelpie_fresh
kelpie_models/kernels/devices.py       # ~ cuda_arch_defaults(arch) split out of defaults_for
```

## Judgement calls

- **Status, not ok.** `Check(name, status, detail, fix)` with status PASS / WARN / FAIL / INFO,
  not an `ok` bool: the spec has warnings (uv.lock) and info (torch, kernels on a detected
  device), and a bool cannot hold them. Only FAIL sets the exit code.
- **Where the code lives.** The engine's three checks are in `kelpie_engine.doctor`, since
  the engine owns libkelpie, and check_core_loop runs in the kelpie-engine venv, which cannot
  import kelpie_http. Everything else, plus the CLI, is in `kelpie_http.doctor`: kelpie-http is
  the only package that sees engine + models and owns the `kelpie` script. Both dirs are now at
  mimir's 7-entry limit.
- **Dispatch.** `kelpie_http/cli.py` is one dict of `"module:function"` strings, imported only
  when named, so doctor does not pay for serve's imports (trio, hypercorn, sdk.run). No leading
  subcommand still means serve, so `kelpie --model gpt2` keeps working (rule 16, additive only);
  `kelpie serve --model ...`, which README documents, did NOT work before and does now.
  `kelpie -h` prints the subcommand list; `kelpie serve -h` prints serve's flags.
- **Freshness is mtime**, as specified (lib newer than every build.zig / build.zig.zon /
  src/** / include/** file). It never false-PASSes, but see papercut 1 for its false FAIL.
- **Shim path** is the rpath from build.zig (`../../xgrammar_shim/build` from zig-out/lib),
  kept as a constant with a citation rather than parsed out of the binary (otool / readelf per
  OS). If build.zig's rpath changes, this constant is a second writer. The ABI check (a real
  dlopen) is the ground truth and catches it anyway.
- **ABI check** goes through `_ffi.load`, the one writer of the version + struct-size
  comparison. It dlopens the lib, the only non-read-only thing about the local checks. When the
  lib or the shim is missing it is INFO "not checked", so one cause gives one FAIL.
- **Kernel check** lists one line per op with a non-reference default on the target, plus one
  INFO line naming the ops that run on the reference body (15 lines of "reference" on a laptop
  would be noise). The import goes through `backends.require`, the one writer of "is this
  backend usable", and it really loads the backend: Marlin dlopens its .so files.
- **`--device cuda:A100`**: GPU names come from a small `GPU_ARCHES` table in kelpie_http.doctor
  (T4, L4, A10G, A100, H100 -> compute capability), matched on the Modal GPU id prefix, so
  `cuda:A100-80GB` works too. `cuda` / `cuda:N` asks the visible device; with no CUDA it is a
  FAIL that tells you to name an arch. An unknown kind or GPU is an argparse error.
- **Disk threshold 10 GiB** (`--min-free-gib`). This laptop has ~15 GiB free, so 20 GiB would
  make every healthy run fail. One check per volume, grouping the repo, uv cache, HF cache and
  zig cache (env overrides: UV_CACHE_DIR, HF_HOME, ZIG_GLOBAL_CACHE_DIR, XDG_CACHE_HOME).
- **uv.lock** covers every tracked `*uv.lock` in the checkout, not only kelpie-engine's: same
  failure, same cost. The fix uses a `:/` pathspec, because git porcelain paths are relative to
  the checkout's top.
- **Modal via the `modal` CLI** (`--json`), not the SDK: modal is not a kelpie dependency, and
  the CLI is what a person debugs with. 30 s timeout per call; a non-zero exit becomes a FAIL
  or WARN with modal's error text.
- **Weights present** = some snapshot under `hf/hub/models--org--name/snapshots/` on the volume
  has config.json and every shard its names count (`-0000k-of-0000N`, 1..N; gpt-oss-20b also
  ships a 00000 shard). Snapshot links are created only after a file finished downloading. The
  fix text uses `modal_run.py --gpu T4 ... -- true` (the cheapest GPU that warms HF_HOME).
- **Leftover sandboxes** = running containers of the Modal app `box` (box/providers/modal.py),
  from ANY tree, because Modal does not record which tree started one. They are a WARN, not a
  FAIL, because one may be another agent's live run.
- **Leftover tmux** = a pane whose cwd is the kelpie dir of some worktree of this repo
  (`git worktree list`, 104 trees today) and that is busy: it runs a non-shell, or it is a shell
  with a child process (`bash run.sh`; the reviewer caught that a plain command filter missed
  this). Proven with a throwaway session running `bash run.sh`: WARN, then PASS once it was
  killed. Doctor reports both kinds with a manual stop command and never stops anything itself.
- **Output** is plain aligned text, not observe spans: `observe` is at the repo root and not a
  dependency of kelpie-http. For a list of verdicts with fixes, aligned lines read best.

## Uncertain

- **hfpat.** Nothing in the repo names it, so the tmux/sandbox filters are my guess at "what
  this repo started". A session running python in `~/research-2` would show; a leftover idle
  shell would not.
- **Revision.** The weights check accepts ANY snapshot. It does not follow `refs/main`, so an
  old revision passes.
- **The running `box` sandbox** `ta-01M3DFG09K7FW0ZVA3VQ72CE6S` (since 16:48 today) showed in
  every --remote run. I did not stop it. Please check whether it is yours.
- **`kelpie check`** (kelpie.toml `[requires]`) already exists with its own `CheckResult`. It
  should probably fold into doctor's `Check` when `kelpie check` is re-cut. I left it alone.
- **Shard 0.** gpt-oss numbers its shards 00000..00002 "of 00002". The check requires 1..N, so
  a missing 00000 passes. The index that would say so is a symlink the Modal CLI cannot read.
- **Deleting a source** moves no mtime, so deleting one alone does not mark the lib stale.
- **Rule 21 (no history in comments).** The "why each check exists" lines in the module
  docstrings name past incidents. I kept them as the reason for each check. The reviewer flagged
  them as history.
- **The ssh-box doctor overlap** is gone: that tooling is deleted from this repo,
  and docs/CODING_STANDARDS.md "Running the gate" runs `kelpie doctor`.

## Papercuts

1. **zig resets libkelpie's mtime.** `zig build lib` installs from its cache with the cached
   file's mtime. So a touched but unchanged source leaves the lib "older" even after a
   successful build, and the next no-op build undoes a manual `touch`. That is why the fix text
   is `zig build lib && touch <lib>`. A branch switch (new mtimes, same content) makes doctor
   FAIL until the next touch. The durable fix is a content stamp: build.zig hashes the sources
   into an exported symbol and doctor compares. That means a kelpie-core change plus a second
   writer of "the source set". TODO(2026-09-25) if the false FAIL bites.
2. **scripts/test rewrites kelpie-engine/uv.lock.** Its plain `uv run` did exactly that in this
   fresh worktree (+192 lines), and doctor caught it (WARN, restored with the printed fix).
   scripts/test should pass `--frozen`.
3. **`.claude/` is gitignored at the repo root**, so the verify-kelpie skill had to be
   `git add -f`'d.
4. **Touching a source that does not exist creates it.** In proof (a) I first touched
   `src/plan.zig` and `src/engine.zig`, which do not exist. Deleted; the proof uses
   `src/scheduler.zig`.
5. **modal_run.py defaults `--volume kelpie-data`**, but every docstring and note uses
   `kelpie-a1`. Doctor defaults to kelpie-a1, as asked.
6. **The shim symlink chains into another project.** The shim symlink target
   (`worktrees/core-option2/.../build`) is itself a symlink into another project, so
   this tree depends on a directory outside it. (`box setup --local` now fixes this.)

## Review

An independent subagent reviewed the diff and found 12 things. Fixed:
- Git, tmux and Modal failures now become a Check instead of crashing doctor. Modal rows are
  parsed with required keys at the boundary.
- A shell running a script now counts as busy.
- tmux is scoped to the kelpie trees, and the sandbox line says "any tree".
- A failed `modal volume ls` reports Modal's error, not "no config.json".
- The uv.lock fix restores from HEAD, so a staged rewrite is also undone.
- `_ffi.load`'s AttributeError is caught.
- Dotfiles are no longer counted as sources.
- HF_HUB_CACHE is honoured.

Left open: the shard 0 and deleted-source limits, rule 21, and a
not-yet-real subcommand (`kelpie bench`) falling through to serve's argparse error.
