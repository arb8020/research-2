"""test_budget.py: prefill_chunks, case by case, then a sweep of every small input. Exit 1 on the first failure."""

from budget import prefill_chunks

CASES = [((10, 4), [4, 4, 2]), ((8, 4), [4, 4]), ((3, 4), [3]), ((0, 4), []), ((1, 1), [1])]
SWEEP_MAX = 64

for (prompt_len, chunk), want in CASES:
    got = prefill_chunks(prompt_len, chunk)
    assert got == want, f"prefill_chunks({prompt_len}, {chunk}) = {got}, expected {want}"

for prompt_len in range(SWEEP_MAX):
    for chunk in range(1, SWEEP_MAX):
        got = prefill_chunks(prompt_len, chunk)
        assert sum(got) == prompt_len, f"prefill_chunks({prompt_len}, {chunk}) = {got} sums to {sum(got)}"
        assert all(0 < c <= chunk for c in got), f"prefill_chunks({prompt_len}, {chunk}) = {got} has a chunk outside 1..{chunk}"
        assert got[:-1] == [chunk] * (len(got) - 1), f"prefill_chunks({prompt_len}, {chunk}) = {got}: only the last chunk may be short"

print(f"ok budget ({len(CASES)} cases + {SWEEP_MAX * (SWEEP_MAX - 1)} sweep)")
