# NOTES-box: one `box` CLI over the SDK; the SSH boxes out of research-2

Branch `box/modal-first`. `box` = `uv run --frozen --project box box` from the repo root.

## What changed (shape)

The `box` CLI is sugar over the SDK. Modal is one provider behind `--provider`, and kelpie is a
layer above that. A first cut made the CLI Modal-first; that was corrected mid-task and then
refactored into this shape.

```
box/
~  provider.py      SDK: + Box.labels/spawn/job, Job (logs/poll/wait/kill), Provider.list/get/
                    volumes/volume/delete_volume, Volume (ls/read/rm), Mount, LogLine, VolumeEntry
~  providers/modal.py   implements all of it (fifo entrypoint: the spawned job is the sandbox's
                        main process); new filesystem API for upload/download/spawn
~  providers/runpod.py  NotImplementedError naming what is missing for each new method
+  recipe.py        Recipe: launch kwargs + job, in SDK terms; plain(image, volumes, cmd, timeout)
+  runs.py          labels `box run` writes (by, cmd, started, user, limit) and parse(Box) -> Run
+  gc.py            generic candidates: labelled boxes past their limit, box-* scratch volumes
+  cli.py           run/logs/who/kill/gc (+ kelpie's setup --local / doctor); `box` entry point
+  kelpie/__init__  kelpie Recipe: generated Dockerfile, tree/box/observe mounts, /data, job
~  kelpie/setup.py  (moved from box/setup.py) touches <key>/.used
+  kelpie/inside.py the kelpie job: ShellBox + setup + `timeout T bash -c cmd`
+  kelpie/local.py  setup --local
+  kelpie/gc.py     kelpie's caches: stale keys on kelpie-* volumes, unlinked local shim keys
~  pyproject.toml   hatchling, [project.scripts] box, editable-only; uv.lock committed
kelpie/scripts/modal_run.py  ~ deprecated wrapper (same flags + defaults) over cli.run
kelpie/scripts/box           - deleted (the SSH-box CLI)
```

```
box run [--provider P] [--profile kelpie|plain] [--detach] -- cmd
  recipe = kelpie.recipe(...) | recipe.plain(...)
  box = provider.launch(offering, image=, mounts=, volumes=, timeout=, labels=runs.labels(...))
  job = box.spawn(recipe.cmd, env={BOX_ID}, timeout=recipe.job_timeout)   # terminate on failure
  --detach: print id; return            else: follow(job.logs(follow=True)); job.wait(); terminate
box logs/kill <id>  provider.get(id).job().logs(follow) | .poll() | .kill()
box who             provider.list() -> runs.parse
box gc              gc.collect(provider) [+ kelpie.gc.collect(provider)]
```

## Judgement calls

- **Detached exec is `Box.spawn -> Job`, one per box, and the box ends with it.** On Modal,
  output from exec'd processes cannot be reattached from another process, but the entrypoint's
  output can (`from_id(id).stdout` replays it, and `.logs` keeps it after exit). So every Modal
  sandbox's entrypoint waits on a fifo, and `spawn` writes `/box/job.sh` and opens the fifo.
  Exec-only users see an idle sandbox, as before. Two races were found live and fixed. First,
  create returns before the fifo exists, so spawn waits for it (bounded at 60 s). Second, a job
  that finishes before the trigger exec returns shuts the sandbox down under that exec; this is
  treated as "started".
- **Setup moved inside the box.** Before, the client drove box.setup over ~0.7 s execs. Now the
  kelpie job runs setup and then the command, so a detached run survives its caller. This also
  fixes the old orphan case: a killed client used to leave a GPU idling until its timeout.
- **The kelpie image is now a generated Dockerfile**: oci/Dockerfile plus
  `COPY requirements.txt` plus the `uv pip install` line, in a temp dir that is also the build
  context. This lets it travel through the generic `image=` kwarg. Before, it was a Modal
  image-builder chain, which is Modal-specific. `_resolve_image` now passes the Dockerfile's dir
  as `context_dir`.
- **Provider ownership vs run ownership.** Modal's `list()`/`get()` only see sandboxes that carry
  box's `box.offering` tag, so `get` of any other id raises LookupError. The CLI adds its own
  `box.by` label on top of that, and `kill` needs both.
- **Ownership is labels** (Modal sandbox tags): `box.by="box run"` plus cmd, started, user,
  limit, and the recipe's tree and volume. `kill` takes an id only. It does NOT refuse a
  labelled run from another worktree or agent: the id is explicit, and `kill` prints what it
  stops first. Old-style modal_run sandboxes (no labels) are invisible to who/gc and refused by
  kill. `kelpie doctor` still lists them, and its fix line names `modal container stop`.
- **gc scope** (tightened after review). `--yes` deletes a labelled box only when it is past
  its own limit (the `box.limit` label, i.e. the job timeout plus 1800 s grace), which Modal should already have enforced. A
  run older than `--sandbox-hours` but within its limit is only noted: it is someone's long
  run. Boxes box did not launch are invisible to it. Volumes: gc deletes only `box-*` ("scratch"); it
  sweeps `kelpie-*` volumes but never deletes them, and ignores all others. A cache key is stale
  when its `.used` (setup touches it on every hit) is older than `--cache-days`, or when it has
  no `.complete` and its newest file is that old (a dead build). A complete key with no `.used`
  is never stale, because checkouts from before this branch don't touch `.used`. Zig installs
  are never swept. Local keys are deleted under their build flock, so a key being built is
  skipped. Defaults: 6 h, 7 d.
- **Command words are joined with spaces** (modal_run's rule, kept for compatibility), so a
  command with its own quotes or `;` must be passed as one quoted argument. The old modal_run
  docstring example was broken this way; I fixed the example, not the rule.
- **`box logs` exits with the run's status** when it follows or the run has ended, so
  `box logs <id> -f` can gate a script. `--detach` together with `--log-file` is refused.
- **`--log-file`.** It still receives every span. The sandbox writes its spans to
  `<volume>/box-runs/<sandbox id>.jsonl`, and the client appends that file after the run.
- **Defaults.** `modal_run.py` keeps `--volume kelpie-data` and `--gpu A100-80GB`. `box run`
  defaults to `kelpie-a1` (the volume doctor, the skill and every docstring already use).
- **Local shim cache.** It lives at `~/.cache/kelpie/xgrammar/<submodule sha[:12]>-<hash>`. The
  key hashes the shim sources, the platform and a recipe salt. The build runs under a flock and
  `.complete` is written last. It is built straight into the key dir, not moved there after,
  because the dylib's LC_RPATH is the build dir. On a miss, xgrammar is cloned into the tree's
  third_party/xgrammar the way box/kelpie/setup.py does in a box: `kelpie/.gitmodules` is not at the
  repo root, so `git submodule update` cannot see it.
- **The spans file is keyed by `$BOX_ID`**, which the CLI passes in the spawn env. Before, it
  used Modal's `MODAL_SANDBOX_ID`, which is provider-specific.
- **`box doctor` shells out** to `uv run --frozen kelpie doctor` in kelpie-http. box cannot
  import kelpie_http (that would pull torch into box's venv), so there is no second copy of any
  check.
- **hatchling, not setuptools.** setuptools executed `box/setup.py` as a build script (it has
  since moved to box/kelpie/). The install is editable only: it puts the repo root on
  sys.path, like `PYTHONPATH=.`.
- **scripts/test now uses `uv run --frozen`** (out of scope, but it rewrote
  kelpie-engine/uv.lock during the proof run).

## Part A (subagent, merged from box/strip-ssh-boxes)

- `kelpie/archive/` and `kelpie/docs/archive/`: all 383 files were duplicates kept elsewhere (the
  reviewer re-checked), so all were deleted. Nothing was unique to research-2.
  `archive/kelpie-models-tests` was a pure duplicate too.
- PAPERCUTS entries about the SSH tooling itself (seeker, box sync/setup) were deleted. Entries
  that only named the box now name the hardware.
- The remaining word-grep hits for the box names are all false positives: design-multigpu's
  invariant labels (and the zig comments and NOTES-rung0 citing them), the MoE down-scale
  tensors, a shell variable, and AWS-style object storage.

- **Second review of the refactor, fixes made.**
  - gc: a labelled run becomes a candidate only once it is 2 h past its limit (`box.started` is
    stamped before the image build).
  - `--profile plain` needs no kelpie checkout, and its default is no volume.
  - RunPod `launch` raises NotImplementedError before creating a paid pod.
  - `list() -> list[Box]` in both providers.
  - `box logs` refuses boxes that were not launched by `box run`, and an unknown id gives
    LookupError (rc 2).
  - `RunPod.from_env` holds the API key.
  - The kelpie image context is `~/.cache/kelpie/images/<hash>` instead of a new temp dir per run.
- **Review items left as notes.**
  - The fifo entrypoint needs `bash`, `mkfifo` and `timeout` in every Modal image, so alpine or
    distroless images die at start.
  - A second `spawn` overwrites `/box/job.sh` before it fails. This is harmless, because the job
    has already exec'd.
  - kelpie gc sweeps every `kelpie-*` volume, but deletes only `builds/<artifact>/<key>` and old
    `box-runs/*.jsonl`.

## Uncertainties

- `box logs` without `-f` on a running sandbox uses `sandbox.logs.tail(N)`. That goes through
  Modal's log store, which may lag the live stream by a few seconds.
- The tag value length limit is unknown. 300 characters worked; commands are cut to 200 in the
  tag, and the full command is kept in the entrypoint argv.
- The first run after this merge rebuilt the Modal xgrammar key (about 2.5 min), because part A
  edited a comment in build_xgrammar.sh, which is a key input. Merging main later changed zig
  sources, which cost one libkelpie rebuild (about 3.4 min).
- RunPod implements none of the new SDK methods yet; each raises NotImplementedError saying what
  it needs. The CLI therefore only works end to end on Modal today.
- `spawn` on Modal takes about 2.8 s, mostly the filesystem-API write of job.sh. An env-var or
  base64 exec would be faster.

## Papercuts

- `modal_run --log-file` was already dominated by client-side `hpack` DEBUG lines (4.8k of 4.8k
  lines); that is pre-existing.
- The laptop has 7.0 GiB free, so `kelpie doctor` FAILs its 10 GiB disk check. The proof used
  `--min-free-gib 5`.
- Main tracks ~45 stray gitlinks (kelpie/worktrees/*, kelpie/.claude/worktrees/*), so a
  root-level `git submodule status` dies.
- Sandbox log timestamps are UTC while client timestamps are local.
- Modal now refuses the legacy `Sandbox.open` filesystem API, so the old `ModalBox.upload` and
  `download` were broken on main without anyone noticing. Both are fixed here.
- Every worktree used to link its shim through another worktree (a chain ending outside this
  repo). `box setup --local` replaces that with one cache.
