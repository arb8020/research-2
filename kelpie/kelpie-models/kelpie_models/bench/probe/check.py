# copied from crucible/verification/engines/probe/check.py @ dfb735f9a8d9
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist, fmean
from typing import Iterable


@dataclass(frozen=True)
class HypothesisSpec:
    reference_mean: float
    sample_count: int
    sigma: float
    alpha: float = 0.05
    beta: float = 0.2
    higher_is_better: bool = True

    _PROB_UPPER = 0.5

    def __post_init__(self) -> None:
        finite = (self.reference_mean, self.sigma, self.alpha, self.beta)
        if not all(math.isfinite(value) for value in finite):
            msg = "hypothesis parameters must be finite"
            raise ValueError(msg)
        if self.sample_count <= 0:
            msg = "sample_count must be positive"
            raise ValueError(msg)
        if self.sigma < 0:
            msg = "sigma must be non-negative"
            raise ValueError(msg)
        if not 0 < self.alpha < self._PROB_UPPER:
            msg = "alpha must be between 0 and 0.5"
            raise ValueError(msg)
        if not 0 < self.beta < self._PROB_UPPER:
            msg = "beta must be between 0 and 0.5"
            raise ValueError(msg)


@dataclass(frozen=True)
class CheckResult:
    spec: HypothesisSpec
    observed_mean: float
    threshold: float
    minimum_detectable_effect: float
    passed: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return {
            "observed_mean": self.observed_mean,
            "reference_mean": self.spec.reference_mean,
            "threshold": self.threshold,
            "minimum_detectable_effect": self.minimum_detectable_effect,
            "sample_count": self.spec.sample_count,
            "alpha": self.spec.alpha,
            "beta": self.spec.beta,
            "passed": self.passed,
        }


def _scale(spec: HypothesisSpec) -> float:
    return math.sqrt(2 * spec.sigma**2 / spec.sample_count)


def one_sided_quality_threshold(spec: HypothesisSpec) -> float:
    # algo: matches TensorRT-LLM's accuracy suite -- the stored reference and
    # algo: the observed run are treated as independent samples, decided by a
    # algo: one-sided normal approximation.
    delta = NormalDist().inv_cdf(spec.alpha) * _scale(spec)
    if spec.higher_is_better:
        return spec.reference_mean + delta
    return spec.reference_mean - delta


def minimum_detectable_effect(spec: HypothesisSpec) -> float:
    z_alpha = NormalDist().inv_cdf(spec.alpha)
    z_beta = NormalDist().inv_cdf(spec.beta)
    return -(z_alpha + z_beta) * _scale(spec)


def required_sample_count(
    *, theta: float, sigma: float, alpha: float = 0.05, beta: float = 0.2
) -> int:
    _prob_upper = 0.5  # noqa: PLR2004
    if not all(math.isfinite(value) for value in (theta, sigma, alpha, beta)):
        msg = "sample-planning parameters must be finite"
        raise ValueError(msg)
    if theta <= 0 or sigma < 0:
        msg = "theta must be positive and sigma non-negative"
        raise ValueError(msg)
    if not 0 < alpha < _prob_upper or not 0 < beta < _prob_upper:
        msg = "alpha and beta must be between 0 and 0.5"
        raise ValueError(msg)
    if sigma == 0:
        return 1
    z_distance = NormalDist().inv_cdf(1 - beta) - NormalDist().inv_cdf(alpha)
    return math.ceil(2 * sigma**2 * (z_distance / theta) ** 2)


def check(spec: HypothesisSpec, scores: Iterable[float]) -> CheckResult:
    observed_scores = tuple(float(score) for score in scores)
    if len(observed_scores) != spec.sample_count:
        msg = (
            f"expected {spec.sample_count} scores,"
            f" received {len(observed_scores)}"
        )
        raise ValueError(msg)
    if not all(math.isfinite(score) for score in observed_scores):
        msg = "scores must be finite"
        raise ValueError(msg)

    observed_mean = fmean(observed_scores)
    gate = one_sided_quality_threshold(spec)
    passed = observed_mean >= gate if spec.higher_is_better else observed_mean <= gate
    return CheckResult(
        spec=spec,
        observed_mean=observed_mean,
        threshold=gate,
        minimum_detectable_effect=minimum_detectable_effect(spec),
        passed=passed,
    )


def bonferroni_equal_alpha_allocation(family_alpha: float, gated_task_count: int) -> float:
    _prob_upper = 0.5  # noqa: PLR2004
    if not math.isfinite(family_alpha) or not 0 < family_alpha < _prob_upper:
        msg = "family_alpha must be between 0 and 0.5"
        raise ValueError(msg)
    if gated_task_count <= 0:
        msg = "gated_task_count must be positive"
        raise ValueError(msg)
    return family_alpha / gated_task_count


