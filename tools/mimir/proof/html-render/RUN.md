# Proof: shared render/source toggle

From research-2:

```
cd ~/research-2/tools/mimir
PYTHONPATH=. uv run python -c "import sys; sys.argv=['mimir','annotate','--port','8765','proof/html-render/show-me-toggle.html']; from mimir.cli import main; main()"
```

Browser opens. The page should be RENDERED (not source). Header has render|source. Click source → CodeMirror of the HTML. Click render → iframe again. Select text → comment toolbar.
