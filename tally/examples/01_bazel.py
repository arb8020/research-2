"""Bazel-style: key=bytes (constructive trace). Early cutoff + old results kept."""
import tempfile
from pathlib import Path

from _cproject import COMPILE, LINK, TEST, run_scenarios

from tally import keys


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        results = run_scenarios(Path(tmp), keys.bytes)
    for label, ran, _ in results:
        print(f"{label:28s} ran={ran}")
    by_label = {label: (ran, outs) for label, ran, outs in results}

    assert by_label["1 cold run"][0] == [COMPILE, COMPILE, LINK, TEST]
    assert by_label["2 rerun"][0] == []

    edit_ran, edit_outs = by_label["3 edit b.c body"]
    assert edit_ran == [COMPILE, LINK, TEST]                        # only b.c recompiled
    assert edit_outs["a.o"] == by_label["2 rerun"][1]["a.o"]        # a.o untouched

    comment_ran, comment_outs = by_label["4 edit comment in util.h"]
    assert comment_ran == [COMPILE, COMPILE]                        # header bytes changed -> both compile
    assert comment_outs["a.o"].digest == edit_outs["a.o"].digest    # ...to byte-identical .o
    assert comment_outs["app"] == edit_outs["app"]                  # early cutoff: link/test skipped

    assert by_label["5a opt O1 -> O2"][0] == [COMPILE, COMPILE, LINK, TEST]
    assert by_label["5b opt O2 -> O1"][0] == []                     # O1 results still in the store
    print("01_bazel: all assertions passed (and every scenario matched a clean build)")


if __name__ == "__main__":
    main()
