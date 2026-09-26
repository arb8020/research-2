"""Run provenance: which commit produced this run, and was the tree dirty.

Lives here, not in a training script, because it exists to fill
`setup_logging(static_fields=...)` — every producer stamping a run wants the
same two fields, and none of them should need the training stack to get them.
"""

from __future__ import annotations

import subprocess

# The provenance fields, stamped on every line by setup_logging. `None` means
# "we could not ask git", which is a different fact from any real sha.
GitInfo = dict[str, str | bool | None]


def git_info() -> GitInfo:
    """Capture the short sha and dirty flag, or null provenance when git can't answer.

    `git_sha="unknown", git_dirty=False` would be a semantic fallback: a reader
    cannot tell "unknown" from a real sha, and `False` would assert a clean tree
    nobody checked. Absent provenance is its own value, so it is JSON null.

    Only the two failures that genuinely mean "there is no git to ask" are
    caught — a non-zero `rev-parse` (not a repository) and a missing binary.
    Anything else (a timeout, a permission error, a corrupt object store) is a
    real problem and propagates.
    """
    try:
        sha = (
            subprocess
            .check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        dirty = (
            subprocess.call(
                ["git", "diff", "--quiet"],
                stderr=subprocess.DEVNULL,
            )
            != 0
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"git_sha": None, "git_dirty": None}
    return {"git_sha": sha, "git_dirty": dirty}
