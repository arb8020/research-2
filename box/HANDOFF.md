# box handoff (end of 2026-10-09)

Next session: reverify, speed up tests, then read the code together.

## Where things are

- **`box/lease`**, worktree `worktrees/box-lease`, at `ebf3b69b`. This is the integration branch: everything below is merged into it except `box/compress`. Nothing is merged to main and nothing is pushed.
  - lease + ceiling + `max_duration`
  - `Machine.stream`, streamed logs
  - `close()` → `Receipt`
  - Colab provider
  - anyio portal for Modal
  - box-dev primitives (names, pty, `expose`/`proxy`, shell, `gitsync`)
  - `.box/setup` snapshots
  - relay `--image`/`--volume`
  - comment sicko
  - `MUST KILL` fixes
  - testmon
- **`box/compress`**, worktree `worktrees/box-compress`, at `800476ee`. Five commits on top of box/lease, **not merged and not reverified**:
  1. file format in `supervisor.py`
  2. one `Place` reader (live | record)
  3. one creation pipeline (`plan_setup → create → wait_up → prepare`, `closing_on_error`)
  4. layering (`Session.used`, `files.py`, `Job.tee`, gitsync knows no session)
  5. `files.check`

  Its testmon run covered the suite after step 4 and passed. The live Modal subset and `overnight.py` were skipped on purpose.
- **`blogs/lease`**, worktree `worktrees/blogs-lease`: the page side. It adds the session length, Extend, requires `lease_until`, redacts the kernel token, and accepts a null `started_at` when a session ends. It's 24 commits ahead of `blogs/flappy`, not merged.
- **Running:** tmux `reader-path` serves the relay on :8790 and the page on :8012, both on box/lease code. No sandboxes or Colab runtimes are live (swept at the end).

## Line counts

| | core | providers | gateway | tests |
|---|---|---|---|---|
| box/lease | 2655 | 2073 | 1100 | 3508 |
| box/compress | 2678 | 2083 | 1077 | 3514 |

The compress consolidated concepts but barely changed the line count:
- `sdk.py` went from 1194 to 1008 lines.
- `supervisor.py` went from 515 to 657, because the format moved there.

## 1. Reverify (in this order)

```
cd worktrees/box-compress/box
uv run --extra dev --extra colab pytest -q          # ~7 min; should be ~171 passed
uv run python examples/overnight.py                 # Modal CPU, ~5 min: the record-from-Volume path step 2 changed
```

Merge `box/compress` into `box/lease` only after both pass.

Other proofs, if needed:
- `uv run --extra dev --extra colab python -m box.tests.smoke_colab --detached-minutes 5`, on the logged-in 400-unit Colab account.
- `uv run --with playwright verify_connect.py` in `blogs-lease/blogs`.

## 2. Test speed-up (first piece of work)

The suite takes ~7 min. It's real timer waits plus running serially, not compute. testmon helps on leaf edits (17 s) but not core edits (~160 s). Agents spent 35–50% of their time waiting on tests today.

Options, ranked:
1. Run in parallel with `pytest-xdist -n auto`. Relay tests must bind port 0.
2. Make the clocks configurable for tests: supervisor poll/heartbeat/flush/linger, and the relay's `min_lease_s`. **Undecided:** a `Timing` knob vs keeping fixed constants (Tiger Style).
3. Apply the test sicko's 28 kills, including the 60 s relay lease test and the 14 s record-follow test.
4. Tighten the slow survivors.
5. Wait on conditions, not sleeps.
6. Add a module-scoped `shared_session` fixture for the ~30–40 tests that never end their session. This is a big win for live Modal/Colab runs.
7. Add a `-m fast` tier.

Expected: 1 + 2 + 3 take the suite from ~7 min to under a minute (an estimate).

Also in this test pass:
- **Add `--provider colab`** (real Colab) next to `colab-fake`.
- **Run live on Colab only.** Modal has had enough live runs.
- **Two test-sicko judgement calls:**
  - rewrite `test_closing_mid_job_still_runs_its_hook` to use `close()`, or kill it?
  - replace the setup-key tests with pure key/expiry tests?
- **The gap tests the test sicko listed:** `/proc/net/tcp` parse, RunPod `GET /pods` fixture, a real Colab token expiry, relay limits. Per the updated `CODING_STANDARDS.md`, the author approves new tests before they're added.

## 3. Read the code together

Start with `sdk.py` on `box/compress`. Decision comments were removed on purpose; the reasons are in the commit messages, so use `git log -p`.

The two big cuts deferred by choice:
- polling instead of the tail protocol (−170 lines);
- the unused box-dev capabilities (−300).

A further compress should have a hard line target and should list candidate cuts before editing anything.

## Then

- **CLI reshape:** `box <verb> <id|name>`, e.g. `box up/run/sync/sh/port/logs/attach/extend/release/kill <name>`. `box dev` folds into these. It's on `worktree-agent-a7fdb11404b864483`, on the old API, and kelpie's `kelpie dev` builds on it.
- **Merges:** `box/lease` → main, `blogs/lease` → `blogs/flappy`.

## Open questions

- `release` semantics: end now (today), or hand back to the idle timer (as SF's hold release does)?
- Should `box run <name> -- cmd` sync by default (as SkyPilot does), with `--no-sync`?
- Configurable timing for tests? (see 2)
- Which team needs `box dev`? (The blogs team doesn't use it.)
- Colab `_jupyter_error` still guesses Jupyter vs proxy 404 from the content-type; settle it with a live check.
- Secrets: which ones, and setup-only or provider store?

## Waiting on us

- **Blogs engine curriculum session** (research-2-b4): pinned at `42c05b12` and reading `lease_until`. They want the commit to pin after the creation refactor, so send it once `box/compress` is reverified and merged. They already know about the `deadline` removal, the nullable `started_at`, and finding Jupyter by name (don't upgrade the relay during live sessions).

## Papercuts

- **Tests:** each agent's full suite run took ~7 min, and briefs that asked for one "per step" made it much worse. Now briefs ask for testmon while iterating plus one run that covers everything (see `CODING_STANDARDS.md`).
- **`git stash`:** two agents touched the shared stash, and one popped `stash@{0}` (restored). Briefs now ban it.
- **Sandbox cleanup:** label-based cleanup once killed another agent's sandbox, so use a unique label per agent.
- **Background bash is blocked for subagents.** They poll tests in tmux, which hides the waiting time.
