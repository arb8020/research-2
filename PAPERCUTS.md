
## `mimir annotate` (no args) — browse mode is broken

**Bug:** `resolve_target()` defaults to `paths=["."]`. Frontend auto-selects `"."`, calls `fetchFile(".")`, server 404s because `"."` is a directory.

**Root cause:** Two-sided — server's `/api/file` only handles files (not dirs), and frontend blindly selects `paths[0]` without checking if it's a directory.

**Fix options:**
1. Frontend: when `paths` contains `"."`, don't auto-select — show tree sidebar via `/api/browse/children` and let user pick a file
2. Server: if `path` is a directory, redirect to `/api/browse/children` response instead of 404
3. Use plannotator's annotate primitives which already handle folders correctly (`plannotator annotate folder/`)

**Workaround:** Always pass explicit file paths: `mimir annotate somefile.py`
