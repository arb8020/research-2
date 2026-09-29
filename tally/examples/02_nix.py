"""Nix-style: key=recipe (deep trace). Same step functions as 01_bazel; only the KeyFn differs."""
import tempfile
from pathlib import Path

from _cproject import DEFAULTS, build, run_scenarios, steps, write_project

from tally import Handle, Key, keys, open_ctx

C, L, T = "compile_c", "link", "run_tests"

with tempfile.TemporaryDirectory() as d:
    nix = run_scenarios(Path(d) / "nix", keys.recipe)
    bazel = run_scenarios(Path(d) / "bazel", keys.bytes)

print(f"{'scenario':28s} {'bazel (bytes)':40s} nix (recipe)")
for (label, b_ran, _), (_, n_ran, _) in zip(bazel, nix, strict=True):
    print(f"{label:28s} {', '.join(b_ran) or '-':40s} {', '.join(n_ran) or '-'}")
r = {label: ran for label, ran, _ in nix}
assert r["1 cold run"] == [C, C, L, T]
assert r["2 rerun"] == []
assert r["3 edit b.c body"] == [C, L, T]
assert r["4 edit comment in util.h"] == [C, C, L, T]  # no early cutoff: recipe changed -> all downstream reruns
assert r["5b opt O2 -> O1"] == []


def plan(files: dict[str, Handle], opt: str) -> Key:
    """The final key, before building anything. Recipe keys read only Handle.key, so key-only stand-ins suffice."""
    COMPILE, LINK, TEST = steps(keys.recipe)

    def ref(step, *args) -> Handle:  # noqa: ANN001, ANN002
        return Handle(key=step.key(step, args, {}), digest="", path="")
    a = ref(COMPILE, files["a.c"], [files["util.h"]], opt)
    b = ref(COMPILE, files["b.c"], [files["util.h"]], opt)
    return ref(TEST, ref(LINK, [a, b])).key


print("\none lookup:")
with tempfile.TemporaryDirectory() as d:
    files = write_project(Path(d) / "src", DEFAULTS["b_body"], DEFAULTS["header_comment"])
    ctx = open_ctx(Path(d) / "store")
    final = plan(files, "O1")
    print(f"  planned final key {final[:16]}..  in store: {ctx.meta.get(final) is not None}")
    assert ctx.meta.get(final) is None
    got = build(ctx, files, keys.recipe, "O1")["test"]
    assert got.key == final
    print(f"  built; final key  {got.key[:16]}..  in store: {ctx.meta.get(final) is not None}")
    assert ctx.meta.get(final) == got  # next time: one lookup answers "is everything up to date?"
print("02_nix: all assertions passed (and every scenario matched a clean build)")
