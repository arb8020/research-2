"""GPU smoke: K=0 `run()` with the DEFAULT capture (None -> CUDA graphs on cuda), so the step
is a `Captured` wrapper. Before 3f24395 run() would raise AttributeError: no `has_drafter`.
    python -m scripts.smoke_run_k0 [model]      # default gpt2

Passes since rung 0 (core/rung0-native-commit): `Captured` gained forward / sample /
capturable and attribute passthrough, which build's `_warm` needs (design-multigpu 7.9).

gpt2, not gpt-oss: gpt-oss's reference MoE does a host sync (`int(local.sum())`), so it cannot be
graph-captured at all -- same on main, independent of this branch.
"""
import importlib
import sys
import time

from kelpie_models.sdk.captured import Captured
from kelpie_models.sdk.run import build, run
from kelpie_models.sdk.tiers import Capacity

name = sys.argv[1] if len(sys.argv) > 1 else "gpt2"
model = importlib.import_module(f"kelpie_models.models.torch.{name}")
cap = Capacity(max_seq_len=128)

seen: list[object] = []


def spy(*a, **kw):
    b = build(*a, **kw)
    seen.append(b.step)
    return b


sys.modules["kelpie_models.sdk.run"].build = spy
with run(model, device="cuda", capacity=cap) as engine:
    assert isinstance(seen[0], Captured), type(seen[0])
    rid = engine.submit([464, 2068, 7586, 21831, 18045, 625, 262], max_new_tokens=16)
    toks: list[int] = []
    t0 = time.perf_counter()
    while True:
        poll = engine.poll(rid)
        toks.extend(poll.new_tokens)
        if poll.finished:
            break
        assert time.perf_counter() - t0 < 600, ("timeout", toks)
        time.sleep(0.001)
print(f"smoke_run_k0: ok, {name}, step={type(seen[0]).__name__}, {len(toks)} tokens: {toks}",
      flush=True)
