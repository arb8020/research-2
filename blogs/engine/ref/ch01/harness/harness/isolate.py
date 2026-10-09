"""Run an untrusted candidate in a spawned child process (pygpubench's shape, CPU only).

    parent (trusted)                              child (untrusted once the candidate imports)
    inputs, fp64 truth, budgets: computed         coverage.start(); import "module:fn"
    BEFORE the child exists                       -> READY
    Child.call(args) --pickle--> ............... clone args; out0 = fn(*clones0)
                                                  clone args; out1 = fn(*clones1)
    parse_frame(json header, raw bytes) <------- out0, out1, args after each run, as raw bytes
    Child.finish() -----------------------------> coverage.stop() -> missing lines/branches

Trust runs one way. Parent -> child is pickle (the child trusts the parent). Child -> parent is
NEVER pickle -- unpickling runs code -- but a JSON header (dtype, shape, byte count per tensor)
plus one raw byte blob, parsed strictly (`parse_frame`). The truth never enters the child, so
no gc scan or stack walk there can find it. Everything the child reports about itself (the two
runs, the inputs after the call, coverage) is only as honest as the candidate lets it be: these
catch honest bugs (an in-place op, a racy kernel, an untested branch), not a candidate that
rewrites the child's reporting code -- which can still only hand the parent tensors to grade.
"""

from __future__ import annotations

import importlib
import json
import math
import multiprocessing
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import torch

MAX_FRAME_BYTES = 512 * 1024 * 1024  # gpt2 logits [2, 64, 50257] fp32 x 2 runs is ~52 MB
MAX_HEADER_BYTES = 1024 * 1024
EXIT_GRACE_S = 10.0  # a finished child gets this long to exit cleanly before it is killed
WIRE_DTYPES = {"float64": torch.float64, "float32": torch.float32, "float16": torch.float16,
               "bfloat16": torch.bfloat16, "int64": torch.int64, "int32": torch.int32,
               "bool": torch.bool}


# ---- results the parent sees -----------------------------------------------------------------


@dataclass(frozen=True)
class Returned:
    """Both runs returned a plain tensor. `args_after[run][i]` is tensor arg i after run `run`
    (None for non-tensor args)."""

    outputs: tuple[torch.Tensor, torch.Tensor]
    args_after: tuple[tuple[torch.Tensor | None, ...], tuple[torch.Tensor | None, ...]]
    seconds: float


@dataclass(frozen=True)
class Raised:
    """The candidate raised, or returned something that is not a plain `torch.Tensor`."""

    error: str


@dataclass(frozen=True)
class TimedOut:
    seconds: float


@dataclass(frozen=True)
class Died:
    """The child exited, or sent a frame that does not parse."""

    why: str


CallResult = Returned | Raised | TimedOut | Died


@dataclass(frozen=True)
class Coverage:
    """Lines and branches of the candidate file the whole sweep never executed."""

    file: str
    missing_lines: tuple[int, ...]
    missing_branches: tuple[tuple[int, int], ...]


class ProtocolError(Exception):
    """A frame from the child that does not parse: the child is broken or lying."""


# ---- parent side ------------------------------------------------------------------------------


class Child:
    """One spawned process running one candidate. Owns the process and the pipe; the context
    manager kills the process on any exit, so a hung candidate never outlives the check."""

    def __init__(self, qualname: str, coverage_file: Path, extra_path: tuple[str, ...],
                 startup_timeout: float, call_timeout: float) -> None:
        context = multiprocessing.get_context("spawn")
        self.conn, child_conn = context.Pipe(duplex=True)
        self.call_timeout = call_timeout
        self.process = context.Process(
            target=child_main, args=(child_conn, qualname, str(coverage_file), extra_path),
            daemon=True, name=f"candidate:{qualname}")
        self.process.start()
        child_conn.close()
        self.startup_error = self._await_ready(startup_timeout)

    def __enter__(self) -> Child:
        return self

    def __exit__(self, *exc: object) -> None:
        self.conn.close()  # a child blocked in recv() sees EOF and exits
        self.process.join(EXIT_GRACE_S)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()

    def _await_ready(self, timeout: float) -> str | None:
        """None once the child imported the candidate, else why it could not."""
        if not self.conn.poll(timeout):
            return f"candidate did not import within {timeout:g}s"
        header, _ = self._receive()
        if header["kind"] == "import_error":
            return f"candidate failed to import:\n{header['error']}"
        if header["kind"] != "ready":
            return f"expected READY, got {header['kind']!r}"
        return None

    def call(self, args: tuple) -> CallResult:
        assert self.startup_error is None, "call on a child that never became ready"
        if not self.process.is_alive():
            return Died(f"child exited (code {self.process.exitcode})")
        started = time.perf_counter()
        try:
            self.conn.send(("call", args))
        except (BrokenPipeError, ConnectionResetError) as exc:
            return Died(f"child closed the pipe: {exc}")
        if not self.conn.poll(self.call_timeout):
            self.process.kill()
            return TimedOut(self.call_timeout)
        try:
            header, tensors = self._receive()
        except EOFError:
            self.process.join(EXIT_GRACE_S)
            return Died(f"child exited mid-call (exit code {self.process.exitcode})")
        except ProtocolError as exc:
            return Died(f"bad reply: {exc}")
        seconds = time.perf_counter() - started
        if header["kind"] == "raised":
            return Raised(str(header["error"]))
        if header["kind"] != "returned":
            return Died(f"unexpected reply kind {header['kind']!r}")
        return _unpack_returned(tensors, len(args), seconds)

    def finish(self) -> Coverage | Died:
        """Stop coverage in the child and collect what the sweep never executed."""
        if not self.process.is_alive():
            return Died(f"child exited (code {self.process.exitcode}) before coverage")
        self.conn.send(("finish", ()))
        if not self.conn.poll(self.call_timeout):
            return Died("no coverage report")
        try:
            header, _ = self._receive()
        except (EOFError, ProtocolError) as exc:
            return Died(f"bad coverage reply: {exc}")
        if header["kind"] != "coverage":
            return Died(f"expected coverage, got {header['kind']!r}")
        return _parse_coverage(header)

    def _receive(self) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
        try:
            header_bytes = self.conn.recv_bytes(MAX_HEADER_BYTES)
            blob = self.conn.recv_bytes(MAX_FRAME_BYTES)
        except OSError as exc:  # oversized frame: multiprocessing raises OSError
            raise ProtocolError(f"frame too large or broken: {exc}") from exc
        return parse_frame(header_bytes, blob)


def parse_frame(header_bytes: bytes, blob: bytes) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
    """The boundary: bytes from the child -> a header dict and named tensors, or ProtocolError.
    Every size is checked against every other before a byte is interpreted."""
    try:
        header = json.loads(header_bytes)
    except ValueError as exc:
        raise ProtocolError(f"header is not JSON: {exc}") from exc
    if not isinstance(header, dict) or not isinstance(header.get("kind"), str):
        raise ProtocolError("header is not an object with a string 'kind'")
    specs = header.get("tensors", [])
    if not isinstance(specs, list):
        raise ProtocolError("'tensors' is not a list")
    tensors: dict[str, torch.Tensor] = {}
    offset = 0
    for spec in specs:
        name, dtype, shape, nbytes = _parse_tensor_spec(spec)
        if name in tensors:
            raise ProtocolError(f"tensor {name!r} sent twice")
        if offset + nbytes > len(blob):
            raise ProtocolError(f"tensor {name!r} runs past the blob ({len(blob)} bytes)")
        chunk = blob[offset:offset + nbytes]
        offset += nbytes
        tensors[name] = (torch.empty(shape, dtype=dtype) if nbytes == 0 else
                         torch.frombuffer(bytearray(chunk), dtype=torch.uint8)
                         .view(dtype).reshape(shape))
    if offset != len(blob):
        raise ProtocolError(f"{len(blob) - offset} trailing bytes after the last tensor")
    return header, tensors


def _parse_tensor_spec(spec: Any) -> tuple[str, torch.dtype, tuple[int, ...], int]:
    if not isinstance(spec, dict):
        raise ProtocolError("tensor spec is not an object")
    name, dtype_name, shape, nbytes = (spec.get(k) for k in ("name", "dtype", "shape", "nbytes"))
    if not isinstance(name, str):
        raise ProtocolError("tensor name is not a string")
    if dtype_name not in WIRE_DTYPES:
        raise ProtocolError(f"tensor {name!r}: dtype {dtype_name!r} not allowed")
    if not isinstance(shape, list) or not all(isinstance(d, int) and d >= 0 for d in shape):
        raise ProtocolError(f"tensor {name!r}: shape {shape!r} is not a list of sizes")
    dtype = WIRE_DTYPES[dtype_name]
    itemsize = torch.empty((), dtype=dtype).element_size()
    if nbytes != math.prod(shape) * itemsize:
        raise ProtocolError(f"tensor {name!r}: {nbytes} bytes for shape {shape} {dtype_name}")
    return name, dtype, tuple(shape), nbytes


def _unpack_returned(tensors: dict[str, torch.Tensor], arg_count: int,
                     seconds: float) -> Returned | Died:
    for run in (0, 1):
        if f"run{run}.out" not in tensors:
            return Died(f"reply has no run{run}.out")
    after = tuple(tuple(tensors.get(f"run{run}.arg{i}") for i in range(arg_count))
                  for run in (0, 1))
    return Returned((tensors["run0.out"], tensors["run1.out"]), (after[0], after[1]), seconds)


def _parse_coverage(header: dict[str, Any]) -> Coverage | Died:
    lines = header.get("missing_lines")
    branches = header.get("missing_branches")
    if not isinstance(lines, list) or not all(isinstance(n, int) for n in lines):
        return Died("coverage: missing_lines is not a list of ints")
    if not isinstance(branches, list) or not all(
            isinstance(b, list) and len(b) == 2 and all(isinstance(n, int) for n in b)
            for b in branches):
        return Died("coverage: missing_branches is not a list of [from, to] pairs")
    return Coverage(str(header.get("file")), tuple(lines), tuple((a, b) for a, b in branches))


# ---- child side (runs in the spawned process) -------------------------------------------------


def child_main(conn: Connection, qualname: str, coverage_file: str,
               extra_path: tuple[str, ...]) -> None:
    import coverage

    sys.path[:0] = list(extra_path)
    tracer = coverage.Coverage(branch=True, include=[coverage_file], data_file=None,
                               config_file=False)
    tracer.clear_exclude()  # a `# pragma: no cover` must not hide an untested line
    tracer.start()
    try:
        module_name, _, fn_name = qualname.partition(":")
        fn = getattr(importlib.import_module(module_name), fn_name)
    except BaseException:  # noqa: BLE001 -- any import failure is reported, then we exit
        _send(conn, {"kind": "import_error", "error": traceback.format_exc()}, {})
        return
    _send(conn, {"kind": "ready"}, {})
    while True:
        try:
            verb, args = conn.recv()
        except EOFError:  # the parent is done with us
            return
        if verb == "finish":
            tracer.stop()
            _send(conn, _coverage_report(tracer, coverage_file), {})
            return
        assert verb == "call", f"unknown verb {verb!r}"
        header, tensors = _call_twice(fn, args)
        _send(conn, header, tensors)


def _call_twice(fn: Any, args: tuple) -> tuple[dict[str, Any], dict[str, torch.Tensor]]:
    """Run the candidate twice on fresh clones; snapshot each output and the args right after
    its own run (so a later call cannot change what we report)."""
    tensors: dict[str, torch.Tensor] = {}
    for run in (0, 1):
        clones = tuple(a.clone() if isinstance(a, torch.Tensor) else a for a in args)
        try:
            out = fn(*clones)
        except Exception as exc:  # noqa: BLE001 -- a raising candidate is a verdict
            return {"kind": "raised", "error": f"{type(exc).__name__}: {exc}"}, {}
        if type(out) is not torch.Tensor:
            return {"kind": "raised",
                    "error": f"returned {type(out).__module__}.{type(out).__qualname__}, "
                             f"want a plain torch.Tensor"}, {}
        tensors[f"run{run}.out"] = out.detach().clone()
        for i, arg in enumerate(clones):
            if isinstance(arg, torch.Tensor):
                tensors[f"run{run}.arg{i}"] = arg.detach().clone()
    return {"kind": "returned"}, tensors


def _coverage_report(tracer: Any, coverage_file: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as scratch:
        out = Path(scratch) / "coverage.json"
        tracer.json_report(outfile=str(out), include=[coverage_file])
        report = json.loads(out.read_text())
    files = list(report["files"].values())
    assert len(files) <= 1, f"coverage measured more than the candidate file: {list(report['files'])}"
    if not files:  # the file was never executed at all
        return {"kind": "coverage", "file": coverage_file, "missing_lines": [-1],
                "missing_branches": []}
    return {"kind": "coverage", "file": coverage_file,
            "missing_lines": files[0]["missing_lines"],
            "missing_branches": files[0].get("missing_branches", [])}


def _send(conn: Connection, header: dict[str, Any], tensors: dict[str, torch.Tensor]) -> None:
    specs = []
    chunks = []
    for name, tensor in tensors.items():
        flat = tensor.contiguous().reshape(-1)
        raw = flat.view(torch.uint8).numpy().tobytes() if flat.numel() else b""
        dtype_name = str(tensor.dtype).removeprefix("torch.")
        assert dtype_name in WIRE_DTYPES, f"cannot send {name} of dtype {tensor.dtype}"
        specs.append({"name": name, "dtype": dtype_name, "shape": list(tensor.shape),
                      "nbytes": len(raw)})
        chunks.append(raw)
    conn.send_bytes(json.dumps({**header, "tensors": specs}).encode())
    conn.send_bytes(b"".join(chunks))
