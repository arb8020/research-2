"""Grading a kernel: is it right, and is it fast.

`compare(op, impl, sample_args)` is the correctness verdict -- reference in fp64 as truth,
reference at native dtype as the error budget, candidate against both. `timing.measure` is the
number. `build(check=True)` / `build(bench=True)` are the two plain bools that turn each on.

`correctness.py` is copied verbatim from crucible so the budget rule has one definition across
both projects; `bench/probe/` (another branch) sits beside these.
"""

from kelpie_models.bench.compare import Verdict, compare
from kelpie_models.bench.timing import measure

__all__ = ["Verdict", "compare", "measure"]
