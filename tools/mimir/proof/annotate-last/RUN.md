# Proof: `--last` stays on this cwd / this agent

From this worktree:

```
cd /Users/chiraagbalu/silares_stuff/mimir/worktrees/annotate-last-session
PYTHONPATH=. uv run pytest tests/test_annotate_last.py -v
```

All six tests should pass. The ones that name the bug:

- `test_claude_prefers_this_cwd_not_other_project` — another repo's newer Claude jsonl is ignored
- `test_missing_claude_id_does_not_fall_back_to_other_project` — a bad `CLAUDE_CODE_SESSION_ID` errors instead of `sources[0]`
- `test_grok_agent_does_not_open_claude` — `GROK_AGENT=1` never returns Claude text
- `test_grok_agent_without_session_does_not_fall_through_to_claude` — Grok fingerprint + missing session does not open Claude
- `test_no_env_uses_cwd_not_global_newest` — with no env vars, a newer other-project Claude session loses to this cwd

See which session *this* process would open:

```
cd /Users/chiraagbalu/silares_stuff/mimir/worktrees/annotate-last-session
PYTHONPATH=. uv run python -c "
from mimir.annotate import _load_session_messages
ms = _load_session_messages(max_messages=1)
print(ms[0].preview)
"
```

stderr prints `mimir annotate --last · grok|claude <path>`. That path must be this repo / this Grok session, not some other Claude project under `~/.claude/projects`.
