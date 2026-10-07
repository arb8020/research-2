"""`kelpie gc [--yes] [--cache-days 7]`: kelpie's caches, on its Modal volumes and on this machine.

    cache   on each kelpie-* volume: a builds/<artifact>/<key> whose .used (setup touches it on
            every hit) is older than --cache-days, or a build that died (no .complete);
            box-runs/*.jsonl older than --cache-days. Zig installs are left alone. The volumes
            themselves are data and are never deleted.
    local   ~/.cache/kelpie/xgrammar/<key> that no worktree of this repo links to, deleted under
            its build lock (a key being built is skipped).

Lists only; --yes deletes. Volumes are Modal's (box knows machines, not volumes), so this talks to
the Modal SDK directly; it runs in box's environment, which has it (cli.py re-executes there).
"""

from __future__ import annotations

import argparse
import fcntl
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from kelpie_http.dev import local

if TYPE_CHECKING:
    import modal

DAY_S = 86400
DATA_PREFIX = "kelpie-"
ARTIFACTS = ("xgrammar", "libkelpie")
USED = ".used"
COMPLETE = ".complete"


@dataclass(frozen=True)
class Candidate:
    kind: str  # cache | local
    what: str
    why: str
    delete: Callable[[], None]


def volume_caches(max_age_s: float, now: float) -> tuple[list[Candidate], list[str]]:
    import modal  # only here: the local half and the pure rule below need no Modal

    names = sorted(
        n
        for n in (v.info().name for v in modal.Volume.objects.list())
        if n and n.startswith(DATA_PREFIX)
    )
    found = [
        c for name in names for c in caches(modal.Volume.from_name(name), name, max_age_s, now)
    ]
    return found, [f"caches swept on: {', '.join(names) or 'no kelpie-* volume'} (volumes kept)"]


def caches(vol: modal.Volume, name: str, max_age_s: float, now: float) -> list[Candidate]:
    top = {e.path for e in vol.listdir("/")}
    found = []
    if "builds" in top:
        listing = [(e.path, float(e.mtime)) for e in vol.listdir("builds", recursive=True)]
        found += [
            _cache(vol, name, key_dir, why) for key_dir, why in stale_keys(listing, max_age_s, now)
        ]
    if "box-runs" in top:
        for e in vol.listdir("box-runs"):
            if now - e.mtime > max_age_s:
                found.append(
                    _cache(vol, name, e.path, f"run log {(now - e.mtime) / DAY_S:.0f} d old")
                )
    return found


def stale_keys(
    listing: list[tuple[str, float]], max_age_s: float, now: float
) -> list[tuple[str, str]]:
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
            stale.append(
                (
                    key_dir,
                    f"incomplete build, last written {(now - key['newest']) / DAY_S:.0f} d ago",
                )
            )
    return stale


def _cache(vol: modal.Volume, name: str, path: str, why: str) -> Candidate:
    return Candidate("cache", f"{name}:{path}", why, lambda: vol.remove_file(path, recursive=True))


def local_caches(repo: Path) -> list[Candidate]:
    linked = local.linked_keys(repo)
    root = local.XGRAMMAR_CACHE
    keys = (
        sorted(p for p in root.iterdir() if not p.name.endswith(".lock")) if root.is_dir() else []
    )
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="kelpie gc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--yes", action="store_true", help="delete the candidates (default: list them)")
    p.add_argument("--cache-days", type=float, default=7.0)
    p.add_argument(
        "--no-volumes", action="store_true", help="only this machine's caches (no Modal calls)"
    )
    a = p.parse_args(argv)
    now = time.time()
    found, notes = (
        ([], ["volumes skipped (--no-volumes)"])
        if a.no_volumes
        else volume_caches(a.cache_days * DAY_S, now)
    )
    found += local_caches(local.KELPIE.parent)
    notes.append(
        f"local: {local.XGRAMMAR_CACHE} ({'exists' if local.XGRAMMAR_CACHE.is_dir() else 'absent'})"
    )
    for note in notes:
        print(f"kelpie gc: {note}")
    for c in found:
        print(f"  {c.kind:<6} {c.what}\n         {c.why}")
    if not a.yes:
        print(f"kelpie gc: {len(found)} candidate(s); nothing deleted (--yes deletes them)")
        return 0
    for c in found:
        c.delete()
        print(f"  deleted {c.kind} {c.what}")
    print(f"kelpie gc: deleted {len(found)}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
