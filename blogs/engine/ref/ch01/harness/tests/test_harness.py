"""Harness tests at its layer boundaries: the case generator, the budget rule, the frame parser
(the trust boundary), the registry, and one end-to-end self-test run through the CLI.

The end-to-end proof of the whole suite is `run_checks ch1 --selftest` (it needs gpt2 and
~1 min); here it runs for layer_norm only.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import pytest
import torch

from harness import cli
from harness.budget import band, compare_greedy, greedy_step
from harness.cases import _pairwise_with_corners, make_inputs, sweep
from harness.isolate import ProtocolError, parse_frame
from specs.causal_attention import causal_attention
from specs.layer_norm import layer_norm

# ---- case generator ---------------------------------------------------------------------------


def check_pairwise(axes: list[tuple]) -> None:
    rows = _pairwise_with_corners(axes)
    for a, b in itertools.combinations(range(len(axes)), 2):
        seen = {(row[a], row[b]) for row in rows}
        want = set(itertools.product(range(len(axes[a])), range(len(axes[b]))))
        assert seen == want, f"axes {a},{b}: missing pairs {sorted(want - seen)}"
    assert tuple(0 for _ in axes) in rows
    assert tuple(len(axis) - 1 for axis in axes) in rows
    full = math.prod(len(axis) for axis in axes)
    if len(axes) >= 3:  # with two axes, every pair IS the full product
        assert len(rows) < full, f"{len(rows)} rows is no better than the product {full}"


def test_pairwise_covers_every_pair() -> None:
    check_pairwise([(1, 2, 3), (1, 2, 3)])
    check_pairwise([(1, 2, 3, 4, 5), (1, 2, 3, 4, 5), (0, 1)])
    check_pairwise([(1, 2, 3), (1, 2, 12), (1, 2, 7, 16, 17, 64), (1, 8, 64), ("a", "b")])


def test_sweep_is_reproducible_and_covers_edges() -> None:
    first = sweep(causal_attention)
    again = sweep(causal_attention)
    assert [c.label() for c in first] == [c.label() for c in again]
    assert [c.seed for c in first] == [c.seed for c in again]
    for dim, sizes in causal_attention.sweep.dims.items():
        seen = {dict(case.sizes)[dim] for case in first}
        assert seen == set(sizes), f"{dim}: sweep missed sizes {set(sizes) - seen}"
    case = first[3]
    a = make_inputs(causal_attention, case)
    b = make_inputs(causal_attention, case)
    assert all(torch.equal(x, y) for x, y in zip(a, b, strict=True))
    assert a[0].shape == tuple(dict(case.sizes)[d] for d in ("batch", "heads", "seq", "head_dim"))


# ---- budget rule ------------------------------------------------------------------------------


def test_budget_is_twice_reference_error_or_the_floor() -> None:
    truth = torch.tensor([1.0, -2.0, 4.0], dtype=torch.float64)
    noisy = torch.tensor([1.0, -2.0, 4.01], dtype=torch.float32)
    assert band(truth, noisy) == pytest.approx(0.02, rel=1e-3)
    exact = truth.float()
    assert band(truth, exact) == pytest.approx(2e-5 * 4.0)


def test_greedy_rule_allows_near_ties_only() -> None:
    tie = greedy_step(torch.tensor([5.0, 5.0, 0.0, -9.0]), k=2)
    tie_other = greedy_step(torch.tensor([5.0, 5.001, 0.0, -9.0]), k=2)
    far = greedy_step(torch.tensor([-9.0, -9.0, 0.0, 5.0]), k=2)
    assert compare_greedy([tie], [tie]) is None
    assert compare_greedy([tie], [tie_other]) is None
    assert "not a near tie" in (compare_greedy([tie], [far]) or "")


# ---- the trust boundary: frames from the child ------------------------------------------------


def frame(header: object, blob: bytes = b"") -> tuple[bytes, bytes]:
    return json.dumps(header).encode(), blob


def check_rejected(header_bytes: bytes, blob: bytes, why: str) -> None:
    with pytest.raises(ProtocolError, match=why):
        parse_frame(header_bytes, blob)


def test_frame_parser_rejects_lies() -> None:
    four_floats = torch.arange(4, dtype=torch.float32).numpy().tobytes()
    spec = {"name": "run0.out", "dtype": "float32", "shape": [4], "nbytes": 16}
    header, tensors = parse_frame(*frame({"kind": "returned", "tensors": [spec]}, four_floats))
    assert header["kind"] == "returned"
    assert torch.equal(tensors["run0.out"], torch.arange(4, dtype=torch.float32))

    check_rejected(b"\x80\x04pickle", b"", "not JSON")
    check_rejected(*frame([1, 2]), "string 'kind'")
    check_rejected(*frame({"kind": "returned", "tensors": [spec]}, four_floats[:8]),
                   "runs past the blob")
    check_rejected(*frame({"kind": "returned", "tensors": [spec]}, four_floats + b"x"),
                   "trailing bytes")
    check_rejected(*frame({"kind": "returned", "tensors": [{**spec, "nbytes": 12}]}, four_floats),
                   "12 bytes for shape")
    check_rejected(*frame({"kind": "returned", "tensors": [{**spec, "dtype": "object"}]}),
                   "not allowed")
    check_rejected(*frame({"kind": "returned", "tensors": [{**spec, "shape": [-4]}]}),
                   "not a list of sizes")
    check_rejected(*frame({"kind": "returned", "tensors": [spec, spec]}, four_floats * 2),
                   "sent twice")


# ---- registry ---------------------------------------------------------------------------------


def test_unknown_names_are_refused_before_bind() -> None:
    from harness import registry

    with pytest.raises(KeyError, match="no impl 'nope'"):
        registry.bind(kernels={layer_norm: "nope"})
    assert not registry._BOUND, "a refused bind must not bind"
    with pytest.raises(RuntimeError, match="called before bind"):
        layer_norm(torch.zeros(1, 1), torch.ones(1), torch.zeros(1), 1e-5)


# ---- end to end -------------------------------------------------------------------------------


def test_layer_norm_selftest_catches_every_bad_candidate(tmp_path: Path) -> None:
    records = tmp_path / "selftest.jsonl"
    status = cli.main(["ch1", "layer_norm", "--selftest", "--records", str(records)])
    assert status == 0, "a layer_norm self-test was not caught as stated (see stdout)"
    lines = [json.loads(line) for line in records.read_text().splitlines()]
    candidates = {line["candidate"] for line in lines}
    assert len(candidates) == 11
    assert all(line["fingerprint"]["candidate_sha256"] for line in lines)


def test_correct_layer_norm_passes_every_case(tmp_path: Path) -> None:
    status = cli.main(["ch1", "layer_norm", "--records", str(tmp_path / "ok.jsonl")])
    assert status == 0
