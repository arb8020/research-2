"""A fake C project shared by 01_bazel.py and 02_nix.py. No real compiler: "compiling" strips comments."""
import re
from pathlib import Path

from tally import Ctx, Handle, KeyFn, Step, assert_matches_clean, open_ctx, src

COMPILE, LINK, TEST = "compile_c", "link", "run_tests"  # step names, as they appear in ctx.ran

DEFAULTS = {"b_body": "return x + 1;", "header_comment": "shared helpers", "opt": "O1"}


def write_project(root: Path, b_body: str, header_comment: str) -> dict[str, Handle]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "util.h").write_text(f"/* {header_comment} */\nint helper(int x);\n")
    (root / "a.c").write_text('#include "util.h"\n// entry point\nint main() { return helper(1); }\n')
    (root / "b.c").write_text(f'#include "util.h"\nint helper(int x) {{ {b_body} }}\n')
    return {name: src(root / name) for name in ("a.c", "b.c", "util.h")}


def _strip(text: str) -> str:
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    no_line = re.sub(r"//[^\n]*", "", no_block)
    return "\n".join(" ".join(line.split()) for line in no_line.splitlines() if line.strip())


# Everything a step depends on is an arg: util.h reaches compile only via `headers`.
def compile_c(ctx: Ctx, source: Handle, headers: list[Handle], opt: str, *, out: Path) -> None:
    decls = [_strip(Path(header.path).read_text()) for header in headers]
    body = _strip(Path(source.path).read_text())
    object_text = "\n".join([f"; object -{opt}", *decls, body if opt == "O1" else body.replace(" ", "")])
    (out / (Path(source.path).stem + ".o")).write_text(object_text + "\n")


def link(ctx: Ctx, objs: list[Handle], *, out: Path) -> None:
    parts = [obj_file.read_text() for obj in objs for obj_file in sorted(Path(obj.path).glob("*.o"))]
    assert len(parts) == len(objs), "each compile output holds exactly one .o"
    (out / "app").write_text("".join(parts))


def run_tests(ctx: Ctx, app: Handle, *, out: Path) -> dict:
    text = (Path(app.path) / "app").read_text()
    return {"passed": "main()" in text.replace(" ", "")}


def steps(key: KeyFn) -> tuple[Step, Step, Step]:
    return Step(compile_c, key=key), Step(link, key=key), Step(run_tests, key=key)


def build(ctx: Ctx, files: dict[str, Handle], key: KeyFn, opt: str) -> dict[str, Handle]:
    compile_step, link_step, test_step = steps(key)
    a_obj = ctx.fetch(compile_step, files["a.c"], [files["util.h"]], opt)
    b_obj = ctx.fetch(compile_step, files["b.c"], [files["util.h"]], opt)
    app = ctx.fetch(link_step, [a_obj, b_obj])
    return {"a.o": a_obj, "b.o": b_obj, "app": app, "test": ctx.fetch(test_step, app)}


SCENARIOS: list[tuple[str, dict[str, str]]] = [
    ("1 cold run", {}),
    ("2 rerun", {}),
    ("3 edit b.c body", {"b_body": "return x + 2;"}),
    ("4 edit comment in util.h", {"header_comment": "shared helpers (reworded)"}),
    ("5a opt O1 -> O2", {"opt": "O2"}),
    ("5b opt O2 -> O1", {"opt": "O1"}),
]


def run_scenarios(root: Path, key: KeyFn) -> list[tuple[str, list[str], dict[str, Handle]]]:
    """Apply each scenario's edits cumulatively; record what ran. Every scenario is checked against a clean build."""
    ctx = open_ctx(root / "store")
    state = dict(DEFAULTS)
    results = []
    for label, edits in SCENARIOS:
        state = {**state, **edits}
        files = write_project(root / "src", state["b_body"], state["header_comment"])
        ran_before = len(ctx.ran)
        outs = build(ctx, files, key, state["opt"])
        ran = ctx.ran[ran_before:]
        results.append((label, ran, {name: ctx.digest(out) for name, out in outs.items()}))  # hash for the report only
        assert ctx.load(outs["test"]) == {"passed": True}
        assert_matches_clean(
            lambda any_ctx, files=files, opt=state["opt"]: tuple(build(any_ctx, files, key, opt).values()), ctx,
        )
    return results
