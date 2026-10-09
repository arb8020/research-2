"""Check one candidate of one op: every case of the sweep, under coverage, in a spawned child.

    check_candidate(op, "candidates.layer_norm:layer_norm", policy)
      prepare: for each case -> inputs, fp64 truth, budget band     (parent; nothing untrusted yet)
               + reference greedy runs, if the op opts in
      Child(qualname): for each case -> call -> judge -> Record      (the candidate's process)
                       greedy top-k, if the op opts in -> Record
                       finish -> coverage -> Record
    -> list[Record], one JSON line each

A judged call fails, in this order, for: raising / timing out / dying, wrong dtype, wrong
shape, mutating an input, two runs not bitwise equal, error over budget.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import inspect
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import torch

from harness.budget import GreedyStep, band, compare_greedy, grade, greedy_step
from harness.cases import DTYPE_NAMES, Case, make_inputs, sweep
from harness.isolate import CallResult, Child, Coverage, Died, Raised, Returned, TimedOut
from harness.registry import Op


@dataclass(frozen=True)
class Policy:
    """How a check runs and whether its failures block. `blocking` is already resolved for the
    op (per-op default, overridden per op or globally by the CLI; model checks always block)."""

    blocking: bool
    startup_timeout: float
    call_timeout: float
    extra_path: tuple[str, ...]


@dataclass(frozen=True)
class Fingerprint:
    """What a verdict was measured on: a cached verdict is valid only while all of this holds."""

    dtype: str
    device: str
    torch_version: str
    candidate_sha256: str
    reference_sha256: str


@dataclass(frozen=True)
class Outcome:
    verdict: str  # "pass" | "fail"
    blocking: bool
    reason: str  # "" on a pass
    err: float | None
    band: float | None


@dataclass(frozen=True)
class Record:
    """One JSONL line: which check, of what, on which case, with what result."""

    check: str  # "budget" | "greedy_topk" | "coverage"
    op: str
    candidate: str
    case: str
    outcome: Outcome
    fingerprint: Fingerprint

    def to_json(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Prepared:
    """A case with everything the parent computes before the candidate exists."""

    case: Case
    inputs: tuple
    truth: torch.Tensor
    band: float


def check_candidate(declared: Op, qualname: str, policy: Policy) -> list[Record]:
    assert ":" in qualname, f"candidate must be 'module:fn', got {qualname!r}"
    candidate_file = locate(qualname.partition(":")[0], policy.extra_path)
    candidate_sha = hashlib.sha256(candidate_file.read_bytes()).hexdigest()
    reference_sha = hashlib.sha256(inspect.getsource(declared.reference).encode()).hexdigest()

    def fingerprint(dtype: torch.dtype) -> Fingerprint:
        return Fingerprint(DTYPE_NAMES[dtype], "cpu", torch.__version__, candidate_sha,
                           reference_sha)

    def record(check: str, case: str, dtype: torch.dtype, outcome: Outcome) -> Record:
        return Record(check, declared.name, qualname, case, outcome, fingerprint(dtype))

    prepared = [_prepare(declared, case) for case in sweep(declared)]
    greedy_reference = _greedy_reference(declared) if declared.greedy else []
    records: list[Record] = []
    with Child(qualname, candidate_file, policy.extra_path, policy.startup_timeout,
               policy.call_timeout) as child:
        if child.startup_error is not None:
            return [record("budget", "(import)", declared.sweep.dtypes[0],
                           _fail(policy, child.startup_error))]
        for item in prepared:
            result = child.call(item.inputs)
            outcome = _judge(item, result, policy)
            records.append(record("budget", item.case.label(), item.case.dtype, outcome))
            if isinstance(result, (TimedOut, Died)):
                return records  # the child is gone; later cases cannot run
        for prompt, reference_steps in greedy_reference:
            outcome = _check_greedy(declared, child, prompt, reference_steps, policy)
            records.append(record("greedy_topk", prompt, torch.float32, outcome))
        covered = child.finish()
        records.append(record("coverage", str(candidate_file), declared.sweep.dtypes[0],
                              _coverage_outcome(covered, policy)))
    return records


def locate(module: str, extra_path: tuple[str, ...]) -> Path:
    """The candidate module's file, found WITHOUT importing it or its packages (importing runs
    code, and this is the trusted process)."""
    search: list[str] | None = [*extra_path, *sys.path]
    spec = None
    for part in module.split("."):
        spec = importlib.machinery.PathFinder.find_spec(part, search)
        if spec is None:
            raise FileNotFoundError(f"candidate module {module!r}: cannot find {part!r}")
        search = list(spec.submodule_search_locations or [])
    assert spec is not None and spec.origin is not None, f"{module!r} has no source file"
    return Path(spec.origin)


def _prepare(declared: Op, case: Case) -> Prepared:
    inputs = make_inputs(declared, case)
    reference = declared.reference(*_clone(inputs))
    truth = (declared.truth_fn(*_clone(inputs)) if declared.truth_fn is not None
             else declared.reference(*_upcast(inputs)))
    return Prepared(case, inputs, truth, band(truth, reference))


def _judge(item: Prepared, result: CallResult, policy: Policy) -> Outcome:
    problem = _call_problem(item.inputs, result)
    if problem is not None:
        return _fail(policy, problem)
    assert isinstance(result, Returned)
    out = result.outputs[0]
    if out.dtype != item.case.dtype:
        return _fail(policy, f"output dtype {out.dtype}, want {item.case.dtype}")
    if out.shape != item.truth.shape:
        return _fail(policy, f"output shape {list(out.shape)}, want {list(item.truth.shape)}")
    graded = grade(out, item.truth, item.band)
    if not graded.passed:
        return Outcome("fail", policy.blocking, f"err {graded.err:.3g} > budget {graded.band:.3g}",
                       graded.err, graded.band)
    return Outcome("pass", policy.blocking, "", graded.err, graded.band)


def _call_problem(inputs: tuple, result: CallResult) -> str | None:
    """Everything wrong with a call that is not about numbers: None if it returned cleanly,
    left its inputs alone, and gave the same bits twice."""
    if isinstance(result, Raised):
        return f"raised: {result.error}"
    if isinstance(result, TimedOut):
        return f"timed out after {result.seconds:g}s"
    if isinstance(result, Died):
        return f"child died: {result.why}"
    for run, after in enumerate(result.args_after):
        for index, arg in enumerate(inputs):
            if isinstance(arg, torch.Tensor) and not _same_bits(arg, after[index]):
                return f"mutated input arg {index} during run {run}"
    if not _same_bits(result.outputs[0], result.outputs[1]):
        return "nondeterministic: two runs on identical inputs differ bitwise"
    return None


def _check_greedy(declared: Op, child: Child, prompt: str, reference: list[GreedyStep],
                  policy: Policy) -> Outcome:
    assert declared.greedy is not None
    ids = declared.greedy.tokenize(prompt)
    steps: list[GreedyStep] = []
    for _ in range(declared.greedy.steps):
        result = child.call((ids,))
        problem = _call_problem((ids,), result)
        if problem is not None:
            return _fail(policy, problem)
        assert isinstance(result, Returned)
        step = greedy_step(result.outputs[0][0, -1], declared.greedy.k)
        steps.append(step)
        ids = torch.cat([ids, torch.tensor([[step.token]])], dim=1)
    why = compare_greedy(reference, steps)
    return _fail(policy, why) if why is not None else Outcome("pass", policy.blocking, "", None, None)


def _greedy_reference(declared: Op) -> list[tuple[str, list[GreedyStep]]]:
    assert declared.greedy is not None
    runs = []
    for prompt in declared.greedy.prompts:
        ids = declared.greedy.tokenize(prompt)
        steps = []
        for _ in range(declared.greedy.steps):
            step = greedy_step(declared.reference(ids)[0, -1], declared.greedy.k)
            steps.append(step)
            ids = torch.cat([ids, torch.tensor([[step.token]])], dim=1)
        runs.append((prompt, steps))
    return runs


def _coverage_outcome(covered: Coverage | Died, policy: Policy) -> Outcome:
    if isinstance(covered, Died):
        return _fail(policy, f"no coverage: {covered.why}")
    if covered.missing_lines == (-1,):
        return _fail(policy, f"{covered.file} never executed")
    if covered.missing_lines or covered.missing_branches:
        lines = ", ".join(map(str, covered.missing_lines)) or "none"
        branches = ", ".join(f"{a}->{b}" for a, b in covered.missing_branches) or "none"
        return _fail(policy, f"sweep never executed lines [{lines}], branches [{branches}]")
    return Outcome("pass", policy.blocking, "", None, None)


def _fail(policy: Policy, reason: str) -> Outcome:
    return Outcome("fail", policy.blocking, reason, None, None)


def _same_bits(a: torch.Tensor, b: torch.Tensor | None) -> bool:
    if b is None or a.dtype != b.dtype or a.shape != b.shape:
        return False
    # compare raw bytes: torch.equal on floats says NaN != NaN and -0.0 == 0.0
    return bool(torch.equal(a.reshape(-1).view(torch.uint8), b.reshape(-1).view(torch.uint8)))


def _clone(args: tuple) -> tuple:
    return tuple(a.clone() if isinstance(a, torch.Tensor) else a for a in args)


def _upcast(args: tuple) -> tuple:
    return tuple(a.double() if isinstance(a, torch.Tensor) and a.dtype.is_floating_point else a
                 for a in args)
