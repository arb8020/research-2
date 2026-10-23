"""Nix-style: key=recipe (deep trace). Same step functions as 01_bazel; only the KeyFn differs."""
import tempfile
from pathlib import Path

from _cproject import COMPILE, DEFAULTS, LINK, TEST, build, run_scenarios, steps, write_project

from tally import Handle, Key, Step, derivation, keys, open_store, start


def compare_with_bazel() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        nix = run_scenarios(Path(tmp) / "nix", keys.recipe)
        bazel = run_scenarios(Path(tmp) / "bazel", keys.bytes)
    print(f"{'scenario':28s} {'bazel (bytes)':40s} nix (recipe)")
    for (label, bazel_ran, _), (_, nix_ran, _) in zip(bazel, nix, strict=True):
        print(f"{label:28s} {', '.join(bazel_ran) or '-':40s} {', '.join(nix_ran) or '-'}")

    nix_ran_by_label = {label: ran for label, ran, _ in nix}
    assert nix_ran_by_label["1 cold run"] == [COMPILE, COMPILE, LINK, TEST]
    assert nix_ran_by_label["2 rerun"] == []
    assert nix_ran_by_label["3 edit b.c body"] == [COMPILE, LINK, TEST]
    # no early cutoff: recipe changed -> all downstream reruns
    assert nix_ran_by_label["4 edit comment in util.h"] == [COMPILE, COMPILE, LINK, TEST]
    assert nix_ran_by_label["5b opt O2 -> O1"] == []


def plan(files: dict[str, Handle], opt: str) -> Key:
    """The final key, before building anything. Recipe keys read only Handle.key, so key-only stand-ins suffice."""
    compile_step, link_step, test_step = steps(keys.recipe)

    def planned(step: Step, *args: object) -> Handle:
        return Handle(key=step.key(step, args, {}), path="")
    a_obj = planned(compile_step, files["a.c"], [files["util.h"]], opt)
    b_obj = planned(compile_step, files["b.c"], [files["util.h"]], opt)
    return planned(test_step, planned(link_step, [a_obj, b_obj])).key


def one_lookup() -> None:
    print("\none lookup:")
    with tempfile.TemporaryDirectory() as tmp:
        files = write_project(Path(tmp) / "src", DEFAULTS["b_body"], DEFAULTS["header_comment"])
        store = open_store(Path(tmp) / "store")
        final_key = plan(files, "O1")
        print(f"  planned final key {final_key[:16]}..  in store: {derivation(store, final_key) is not None}")
        assert derivation(store, final_key) is None
        built = build(start(store), files, keys.recipe, "O1")["test"]
        assert built.key == final_key
        print(f"  built; final key  {built.key[:16]}..  in store: {derivation(store, final_key) is not None}")
        assert derivation(store, final_key) == built  # next time: one lookup answers "is everything up to date?"


def main() -> None:
    compare_with_bazel()
    one_lookup()
    print("02_nix: all assertions passed (and every scenario matched a clean build)")


if __name__ == "__main__":
    main()
