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

STORE = ".box.git"  # not .git: git looks for a .git in every parent directory
MAX_PACK_BYTES = 256 << 20
GIT_TIMEOUT_S = 300.0
INLINE_PACK_BYTES = 64 << 10
ORIGIN = "box sync from "
IDENTITY = {"GIT_AUTHOR_NAME": "box", "GIT_AUTHOR_EMAIL": "box@localhost", "GIT_COMMITTER_NAME": "box", "GIT_COMMITTER_EMAIL": "box@localhost"}
NO_GIT, MOVED, DRIFT = 3, 4, 6
EXIT_CODES = {"NO_GIT": str(NO_GIT), "MOVED": str(MOVED), "DRIFT": str(DRIFT)}


@dataclass(frozen=True)
class Synced:
    commit: str
    path: str
    pack_bytes: int


class Drift(Exception):
    pass


class Moved(Exception):
    pass


PROBE = """
set -euo pipefail
touch "$TOUCH"
command -v git >/dev/null || { echo "box sync: no git on the machine (its image needs git)" >&2; exit "$NO_GIT"; }
mkdir -p "$W" && { [ -d "$G" ] || git init -q --bare "$G"; }
if [ -e "$T/.git" ]; then git -C "$T" log -1 --format='own %H%norigin %s' HEAD; fi
for dot in "$W"/*/.git; do if [ -e "$dot" ]; then git -C "${dot%/.git}" log -1 --format='have %H' HEAD; fi; done
"""

APPLY = """
set -euo pipefail
lock="$G/box-sync-$WT"
mkdir "$lock" 2>/dev/null || { echo "box sync: another sync of $WT is running here (if none is: rm -r $lock)" >&2; exit "$MOVED"; }
trap 'rm -rf "$lock" "$PACK"' EXIT
git --git-dir="$G" index-pack --stdin < "$PACK" >/dev/null
if [ ! -e "$T/.git" ]; then
  [ -z "$OLD" ] || { echo "box sync: $T is gone; expected it at $OLD" >&2; exit "$MOVED"; }
  git --git-dir="$G" worktree add -q --no-checkout --detach "$T" "$NEW"
  git -C "$T" read-tree --reset -u HEAD
  exit 0
fi
cur=$(git -C "$T" rev-parse HEAD)
[ "$cur" = "$OLD" ] || { echo "box sync: $T is at $cur, not $OLD (another sync got there first?)" >&2; exit "$MOVED"; }
if [ "$FORCE" = 1 ]; then
  git -C "$T" read-tree --reset -u "$NEW"
else
  git -C "$T" update-index -q --refresh >/dev/null || true
  drift=$(git -C "$T" diff-files --name-only)
  [ -z "$drift" ] || { echo "$drift" >&2; exit "$DRIFT"; }
  git -C "$T" read-tree -m -u "$cur" "$NEW"
fi
git -C "$T" update-ref --no-deref HEAD "$NEW" "$cur"
"""


def sync(machine: Machine, repo: Path, *, paths: tuple[str, ...], force: bool, keep: str, touch: str) -> Synced:  # noqa: PLR0913  # MUST KILL: touch= (the session's activity file) rides on the probe exec, a session concern inside gitsync; let the caller prepend its own command
    top = toplevel(repo)
    origin = f"{ORIGIN}{top}"
    where = {"W": machine.work, "G": f"{machine.work}/{STORE}", "T": tree_path(machine.work, top), "WT": top.name}
    rc, out, err = machine.exec(assign({**where, **EXIT_CODES, "TOUCH": touch}) + PROBE)
    if rc == NO_GIT:
        raise RuntimeError(err.strip())
    if rc != 0:
        raise RuntimeError(f"{machine.id}: box sync probe exited {rc}: {err.strip()}")
    probed = [line.split(" ", 1) for line in out.splitlines()]
    own = {k: v for k, v in probed if k in ("own", "origin")}
    old = own.get("own", "")
    if old and own["origin"] != origin and not force:
        raise Moved(f"{where['T']} on {machine.id} was synced {own['origin']!r}, not from {top}; force=True replaces it")
    have = [old] if old else []
    have += [sha for k, sha in probed if k == "have" and sha != old]
    parent = next((sha for sha in have if has_commit(top, sha)), None)
    tree = snapshot(top, paths)
    if parent is not None and parent == old and tree == git(top, "rev-parse", f"{old}^{{tree}}"):
        return Synced(old, where["T"], 0)
    # pack-objects --revs ^X leaves out X's objects only when X is a parent of the new commit
    new = git(top, "commit-tree", tree, *(["-p", parent] if parent else []), "-m", origin, env=IDENTITY)
    data = pack(top, new, exclude=parent)
    incoming = f"{where['G']}/incoming-{secrets.token_hex(4)}.pack"
    if len(data) <= INLINE_PACK_BYTES:
        send = f"base64 -d > {incoming} <<'BOX_PACK'\n{base64.b64encode(data).decode()}\nBOX_PACK\n"
    else:
        machine.write(incoming, data)
        send = ""
    rc, _, err = machine.exec(assign({**where, **EXIT_CODES, "OLD": old, "NEW": new, "PACK": incoming, "FORCE": "1" if force else "0"}) + send + APPLY)
    if rc == DRIFT:
        raise Drift(f"changed on {machine.id} since the last sync (force=True overwrites):\n{err.rstrip()}")
    if rc == MOVED:
        raise Moved(err.strip())
    if rc != 0:
        raise RuntimeError(f"{machine.id}: box sync apply exited {rc}: {err.strip()}")
    git(top, "update-ref", f"{keep}/{top.name}", new)
    return Synced(new, where["T"], len(data))


def toplevel(repo: Path) -> Path:
    return Path(git(repo, "rev-parse", "--show-toplevel"))


def tree_path(work: str, top: Path) -> str:
    return f"{work}/{top.name}"


def snapshot(top: Path, paths: tuple[str, ...]) -> str:
    for p in paths:
        if not (top / p).exists():
            raise FileNotFoundError(f"box sync: paths {p!r}: no {top / p}")
    with tempfile.TemporaryDirectory(prefix="box-sync-") as tmp:
        index = Path(tmp) / "index"
        real = Path(git(top, "rev-parse", "--path-format=absolute", "--git-path", "index"))
        env = {"GIT_INDEX_FILE": str(index)}
        if real.exists():
            shutil.copyfile(real, index)
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
        from box.sdk import Refused

        raise Refused(f"box sync: {len(data) >> 20} MiB to send (limit {MAX_PACK_BYTES >> 20}); is something big tracked or under paths?")
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
