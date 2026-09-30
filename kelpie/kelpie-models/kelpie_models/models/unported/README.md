# unported

Model files not yet on the kernel seam; see `docs/ladder.md`. Each moves back to
`kelpie_models/` when its forward runs on `k = kernels.for_device(...)` / `batch.attn[g]` / taps.

Tests for these models skip with one reason ("unported: see docs/ladder.md") through
`tests/skips.py::unported(name)`; moving a file back makes its tests run again with no edit.
