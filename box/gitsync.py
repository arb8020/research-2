"""Code onto a machine by git: snapshot this worktree, send the objects the machine lacks, check out.
Session.sync is the way in; this module needs only a Machine's exec and write.

    sync(machine, repo, paths=("kelpie",), force=False, keep="refs/box/<name>", touch=<file>) -> Synced

    here     snapshot   temp index (a copy of the worktree's, for its stat cache) + `add -u` (tracked
                        files as on disk) + `add -A -- paths` (untracked ones only there: a repo's
                        untracked clutter stays home) -> write-tree -> commit-tree -p <parent>
             pack       pack-objects --revs <new> ^<parent>: only what the machine lacks. parent =
                        this worktree's last sync, else another worktree's on the same machine.
                        It must be the parent: `^X` for an X that is not an ancestor excludes
                        nothing (measured: 200 kB either way, vs 236 B as the parent).
    machine  APPLY      index-pack, then a two-tree read-tree from the last synced commit to the new
                        one (adds, edits, deletes, modes, symlinks), then move HEAD.

On the machine, <work>/.box.git is one object store for every worktree synced there, and each
worktree is a linked git worktree of it at <work>/<worktree dir name>, with its own HEAD (the last
synced snapshot) and index. So `git status` there shows what changed on the machine since the sync,
and a sync refuses (Drift) to overwrite a tracked file changed there, unless force.

`keep` + /<worktree> is a local ref to the last synced snapshot: it keeps those objects from local
gc, so the next pack can exclude them.
"""

from __future__ import annotations

import base64
import os
import secrets
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from box.sdk import Machine

STORE = ".box.git"  # under machine.work; not .git, so git in <work>/<worktree> never finds it by walking up
MAX_PACK_BYTES = 256 << 20  # a sync is source code; past this something big is tracked or under paths
GIT_TIMEOUT_S = 300.0  # one local git command (a pack of MAX_PACK_BYTES takes seconds)
INLINE_PACK_BYTES = 64 << 10  # up to this, the pack rides in the apply exec (base64) instead of a write
ORIGIN = "box sync from "  # snapshot message prefix; then the absolute path of the local worktree
IDENTITY = {"GIT_AUTHOR_NAME": "box", "GIT_AUTHOR_EMAIL": "box@localhost", "GIT_COMMITTER_NAME": "box", "GIT_COMMITTER_EMAIL": "box@localhost"}
NO_GIT, MOVED, DRIFT = 3, 4, 6  # APPLY's exit codes for the cases a caller is told about


@dataclass(frozen=True)
class Synced:
    """What a sync did."""

    commit: str  # the snapshot commit now checked out on the machine
    path: str  # where: machine.work/<worktree dir name>
    pack_bytes: int  # what was sent; 0 when nothing changed


class Drift(Exception):
    """Tracked files changed on the machine since the last sync (a run wrote them); force overwrites."""


class Moved(Exception):
    """The machine's copy is not the snapshot this sync was built on (another sync got there first,
    or another worktree with the same directory name syncs to this machine)."""


# The machine's side of a sync, before the pack is sent: is git there, what did we last sync.
# It also touches $TOUCH (the session's activity file): one round trip fewer than its own exec.
PROBE = """
set -euo pipefail
touch "$TOUCH"
command -v git >/dev/null || { echo "box sync: no git on the machine (its image needs git)" >&2; exit 3; }
mkdir -p "$W" && { [ -d "$G" ] || git init -q --bare "$G"; }
if [ -e "$T/.git" ]; then git -C "$T" log -1 --format='own %H%norigin %s' HEAD; fi
for dot in "$W"/*/.git; do if [ -e "$dot" ]; then git -C "${dot%/.git}" log -1 --format='have %H' HEAD; fi; done
"""

# ... and after: the objects are in the pack at $PACK; check out $NEW where $OLD was.
APPLY = """
set -euo pipefail
lock="$G/box-sync-$WT"
mkdir "$lock" 2>/dev/null || { echo "box sync: another sync of $WT is running here (if none is: rm -r $lock)" >&2; exit 4; }
trap 'rm -rf "$lock" "$PACK"' EXIT
git --git-dir="$G" index-pack --stdin < "$PACK" >/dev/null
if [ ! -e "$T/.git" ]; then
  [ -z "$OLD" ] || { echo "box sync: $T is gone; expected it at $OLD" >&2; exit 4; }
  git --git-dir="$G" worktree add -q --no-checkout --detach "$T" "$NEW"
  git -C "$T" read-tree --reset -u HEAD
  exit 0
fi
cur=$(git -C "$T" rev-parse HEAD)
[ "$cur" = "$OLD" ] || { echo "box sync: $T is at $cur, not $OLD (another sync got there first?)" >&2; exit 4; }
if [ "$FORCE" = 1 ]; then
  git -C "$T" read-tree --reset -u "$NEW"
else
  git -C "$T" update-index -q --refresh >/dev/null || true
  drift=$(git -C "$T" diff-files --name-only)
  [ -z "$drift" ] || { echo "$drift" >&2; exit 6; }
  git -C "$T" read-tree -m -u "$cur" "$NEW"
fi
git -C "$T" update-ref --no-deref HEAD "$NEW" "$cur"
"""


def sync(machine: Machine, repo: Path, *, paths: tuple[str, ...], force: bool, keep: str, touch: str) -> Synced:  # noqa: PLR0913
    """Two round trips: PROBE (and the touch of `touch`, the session's activity), then the pack and
    APPLY in one exec when it is small (else a write first). Drift, Moved: see their docstrings."""
    top = Path(git(repo, "rev-parse", "--show-toplevel"))
    origin = f"{ORIGIN}{top}"
    where = {"W": machine.work, "G": f"{machine.work}/{STORE}", "T": f"{machine.work}/{top.name}", "WT": top.name}
    rc, out, err = machine.exec(assign({**where, "TOUCH": touch}) + PROBE)
    if rc == NO_GIT:
        raise RuntimeError(err.strip())
    if rc != 0:
        raise RuntimeError(f"{machine.id}: box sync probe exited {rc}: {err.strip()}")
    probed = [line.split(" ", 1) for line in out.splitlines()]
    own = {k: v for k, v in probed if k in ("own", "origin")}
    old = own.get("own", "")
    if old and own["origin"] != origin and not force:
        raise Moved(f"{where['T']} on {machine.id} was synced {own['origin']!r}, not from {top}; force=True replaces it")
    # The parent is only what the pack is cut against: this worktree's last sync, else any snapshot
    # the machine holds (another worktree's) that we hold too; else nothing, and a full pack.
    have = [old] if old else []
    have += [sha for k, sha in probed if k == "have" and sha != old]
    parent = next((sha for sha in have if has_commit(top, sha)), None)
    tree = snapshot(top, paths)
    if parent is not None and parent == old and tree == git(top, "rev-parse", f"{old}^{{tree}}"):
        return Synced(old, where["T"], 0)  # nothing changed since the last sync
    new = git(top, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", origin, env=IDENTITY)
    data = pack(top, new, exclude=parent)
    incoming = f"{where['G']}/incoming-{secrets.token_hex(4)}.pack"
    if len(data) <= INLINE_PACK_BYTES:  # the usual few-file edit: in the apply exec itself, one round trip fewer
        send = f"base64 -d > {incoming} <<'BOX_PACK'\n{base64.b64encode(data).decode()}\nBOX_PACK\n"
    else:
        machine.write(incoming, data)
        send = ""
    rc, _, err = machine.exec(assign({**where, "OLD": old, "NEW": new, "PACK": incoming, "FORCE": "1" if force else "0"}) + send + APPLY)
    if rc == DRIFT:
        raise Drift(f"changed on {machine.id} since the last sync (force=True overwrites):\n{err.rstrip()}")
    if rc == MOVED:
        raise Moved(err.strip())
    if rc != 0:
        raise RuntimeError(f"{machine.id}: box sync apply exited {rc}: {err.strip()}")
    git(top, "update-ref", f"{keep}/{top.name}", new)
    return Synced(new, where["T"], len(data))


def snapshot(top: Path, paths: tuple[str, ...]) -> str:
    """The tree of the worktree as it is on disk: tracked files repo-wide, untracked ones under paths."""
    for p in paths:
        if not (top / p).exists():
            raise FileNotFoundError(f"box sync: paths {p!r}: no {top / p}")
    with tempfile.TemporaryDirectory(prefix="box-sync-") as tmp:
        index = Path(tmp) / "index"
        real = Path(git(top, "rev-parse", "--path-format=absolute", "--git-path", "index"))
        env = {"GIT_INDEX_FILE": str(index)}
        if real.exists():
            shutil.copyfile(real, index)  # its stat cache: `add -u` rehashes only what changed
        else:
            git(top, "read-tree", "HEAD", env=env)
        git(top, "add", "-u", "--", ":/", env=env)
        if paths:
            git(top, "add", "-A", "--", *(f":/{p}" for p in paths), env=env)
        return git(top, "write-tree", env=env)


def pack(top: Path, new: str, *, exclude: str | None) -> bytes:
    revs = f"{new}\n" + (f"^{exclude}\n" if exclude else "")
    data = subprocess.run(
        ["git", "pack-objects", "--revs", "--stdout", "-q"], cwd=top, input=revs.encode(), capture_output=True, check=True, timeout=GIT_TIMEOUT_S,
    ).stdout  # fmt: skip
    if len(data) > MAX_PACK_BYTES:
        raise ValueError(f"box sync: {len(data) >> 20} MiB to send (limit {MAX_PACK_BYTES >> 20}); is something big tracked or under paths?")
    return data


def has_commit(top: Path, sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=top, capture_output=True, timeout=GIT_TIMEOUT_S).returncode == 0


def git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=GIT_TIMEOUT_S)
    if done.returncode != 0:
        raise RuntimeError(f"box sync: `git {' '.join(args)}` in {cwd} exited {done.returncode}: {done.stderr.strip()}")
    return done.stdout.strip()


def assign(values: dict[str, str]) -> str:
    return "".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items())
