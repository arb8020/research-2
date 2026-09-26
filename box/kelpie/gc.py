"""The kelpie layer's part of `box gc`: its caches, on the volumes it uses and on this machine.

    cache   on each kelpie-* volume: a builds/<artifact>/<key> whose .used (setup touches it on
            every hit) is older than --cache-days, or a build that died (no .complete);
            box-runs/*.jsonl older than --cache-days. Zig installs are left alone. The volumes
            themselves are data and are never deleted.
    local   ~/.cache/kelpie/xgrammar/<key> that no worktree of this repo links to, deleted under
            its build lock (a key being built is skipped).
"""

from __future__ import annotations

import fcntl
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from box.gc import DAY_S, Candidate
from box.kelpie import local
from box.provider import Provider, Volume

DATA_PREFIX = "kelpie-"
ARTIFACTS = ("xgrammar", "libkelpie")
USED = ".used"
COMPLETE = ".complete"


def collect(provider: Provider, repo: Path, cache_days: float) -> tuple[list[Candidate], list[str]]:
    now = time.time()
    max_age_s = cache_days * DAY_S
    data = [name for name, _ in provider.volumes() if name.startswith(DATA_PREFIX)]
    found = [c for name in data for c in caches(provider.volume(name), max_age_s, now)]
    found += local_caches(repo)
    notes = [
        f"kelpie caches swept on: {', '.join(data)} (volumes kept)",
        f"kelpie local: {local.XGRAMMAR_CACHE} ({'exists' if local.XGRAMMAR_CACHE.is_dir() else 'absent'})",
    ]
    return found, notes


def caches(vol: Volume, max_age_s: float, now: float) -> list[Candidate]:
    top = {e.path for e in vol.ls("/")}
    found = []
    if "builds" in top:
        listing = [(e.path, e.mtime) for e in vol.ls("builds", recursive=True)]
        found += [_cache(vol, key_dir, why) for key_dir, why in stale_keys(listing, max_age_s, now)]
    if "box-runs" in top:
        for entry in vol.ls("box-runs"):
            if now - entry.mtime > max_age_s:
                found.append(_cache(vol, entry.path, f"run log {(now - entry.mtime) / DAY_S:.0f} d old"))
    return found


def stale_keys(listing: list[tuple[str, float]], max_age_s: float, now: float) -> list[tuple[str, str]]:
    """(key dir, why) for each builds/<artifact>/<key> in a recursive (path, mtime) listing that is
    stale: its .used is older than max_age_s, or it has no .complete and its newest file is (a
    build that died). A complete key with no .used is never stale: setup from a checkout before
    .used existed may still use it every day."""
    marks: dict[str, dict[str, float]] = {}
    for path, mtime in listing:
        parts = path.split("/")  # builds/<artifact>/<key>[/<file>...]
        if len(parts) < 3 or parts[1] not in ARTIFACTS:
            continue
        key = marks.setdefault("/".join(parts[:3]), {"newest": mtime})
        key["newest"] = max(key["newest"], mtime)
        if len(parts) == 4 and parts[3] in (USED, COMPLETE):
            key[parts[3]] = mtime
    stale = []
    for key_dir, key in sorted(marks.items()):
        if USED in key and now - key[USED] > max_age_s:
            stale.append((key_dir, f"used {(now - key[USED]) / DAY_S:.0f} d ago"))
        elif COMPLETE not in key and now - key["newest"] > max_age_s:
            stale.append((key_dir, f"incomplete build, last written {(now - key['newest']) / DAY_S:.0f} d ago"))
    return stale


def _cache(vol: Volume, path: str, why: str) -> Candidate:
    return Candidate("cache", f"{vol.name}:{path}", why, lambda: vol.rm(path))


def local_caches(repo: Path) -> list[Candidate]:
    linked = local.linked_keys(repo)
    root = local.XGRAMMAR_CACHE
    keys = sorted(p for p in root.iterdir() if not p.name.endswith(".lock")) if root.is_dir() else []
    return [
        Candidate("local", str(key_dir), "no worktree links to it", _locked_rmtree(key_dir))
        for key_dir in keys
        if key_dir.resolve() not in linked
    ]


def _locked_rmtree(key_dir: Path) -> Callable[[], None]:
    """Delete under the key's build lock; a key some worktree is building now is not linked yet."""

    def delete() -> None:
        with (key_dir.parent / f"{key_dir.name}.lock").open("w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print(f"  skipped {key_dir}: being built")
                return
            shutil.rmtree(key_dir)

    return delete
