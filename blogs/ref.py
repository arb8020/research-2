"""Reference code for a workspace series: layered chapter folders -> chapter trees -> a tagged git repo.

    uv run ref.py materialize ch00 start /tmp/ch00-start     # write one chapter's tree (start or solution)
    uv run ref.py repo /tmp/engine-ref                        # the tagged repo: chNN/start, chNN/solution
    uv run ref.py bundle ch00 /tmp/ref.bundle                 # what a reader's page ships: only chNN/start
    uv run ref.py verify [ch00]                               # solution passes run_checks; every start stub fails

Layout (engine/ref/ by default; --root to point elsewhere):

    chNN/files/   every file this chapter adds or changes, as the reference has it (the solution)
    chNN/start/   the reader's starting version of this chapter's cell files (stubs); only cell files

    chNN/STANDALONE  (optional) this chapter stacks on nothing and nothing stacks on it (ch00, the toy)

materialize(chN, "solution") stacks the series' files/ up to chN (a later chapter wins; standalone chapters are left
out). materialize(chN, "start") is the solution of the chapter before with chN's files/ and then chN's start/ on top.
The cells are listed in the tree itself, in checks/chNN.json ({name, file, region, ops, cmd}), so workspace.py in the
sandbox, the page and the check command read the same list. A cell's region names a `# region: <name>` ...
`# endregion` block in its file (display only: the page scrolls to and highlights it); the build checks it exists.

The check command (cmd[0], e.g. run_checks) is trusted code, not part of the tree: TRUSTED_SRC below is the one place
that says which package the page ships as _blogs/assay/ and `verify` runs from. `verify` runs it with assay's own uv
env (blogs/assay: torch, transformers, einops, ...), the local stand-in for the sandbox image's python.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, NamedTuple

import workspace

HERE = Path(__file__).resolve().parent
REF = HERE / "engine" / "ref"
TRUSTED_SRC = HERE / "assay" / "assay"
ASSAY_PROJECT = HERE / "assay"
CHAPTER = re.compile(r"ch\d{2}")
MAX_TREE_FILES = 2000
GIT_ENV = {"GIT_AUTHOR_NAME": "blogs-ref", "GIT_AUTHOR_EMAIL": "ref@blogs.local", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
           "GIT_COMMITTER_NAME": "blogs-ref", "GIT_COMMITTER_EMAIL": "ref@blogs.local", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}  # fmt: skip

Kind = Literal["start", "solution"]


@dataclass(frozen=True)
class File:
    data: bytes
    executable: bool


Tree = dict[str, File]


@dataclass(frozen=True)
class Cell:
    name: str
    file: str
    region: str | None
    ops: tuple[str, ...]
    cmd: tuple[str, ...]


def chapters(root: Path = REF) -> list[str]:
    found = sorted(p.name for p in root.iterdir() if p.is_dir() and CHAPTER.fullmatch(p.name))
    assert found, f"no chNN folders under {root}"
    return found


def lineage(chapter: str, root: Path = REF) -> list[str]:
    order = chapters(root)
    assert chapter in order, f"no {chapter} under {root}; chapters are {order}"
    if (root / chapter / "STANDALONE").exists():
        return [chapter]
    return [ch for ch in order[: order.index(chapter) + 1] if not (root / ch / "STANDALONE").exists()]


class Region(NamedTuple):
    first_line: int
    last_line: int


def region_span(text: str, region: str) -> Region | None:
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if line.strip() == f"# region: {region}"]
    if len(starts) != 1:
        return None
    ends = [i for i in range(starts[0] + 1, len(lines)) if lines[i].strip() == "# endregion"]
    return Region(starts[0] + 1, ends[0] + 1) if ends else None


def read_layer(folder: Path) -> Tree:
    if not folder.is_dir():
        return {}
    tree = {p.relative_to(folder).as_posix(): File(p.read_bytes(), os.access(p, os.X_OK)) for p in sorted(folder.rglob("*")) if p.is_file()}
    assert len(tree) <= MAX_TREE_FILES, f"{folder}: {len(tree)} files (limit {MAX_TREE_FILES})"
    return tree


def cells(tree: Tree, chapter: str) -> list[Cell]:
    key = f"checks/{chapter}.json"
    assert key in tree, f"{chapter}: the tree has no {key}"
    raw = json.loads(tree[key].data)
    assert raw["chapter"] == chapter, f"{key} says chapter {raw['chapter']!r}"
    found = [Cell(c["name"], c["file"], c["region"], tuple(c["ops"]), tuple(c["cmd"])) for c in raw["cells"]]
    names = [c.name for c in found]
    assert len(names) == len(set(names)), f"{key}: duplicate cell names {names}"
    for c in found:
        assert c.file in tree, f"{key}: cell {c.name}'s file {c.file} is not in the tree"
        assert c.cmd, f"{key}: cell {c.name} has no cmd"
        if c.region is not None:
            span = region_span(tree[c.file].data.decode(), c.region)
            assert span is not None, f"{key}: cell {c.name}'s region {c.region!r} has no `# region: {c.region}` ... `# endregion` in {c.file}"
    return found


def materialize(chapter: str, kind: Kind, root: Path = REF) -> Tree:
    tree: Tree = {}
    for ch in lineage(chapter, root):
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
    cells(tree, chapter)
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
    assert not out.exists() or not any(out.iterdir()), f"{out} is not empty"
    out.mkdir(parents=True, exist_ok=True)
    git(out, "init", "-q", "-b", "main")
    for ch in lineage(upto, root) if upto else [c for c in chapters(root) if not (root / c / "STANDALONE").exists()]:
        commit_tree(out, materialize(ch, "start", root), f"{ch}: start", f"{ch}/start")
        commit_tree(out, materialize(ch, "solution", root), f"{ch}: solution", f"{ch}/solution")
    return out


def reader_bundle(chapter: str, out: Path, root: Path = REF) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        repo = build_repo(Path(tmp) / "ref", root, upto=chapter)
        git(repo, "bundle", "create", "-q", str(out.resolve()), f"refs/tags/{chapter}/start")
        listed = git(repo, "bundle", "list-heads", str(out.resolve()))
        assert listed.split()[1:] == [f"refs/tags/{chapter}/start"], f"bundle refs: {listed}"
        reachable = git(repo, "rev-list", f"{chapter}/start").split()
        for tag in git(repo, "tag", "--list", "*/solution").split():
            if tag.split("/")[0] >= chapter:
                assert git(repo, "rev-parse", tag).strip() not in reachable, f"{tag} is reachable from {chapter}/start"
    return out


def stage_trusted(out: Path) -> str:
    assert not (out / "assay").exists(), f"{out}/assay already exists"
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HERE / "workspace.py", out / "workspace.py")
    for src in sorted(TRUSTED_SRC.rglob("*.py")):
        if "__pycache__" in src.parts:
            continue
        dest = out / "assay" / src.relative_to(TRUSTED_SRC)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
    text = workspace.manifest_lines(out)
    (out / workspace.TRUST_MANIFEST).write_text(text)
    return hashlib.sha256(text.encode()).hexdigest()


def assay_python() -> str:
    out = subprocess.run(["uv", "run", "--project", str(ASSAY_PROJECT), "--frozen", "python", "-c", "import sys; print(sys.executable)"],
                         capture_output=True, text=True, check=True)  # fmt: skip
    return out.stdout.strip().splitlines()[-1]


def run_cell(cell: Cell, tree: Path, trusted: Path, python: str) -> tuple[int, str]:
    argv, extra = workspace.command(list(cell.cmd), trusted, python)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", **extra}
    proc = subprocess.run(argv, cwd=tree, capture_output=True, text=True, check=False, env=env)
    why = ""
    for line in proc.stdout.splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("kind") == "verdict" and rec.get("outcome") in ("fail", "blocked") and not why:
            why = f"{rec['outcome']}: {rec.get('op')} {rec.get('case')} {rec.get('dtype')}: {rec.get('notes', '')}"[:200]
        if rec.get("kind") == "summary":
            why = why or f"summary {rec.get('outcome')} {rec.get('counts')}"
    if proc.returncode == 2:
        why = f"infrastructure: {(proc.stdout + proc.stderr)[-1500:]}"
    return proc.returncode, why


def verify(chapter: str, root: Path = REF) -> bool:
    ok = True
    python = assay_python()
    with tempfile.TemporaryDirectory() as tmp:
        trusted = Path(tmp) / "_blogs"
        stage_trusted(trusted)
        solution_tree = materialize(chapter, "solution", root)
        solution = Path(tmp) / "solution"
        write_tree(solution_tree, solution)
        start_tree = materialize(chapter, "start", root)
        for cell in cells(start_tree, chapter):
            rc, why = run_cell(cell, solution, trusted, python)
            print(f"{chapter} solution: {' '.join(cell.cmd)} -> exit {rc} (want 0) {why}", flush=True)
            ok &= rc == 0
            one = Path(tmp) / f"start-{cell.name}"
            write_tree({**solution_tree, cell.file: start_tree[cell.file]}, one)
            rc, why = run_cell(cell, one, trusted, python)
            print(f"{chapter} start {cell.file}: {' '.join(cell.cmd)} -> exit {rc} (want 1) {why}", flush=True)
            ok &= rc == 1
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
