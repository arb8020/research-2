"""Bazel-style: key=bytes (constructive trace). Early cutoff + old results kept."""
import tempfile
from pathlib import Path

from _cproject import run_scenarios

from tally import keys

C, L, T = "compile_c", "link", "run_tests"

with tempfile.TemporaryDirectory() as d:
    results = run_scenarios(Path(d), keys.bytes)

for label, ran, _ in results:
    print(f"{label:28s} ran={ran}")
r = {label: (ran, outs) for label, ran, outs in results}

assert r["1 cold run"][0] == [C, C, L, T]
assert r["2 rerun"][0] == []
ran, outs = r["3 edit b.c body"]
assert ran == [C, L, T]                                      # only b.c recompiled
assert outs["a.o"] == r["2 rerun"][1]["a.o"]                 # a.o untouched
ran, outs = r["4 edit comment in util.h"]
assert ran == [C, C]                                         # header bytes changed -> both compile
assert outs["a.o"].digest == r["3 edit b.c body"][1]["a.o"].digest  # ...to byte-identical .o
assert outs["app"] == r["3 edit b.c body"][1]["app"]         # early cutoff: link/test skipped
assert r["5a opt O1 -> O2"][0] == [C, C, L, T]
assert r["5b opt O2 -> O1"][0] == []                         # O1 results still in the store
print("01_bazel: all assertions passed (and every scenario matched a clean build)")
