# Proof: shared render/source toggle

From this worktree:

```
cd /Users/chiraagbalu/silares_stuff/mimir/worktrees/html-annotate
PYTHONPATH=. uv run python -c "import sys; sys.argv=['mimir','annotate','--port','8765','proof/show-me-toggle.html']; from mimir.cli import main; main()"
```

Browser opens. The page should be RENDERED (not source). Header has render|source. Click source → CodeMirror of the HTML. Click render → iframe again. Select text → comment toolbar.
