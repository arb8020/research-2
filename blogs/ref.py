"""Reference code for a workspace series: layered chapter folders -> chapter trees -> a tagged git repo.

    uv run ref.py materialize ch00 start /tmp/ch00-start     # write one chapter's tree (start or solution)
    uv run ref.py repo /tmp/engine-ref                        # the tagged repo: chNN/start, chNN/solution
    uv run ref.py bundle ch00 /tmp/ref.bundle                 # what a reader's page ships: only chNN/start
    uv run ref.py verify [ch00]                               # solution passes run_checks; every start stub fails

Layout (engine/ref/ by default; --root to point elsewhere):

    chNN/files/   every file this chapter adds or changes, as the reference has it (the solution)
    chNN/start/   the reader's starting version of this chapter's cell files (stubs); only cell files

materialize(chN, "solution") stacks ch00..chN's files/ (a later chapter wins). materialize(chN, "start") is the
solution of chN-1 with chN's files/ and then chN's start/ on top. The cells are listed in the tree itself, in
checks/chNN.json (cell name, file, check steps), so the sandbox's run_checks and ws.py read the same list.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HERE = Path(__file__).resolve().parent
REF = HERE / "engine" / "ref"
CHAPTER = re.compile(r"ch\d{2}")
MAX_TREE_FILES = 2000  # a chapter tree past this is a mistake (build output copied in?)
# Fixed identity and dates: the same reference always makes the same commits, so bundles are reproducible.
GIT_ENV = {"GIT_AUTHOR_NAME": "blogs-ref", "GIT_AUTHOR_EMAIL": "ref@blogs.local", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_NAME": "blogs-ref", "GIT_COMMITTER_EMAIL": "ref@blogs.local", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}  # fmt: skip

Kind = Literal["start", "solution"]


@dataclass(frozen=True)
class File:
    data: bytes
    executable: bool


Tree = dict[str, File]  # tree-relative POSIX path -> file


@dataclass(frozen=True)
class Cell:
    name: str
    file: str


def chapters(root: Path = REF) -> list[str]:
    found = sorted(p.name for p in root.iterdir() if p.is_dir() and CHAPTER.fullmatch(p.name))
    assert found, f"no chNN folders under {root}"
    return found


def read_layer(folder: Path) -> Tree:
    if not folder.is_dir():
        return {}
    tree = {p.relative_to(folder).as_posix(): File(p.read_bytes(), os.access(p, os.X_OK)) for p in sorted(folder.rglob("*")) if p.is_file()}
    assert len(tree) <= MAX_TREE_FILES, f"{folder}: {len(tree)} files (limit {MAX_TREE_FILES})"
    return tree


def cells(tree: Tree, chapter: str) -> list[Cell]:
    """The chapter's cells, in order, from checks/<chapter>.json in its tree (the file the sandbox reads too)."""
    key = f"checks/{chapter}.json"
    assert key in tree, f"{chapter}: the tree has no {key}"
    raw = json.loads(tree[key].data)
    assert raw["chapter"] == chapter, f"{key} says chapter {raw['chapter']!r}"
    found = [Cell(c["name"], c["file"]) for c in raw["cells"]]
    names = [c.name for c in found]
    assert len(names) == len(set(names)), f"{key}: duplicate cell names {names}"
    for c in found:
        assert c.file in tree, f"{key}: cell {c.name}'s file {c.file} is not in the tree"
    return found


def materialize(chapter: str, kind: Kind, root: Path = REF) -> Tree:
    order = chapters(root)
    assert chapter in order, f"no {chapter} under {root}; chapters are {order}"
    tree: Tree = {}
    for ch in order[: order.index(chapter) + 1]:
        tree.update(read_layer(root / ch / "files"))
    if kind == "solution":
        return tree
    start = read_layer(root / chapter / "start")
    owned = {c.file for c in cells(tree, chapter)}
    for path in start:
        assert path in owned, f"{chapter}/start/{path} is not one of the chapter's cell files {sorted(owned)}"
    for path in owned:
        assert path in start, f"{chapter}: cell file {path} has no stub in {chapter}/start/"
        assert start[path].data != tree[path].data, f"{chapter}/start/{path} is the solution itself"
    tree.update(start)
    return tree


def write_tree(tree: Tree, out: Path) -> None:
    for path, f in tree.items():
        dest = out / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.data)
        dest.chmod(0o755 if f.executable else 0o644)


def git(repo: Path, *args: str, stdin: bytes | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, env={**os.environ, **GIT_ENV}, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} (in {repo}) exited {proc.returncode}: {proc.stderr.decode(errors='replace')}")
    return proc.stdout.decode()


def commit_tree(repo: Path, tree: Tree, message: str, tag: str) -> None:
    """Make the work tree exactly `tree`, commit it, tag it (annotated tags would carry dates; lightweight ones are enough)."""
    for p in repo.iterdir():
        if p.name == ".git":
            continue
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    write_tree(tree, repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)
    git(repo, "tag", tag)


def build_repo(out: Path, root: Path = REF, upto: str | None = None) -> Path:
    """The tagged reference repo: for each chapter, chNN/start then chNN/solution, on one line of history."""
    assert not out.exists() or not any(out.iterdir()), f"{out} is not empty"
    out.mkdir(parents=True, exist_ok=True)
    git(out, "init", "-q", "-b", "main")
    order = chapters(root)
    for ch in order[: order.index(upto) + 1] if upto else order:
        commit_tree(out, materialize(ch, "start", root), f"{ch}: start", f"{ch}/start")
        commit_tree(out, materialize(ch, "solution", root), f"{ch}: solution", f"{ch}/solution")
    return out


def reader_bundle(chapter: str, out: Path, root: Path = REF) -> Path:
    """A bundle with one ref, chNN/start, for the reader's sandbox. History reaches back through earlier chapters'
    solutions (they are this chapter's starting point anyway) but never this chapter's solution or later ones."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = build_repo(Path(tmp) / "ref", root, upto=chapter)
        git(repo, "bundle", "create", "-q", str(out.resolve()), f"refs/tags/{chapter}/start")
        listed = git(repo, "bundle", "list-heads", str(out.resolve()))
        assert listed.split()[1:] == [f"refs/tags/{chapter}/start"], f"bundle refs: {listed}"
        solution = git(repo, "rev-parse", f"{chapter}/solution").strip()
        reachable = git(repo, "rev-list", f"{chapter}/start").split()
        assert solution not in reachable, f"{chapter}/solution is reachable from {chapter}/start"
    return out


def verify(chapter: str, root: Path = REF) -> bool:
    """The reference passes its own chapter check; each start stub fails its cell's check (else it gives nothing to do)."""
    ok = True
    with tempfile.TemporaryDirectory() as tmp:
        solution = Path(tmp) / "solution"
        write_tree(materialize(chapter, "solution", root), solution)
        rc = subprocess.run([sys.executable, "run_checks", chapter], cwd=solution, capture_output=True, text=True, check=False)
        print(f"{chapter} solution: run_checks {chapter} -> exit {rc.returncode}")
        ok &= rc.returncode == 0
        start_tree = materialize(chapter, "start", root)
        for cell in cells(start_tree, chapter):
            # The stub on its own, on top of the solution: does this cell's check notice?
            one = Path(tmp) / f"start-{cell.name}"
            write_tree({**materialize(chapter, "solution", root), cell.file: start_tree[cell.file]}, one)
            rc = subprocess.run([sys.executable, "run_checks", chapter, cell.name], cwd=one, capture_output=True, text=True, check=False)
            print(f"{chapter} start stub {cell.file}: run_checks {chapter} {cell.name} -> exit {rc.returncode} (want 1)")
            ok &= rc.returncode == 1
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=REF)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("materialize")
    m.add_argument("chapter")
    m.add_argument("kind", choices=("start", "solution"))
    m.add_argument("out", type=Path)
    r = sub.add_parser("repo")
    r.add_argument("out", type=Path)
    b = sub.add_parser("bundle")
    b.add_argument("chapter")
    b.add_argument("out", type=Path)
    v = sub.add_parser("verify")
    v.add_argument("chapter", nargs="?")
    args = ap.parse_args()
    if args.cmd == "materialize":
        write_tree(materialize(args.chapter, args.kind, args.root), args.out)
        print(f"wrote {args.chapter}/{args.kind} to {args.out}")
    elif args.cmd == "repo":
        build_repo(args.out, args.root)
        print(git(args.out, "log", "--oneline", "--decorate"), end="")
    elif args.cmd == "bundle":
        reader_bundle(args.chapter, args.out, args.root)
        print(f"wrote {args.out} ({args.out.stat().st_size} bytes, refs/tags/{args.chapter}/start)")
    else:
        todo = [args.chapter] if args.chapter else chapters(args.root)
        sys.exit(0 if all([verify(ch, args.root) for ch in todo]) else 1)


if __name__ == "__main__":
    main()
