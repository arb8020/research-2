"""The run step for chapter 1: expected answers (trusted, cached) and candidate Runs (isolated child, cached).

    execute(ctx, op, candidate, cases)
      expected(case)       store "expected" <- (fp64 truth on ctx.device, the reference's own error); the truth tensor
                           itself is a "truth" entry (a model's is dtype-independent: one ~150 MB copy, not one per dtype)
      run keys             candidate file sha256 + attr + case + env + runner code fp + expected key
      all in the store?    -> done, no child at all (a warm check never imports the reader's code)
      else one Child       load -> blocked (import / bind error) | ready
                           per case: call -> facts (returned? dtype, shape, inputs unchanged, deterministic, err vs
                           truth, logit reductions) -> store "run"
                           finish -> coverage of the bound function's lines -> store "run" (case "coverage")
A died / timed-out call is recorded for grading but not cached (it may be the machine, not the code), and the cases
after it are reported as not run.
"""

from __future__ import annotations

import ast
import json
import platform
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import torch

from assay.ch01.cases import Case, make_inputs
from assay.ch01.numerics import band, reduce_output, reference_stats
from assay.ch01.registry import Op
from assay.ch01.tensors import decode, digest, pack_args, raw
from assay.sandbox import Child, ChildDied, ChildTimeout, Isolation, ProtocolError
from assay.store import Entry, Store, files_fp, key_of, sha256

ASSAY = Path(__file__).resolve().parents[1]  # .../assay (the package)
RUN_CODE = ("store.py", "sandbox.py", "ch01/child.py", "ch01/tensors.py", "ch01/numerics.py", "ch01/run.py",
            "ch01/cases.py")
KEEP_FULL_BYTES = 16 << 20  # outputs up to this size are stored whole; bigger ones only when they look wrong
STORAGE_MULT, STORAGE_FLOORS = 2.0, {"fp32": 2e-5, "fp16": 1e-3, "bf16": 2e-2}  # "looks wrong", for storage only


class InfraError(Exception):
    """Not evidence about the candidate (the child never booted, the store broke): exit 2, nothing graded."""


@dataclass(frozen=True)
class Ctx:
    store: Store
    env: dict[str, Any]
    iso: Isolation
    log: Callable[[str], None]
    startup_timeout: float = 180.0
    call_timeout: float = 60.0
    zygote: Path | None = None  # the warm process's socket: children fork from it instead of spawning

    @property
    def device(self) -> str:
        return self.env["device"]


@dataclass(frozen=True)
class Candidate:
    file: Path
    attr: str
    adapter: str  # child.ADAPTERS: "plain" | "forward"

    def fp(self) -> dict[str, str]:
        return {"file": self.file.name, "sha256": sha256(self.file.read_bytes()), "attr": self.attr,
                "adapter": self.adapter}


@dataclass(frozen=True)
class OpRuns:
    blocked: dict[str, Any] | None  # {notes, where} when the file would not import / bind
    runs: list[tuple[Case, Entry | None]]  # None: not run (the child died on an earlier case)
    coverage: Entry | None
    executed: bool  # False: everything came from the store


def detect_env() -> dict[str, Any]:
    """One env per process: where expected answers and runs are computed. Part of every cache key."""
    cuda = torch.cuda.is_available()
    chip = "sm_{}{}".format(*torch.cuda.get_device_capability()) if cuda else "cpu"
    return {"chip": chip, "device": "cuda" if cuda else "cpu", "torch": torch.__version__,
            "transformers": _version("transformers"), "python": platform.python_version(),
            "machine": f"{platform.system()} {platform.machine()}"}


def _version(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "absent"


def runner_fp() -> str:
    return files_fp([ASSAY / f for f in RUN_CODE], ASSAY)


def reference_fp(op: Op) -> str:
    spec_file = Path(op.reference.__code__.co_filename)
    return files_fp([spec_file, ASSAY / "ch01/numerics.py", ASSAY / "ch01/cases.py", ASSAY / "ch01/texts.py"], ASSAY)


def _inputs_key(case: Case) -> dict[str, Any]:
    """What the truth depends on: a model's token ids do not depend on the dtype; an op's randn inputs do."""
    full = case.to_json()
    return {k: v for k, v in full.items() if k != "dtype"} if case.prompt else full


def expected(ctx: Ctx, op: Op, case: Case, inputs: tuple) -> Entry:
    truth_parts = {"op": op.name, "reference": reference_fp(op), "inputs": _inputs_key(case), "env": ctx.env}
    parts = {**truth_parts, "dtype": case.dtype_name}
    found = ctx.store.get("expected", key_of(parts))
    if found is not None:
        return found
    on = tuple(a.to(ctx.device) if isinstance(a, torch.Tensor) else a for a in inputs)
    if op.truth_fn is not None:
        truth, reference = op.truth_fn(case, on, ctx.device)
    else:
        upcast = tuple(a.double() if isinstance(a, torch.Tensor) and a.is_floating_point() else a for a in on)
        truth, reference = op.reference(*upcast), op.reference(*on)
    truth = truth.cpu()
    truth_entry = ctx.store.derive("truth", truth_parts, lambda: (
        {"shape": list(truth.shape), "summary": f"{op.name} {case.label()}"}, {"truth.bin": raw(truth)}))
    stats = reference_stats(truth, reference.cpu())
    return ctx.store.put("expected", key_of(parts), {
        "parts": parts, "truth": truth_entry.key, "shape": list(truth.shape),
        "dtype": str(reference.dtype).removeprefix("torch."), **stats,
        "summary": f"{op.name} {case.label()} {case.dtype_name}"}, {})


def load_truth(store: Store, exp: Entry) -> torch.Tensor:
    entry = store.get("truth", exp.meta["truth"])
    assert entry is not None, f"truth {exp.meta['truth']} is missing from the store"
    return decode({"dtype": "float64", "shape": exp.meta["shape"]}, entry.read("truth.bin"))


def execute(ctx: Ctx, op: Op, cand: Candidate, cases: list[Case], *, grade_only: bool = False) -> OpRuns:
    inputs = {case: make_inputs(op, case) for case in cases}
    exps = {case: expected(ctx, op, case, inputs[case]) for case in cases}
    cand_fp, runner = cand.fp(), runner_fp()
    keys = {case: key_of({"chapter": "ch01", "op": op.name, "candidate": cand_fp, "case": case.to_json(),
                          "env": ctx.env, "runner": runner, "expected": exps[case].key}) for case in cases}
    want_coverage = op.kind == "op"
    cov_key = key_of({"op": op.name, "candidate": cand_fp, "cases": sorted(keys.values()), "runner": runner})
    stored = {case: ctx.store.get("run", keys[case]) for case in cases}
    cov = ctx.store.get("run", cov_key) if want_coverage else None
    if all(stored.values()) and (cov is not None or not want_coverage):
        return OpRuns(None, [(c, stored[c]) for c in cases], cov, executed=False)
    if grade_only:
        raise InfraError(f"--grade-only: {op.name} has runs missing from the store; run without it first")
    ctx.log(f"{op.name}: running {cand.file.name}:{cand.attr} on {len(cases)} cases in an isolated child "
            f"({ctx.iso.mode}, {'forked' if ctx.zygote else 'spawned'})")
    with Child("assay.ch01.child", cwd=cand.file.parent, iso=ctx.iso, pythonpath=ASSAY.parent,
               extra_env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}, zygote=ctx.zygote) as child:
        blocked = _load(ctx, child, cand, want_coverage)
        if blocked is not None:
            return OpRuns(blocked, [(c, None) for c in cases], None, executed=True)
        results: list[tuple[Case, Entry | None]] = []
        alive = True
        for case in cases:
            if not alive:
                results.append((case, None))
                continue
            facts, files = _call(ctx, child, case, inputs[case], exps[case])
            alive = facts["status"] in ("returned", "raised")
            meta = {"parts": {"case": case.to_json(), "op": op.name, "candidate": cand_fp},
                    "expected": exps[case].key, "isolation": ctx.iso.to_json(), "facts": facts,
                    "summary": f"{op.name} {case.label()} {case.dtype_name}: {facts['status']}"}
            results.append((case, ctx.store.put("run", keys[case], meta, files) if alive
                            else Entry("run", keys[case], None, {**meta, "files": {}})))
        if want_coverage and alive:
            cov = ctx.store.put("run", cov_key, {"facts": _coverage(ctx, child, cand), "isolation": ctx.iso.to_json(),
                                                 "summary": f"{op.name} coverage"}, {})
        return OpRuns(None, results, cov if alive else None, executed=True)


def _load(ctx: Ctx, child: Child, cand: Candidate, coverage: bool) -> dict[str, Any] | None:
    """Boot + import the candidate. None when ready; a `blocked` record when the reader's file is the problem;
    InfraError when the child never booted (that is our environment, not their code)."""
    try:
        boot, _ = child.recv(ctx.startup_timeout)
    except (ChildTimeout, ChildDied, ProtocolError) as exc:
        raise InfraError(f"the check child did not boot ({type(exc).__name__}: {exc})\n{child.log_tail()}") from exc
    assert boot["kind"] == "boot", boot
    child.send({"kind": "load", "file": str(cand.file), "attr": cand.attr, "adapter": cand.adapter,
                "device": ctx.device, "coverage": coverage}, {}, ctx.call_timeout)
    try:
        header, _ = child.recv(ctx.startup_timeout)
    except ChildTimeout:
        return {"notes": f"importing {cand.file.name} did not finish in {ctx.startup_timeout:g}s",
                "where": where(cand.file, None)}
    except (ChildDied, ProtocolError) as exc:
        return {"notes": f"importing {cand.file.name} killed the check child: {exc}", "where": where(cand.file, None)}
    if header["kind"] == "import_error":
        return {"notes": f"{cand.file.name} does not import: {header.get('error')}",
                "where": where(cand.file, header.get("line")), "traceback": header.get("traceback", "")}
    if header["kind"] == "bind_error":
        return {"notes": str(header.get("error")), "where": where(cand.file, None)}
    if header["kind"] != "ready":
        return {"notes": f"unexpected reply {header['kind']!r} to load", "where": where(cand.file, None)}
    return None


def _call(ctx: Ctx, child: Child, case: Case, inputs: tuple, exp: Entry) -> tuple[dict[str, Any], dict[str, bytes]]:
    """One case: the child's reply -> facts (no thresholds; the grader decides) + files to keep."""
    header_args, blobs = pack_args(inputs)
    want = {"dtype": exp.meta["dtype"], "shape": exp.meta["shape"]}
    base = {"want": want, "ref_err": exp.meta["ref_err"], "scale": exp.meta["scale"],
            "ref_kl_max": exp.meta.get("ref_kl_max")}
    try:
        child.send({"kind": "call", "args": header_args, "dtype": case.dtype_name}, blobs, ctx.call_timeout)
        reply, got = child.recv(ctx.call_timeout)
        if reply["kind"] == "raised":
            return {**base, "status": "raised", "notes": f"raised: {reply.get('error')}"}, {}
        if reply["kind"] != "returned":
            raise ProtocolError(f"unexpected reply kind {reply['kind']!r}")
        out = decode(reply.get("out"), got.get("out", b""))
        after = reply.get("args_after")
        if not (isinstance(after, list) and len(after) == 2):
            raise ProtocolError("args_after is not two lists")
    except ChildTimeout:
        return {**base, "status": "timed_out", "notes": f"timed out after {ctx.call_timeout:g}s"}, {}
    except ChildDied as exc:
        return {**base, "status": "died", "notes": f"child died: {exc}"}, {}
    except ProtocolError as exc:
        return {**base, "status": "died", "notes": f"bad reply: {exc}"}, {}
    sent = [digest(a) if isinstance(a, torch.Tensor) else None for a in inputs]
    mutated = [(run, i) for run, row in enumerate(after) for i, d in enumerate(sent)
               if d is not None and (not isinstance(row, list) or i >= len(row) or row[i] != d)]
    facts: dict[str, Any] = {
        **base, "status": "returned", "seconds": reply.get("seconds"),
        "out": {"dtype": str(out.dtype).removeprefix("torch."), "shape": list(out.shape)},
        "inputs_unchanged": not mutated, "mutated": mutated[:1],
        "deterministic": reply.get("out1") == digest(out)}
    files: dict[str, bytes] = {}
    if facts["out"] == want:
        reduced = reduce_output(out, load_truth(ctx.store, exp))
        if "reduced" in reduced:
            files["reduced.json"] = json.dumps(reduced.pop("reduced")).encode()
        facts.update(reduced)
    looks_wrong = facts["out"] != want or not facts.get("finite", False) or facts["err"] > band(
        facts["ref_err"], facts["scale"], case.dtype_name, STORAGE_MULT, STORAGE_FLOORS)
    if out.numel() * out.element_size() <= KEEP_FULL_BYTES or looks_wrong:
        files["out.bin"] = raw(out)
    return facts, files


def _coverage(ctx: Ctx, child: Child, cand: Candidate) -> dict[str, Any]:
    """The bound function's lines and branches the whole sweep never executed."""
    try:
        child.send({"kind": "finish"}, {}, ctx.call_timeout)
        report, _ = child.recv(ctx.call_timeout)
    except (ChildTimeout, ChildDied, ProtocolError) as exc:
        return {"status": "died", "notes": f"no coverage report: {exc}"}
    lines = function_lines(cand.file, cand.attr)
    if report.get("kind") != "coverage" or not isinstance(report.get("missing_lines"), list):
        return {"status": "died", "notes": f"bad coverage report: {str(report)[:200]}"}
    if lines is None:
        return {"status": "returned", "executed": False, "missing_lines": [], "missing_branches": [], "range": None}
    first, last = lines
    branches = report.get("missing_branches") or []
    return {"status": "returned", "executed": bool(report.get("executed")), "range": [first, last],
            "missing_lines": [n for n in report["missing_lines"] if isinstance(n, int) and first <= n <= last],
            "missing_branches": [b for b in branches if isinstance(b, list) and len(b) == 2
                                 and isinstance(b[0], int) and first <= b[0] <= last]}


# ---- where (file, line, region), from the source text: parsed, never imported ---------------------------------------

REGION = re.compile(r"^\s*#\s*region:\s*(\S+)")
ENDREGION = re.compile(r"^\s*#\s*endregion")


def function_lines(path: Path, name: str) -> tuple[int, int] | None:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except (SyntaxError, ValueError):
        return None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.lineno, node.end_lineno or node.lineno
    return None


def region_at(path: Path, line: int) -> str | None:
    """The `# region: <name>` ... `# endregion` block holding `line` (markers are navigation; a broken one -> None)."""
    current = None
    for number, text in enumerate(path.read_text(errors="replace").splitlines(), start=1):
        opened = REGION.match(text)
        if opened:
            current = opened.group(1)
        if number == line:
            return current
        if ENDREGION.match(text):
            current = None
    return None


def where(path: Path, line: int | None, attr: str | None = None) -> dict[str, Any]:
    if line is None and attr is not None:
        found = function_lines(path, attr)
        line = found[0] if found else None
    out: dict[str, Any] = {"file": path.name, "line": line}
    region = region_at(path, line) if line is not None else None
    if region is not None:
        out["region"] = region
    return out

