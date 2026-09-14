# Review: `mimir annotate --last` session picker

Diagnostic only. Compared `mimir/annotate.py` (session loading), `tests/test_annotate_last.py`, and `proof/RUN.md` to the four intended rules.

## Verdict

The uncommitted picker **matches the intended rules**. The old bugs (global `discover()[0]`, missing Claude id → another project, Grok fingerprint → Claude) are gone in this code.

```
if GROK_SESSION_ID or GROK_AGENT:
    grok only; missing → SystemExit          # never Claude
elif CLAUDE_CODE_SESSION_ID:
    that jsonl only; missing → SystemExit    # never another project
else:
    grok cwd-slug
    then claude cwd-slug (plannotator re.sub)
    then claude ancestor cwd
    else SystemExit("no session found for this directory")
```

Slug is `re.sub(r"[^a-zA-Z0-9-]", "-", cwd)` in `_claude_project_slug`. No global newest-across-`~/.claude/projects`.

## Rule check

1. **Grok fingerprint → Grok only.** `prefer_grok` short-circuits. Failed / empty Grok load raises, does not call Claude. `GROK_SESSION_ID` alone is enough (no need for `GROK_AGENT`). If both Grok and Claude env are set, Grok wins.

2. **`CLAUDE_CODE_SESSION_ID` (and not Grok) → that jsonl only.** `resolve_claude_log` with an id does `projects/*/{id}.jsonl`. Missing id / empty parse → `SystemExit("no Claude session found for …")`. Does not walk cwd or other projects for a substitute session.

3. **No fingerprint → Grok cwd, Claude cwd, Claude ancestor. Never global newest.** Grok group is `quote(Path.cwd(), safe="")`. Claude uses `PLANNOTATOR_CWD` or `getcwd()`, newest `.jsonl` in that slug dir, then parents via `_claude_logs_ancestor`. Sibling project dirs are never scanned as a pool.

4. **Claude slug is plannotator's.** Production regex matches the spec. Tests write dirs with an `isalnum()` helper that agrees on ASCII paths (tmp paths in the suite).

## Remaining holes (none are the original bug)

Expected / out of scope:

- **PID walk not ported.** Claude Code can recover a session by walking parent PIDs. This picker does not. Missing `CLAUDE_CODE_SESSION_ID` is an error (fingerprinted) or cwd/ancestor (not). That is the specified contract.

Real but small:

- **Empty transcript after a hit still counts as a miss.** File found, no completed-turn assistant text → loader returns `None`. With a fingerprint that is an error (good). With no fingerprint, Grok-empty falls through to Claude for this cwd/ancestor. Not "global newest", but it is a failed Grok load into Claude when no env is set.
- **Grok cwd ignores `PLANNOTATOR_CWD`.** Claude honors it; Grok always uses `Path.cwd()`. A subprocess that only sets `PLANNOTATOR_CWD` can Groks-miss then Claude-hit a different tree.
- **Grok explicit-id glob is unsorted.** `list(root.glob(f"*/{id}/chat_history.jsonl"))[0]` if the same id exists under two cwd encodings. Claude id collisions pick newest mtime. Rare.
- **`GROK_AGENT=0` is truthy.** Any non-empty value locks the Grok-only path.
- **Ancestor can walk to `/`.** First parent slug that has any jsonl wins — including a parent checkout (e.g. worktree → main repo). Intended by rule 3, easy to misread as "wrong project" in a live run.
- **Case-insensitive Claude dir fallback** (`child.name.lower() == slug.lower()`) is extra vs the spec. Fine on typical macOS volumes.

Not a hole: explicit Claude id may live under another project dir. That is "this jsonl", not "newest in that other project".

## Test gaps

Six tests lock the reported bug. They do **not** cover the whole rule 3 ladder.

Covered:

- this-cwd Claude over a newer other-project jsonl
- bad `CLAUDE_CODE_SESSION_ID` errors (no `sources[0]`)
- `GROK_AGENT` + `GROK_SESSION_ID` returns Grok text
- `GROK_AGENT` and no Grok session errors (no Claude)
- no env: this-cwd Claude, not global newest
- Grok current-turn skip (parsing, not picking)

Missing:

- **Claude ancestor cwd.** Rule 3's third step has no test. A worktree with no own slug and a parent repo jsonl is unasserted.
- **No-env prefers Grok cwd-slug over Claude.** Fallthrough order is untested when both exist.
- **`GROK_SESSION_ID` without `GROK_AGENT`** vs a Claude session (the combined test sets both).
- **Bad `GROK_SESSION_ID`** errors with the id in the message (the no-session test is `GROK_AGENT` only).
- **`_claude_project_slug` vs `_` / `.` / non-ASCII.** Test writer uses `isalnum()`, which is not the ASCII regex (`_` and unicode letters diverge).
- **`PLANNOTATOR_CWD`** vs process cwd.
- Isolation: `test_claude_prefers_this_cwd_not_other_project` does not set `GROK_HOME`. Harmless for a unique tmp cwd; sloppy.

## Can the user prove it via `proof/RUN.md`?

**Yes for the original bug. Partially for the full contract.**

1. `PYTHONPATH=. uv run pytest tests/test_annotate_last.py -v` — six tests, all aimed at "wrong project / wrong agent". If they pass, the fallthrough and global-newest bugs are gone.

2. The live `python -c "_load_session_messages…"` print is a real check of *this* process:
   - stderr: `mimir annotate --last · grok|claude <path>`
   - under a Grok agent (`GROK_SESSION_ID` / `GROK_AGENT`) the path must be this Grok history, never `~/.claude/projects/<other-slug>/…`
   - in a bare shell it may legally pick Claude ancestor (parent mimir checkout). RUN.md says "this repo / this Grok session"; ancestor-of-worktree is allowed by rule 3 and can look like a miss.

RUN.md does not exercise ancestor, slug characters, or `PLANNOTATOR_CWD`. Pytest is the proof for the bug; the one-liner is a smoke test that this session is not some other Claude project.
