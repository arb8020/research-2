"""PPO on Andy Jones' probe envs: each probe isolates one piece (value, obs, discount, policy, both).

Slow (each trains for a few seconds): set RUN_SLOW_TESTS=1 to run.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import torch

from robots.envs.probes import (
    Probe1Value,
    Probe2Obs,
    Probe3Discount,
    Probe4Policy,
    Probe5PolicyValue,
)

pytestmark = pytest.mark.skipif(os.environ.get("RUN_SLOW_TESTS") != "1", reason="slow; set RUN_SLOW_TESTS=1")


def _load_example(name: str) -> Any:
    # robots/examples is scripts, not a package; dataclasses need the module in sys.modules.
    path = Path(__file__).parent.parent / "examples" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


ppo = _load_example("breakout_ppo")

GAMMA_PROBE3 = 0.5
SMALL = {"num_envs": 8, "num_steps": 16, "iters": 60, "lr": 1e-3}

# (label, obs, quantity, want, tol). quantity "V" is the value; "P1" is P(action=1 | obs).
Expect = list[tuple[str, float, str, float, float]]


def check(make_env: Callable[[int], Any], expect: Expect, cfg_overrides: dict[str, Any]) -> None:
    cfg = replace(ppo.Config(), **cfg_overrides)
    params, history = ppo.train(make_env(cfg.num_envs), cfg)
    obs = torch.tensor([[o] for _, o, _, _, _ in expect])
    with torch.no_grad():
        logits, value = ppo.forward(params, obs)
    p1 = torch.softmax(logits, dim=-1)[:, -1]
    actual = [value[i].item() if q == "V" else p1[i].item() for i, (_, _, q, _, _) in enumerate(expect)]
    lines = [
        f"{'ok  ' if abs(a - want) <= tol else 'FAIL'} {label}: {a:+.4f} (want {want:+.3f} +- {tol})"
        for (label, _, _, want, tol), a in zip(expect, actual, strict=True)
    ]
    failed = any(line.startswith("FAIL") for line in lines)
    assert not failed, "\n" + "\n".join(lines) + f"\nlast iter: {history[-1]}"


def test_probe1_value() -> None:
    check(Probe1Value, [("V(0)", 0.0, "V", 1.0, 0.1)], SMALL)


def test_probe2_obs() -> None:
    check(Probe2Obs, [("V(-1)", -1.0, "V", -1.0, 0.1), ("V(+1)", 1.0, "V", 1.0, 0.1)], SMALL)


def test_probe3_discount() -> None:
    check(
        Probe3Discount,
        [("V(0)", 0.0, "V", GAMMA_PROBE3, 0.1), ("V(1)", 1.0, "V", 1.0, 0.1)],
        {**SMALL, "gamma": GAMMA_PROBE3},
    )


def test_probe4_policy() -> None:
    check(Probe4Policy, [("V(0)", 0.0, "V", 1.0, 0.1), ("P(1|0)", 0.0, "P1", 1.0, 0.1)], SMALL)


def test_probe5_policy_value() -> None:
    check(
        Probe5PolicyValue,
        [
            ("V(-1)", -1.0, "V", 1.0, 0.1),
            ("V(+1)", 1.0, "V", 1.0, 0.1),
            ("P(1|-1)", -1.0, "P1", 0.0, 0.1),
            ("P(1|+1)", 1.0, "P1", 1.0, 0.1),
        ],
        SMALL,
    )
