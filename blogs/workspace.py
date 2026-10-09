"""The reader's workspace: a git repo in their sandbox that the page's cells are views onto. Stdlib only: the page
uploads this file to the sandbox (_blogs/workspace.py) and runs it there; it never runs on the page's server.

    python3 _blogs/workspace.py boot ch00 --ref _blogs/ref.bundle    restore the repo from the persisted bundle, or seed it
                                                              from the chapter's start; prints {created, ms, status}
    python3 _blogs/workspace.py status ch00                          {chapter, cells: [{name, file, passed, locked, why,
                                                              draft}], persist}; JSON on stdout
    python3 _blogs/workspace.py check ch00 ring -- run_checks ch00 ring
                                                              the latest passing tree + only ring's file -> build +
                                                              check, streamed; pass -> commit + tag pass/ch00/ring +
                                                              bundle. Exit 0 pass, 1 fail, 2 refused (locked, busy)
    python3 _blogs/workspace.py save                                 bundle the repo into the persist dir now
    python3 _blogs/workspace.py advance ch00 ch01                    (not yet: splice into the next chapter; see advance())

Layout under the root (the cwd: Jupyter's root_dir, where the kernel runs):

    workspace/            the repo. HEAD (branch main) is the latest passing tree; the working tree holds the
                          reader's drafts, written by the page through Jupyter's Contents API. The index always
                          equals HEAD: drafts are never staged, a pass commits exactly the bytes it checked.
    _blogs/check/         where checks build and run: HEAD's tree + the one cell file being checked. Kept between
                          checks so make only rebuilds what changed.
    _blogs/check.lock     one check at a time

Persistence: $BLOGS_WS_PERSIST names a directory that outlives the sandbox (locally any directory; on Modal a
Volume mount). Every pass writes workspace.bundle there (temp + rename; the previous one is kept as
workspace.prev.bundle); boot verifies a bundle before restoring from it. Unset: nothing persists, status says so.
"""

from __future__ import annotations

import argparse
import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

ROOT = Path.cwd()
REPO = ROOT / "workspace"
STATE = ROOT / "_blogs"
CHECK_TREE = STATE / "check"
LOCK = STATE / "check.lock"
BRANCH = "main"
BUNDLE = "workspace.bundle"
PREV_BUNDLE = "workspace.prev.bundle"
CHECK_TIMEOUT_S = 300  # run_checks bounds each step itself; this bounds the whole check
MAX_TREE_FILES = 5000
IDENTITY = ["-c", "user.name=reader", "-c", "user.email=reader@blogs.local", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]
KEEP_IN_CHECK_TREE = ("build",)  # build products survive between checks (incremental builds)


class Refused(Exception):
    """The check can't start (cell locked, another check running): exit 2 with this message."""


def git(*args: str, cwd: Path = REPO, stdin: bytes | None = None, env: dict[str, str] | None = None) -> bytes:
    proc = subprocess.run(["git", *IDENTITY, *args], cwd=cwd, input=stdin, capture_output=True, env={**os.environ, **(env or {})}, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def git_text(*args: str) -> str:
    return git(*args).decode().strip()


def persist_dir() -> Path | None:
    raw = os.environ.get("BLOGS_WS_PERSIST", "")
    return Path(raw) if raw else None


def say(text: str) -> None:
    print(f"workspace: {text}", flush=True)


def ms(t0: float) -> int:
    return round((time.perf_counter() - t0) * 1000)


# ---- reading the repo ----


def manifest(chapter: str) -> list[dict[str, Any]]:
    """checks/<chapter>.json from HEAD (the passing tree, not a draft): the chapter's cells in order."""
    raw = json.loads(git("show", f"HEAD:checks/{chapter}.json"))
    if raw.get("chapter") != chapter or not isinstance(raw.get("cells"), list):
        raise ValueError(f"checks/{chapter}.json: expected {{chapter: {chapter!r}, cells: [...]}}")
    for c in raw["cells"]:
        if not (isinstance(c.get("name"), str) and isinstance(c.get("file"), str)):
            raise ValueError(f"checks/{chapter}.json: a cell without a name and file: {c}")
    return raw["cells"]


def status(chapter: str) -> dict[str, Any]:
    """Which cells passed (a pass/<chapter>/<cell> tag), which are locked (an earlier cell hasn't), which have drafts."""
    passed = set(git_text("tag", "--list", f"pass/{chapter}/*").split())
    changed = set(git_text("diff", "--name-only", "HEAD").split())  # working tree vs the passing tree
    cells = []
    blocker = None  # the first cell that hasn't passed: every later cell waits for it
    for c in manifest(chapter):
        ok = f"pass/{chapter}/{c['name']}" in passed
        cells.append({"name": c["name"], "file": c["file"], "passed": ok, "locked": blocker is not None,
                      "why": f"locked until {blocker} passes" if blocker else "", "draft": c["file"] in changed})  # fmt: skip
        if not ok and blocker is None:
            blocker = c["name"]
    vol = persist_dir()
    bundle = vol / BUNDLE if vol else None
    saved = {"dir": str(vol), "bundle_bytes": bundle.stat().st_size if bundle and bundle.exists() else 0} if vol else None
    return {"chapter": chapter, "head": git_text("rev-parse", "--short", "HEAD"), "cells": cells, "persist": saved}


# ---- persistence ----


def save() -> dict[str, Any] | None:
    """Bundle every ref into the persist dir: verified locally first, then copied as a temp file and renamed over
    the old bundle, which is kept as the previous one. None when there is no persist dir."""
    vol = persist_dir()
    if vol is None:
        return None
    t0 = time.perf_counter()
    vol.mkdir(parents=True, exist_ok=True)
    local = STATE / "out.bundle"
    git("bundle", "create", "-q", str(local), "--all")
    git("bundle", "verify", "-q", str(local))
    tmp = vol / f"{BUNDLE}.tmp"
    shutil.copyfile(local, tmp)
    with tmp.open("rb") as f:
        os.fsync(f.fileno())
    if (vol / BUNDLE).exists():
        os.replace(vol / BUNDLE, vol / PREV_BUNDLE)
    os.replace(tmp, vol / BUNDLE)
    dir_fd = os.open(vol, os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
    if sys.platform == "linux":
        # A Modal Volume (v2) mounted in a sandbox persists writes on `sync <mount>` (spike exp5: without it the next
        # sandbox saw a broken repo). On a plain Linux dir this is one more fsync.
        subprocess.run(["sync", str(vol)], check=True)
    return {"bytes": (vol / BUNDLE).stat().st_size, "ms": ms(t0)}


def new_repo(fill: Any) -> None:
    """Build the repo in a temp dir and rename it into place, so a failure halfway never leaves a half-made
    workspace that the next boot would take as existing."""
    tmp = STATE / "workspace.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    git("init", "-q", "-b", BRANCH, cwd=tmp)
    fill(tmp)
    os.replace(tmp, REPO)


def restore_from(bundle: Path) -> None:
    """A fresh repo from a verified bundle: every ref as it was, the branch checked out."""

    def fill(repo: Path) -> None:
        git("bundle", "verify", "-q", str(bundle), cwd=repo)  # inside a repo: verify checks prerequisites against it
        git("fetch", "-q", "--update-head-ok", str(bundle), "+refs/*:refs/*", cwd=repo)
        git("checkout", "-q", "-f", BRANCH, cwd=repo)

    new_repo(fill)


def seed(chapter: str, ref: Path) -> None:
    """A fresh repo at the reference start of `chapter` (tagged ref/<chapter>/start), from the page's ref bundle."""

    def fill(repo: Path) -> None:
        git("fetch", "-q", str(ref), f"refs/tags/{chapter}/start:refs/tags/ref/{chapter}/start", cwd=repo)
        git("checkout", "-q", "-B", BRANCH, f"refs/tags/ref/{chapter}/start", cwd=repo)

    new_repo(fill)


def boot(chapter: str, ref: Path) -> dict[str, Any]:
    """The workspace as this sandbox should start it: already here, restored from the persisted bundle (the
    previous bundle if the latest fails verify), or seeded from the reference start of `chapter`."""
    t0 = time.perf_counter()
    STATE.mkdir(exist_ok=True)
    vol = persist_dir()
    if (REPO / ".git").is_dir():
        created = "existing"
    elif vol is not None and (vol / BUNDLE).exists():
        created = "restored"
        try:
            restore_from(vol / BUNDLE)
        except RuntimeError as e:
            if not (vol / PREV_BUNDLE).exists():
                raise
            say(f"the latest bundle failed ({e}); restoring the previous one")
            restore_from(vol / PREV_BUNDLE)
            created = "restored-previous"
    else:
        created = "seeded"
        seed(chapter, ref.resolve())
        save()
    has = subprocess.run(["git", "cat-file", "-e", f"HEAD:checks/{chapter}.json"], cwd=REPO, capture_output=True, check=False)
    if has.returncode != 0:
        # TODO(workspace): this is where advance() (splice) will run, once it exists.
        raise RuntimeError(f"the workspace has no {chapter} yet (checks/{chapter}.json missing at HEAD); advancing chapters is not built")
    return {"created": created, "ms": ms(t0), "status": status(chapter)}


# ---- checking a cell ----


def head_tree() -> dict[str, tuple[bytes, int]]:
    """HEAD's files: path -> (bytes, mode)."""
    files: dict[str, tuple[bytes, int]] = {}
    with tarfile.open(fileobj=io.BytesIO(git("archive", "--format=tar", "HEAD"))) as tar:
        for m in tar.getmembers():
            if m.isfile():
                f = tar.extractfile(m)
                assert f is not None, m.name
                files[m.name] = (f.read(), m.mode)
    if len(files) > MAX_TREE_FILES:
        raise ValueError(f"HEAD has {len(files)} files (limit {MAX_TREE_FILES})")
    return files


def sync_check_tree(want: dict[str, tuple[bytes, int]]) -> list[str]:
    """Make _blogs/check/ hold exactly `want` (build/ aside). Unchanged files keep their mtimes, so make rebuilds
    only what changed. Returns the paths written."""
    CHECK_TREE.mkdir(parents=True, exist_ok=True)
    for p in sorted(CHECK_TREE.rglob("*"), reverse=True):
        rel = p.relative_to(CHECK_TREE).as_posix()
        if rel.split("/")[0] in KEEP_IN_CHECK_TREE:
            continue
        if p.is_file() and rel not in want:
            p.unlink()
        elif p.is_dir() and not any(p.iterdir()):
            p.rmdir()
    stale = [path for path, (data, _) in want.items() if not (CHECK_TREE / path).is_file() or (CHECK_TREE / path).read_bytes() != data]
    if stale and sys.platform == "darwin":
        wait_for_next_second()
    for path in stale:
        data, mode = want[path]
        dest = CHECK_TREE / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod(mode & 0o777)
    return stale


def wait_for_next_second() -> None:
    """macOS's make 3.81 compares mtimes in whole seconds: a source rewritten in the same second its object was
    built looks up to date. Wait out that second (only when something in build/ is that recent)."""
    newest = max((p.stat().st_mtime for p in (CHECK_TREE / "build").rglob("*") if p.is_file()), default=0.0)
    now = time.time()
    if int(newest) == int(now):
        time.sleep(1 - (now - int(now)) + 0.01)


def commit_pass(chapter: str, cell: str, path: str, data: bytes, mode: int) -> str:
    """Commit exactly the checked bytes of `path` on top of HEAD (not whatever the draft is now) and move the
    pass tag to it. Returns the commit. The working tree is not touched; the index is reset to the new HEAD."""
    blob = git("hash-object", "-w", "--stdin", stdin=data).decode().strip()
    index = {"GIT_INDEX_FILE": str(STATE / "pass.index")}
    git("read-tree", "HEAD", env=index)
    git("update-index", "--cacheinfo", f"{mode:o},{blob},{path}", env=index)
    tree = git("write-tree", env=index).decode().strip()
    head = git_text("rev-parse", "HEAD")
    if tree == git_text("rev-parse", "HEAD^{tree}"):
        commit = head  # the passing version is already HEAD (a re-check of an unchanged file)
    else:
        commit = git("commit-tree", tree, "-p", head, "-m", f"pass {chapter}/{cell}").decode().strip()
        git("update-ref", f"refs/heads/{BRANCH}", commit, head)  # compare-and-swap against the HEAD we built on
        git("reset", "-q")  # index = the new HEAD; drafts in the working tree stay as they are
    git("tag", "-f", f"pass/{chapter}/{cell}", commit)
    return commit


def check(chapter: str, cell: str, command: list[str]) -> int:
    """Build + check one cell: the latest passing tree with only this cell's draft swapped in. Streams output;
    on pass commits, tags and saves the bundle. Exit 0 pass, 1 fail."""
    t0 = time.perf_counter()
    st = status(chapter)
    found = [c for c in st["cells"] if c["name"] == cell]
    if not found:
        raise Refused(f"{chapter} has no cell {cell!r}; its cells are {[c['name'] for c in st['cells']]}")
    if found[0]["locked"]:
        raise Refused(f"{cell} is {found[0]['why']}")
    path = found[0]["file"]
    tree = head_tree()
    draft = (REPO / path).read_bytes()
    mode = tree[path][1] if path in tree else 0o100644
    written = sync_check_tree({**tree, path: (draft, mode)})
    say(f"checking {chapter}/{cell}: passing tree {st['head']} + your {path}" + (f" ({len(written)} file(s) changed)" if written else ""))
    t_run = time.perf_counter()
    env = {**os.environ, "PATH": os.pathsep.join([str(CHECK_TREE), str(Path(sys.executable).parent), os.environ.get("PATH", "")])}
    try:
        rc = subprocess.run(command, cwd=CHECK_TREE, env=env, timeout=CHECK_TIMEOUT_S, check=False).returncode
    except subprocess.TimeoutExpired:
        say(f"FAIL {chapter}/{cell}: the check ran past {CHECK_TIMEOUT_S}s")
        return 1
    run_ms = ms(t_run)
    if rc != 0:
        say(f"FAIL {chapter}/{cell} (check exited {rc}; {run_ms} ms). Nothing committed; later cells keep using your last passing version.")
        return 1
    t_commit = time.perf_counter()
    commit = commit_pass(chapter, cell, path, draft, mode)
    commit_ms = ms(t_commit)
    saved = save()
    where = f"bundle {saved['bytes'] / 1024:.1f} KiB saved in {saved['ms']} ms" if saved else "not persisted (BLOGS_WS_PERSIST unset)"
    say(f"PASS {chapter}/{cell} -> commit {commit[:7]}, tag pass/{chapter}/{cell}; {where} "
        f"(check {run_ms} ms, commit {commit_ms} ms, total {ms(t0)} ms)")  # fmt: skip
    return 0


def advance(chapter: str, to: str) -> None:
    # TODO(workspace): splice. Fetch <to>/start from the page's ref bundle, then for each of <chapter>'s cells take the
    # reader's latest passing file (HEAD) where pass/<chapter>/<cell> exists, else the reference's (and say so);
    # commit that as the new chapter's first commit, tag ref/<to>/start. Open: a file <to> hands back as a cell
    # (its start/ stub) when the reader already owns a passing version of it.
    raise NotImplementedError(f"advance {chapter} -> {to}: splicing into the next chapter is not built yet")


def locked(fn: Any, *args: Any) -> int:
    """Run fn while holding the check lock (one check at a time); a held lock refuses rather than queues."""
    STATE.mkdir(exist_ok=True)
    with LOCK.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused("another check is still running (Stop it, or wait)") from None
        return fn(*args)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("boot")
    b.add_argument("chapter")
    b.add_argument("--ref", type=Path, required=True, help="the page's reference bundle (refs/tags/<chapter>/start)")
    s = sub.add_parser("status")
    s.add_argument("chapter")
    c = sub.add_parser("check")
    c.add_argument("chapter")
    c.add_argument("cell")
    c.add_argument("command", nargs=argparse.REMAINDER, help="after --: the check command, e.g. run_checks ch00 ring")
    sub.add_parser("save")
    a = sub.add_parser("advance")
    a.add_argument("chapter")
    a.add_argument("to")
    args = ap.parse_args()
    if args.cmd == "boot":
        print(json.dumps(boot(args.chapter, args.ref)))
    elif args.cmd == "status":
        print(json.dumps(status(args.chapter)))
    elif args.cmd == "save":
        print(json.dumps(save()))
    elif args.cmd == "advance":
        advance(args.chapter, args.to)
    else:
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            ap.error("check needs a command after --")
        try:
            return locked(check, args.chapter, args.cell, command)
        except Refused as e:
            say(f"refused: {e}")
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
