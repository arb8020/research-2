"""Chapter 1's run step: the trusted parent computes expected answers and stores candidate Runs; the untrusted child
imports the reader's file and calls one function. Both sides import this module (the child only uses its child part).

Sections: tensors over frames, the untrusted child, the run step (trusted parent).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import math
import platform
import re
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import torch

from assay.ch01.ops import NAMES, Case, Op, band, make_inputs, reduce_output, reference_stats
from assay.core import (
    Child,
    ChildDied,
    ChildTimeout,
    Entry,
    Isolation,
    ProtocolError,
    Store,
    child_recv,
    child_send,
    files_fp,
    key_of,
    sha256,
)

# --------------------------------------------------------------------------------------------------------------------
# tensors over frames
#
# Tensors over frames: a spec in the JSON header (dtype, shape) + raw bytes in a blob. Both sides use this; the parent
# parses what the child sends with `decode`, which checks every size before it interprets a byte.
# --------------------------------------------------------------------------------------------------------------------

DTYPES = {"float64": torch.float64, "float32": torch.float32, "float16": torch.float16, "bfloat16": torch.bfloat16,
          "int64": torch.int64, "int32": torch.int32, "bool": torch.bool}


def raw(tensor: torch.Tensor) -> bytes:
    flat = tensor.detach().cpu().contiguous().reshape(-1)
    return flat.view(torch.uint8).numpy().tobytes() if flat.numel() else b""


def digest(tensor: torch.Tensor) -> str:
    """sha256 of dtype, shape and raw bytes: equal digests = bitwise equal (NaN payloads and -0.0 included)."""
    h = hashlib.sha256(f"{tensor.dtype}|{list(tensor.shape)}|".encode())
    h.update(raw(tensor))
    return h.hexdigest()


def spec(tensor: torch.Tensor) -> dict[str, Any]:
    dtype = str(tensor.dtype).removeprefix("torch.")
    assert dtype in DTYPES, f"cannot send dtype {tensor.dtype}"
    return {"dtype": dtype, "shape": list(tensor.shape)}


def decode(spec_: Any, data: bytes) -> torch.Tensor:
    if not isinstance(spec_, dict):
        raise ProtocolError("tensor spec is not an object")
    dtype_name, shape = spec_.get("dtype"), spec_.get("shape")
    if dtype_name not in DTYPES:
        raise ProtocolError(f"dtype {dtype_name!r} not allowed")
    if not isinstance(shape, list) or not all(isinstance(d, int) and d >= 0 for d in shape):
        raise ProtocolError(f"shape {shape!r} is not a list of sizes")
    dtype = DTYPES[dtype_name]
    if len(data) != math.prod(shape) * torch.empty((), dtype=dtype).element_size():
        raise ProtocolError(f"{len(data)} bytes for shape {shape} {dtype_name}")
    if not data:
        return torch.empty(shape, dtype=dtype)
    return torch.frombuffer(bytearray(data), dtype=torch.uint8).view(dtype).reshape(shape)


def pack_args(args: tuple) -> tuple[list[Any], dict[str, bytes]]:
    """Call arguments -> header list (a tensor spec, or a plain JSON scalar) + blobs arg0, arg1, ..."""
    header: list[Any] = []
    blobs: dict[str, bytes] = {}
    for i, arg in enumerate(args):
        if isinstance(arg, torch.Tensor):
            header.append({"tensor": spec(arg)})
            blobs[f"arg{i}"] = raw(arg)
        else:
            assert isinstance(arg, int | float), f"arg {i}: {type(arg)} is neither a tensor nor a scalar"
            header.append({"scalar": arg})
    return header, blobs


def unpack_args(header: list[Any], blobs: dict[str, bytes]) -> tuple:
    return tuple(decode(a["tensor"], blobs[f"arg{i}"]) if "tensor" in a else a["scalar"]
                 for i, a in enumerate(header))


# --------------------------------------------------------------------------------------------------------------------
# the untrusted child
#
# The untrusted side: runs in the isolated child (sandbox.Child), imports the reader's file, calls one function.
#
#     parent                                         child
#                                                    import torch, coverage          -> boot
#     load {file, attr, adapter, device, coverage}   coverage.start(); import file    -> ready | import_error {file, line}
#                                                                                        | bind_error
#     call {args, dtype} + arg blobs                 out0 = fn(clones); out1 = fn(clones)
#                                                    -> returned {out spec, sha256 of out1 and of every arg after each
#                                                       run} + out0's bytes | raised {error, line: the deepest frame in
#                                                       the reader's file, e.g. the stub that raised}
#     finish                                         coverage.stop()                  -> coverage {missing lines/branches}
#
# Only run 0's output crosses the pipe in full; run 1 and the inputs-after come back as digests, which the parent
# compares against the bytes it has (a gpt2 output is ~77 MB at 384 tokens; two of them per call would be waste).
# Everything here is as honest as the candidate lets it be: it can patch this module (forges_reply does), but the parent
# only ever parses JSON + raw bytes from it.
# --------------------------------------------------------------------------------------------------------------------

def main(in_fd: int, out_fd: int) -> None:
    import coverage

    _send(out_fd, {"kind": "boot", "torch": torch.__version__}, {})
    header, _ = child_recv(in_fd)
    assert header["kind"] == "load", header
    path = Path(header["file"])
    tracer = None
    if header["coverage"]:
        tracer = coverage.Coverage(branch=True, include=[str(path)], data_file=None, config_file=False)
        tracer.clear_exclude()  # a `# pragma: no cover` must not hide an untested line
        tracer.start()
    try:
        module = _import(path)
    except BaseException as exc:  # noqa: BLE001 -- any import failure is reported (blocked), then we exit
        _send(out_fd, {"kind": "import_error", **_where(exc, path)}, {})
        return
    try:
        fn = ADAPTERS[header["adapter"]](module, header["attr"], header["device"])
    except Exception as exc:  # noqa: BLE001
        _send(out_fd, {"kind": "bind_error", "error": f"{type(exc).__name__}: {exc}"}, {})
        return
    _send(out_fd, {"kind": "ready"}, {})
    _serve(in_fd, out_fd, fn, header["device"], tracer, path)


def _serve(in_fd: int, out_fd: int, fn: Callable[..., Any], device: str, tracer: Any, path: Path) -> None:
    while True:
        try:
            header, blobs = child_recv(in_fd)
        except Exception:  # noqa: BLE001 -- EOF: the parent is done with us
            return
        if header["kind"] == "finish":
            if tracer is not None:
                tracer.stop()
            _send(out_fd, _coverage_report(tracer, path), {})
            return
        assert header["kind"] == "call", header
        args = unpack_args(header["args"], blobs)
        reply, out = _call_twice(fn, args, NAMES[header["dtype"]], device, path)
        _send(out_fd, reply, out)


def _import(path: Path) -> Any:
    sys.path.insert(0, str(path.parent))  # the reader's file may import its siblings
    spec_ = importlib.util.spec_from_file_location(path.stem, path)
    assert spec_ is not None and spec_.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec_)
    sys.modules[path.stem] = module
    spec_.loader.exec_module(module)
    return module


def _where(exc: BaseException, path: Path) -> dict[str, Any]:
    """file:line of an import failure, in the reader's file when it is there (a SyntaxError, or the deepest frame of
    the traceback inside the file)."""
    line = None
    if isinstance(exc, SyntaxError) and exc.filename and Path(exc.filename).resolve() == path.resolve():
        line = exc.lineno
    else:
        for frame in traceback.extract_tb(exc.__traceback__):
            if Path(frame.filename).resolve() == path.resolve():
                line = frame.lineno
    error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return {"error": error, "file": path.name, "line": line, "traceback": traceback.format_exc()[-4000:]}


def _plain(module: Any, attr: str, device: str) -> Callable[..., Any]:
    if not hasattr(module, attr):
        raise AttributeError(f"{Path(module.__file__).name} defines no `{attr}`")
    fn = getattr(module, attr)

    def call(*args: Any, dtype: torch.dtype) -> Any:
        return fn(*args)

    return call


def _model(module: Any, attr: str, device: str) -> tuple[Callable[..., Any], Callable[[torch.dtype], Any]]:
    """gpt2.py's model contract: `load(dtype, device) -> (weights, config)` (given code), then the op's function.
    Weights load once per dtype, inside the first call (under its timeout)."""
    for name in ("load", attr):
        if not hasattr(module, name):
            raise AttributeError(f"{Path(module.__file__).name} defines no `{name}`")
    loaded: dict[torch.dtype, Any] = {}

    def weights(dtype: torch.dtype) -> Any:
        if dtype not in loaded:
            loaded[dtype] = module.load(dtype, device)
        return loaded[dtype]

    return getattr(module, attr), weights


def _forward(module: Any, attr: str, device: str) -> Callable[..., Any]:
    """forward(weights, config, tokens_T) -> logits [T, V]."""
    fn, weights = _model(module, attr, device)

    def call(tokens_T: torch.Tensor, *, dtype: torch.dtype) -> Any:
        w, cfg = weights(dtype)
        with torch.no_grad():
            return fn(w, cfg, tokens_T)

    return call


def _block(module: Any, attr: str, device: str) -> Callable[..., Any]:
    """block(x_TD, weights.layers[i], config) -> [T, D]; x arrives fp32 and is cast to the case's dtype here."""
    fn, weights = _model(module, attr, device)

    def call(x_TD: torch.Tensor, layer: int, *, dtype: torch.dtype) -> Any:
        w, cfg = weights(dtype)
        with torch.no_grad():
            return fn(x_TD.to(dtype), w.layers[layer], cfg)

    return call


def _generate(module: Any, attr: str, device: str) -> Callable[..., Any]:
    """generate(weights, config, prompt ids (a list), n) -> n new ids (a list), returned as an int64 tensor."""
    fn, weights = _model(module, attr, device)

    def call(prompt_T: torch.Tensor, n: int, *, dtype: torch.dtype) -> Any:
        w, cfg = weights(dtype)
        with torch.no_grad():
            ids = fn(w, cfg, prompt_T.tolist(), n)
        if not (isinstance(ids, list) and all(isinstance(i, int) for i in ids)):
            return ids  # not a list of ints: returned as is, and the check says what it was
        return torch.tensor(ids, dtype=torch.int64)

    return call


ADAPTERS = {"plain": _plain, "forward": _forward, "block": _block, "generate": _generate}


def _call_twice(fn: Callable[..., Any], args: tuple, dtype: torch.dtype, device: str,
                path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Two runs on fresh clones; digests of run 1's output and of the args right after each run."""
    out0: torch.Tensor | None = None
    digests: dict[str, Any] = {"args_after": []}
    started = time.perf_counter()
    for run in (0, 1):
        clones = tuple(a.clone().to(device) if isinstance(a, torch.Tensor) else a for a in args)
        try:
            out = fn(*clones, dtype=dtype)
        except Exception as exc:  # noqa: BLE001 -- a raising candidate is a verdict
            return {"kind": "raised", "error": f"{type(exc).__name__}: {exc}"[:2000],
                    "line": _where(exc, path)["line"]}, {}
        if type(out) is not torch.Tensor:
            return {"kind": "raised", "error": f"returned {type(out).__module__}.{type(out).__qualname__}, "
                                               f"want a plain torch.Tensor"}, {}
        out = out.detach().cpu().clone()
        digests["args_after"].append([digest(a.cpu()) if isinstance(a, torch.Tensor) else None for a in clones])
        if run == 0:
            out0 = out
        else:
            digests["out1"] = digest(out)
    assert out0 is not None
    return ({"kind": "returned", "out": spec(out0), "seconds": time.perf_counter() - started, **digests},
            {"out": raw(out0)})


def _coverage_report(tracer: Any, path: Path) -> dict[str, Any]:
    if tracer is None:
        return {"kind": "coverage", "measured": False}
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "coverage.json"
        tracer.json_report(outfile=str(out), include=[str(path)])
        report = json.loads(out.read_text())
    files = list(report["files"].values())
    if not files:
        return {"kind": "coverage", "measured": True, "executed": False, "missing_lines": [], "missing_branches": []}
    return {"kind": "coverage", "measured": True, "executed": True, "missing_lines": files[0]["missing_lines"],
            "missing_branches": files[0].get("missing_branches", [])}


def _send(fd: int, header: dict[str, Any], blobs: dict[str, bytes]) -> None:
    child_send(fd, header, blobs)


# --------------------------------------------------------------------------------------------------------------------
# the run step (trusted parent)
#
# The run step for chapter 1: expected answers (trusted, cached) and candidate Runs (isolated child, cached).
#
#     execute(ctx, op, candidate, cases)
#       expected(case)       store "expected" <- (fp64 truth on ctx.device, the reference's own error); the truth tensor
#                            itself is a "truth" entry (a model's is dtype-independent: one ~150 MB copy, not one per dtype)
#       run keys             candidate file sha256 + attr + case + env + runner code fp + expected key
#       all in the store?    -> done, no child at all (a warm check never imports the reader's code)
#       else one Child       load -> blocked (import / bind error) | ready
#                            per case: call -> facts (returned? dtype, shape, inputs unchanged, deterministic, err vs
#                            truth, logit reductions) -> store "run"
#                            finish -> coverage of the bound function's lines -> store "run" (case "coverage")
# A died / timed-out call is recorded for grading but not cached (it may be the machine, not the code), and the cases
# after it are reported as not run.
# --------------------------------------------------------------------------------------------------------------------

ASSAY = Path(__file__).resolve().parents[1]  # .../assay (the package)
RUN_CODE = ("core.py", "ch01/ops.py", "ch01/run.py")
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
    warm: Path | None = None  # the warm process's socket: children fork from it instead of spawning

    @property
    def device(self) -> str:
        return self.env["device"]


@dataclass(frozen=True)
class Candidate:
    file: Path
    attr: str
    adapter: str  # ADAPTERS: "plain" | "forward" | "block" | "generate"

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
    """The references, inputs, prompts and numerics all live in ops.py: any edit there recomputes expected answers."""
    return files_fp([ASSAY / "ch01/ops.py"], ASSAY)


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
            f"({ctx.iso.mode}, {'forked' if ctx.warm else 'spawned'})")
    with Child("assay.ch01.run", cwd=cand.file.parent, iso=ctx.iso, pythonpath=ASSAY.parent,
               extra_env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}, warm=ctx.warm) as child:
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
            line = reply.get("line") if isinstance(reply.get("line"), int) else None
            return {**base, "status": "raised", "notes": f"raised: {reply.get('error')}", "line": line}, {}
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
