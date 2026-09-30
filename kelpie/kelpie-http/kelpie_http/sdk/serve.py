"""Rungs 3 and 4: `serve` (HTTP over a running engine) and `main` (argparse over `serve`).

Rung 4 is the ONLY place model names, device names and kernel choices exist as strings. Below
it everything is a value: a module, a kernel function, a `torch.dtype`.
"""

from __future__ import annotations

import argparse
import functools
import logging
import signal
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

import trio
from hypercorn.config import Config
from hypercorn.trio import serve as hypercorn_serve
from hypercorn.typing import ASGIFramework
from kelpie_models.kernels import ops
from kelpie_models.kernels.op import REGISTRY
from kelpie_models.sdk.run import build, run
from kelpie_models.sdk.tiers import Buckets, Capacity

from kelpie_http.chat import ChatCodec
from kelpie_http.sdk.app import create_app

# TODO(2026-09-10): hand list, and it lies (two tiny names -> one module); --model should take
# an import path, the list is models/torch/*.py, hf-models.txt derives from CHECKPOINT
# (handoff debt 3)
MODELS = {
    "gpt2": "kelpie_models.models.torch.gpt2",
    "qwen3": "kelpie_models.models.torch.qwen3",
    "gpt_oss": "kelpie_models.models.torch.gpt_oss",
    "smolvlm": "kelpie_models.models.torch.smolvlm",
    "kimi_linear": "kelpie_models.models.torch.kimi_linear",
    "deepseek_v4_flash": "kelpie_models.models.torch.deepseek_v4_flash",
    "deepseek_v4_tiny": "kelpie_models.models.torch.tiny",
    "kimi_linear_tiny": "kelpie_models.models.torch.tiny",
    "echo": "kelpie_models.sdk.echo",
}


def serve(
    model: ModuleType,
    *,
    port: int = 8000,
    tokenizer: str | None = None,
    chat: object | None = None,
    # Any: forwarded verbatim to `run`, whose signature is the one writer of these names.
    **engine: Any,
) -> None:
    """Load the model, start the Zig loop, and serve OpenAI HTTP over it until interrupted.

    The engine's lifetime is the `with` block; the server's is the nursery inside it. Ctrl-C
    cancels the nursery, hypercorn stops, the block exits and `eng.close()` drains the loop."""
    with run(model, **engine) as eng:
        app = create_app(eng, tokenizer or model.CHECKPOINT, chat)
        trio.run(_serve_until_interrupted, app, port)


async def _serve_until_interrupted(app: ASGIFramework, port: int) -> None:
    """Lifecycle verb: hypercorn under trio until Ctrl-C.

    The nursery holds exactly one child, the server; `nursery.cancel_scope` is its lifetime.
    `open_signal_receiver` makes SIGINT an ordinary value to await rather than an exception
    raised at whatever line happened to be running, so shutdown has one visible path: the
    signal arrives, the scope is cancelled, the child unwinds, `serve` returns to `run`'s
    `finally` and the engine closes."""
    config = Config()
    config.bind = [f"127.0.0.1:{port}"]
    async with trio.open_nursery() as nursery:
        nursery.start_soon(
            functools.partial(hypercorn_serve, app, config, shutdown_trigger=trio.sleep_forever)
        )
        with trio.open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
            await signals.__anext__()
        nursery.cancel_scope.cancel()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kelpie serve", description="serve a model over the kelpie core"
    )
    p.add_argument("--config", type=Path, default=None, help="kelpie.toml deployment spec")
    p.add_argument("--model", default=None, help=f"a name ({', '.join(MODELS)}) or a module path")
    p.add_argument("--device", default=None)
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--tokenizer", default=None, help="HF id; default is the model's CHECKPOINT")
    p.add_argument(
        "--chat-format",
        default=None,
        help="chat template family for /v1/chat/completions; default is the model's CHAT_FAMILY",
    )
    _tier_groups(p)
    p.add_argument("--cache", type=Path, default=None, help="a directory kelpie build wrote")
    return p


def _tier_groups(p: argparse.ArgumentParser) -> None:
    """The flags, grouped by what changing one costs (`kelpie_models.sdk.tiers`). The grouping
    is the documentation: a reader sees at a glance which flags are free to retune and which
    mean rebuilding the program."""
    program = p.add_argument_group("program tier", "changing one rebuilds the program")
    program.add_argument(
        "--kernel",
        action="append",
        default=[],
        metavar="OP=module.attr|impl",
        help="override one kernel: --kernel rms_norm=fla or --kernel layer_norm=my_ln.layer_norm",
    )
    program.add_argument("--capture", action=argparse.BooleanOptionalAction, default=None)
    program.add_argument("--compile", action="store_true", help="wrap the forward in torch.compile")

    realloc = p.add_argument_group("realloc tier", "changing one drains and re-allocates the arena")
    realloc.add_argument("--max-requests", type=int, default=Capacity().max_requests)
    realloc.add_argument("--num-slabs", type=int, default=Capacity().num_slabs)

    recapture = p.add_argument_group("recapture tier", "changing one recompiles the bucket ladder")
    recapture.add_argument("--bucket-tokens", type=int, nargs="*", default=[])
    recapture.add_argument("--bucket-requests", type=int, nargs="*", default=[])


def model_module(name: str) -> ModuleType:
    """A short name is sugar over the module path, never the only door."""
    return import_module(MODELS.get(name, name))


def kernel_overrides(specs: list[str]) -> dict[Any, Any]:
    """`OP=module.attr` or `OP=impl` -> `{op object: value}`. Rung 4 is the only place an op or
    a kernel is named by a STRING; below it `kernels=` is keyed by the op object itself.

    A dotted right-hand side is an import path (`my_ln.layer_norm`); a bare word is an impl
    name registered on that op (`fla`), which `Op.resolve` checks."""
    out: dict[Any, Any] = {}
    for spec in specs:
        name, sep, path = spec.partition("=")
        assert sep, f"--kernel wants OP=module.attr or OP=impl, got {spec!r}"
        assert name in REGISTRY, f"--kernel {spec}: no op {name!r}; ops: {sorted(REGISTRY)}"
        out[REGISTRY[name]] = _kernel_value(spec, path)
    return out


def _kernel_value(spec: str, path: str) -> Any:
    """A dotted path is imported to a value; a bare word stays a string for `Op.resolve`."""
    if "." not in path:
        return path
    module_name, _, attr = path.rpartition(".")
    module = import_module(module_name)
    assert hasattr(module, attr), f"--kernel {spec}: {module_name} has no {attr}"
    return getattr(module, attr)


def chat_codec(
    model: ModuleType, tokenizer: str | None, chat_format: str | None
) -> ChatCodec | None:
    """The chat template + tool-parser family for this model. None when the model declares none
    and none was asked for: /v1/chat/completions is then simply absent."""
    from kelpie_http.chat import resolve

    family = chat_format or getattr(model, "CHAT_FAMILY", None)
    if family is None:
        return None
    return resolve(tokenizer or model.CHECKPOINT, chat_format=family)


def build_parser() -> argparse.ArgumentParser:
    """`kelpie build`: the one writer of `cache/manifest.json`. Takes serve's own program- and
    recapture-tier flags, because those are exactly what a build is keyed on, plus the two
    grading bools."""
    p = argparse.ArgumentParser(prog="kelpie build", description="write the program cache")
    p.add_argument("--model", required=True, help=f"a name ({', '.join(MODELS)}) or a module path")
    p.add_argument("--device", default="cpu")
    p.add_argument("--cache", type=Path, required=True, help="cache directory to write into")
    p.add_argument("--check", action="store_true", help="grade each kernel against the reference")
    p.add_argument("--bench", action="store_true", help="time each kernel; warn on a regression")
    _tier_groups(p)
    return p


def build_main(argv: list[str] | None = None) -> None:
    """`kelpie build --model gpt2 --device cpu --cache /tmp/k`. Builds every op the model calls
    over every step shape (`sdk/shapes.py`), grades and times them if asked, and writes the manifest. The ONLY writer of
    that cache: `serve --cache` opens it read-only."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    built = build(
        model_module(args.model),
        device=args.device,
        cache=args.cache,
        allow_build=True,
        check=args.check,
        bench=args.bench,
        kernels=kernel_overrides(args.kernel),
        capture=args.capture,
        compile=args.compile,
        capacity=Capacity(max_requests=args.max_requests, num_slabs=args.num_slabs),
        buckets=Buckets(tuple(args.bucket_tokens), tuple(args.bucket_requests)),
    )
    built.engine.close()
    logging.getLogger("kernels").info("built %s -> %s", args.model, args.cache / "manifest.json")


def cache_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kelpie cache", description="print a cache's manifest")
    p.add_argument("cache", type=Path)
    return p


def cache_main(argv: list[str] | None = None) -> None:
    """`kelpie cache <dir>`: the manifest as a table. What is in this cache, which kernel it
    came from, whether anything graded it, and how long it took."""
    from kelpie_models.sdk.manifest import read

    found = read(cache_parser().parse_args(argv).cache)
    header = ("op", "impl", "step", "verdict", "time_us", "built_at")
    rows = [
        (
            e.op,
            e.impl,
            e.step,
            e.verdict or "-",
            f"{e.time_us:.1f}" if e.time_us is not None else "-",
            found.built_at,
        )
        for e in found.entries
    ]
    widths = [max(len(r[i]) for r in (header, *rows)) for i in range(len(header))]
    for row in (header, *rows):
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths, strict=True)))


def check_main(argv: list[str]) -> None:
    """kelpie check --config kelpie.toml — validate environment against the deployment spec."""
    import argparse

    p = argparse.ArgumentParser(prog="kelpie check", description="validate environment against kelpie.toml")
    p.add_argument("--config", type=Path, required=True, help="kelpie.toml deployment spec")
    args = p.parse_args(argv)

    from kelpie_engine.config import check, check_print, load

    cfg = load(args.config)
    results = check(cfg)
    all_ok = check_print(results)
    sys.exit(0 if all_ok else 1)


def main(argv: list[str] | None = None) -> None:
    """Lifecycle verb: `kelpie serve`, runs until interrupted. Subcommands are dispatched by
    `kelpie_http.cli`; this is serve's flags only."""
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    # Load toml if provided — CLI args override toml values.
    cfg = None
    if args.config is not None:
        from kelpie_engine.config import load, resolve_kernels

        cfg = load(args.config)
        logging.getLogger("config").info("loaded %s", args.config)

    # Resolve each value: CLI wins, then toml, then default.
    model_name = args.model or (cfg.model_module if cfg else None)
    assert model_name, "--model is required (or set [model].module in kelpie.toml)"
    device = args.device or (cfg.device if cfg else "cpu")
    capture = args.capture if args.capture is not None else (cfg.capture if cfg else None)
    compile_ = args.compile or (cfg.compile if cfg else False)

    # Kernels: CLI --kernel overrides win over toml [kernels].
    kernels: dict[Any, Any] = {}
    if cfg and cfg.kernels:
        kernels = resolve_kernels(cfg)
    cli_kernels = kernel_overrides(args.kernel)
    kernels.update(cli_kernels)

    # Capacity: CLI wins over toml.
    max_requests = args.max_requests
    num_slabs = args.num_slabs
    if cfg:
        if max_requests == Capacity().max_requests and cfg.max_requests is not None:
            max_requests = cfg.max_requests
        if num_slabs == Capacity().num_slabs and cfg.num_slabs is not None:
            num_slabs = cfg.num_slabs

    # Buckets: CLI wins over toml.
    bucket_tokens = tuple(args.bucket_tokens) if args.bucket_tokens else (
        tuple(cfg.bucket_tokens) if cfg and cfg.bucket_tokens else ()
    )
    bucket_requests = tuple(args.bucket_requests) if args.bucket_requests else (
        tuple(cfg.bucket_requests) if cfg and cfg.bucket_requests else ()
    )

    model = model_module(model_name)
    serve(
        model,
        port=args.port,
        tokenizer=args.tokenizer,
        chat=chat_codec(model, args.tokenizer, args.chat_format),
        device=device,
        cache=args.cache,
        kernels=kernels or None,
        capture=capture,
        compile=compile_,
        capacity=Capacity(max_requests=max_requests, num_slabs=num_slabs),
        buckets=Buckets(bucket_tokens, bucket_requests),
    )


if __name__ == "__main__":
    main()
