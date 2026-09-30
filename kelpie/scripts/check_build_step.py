#!/usr/bin/env python3
"""The build step's fail-loud paths, one fresh process per case (bind runs once per process).

    uv run --project kelpie-http python scripts/check_build_step.py            # every case
    uv run --project kelpie-http python scripts/check_build_step.py --case X   # one, in-process

Op-level cases need no checkpoint; the `gpt2_*` cases build gpt2 on cpu (downloads it once).
Each case prints `ok: <what it showed>` and the message a user would see; any other outcome is a
non-zero exit.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import torch

FAKE_BACKEND = "kelpie_fake_missing"


def _expect(exc_type: type[BaseException], fn: Callable[[], object], *needles: str) -> str:
    """Run `fn`; it must raise `exc_type` whose message contains every needle. -> message."""
    try:
        fn()
    except exc_type as exc:
        message = str(exc)
        missing = [n for n in needles if n not in message]
        assert not missing, f"message lacks {missing}: {message}"
        return message
    raise AssertionError(f"{fn} did not raise {exc_type.__name__}")


def case_second_bind() -> None:
    from kelpie_models.kernels import BuildError, bind

    bind("cpu")
    message = _expect(BuildError, lambda: bind("cpu"), "once per process", "new process")
    print(f"ok: a second bind raises\n    {message}")


def case_post_freeze() -> None:
    from kelpie_models.kernels import BuildError, bind, freeze, ops
    from kelpie_models.kernels.op import STEP_NOTE
    from kelpie_models.sdk.shapes import StepKey

    binding = bind("cpu")
    x = torch.randn(2, 8)
    ops.rms_norm(x, torch.ones(8), 1e-6)  # resolves rms_norm during "build"
    table = freeze(binding)
    assert table.names() == ("rms_norm",), table
    ops.rms_norm(x, torch.ones(8), 1e-6)  # a resolved op still dispatches after freeze
    STEP_NOTE.set(StepKey("decode", 8))
    message = _expect(BuildError, lambda: ops.gelu(x),
                      "kelpie::gelu first dispatched after build (decode R=8)")
    print(f"ok: an op first dispatched after freeze raises\n    {message}")


def case_unknown_kernels_key() -> None:
    from kelpie_models.kernels import KernelsError, bind, freeze, ops

    binding = bind("cpu", {ops.moe: "reference"})
    ops.rms_norm(torch.randn(2, 8), torch.ones(8), 1e-6)
    message = _expect(KernelsError, lambda: freeze(binding),
                      "kernels={ops.moe: ...}", "never called by this model", "rms_norm")
    print(f"ok: a kernels= key for an op the model never called raises at freeze\n    {message}")


def case_unknown_kernels_impl() -> None:
    from kelpie_models.kernels import KernelsError, bind, ops

    message = _expect(KernelsError, lambda: bind("cpu", {ops.gelu: "no_such_impl"}),
                      "gelu has no impl 'no_such_impl'", "impls: reference")
    print(f"ok: a kernels= value naming no impl raises at bind\n    {message}")


def case_other_device() -> None:
    from kelpie_models.kernels import BuildError, bind, ops

    bind("mps")  # never dispatched on mps here; the point is the cpu call below
    message = _expect(BuildError, lambda: ops.gelu(torch.randn(2, 8)),
                      "kelpie::gelu dispatched on a device other than 'mps'")
    print(f"ok: an op on another device's tensors raises instead of running unresolved\n    "
          f"{message}")


def _draw(top_ks: list[int], temperature: float, rows: int) -> object:
    from kelpie_models.sdk.decide import Draw

    over_one = [k for k in top_ks if k > 1]
    return Draw(temperatures=torch.full((rows,), temperature),
                top_ks=torch.tensor(top_ks, dtype=torch.int32),
                key=torch.tensor([7, 11], dtype=torch.uint32),
                logit_mask=torch.empty((rows, 0), dtype=torch.int32),
                all_greedy=all(k == 1 for k in top_ks), max_top_k=max(over_one, default=0))


def case_greedy_skips_rng() -> None:
    """All-greedy decide draws no random number; a mixed batch draws once; tokens = argmax."""
    import importlib

    from kelpie_models.kernels import bind
    from kelpie_models.sdk.decide import decide

    sample_mod = importlib.import_module("kelpie_models.kernels.ops.sample")
    calls = [0]
    real = sample_mod.philox_uniform

    def counting(*args: object) -> torch.Tensor:
        calls[0] += 1
        return real(*args)

    sample_mod.philox_uniform = counting
    bind("cpu")
    r, k, v = 4, 3, 50
    logits = torch.randn(r, 1 + k, v, generator=torch.Generator().manual_seed(0))
    drafts, n_extra = torch.zeros(r, k, dtype=torch.long), torch.full((r,), k)
    tokens, _ = decide(logits, _draw([1] * r, 1.0, r), drafts, n_extra)
    assert calls[0] == 0, f"all-greedy decide drew random numbers ({calls[0]} philox calls)"
    assert torch.equal(tokens, logits.argmax(-1)), "all-greedy tokens != argmax"
    mixed, _ = decide(logits, _draw([1, 0, 1, 0], 1.0, r), drafts, n_extra)
    assert calls[0] == 1, calls
    assert torch.equal(mixed[[0, 2]], logits.argmax(-1)[[0, 2]]), "greedy rows of a mixed batch"
    print("ok: all-greedy decide = argmax with 0 philox calls; a mixed batch makes 1, its greedy "
          "rows still argmax")


def case_top_k_sampling() -> None:
    """top_k=3, T=0.8 over many independent rows: only the top 3 tokens appear, at the
    frequencies of softmax(top3 / T) (the reference: torch.topk + categorical)."""
    from kelpie_models.kernels import bind
    from kelpie_models.sdk.decide import decide

    bind("cpu")
    rows, v, top_k, temperature = 40000, 10, 3, 0.8
    base = torch.tensor([2.0, 0.5, 1.5, -1.0, 1.8, 0.0, 0.3, -0.5, 1.0, 0.2])
    logits = base.expand(rows, v)[:, None, :].clone()
    tokens, _ = decide(logits, _draw([top_k] * rows, temperature, rows),
                       torch.zeros(rows, 0, dtype=torch.long), torch.zeros(rows, dtype=torch.long))
    got = torch.bincount(tokens[:, 0], minlength=v).double() / rows
    top = torch.topk(base, top_k)
    want = torch.zeros(v, dtype=torch.float64)
    want[top.indices] = torch.softmax(top.values.double() / temperature, dim=0)
    reference = torch.multinomial(want, rows, replacement=True,
                                  generator=torch.Generator().manual_seed(0))
    ref_freq = torch.bincount(reference, minlength=v).double() / rows
    outside = got[want == 0].sum().item()
    worst = (got - want).abs().max().item()
    assert outside == 0, f"tokens outside the top {top_k} drawn: {got}"
    assert worst < 0.01, f"frequencies off by {worst:.4f}: got {got.tolist()} want {want.tolist()}"
    print(f"ok: top_k={top_k} draws: outside-top-k 0, max |freq - softmax| {worst:.4f} (torch "
          f"multinomial reference: {(ref_freq - want).abs().max().item():.4f}) over {rows} rows")


def _toy_engine(max_extra: int) -> tuple[object, object]:
    from kelpie_models.models.torch import toy_hybrid
    from kelpie_models.sdk.run import build
    from kelpie_models.sdk.tiers import Capacity

    return build(toy_hybrid, device="cpu", capture=False, max_extra=max_extra,
                 capacity=Capacity(max_requests=6, max_seq_len=96, num_slabs=48))


def case_degraded_extra() -> None:
    """3 drafting entries + 1 without extra rows (a degraded decode_extra plan) lands on a
    warmed token bucket and runs."""
    import numpy as np
    from kelpie_models.sdk.device import to_device
    from kelpie_models.sdk.shapes import key_of

    k = 3
    engine, step = _toy_engine(k)
    try:
        for i in range(4):
            engine.submit([2 + i, 3, 4, 5], max_new_tokens=8)
        plan = engine.plan()
        assert plan is not None and plan.n_reqs == 4, plan
        tokens = step.sample(step.forward(plan), plan)
        engine.commit(tokens, None, np.array([k, k, k, 0], dtype=np.uint32))
        plan = engine.plan()
        key = key_of(plan)
        n_extra = plan.requests.n_extra[: plan.n_reqs].tolist()
        assert sorted(n_extra) == [0, k, k, k], n_extra
        assert key.family == "decode_extra", key
        assert key in step.warmed, (key, sorted(map(str, step.warmed)))
        dev_tokens, requests = to_device(plan, step.device)
        extra = dev_tokens.input_ids < 0
        dev_tokens.input_ids[extra] = 0  # the caller fills extra rows (drafts); any id will do
        logits = step.forward_device(plan, dev_tokens, requests)
        assert logits.shape[1] == 1 + k, logits.shape
        warmed = sorted(str(s) for s in step.warmed if s.family == "decode_extra")
        print(f"ok: degraded plan n_extra={n_extra} ({plan.n_tokens} tokens) is {key}, warmed; "
              f"decode_extra warmed: {warmed}")
    finally:
        engine.close()


def case_unwarmed_shape() -> None:
    """Simulate an enumeration gap (prefill T=64 left out); the first plan that lands there
    after build raises instead of running unwarmed."""
    from kelpie_models.kernels import BuildError
    from kelpie_models.sdk import run as run_mod

    real = run_mod.enumerate_steps
    run_mod.enumerate_steps = lambda config: [
        s for s in real(config) if not (s.family == "prefill" and s.size == 64)]
    engine, step = _toy_engine(0)
    try:
        engine.submit(list(range(2, 42)), max_new_tokens=2)  # 40 prompt rows -> prefill T=64
        plan = engine.plan()
        message = _expect(BuildError, lambda: step.forward(plan), "step shape prefill T=64 was "
                          "never warmed")
        print(f"ok: a plan on an unwarmed shape after freeze raises\n    {message[:200]}")
    finally:
        engine.close()


def case_gpt2_top_k() -> None:
    """submit(top_k=5, temperature=1) reaches the plan and every sampled token is in its
    row's top 5; a greedy request in the same batch stays argmax."""
    from kelpie_models.models.torch import gpt2
    from kelpie_models.sdk.run import build

    engine, step = build(gpt2, device="cpu")
    try:
        sampled = engine.submit([464, 3139, 286, 4881, 318], max_new_tokens=6, temperature=1.0,
                                top_k=5)
        engine.submit([464, 3139, 286, 4881, 318], max_new_tokens=6)
        checked = 0
        while (plan := engine.plan()) is not None:
            logits = step.forward(plan)
            tokens = step.sample(logits, plan)
            for r in range(plan.n_reqs):
                row = logits[r, 0]
                if int(plan.requests.req_ids[r]) == sampled:
                    assert int(plan.sampling.top_ks[r]) == 5, plan.sampling.top_ks
                    assert int(tokens[r]) in torch.topk(row, 5).indices.tolist(), int(tokens[r])
                else:
                    assert int(plan.sampling.top_ks[r]) == 1, plan.sampling.top_ks
                    assert int(tokens[r]) == int(row.argmax()), "greedy row != argmax"
                checked += 1
            engine.commit(tokens)
        print(f"ok: top_k=5 via Engine.submit reaches the plan; {checked} decided rows, sampled "
              f"ones within the top 5, greedy ones argmax")
    finally:
        engine.close()


def case_raise_past_warmed() -> None:
    """engine.set refuses a batch limit above what build warmed (HTTP: a 400), so a live raise
    cannot reach unwarmed shapes; lowering is fine."""
    engine, _ = _toy_engine(0)
    try:
        engine.set(max_batch_tokens=64)
        message = _expect(ValueError, lambda: engine.set(max_batch_tokens=4096),
                          "max_batch_tokens=4096 is above 1024")
        print(f"ok: raising a batch limit past the warmed one is refused\n    {message}")
    finally:
        engine.close()


def _fake_default(op_name: str) -> None:
    """Make `op_name`'s cpu default an impl whose backend package is not installed -- what a
    missing Marlin is on an A100 outside the image."""
    from kelpie_models.kernels import devices
    from kelpie_models.kernels.backends import declare_backend
    from kelpie_models.kernels.op import REGISTRY

    declare_backend(FAKE_BACKEND, package="kelpie_fake_missing_package", extra="fake-extra")

    @REGISTRY[op_name].register("fake_fast", backend=FAKE_BACKEND)
    def _fake(*args: object) -> object:
        raise AssertionError("never runs: its backend is missing")

    devices.DEFAULTS["cpu"] = {**devices.DEFAULTS["cpu"], op_name: "fake_fast"}


def case_missing_backend() -> None:
    from kelpie_models.kernels import BuildError, bind, ops

    _fake_default("gelu")
    bind("cpu")  # resolves nothing, so the missing backend is not an error yet
    print("    bind('cpu') with a gelu default whose backend is missing: no error")
    message = _expect(BuildError, lambda: ops.gelu(torch.randn(2, 8)),
                      "kelpie::gelu=fake_fast (default on cpu", "needs backend",
                      "install kelpie[fake-extra]", "kernels={ops.gelu: <one of 'reference'")
    print(f"ok: a default whose backend is missing fails at its first dispatch\n    {message}")


def case_gpt2_missing_backend() -> None:
    from kelpie_models.kernels import BuildError
    from kelpie_models.models.torch import gpt2
    from kelpie_models.sdk.run import build

    _fake_default("gelu")
    message = _expect(BuildError, lambda: build(gpt2, device="cpu"),
                      "kelpie::gelu=fake_fast", "first dispatched at decode R=")
    print(f"ok: gpt2's build fails in its warm pass, naming the op, step and fix\n    {message}")


def case_gpt2_dense_no_moe() -> None:
    from kelpie_models.models.torch import gpt2
    from kelpie_models.sdk.run import build

    _fake_default("moe")  # a default moe whose backend is missing: a dense model never sees it
    built = build(gpt2, device="cpu")
    try:
        assert "moe" not in built.binding.resolved, built.binding.resolved
        assert "moe" not in built.table.names(), built.table
        print(f"ok: gpt2 builds with a broken moe default; moe never resolved\n    "
              f"{built.table.line()}")
    finally:
        built.engine.close()


CASES: dict[str, Callable[[], None]] = {
    "second_bind": case_second_bind,
    "post_freeze": case_post_freeze,
    "unknown_kernels_key": case_unknown_kernels_key,
    "unknown_kernels_impl": case_unknown_kernels_impl,
    "missing_backend": case_missing_backend,
    "other_device": case_other_device,
    "greedy_skips_rng": case_greedy_skips_rng,
    "top_k_sampling": case_top_k_sampling,
    "degraded_extra": case_degraded_extra,
    "unwarmed_shape": case_unwarmed_shape,
    "raise_past_warmed": case_raise_past_warmed,
    "gpt2_missing_backend": case_gpt2_missing_backend,
    "gpt2_dense_no_moe": case_gpt2_dense_no_moe,
    "gpt2_top_k": case_gpt2_top_k,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", choices=sorted(CASES))
    ap.add_argument("--no-model", action="store_true", help="skip the gpt2_* cases")
    args = ap.parse_args()
    if args.case is not None:
        CASES[args.case]()
        return 0
    failed = []
    for name in CASES:
        if args.no_model and name.startswith("gpt2_"):
            continue
        print(f"--- {name}", flush=True)
        rc = subprocess.run([sys.executable, str(Path(__file__)), "--case", name]).returncode
        if rc != 0:
            failed.append(name)
    print(f"{len(CASES) - len(failed)} passed, {len(failed)} failed {failed or ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
