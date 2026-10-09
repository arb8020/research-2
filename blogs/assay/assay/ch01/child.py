"""The untrusted side: runs in the isolated child (sandbox.Child), imports the reader's file, calls one function.

    parent                                         child
                                                   import torch, coverage          -> boot
    load {file, attr, adapter, device, coverage}   coverage.start(); import file    -> ready | import_error {file, line}
                                                                                       | bind_error
    call {args, dtype} + arg blobs                 out0 = fn(clones); out1 = fn(clones)
                                                   -> returned {out spec, sha256 of out1 and of every arg after each
                                                      run} + out0's bytes | raised {error}
    finish                                         coverage.stop()                  -> coverage {missing lines/branches}

Only run 0's output crosses the pipe in full; run 1 and the inputs-after come back as digests, which the parent
compares against the bytes it has (a gpt2 output is ~77 MB at 384 tokens; two of them per call would be waste).
Everything here is as honest as the candidate lets it be: it can patch this module (forges_reply does), but the parent
only ever parses JSON + raw bytes from it.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import torch

from assay.ch01.tensors import NAMES, digest, raw, spec, unpack_args
from assay.sandbox import child_recv, child_send


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
            _send(out_fd, _coverage(tracer, path), {})
            return
        assert header["kind"] == "call", header
        args = unpack_args(header["args"], blobs)
        reply, out = _call_twice(fn, args, NAMES[header["dtype"]], device)
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


def _forward(module: Any, attr: str, device: str) -> Callable[..., Any]:
    """gpt2.py's model contract: `load(dtype) -> (weights, config)`, `forward(weights, config, tokens) -> logits`.
    Weights load once per dtype (inside the first call, under its timeout)."""
    for name in ("load", attr):
        if not hasattr(module, name):
            raise AttributeError(f"{Path(module.__file__).name} defines no `{name}`")
    loaded: dict[torch.dtype, Any] = {}

    def call(tokens: torch.Tensor, *, dtype: torch.dtype) -> Any:
        if dtype not in loaded:
            weights, config = module.load(dtype)
            loaded[dtype] = ({k: v.to(device) for k, v in weights.items()}, config)
        weights, config = loaded[dtype]
        with torch.no_grad():
            return getattr(module, attr)(weights, config, tokens)

    return call


ADAPTERS = {"plain": _plain, "forward": _forward}


def _call_twice(fn: Callable[..., Any], args: tuple, dtype: torch.dtype,
                device: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Two runs on fresh clones; digests of run 1's output and of the args right after each run."""
    out0: torch.Tensor | None = None
    digests: dict[str, Any] = {"args_after": []}
    started = time.perf_counter()
    for run in (0, 1):
        clones = tuple(a.clone().to(device) if isinstance(a, torch.Tensor) else a for a in args)
        try:
            out = fn(*clones, dtype=dtype)
        except Exception as exc:  # noqa: BLE001 -- a raising candidate is a verdict
            return {"kind": "raised", "error": f"{type(exc).__name__}: {exc}"[:2000]}, {}
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


def _coverage(tracer: Any, path: Path) -> dict[str, Any]:
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
