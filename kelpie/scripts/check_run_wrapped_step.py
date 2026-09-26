"""CPU check: `run()` starts the Zig loop for any step, and refuses `drafter=` (a drafter's loop
is caller-written, docs/design-core-option2.md 1(b)).

With capture (default on cuda) or compile=True, `build` returns a Captured / torch.compile
wrapper as the step, and that wrapper has no `has_drafter`. `build` is stubbed here, so no
libkelpie, no weights, no GPU. Run from kelpie/:
    PYTHONPATH=kelpie-models:kelpie-engine uv run --no-project --with torch --with numpy \
        python scripts/check_run_wrapped_step.py
"""
from types import ModuleType, SimpleNamespace

from kelpie_models.sdk import run as run_mod


class FakeEngine:
    def __init__(self) -> None:
        self.started_with = None
        self.closed = False

    def start_loop(self, step: object) -> None:
        self.started_with = step

    def close(self) -> None:
        self.closed = True


class WrappedStep:
    """Stands in for Captured(step) / torch.compile(step): no `has_drafter`."""


def built(step: object) -> SimpleNamespace:
    return SimpleNamespace(engine=FakeEngine(), step=step)


real_build = run_mod.build

# K=0, wrapped step: must start the Zig loop, not touch step.has_drafter.
b = built(WrappedStep())
run_mod.build = lambda model, **kw: b
with run_mod.run(object(), device="cuda") as engine:
    assert engine is b.engine
assert b.engine.started_with is b.step, "K=0 run() did not start the loop"
assert b.engine.closed
print("ok: K=0 run() with a wrapped step starts the loop")

# Drafter passed: refused before anything is built.
b = built(WrappedStep())
try:
    with run_mod.run(object(), device="cpu", capture=False, drafter=object()):
        raise SystemExit("run(drafter=...) did not refuse")
except ValueError as e:
    assert "caller-written loop" in str(e), e
assert b.engine.started_with is None, "run(drafter=...) started the loop"
print("ok: run(drafter=...) is refused; build + the caller's loop drive a drafter")

# build refuses drafter + compile up front (before any weights load); capture is the drafter
# step's own (DFlashStep.capture).
run_mod.build = real_build
stub = ModuleType("stub_model")
stub.DTYPE = "float32"
for kw in (dict(device="cuda", compile=True), dict(device="cpu", compile=True)):
    try:
        real_build(stub, drafter=object(), **kw)
    except AssertionError as e:
        assert "drafter needs compile=False" in str(e), e
    else:
        raise SystemExit(f"build accepted a drafter with {kw}")
print("ok: build rejects drafter with compile")
