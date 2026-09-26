#!/usr/bin/env python3
"""The endpoint check: does `serve` still answer the way it did? One line per row.

    python scripts/check_serve.py            # every row
    python scripts/check_serve.py gpt2 echo  # only rows whose name matches

A ROW is data: a model, a device, a list of requests, and what the answers must be. The runner
below is the only code, and it is the same for every row -- adding a model or a case means
adding a row, never a function.

    Row(name, model, device, requests, expected, engine)

`requests` are `Ask`s (prompt + max_tokens, `response_format` when structured output lands).
`expected` is either a tuple of literal completion strings, one per request, or `SOLO`: run
each request ALONE and require the batched answers to equal the solo ones. `SOLO` is the check
that matters for batching -- it needs no golden text and it fails exactly when a request's
answer depends on who it was batched with (a bad plan, a leaked KV row, a wrong `n_reqs`).

HOW IT RUNS: through the ASGI app, over a real engine, one SUBPROCESS per engine.
`kelpie_models.sdk.run.run` builds the model and starts the Zig loop,
`kelpie_http.sdk.app.create_app` puts the OpenAI surface on it, and `httpx.ASGITransport`
speaks to that app with no socket. That is `serve()` minus `trio.run(hypercorn)` -- the same
engine, the same app, the same handlers, so a row exercises everything a curl would except the
TCP. One process per engine keeps each engine's memory and kernel binding (registered on the
torch ops process-wide) from leaking into the next row. A `SOLO` row therefore costs one
process for the batch plus one per request.

WHAT IS NOT A ROW YET: the SmolVLM image row. `kelpie_http.sdk.chat.prepare` rejects images
and `response_format` with a 400 ("structured output and images are follow-up rungs"), so an
image cannot reach the model through the endpoint at all. Until it can, the SmolVLM row here
is a STEP-level row: same engine, same forward, but the payload is attached to the `Step`
directly rather than parsed out of an HTTP body. It is marked as such in its output line.

This file is the first check function, and it stays.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

# The parent process only builds Row values; the worker is what imports torch. `Capacity` is a
# plain frozen dataclass with no torch in its import chain, so a row can name it here.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "kelpie-models"))
from kelpie_models.sdk.tiers import Capacity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

HTTP_OK = 200
SOLO = "== solo"  # expected: each request must answer the same alone as it does batched


@dataclass(frozen=True)
class Ask:
    """One request as the endpoint takes it."""

    prompt: str
    max_tokens: int
    response_format: dict[str, Any] | None = None


@dataclass(frozen=True)
class Row:
    """One check: this model, on this device, answering these requests with these answers."""

    name: str
    model: str  # dotted module path, or "roll:<module>" for a rolled random-weight tiny config
    device: str
    requests: tuple[Ask, ...]
    expected: tuple[str, ...] | str
    # The two config tiers a row may set, each spelled where that tier lives
    # (kelpie_models.sdk.tiers): `engine` is realloc, a build() argument; `live` is a knob.
    engine: Capacity = Capacity()
    live: dict[str, Any] = dataclass_field(default_factory=dict)
    step_level: str = ""  # non-empty: run below HTTP, and say why in the output line


ROWS: tuple[Row, ...] = (
    Row(
        name="gpt2",
        model="kelpie_models.models.torch.gpt2",
        device="cpu",
        requests=(Ask("The capital of France is", 6),),
        # HF GPT2LMHeadModel's own greedy continuation, verified against transformers. The
        # brief asked for " its capital city, Burgundy": that string predates the kv[member]
        # fix in 8b18da7, when every layer read layer 0's cache and the stack diverged from HF
        # after the first token (BREADCRUMBS 23:07 / 23:17). This is the corrected answer.
        expected=(" the capital of the French Republic",),
        engine=Capacity(num_slabs=64),
    ),
    Row(
        name="echo",
        model="kelpie_models.sdk.echo",
        device="cpu",
        # The echo model emits the prompt's tokens back in reverse order. Its whole point is
        # that a wrong plan shows up as wrong TEXT, not as silence. The text is the DETOKENIZED
        # reversal, so gpt2's leading-space tokens land where the reversal puts them:
        # " alpha"/" beta"/" gamma" -> " gamma"+" beta"+"alpha".
        requests=(Ask("alpha beta gamma", 3),),
        expected=(" gamma betaalpha",),
        engine=Capacity(num_slabs=16),
    ),
    Row(
        name="gpt_oss_tiny",
        model="roll:kelpie_models.models.torch.gpt_oss",
        device="cpu",
        # Two requests in one batch, on a model with TWO cache groups (sliding + full). If the
        # window group's block table or slot mapping is wrong for either entry, the batched
        # answers stop matching the solo ones.
        requests=(Ask("the quick brown fox jumps over", 4), Ask("a b c d e f g h", 4)),
        expected=SOLO,
        engine=Capacity(num_slabs=128),
        live={"max_batch_tokens": 256},
    ),
    Row(
        name="stale_cancel",
        model="kelpie_models.sdk.echo",
        device="cpu",
        # Design-multigpu section 8 B2 through the HTTP layer's own cancel: request A finishes
        # and is polled (its id released), B is submitted into the same id, then A's handler
        # "sees a disconnect" and cancels with A's generation. B must finish untouched. A
        # plain cancel(id) -- what the app did before -- is shown to kill B as the control.
        requests=(Ask("alpha beta gamma", 3),),
        expected=SOLO,
        engine=Capacity(num_slabs=16, max_requests=1),
        step_level="drives kelpie_http.sdk.app.cancel_on_disconnect on a reused id",
    ),
    Row(
        name="smolvlm_image",
        model="kelpie_models.models.torch.smolvlm",
        device="cpu",
        requests=(Ask("What color?", 8),),
        expected=SOLO,  # compared against HF transformers instead; see run_smolvlm
        engine=Capacity(num_slabs=256),
        live={"max_batch_tokens": 2048},
        step_level="images are a 400 on /v1/chat/completions (kelpie_http.sdk.chat.NOT_YET)",
    ),
)


# ---- the runner ------------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--worker":
        name, mode, which = argv[2], argv[3], argv[4]
        return worker(name, mode, tuple(int(i) for i in which.split(",") if i != ""))
    wanted = set(argv[1:])
    rows = [r for r in ROWS if not wanted or r.name in wanted]
    if wanted and not rows:
        print(f"no row named {sorted(wanted)}; rows: {[r.name for r in ROWS]}")
        return 2
    worst = 0
    for row in rows:
        started = time.monotonic()
        try:
            ok, detail = check(row)
        except SkipRow as e:
            print(f"SKIP {row.name:16s} {e}")
            continue
        except Exception:  # noqa: BLE001 -- a crashed row is a FAILED row, with its traceback
            traceback.print_exc()
            ok, detail = False, "raised"
        took = time.monotonic() - started
        print(f"{'OK  ' if ok else 'FAIL'} {row.name:16s} {took:5.1f}s  {detail}")
        worst = worst or (0 if ok else 1)
    return worst


class SkipRow(Exception):
    """This row cannot run here (a checkpoint is not cached), with the reason."""


def check(row: Row) -> tuple[bool, str]:
    if row.step_level:
        return in_worker(row, "step", tuple(range(len(row.requests))))
    got = serve(row, tuple(range(len(row.requests))))
    if row.expected is SOLO:
        want = tuple(serve(row, (i,))[0] for i in range(len(row.requests)))
        label = "== solo"
    else:
        assert isinstance(row.expected, tuple), row.expected
        assert len(row.expected) == len(row.requests), (row.expected, row.requests)
        want, label = row.expected, "== expected"
    if got == want:
        return True, f"{len(got)} request(s) {label}: {shorten(got)}"
    diff = [
        f"[{i}] got {g!r} want {w!r}"
        for i, (g, w) in enumerate(zip(got, want, strict=True))
        if g != w
    ]
    return False, "; ".join(diff)


def serve(row: Row, which: tuple[int, ...]) -> tuple[str, ...]:
    """The row's requests at indices `which`, answered by one server in one subprocess."""
    ok, payload = in_worker(row, "serve", which)
    assert ok, payload
    return tuple(json.loads(payload))


def in_worker(row: Row, mode: str, which: tuple[int, ...]) -> tuple[bool, str]:
    """Run one engine in a fresh process. `ops.bind` may run only once per process, so every
    engine needs its own; the worker prints one JSON line and nothing else is parsed."""
    argv = [
        sys.executable if os.environ.get("CHECK_SERVE_CHILD") else "uv",
        *([] if os.environ.get("CHECK_SERVE_CHILD") else ["run", "--project", "kelpie-http"]),
        *([] if os.environ.get("CHECK_SERVE_CHILD") else ["python"]),
        os.path.abspath(__file__),
        "--worker",
        row.name,
        mode,
        ",".join(str(i) for i in which),
    ]
    result = subprocess.run(  # noqa: S603 -- argv is this file plus row names from ROWS
        argv,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,  # a crashed worker is a FAILED row, reported, not an exception here
        env={**os.environ, "CHECK_SERVE_CHILD": "1"},
    )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith(WORKER_OK):
            return True, line.removeprefix(WORKER_OK)
        if line.startswith(WORKER_SKIP):
            raise SkipRow(line.removeprefix(WORKER_SKIP))
        if line.startswith(WORKER_FAIL):
            return False, line.removeprefix(WORKER_FAIL)
    tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
    return False, f"worker produced no verdict (rc={result.returncode}): {' / '.join(tail)}"


WORKER_OK = "CHECK_SERVE_OK "
WORKER_FAIL = "CHECK_SERVE_FAIL "
WORKER_SKIP = "CHECK_SERVE_SKIP "


def worker(name: str, mode: str, which: tuple[int, ...]) -> int:
    """The child: build one engine, answer, print one verdict line."""
    row = next(r for r in ROWS if r.name == name)
    try:
        if mode == "step":
            ok, detail = run_stale_cancel(row) if row.name == "stale_cancel" else run_smolvlm(row)
            print((WORKER_OK if ok else WORKER_FAIL) + detail)
            return 0 if ok else 1
        print(WORKER_OK + json.dumps(list(serve_batch(row, tuple(row.requests[i] for i in which)))))
    except SkipRow as e:
        print(WORKER_SKIP + str(e))
    except Exception:  # noqa: BLE001 -- the verdict line must be printed whatever went wrong
        traceback.print_exc()
        print(WORKER_FAIL + "raised; see stderr")
        return 1
    return 0


def serve_batch(row: Row, asks: tuple[Ask, ...]) -> tuple[str, ...]:
    """Run `asks` CONCURRENTLY against one in-process server and return their completions."""
    import httpx
    import trio

    model = load_model(row)
    from kelpie_models.sdk.run import run

    from kelpie_http.sdk.app import create_app

    out: list[str | None] = [None] * len(asks)
    with run(model, device=row.device, capacity=row.engine) as engine:
        # The two tiers a row can set, spelled where each belongs: `capacity` is realloc and is
        # a `build` argument; `live` is a knob and takes effect at a step boundary.
        if row.live:
            engine.set(**row.live)
        app = create_app(engine, model.CHECKPOINT, chat_codec(model))

        async def drive() -> None:
            transport = httpx.ASGITransport(app=app)
            async with (
                httpx.AsyncClient(
                    transport=transport, base_url="http://check", timeout=600.0
                ) as client,
                trio.open_nursery() as nursery,
            ):
                for i, ask in enumerate(asks):
                    nursery.start_soon(one, client, i, ask)

        async def one(client: httpx.AsyncClient, i: int, ask: Ask) -> None:
            body: dict[str, Any] = {
                "model": row.name,
                "prompt": ask.prompt,
                "max_tokens": ask.max_tokens,
                "temperature": 0.0,
            }
            if ask.response_format is not None:
                body["response_format"] = ask.response_format
            r = await client.post("/v1/completions", json=body)
            assert r.status_code == HTTP_OK, f"{r.status_code}: {r.text}"
            out[i] = json.loads(r.text)["choices"][0]["text"]

        trio.run(drive)
    assert all(t is not None for t in out), out
    return tuple(t for t in out if t is not None)


def run_stale_cancel(row: Row) -> tuple[bool, str]:
    """One slot, so B must reuse A's id. -> (A's stale cancel left B alone, and the control
    plain cancel does kill a reused id's occupant)."""
    from kelpie_models.sdk.run import run
    from tokenizers import Tokenizer

    from kelpie_http.sdk.app import cancel_on_disconnect

    model = load_model(row)
    ids = Tokenizer.from_pretrained(model.CHECKPOINT).encode(row.requests[0].prompt).ids
    with run(model, device=row.device, capacity=row.engine) as engine:
        a = engine.submit(ids, 3)
        gen_a = engine.generation(a)
        done_a = engine.wait(a, timeout_s=60)  # finished and polled: a's release is queued
        b = engine.submit(ids, 3)
        assert b == a, (a, b)  # one slot: the id is reused
        queued = cancel_on_disconnect(engine, a, gen_a)  # a's handler, too late
        done_b = engine.wait(b, timeout_s=60)
        c = engine.submit(ids, 3)
        engine.cancel(c)  # control: an ungated cancel of the id kills whoever holds it
        done_c = engine.wait(c, timeout_s=60)
    ok = (not queued and done_b.reason != "cancelled" and done_b.new_tokens == done_a.new_tokens
          and done_c.reason == "cancelled")
    return ok, (f"stale cancel queued={queued}; reused id's request finished {done_b.reason} "
                f"{done_b.new_tokens} (== first: {done_b.new_tokens == done_a.new_tokens}); "
                f"control plain cancel -> {done_c.reason}")


def run_smolvlm(row: Row) -> tuple[bool, str]:
    """SmolVLM with one image, below HTTP (see the module docstring), against HF transformers."""
    import numpy as np
    import torch
    from PIL import Image

    model = load_model(row)
    checkpoint = model.CHECKPOINT
    require_cached(checkpoint)
    from huggingface_hub import hf_hub_download
    from kelpie_models.sdk.multimodal import MultimodalInput
    from kelpie_models.sdk.run import build
    from tokenizers import Tokenizer

    image = Image.new("RGB", (96, 64))
    for x in range(96):
        for y in range(64):
            image.putpixel((x, y), ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256))

    engine, step = build(model, device=row.device, **row.engine)
    config = step.config
    tiles = model.preprocess(image, config)
    text = model.chat_prompt([("user", [tiles, row.requests[0].prompt])], config)
    tokenizer = Tokenizer.from_file(hf_hub_download(checkpoint, "tokenizer.json"))
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    placeholders = np.flatnonzero(np.asarray(ids) == config.image_token).astype(np.int64)

    request_id = engine.submit(ids, row.requests[0].max_tokens)
    step.attach(request_id, MultimodalInput(placeholder_positions=placeholders, data=[tiles]))
    engine.start_loop(step)
    got: list[int] = []
    try:
        while True:
            poll = engine.poll(request_id)
            got += poll.new_tokens
            if poll.finished:
                break
            time.sleep(0.05)
    finally:
        engine.close()

    from transformers import AutoModelForImageTextToText, AutoProcessor

    processor = AutoProcessor.from_pretrained(checkpoint)
    hf = AutoModelForImageTextToText.from_pretrained(checkpoint, dtype=torch.float32).eval()
    raw = f"<|im_start|>User:<image>{row.requests[0].prompt}<end_of_utterance>\nAssistant:"
    inputs = processor(text=raw, images=[image], return_tensors="pt")
    assert inputs["input_ids"][0].tolist() == ids, "our prompt tokens differ from HF's"
    with torch.no_grad():
        generated = hf.generate(
            **inputs, max_new_tokens=row.requests[0].max_tokens, do_sample=False
        )
    want = generated[0, inputs["input_ids"].shape[1] :].tolist()
    encodes = step.encoder.n_encodes
    detail = (
        f"step-level ({row.step_level}); {len(ids)} prompt tokens, "
        f"{placeholders.shape[0]} image rows, {encodes} encode; "
        f"{tokenizer.decode(got)!r} == HF"
    )
    if got != want or encodes != 1:
        return False, f"got {got} ({encodes} encodes) want {want} (1 encode)"
    return True, detail


# ---- loading ----------------------------------------------------------------------------------


def load_model(row: Row) -> ModuleType:
    """The row's model module. `roll:<module>` wraps it in a tiny rolled config with random
    weights, so a 20B checkpoint is never downloaded to run a check."""
    if not row.model.startswith("roll:"):
        module = import_module(row.model)
        if hasattr(module, "CHECKPOINT"):
            require_cached(module.CHECKPOINT)
        return module
    return rolled(import_module(row.model.removeprefix("roll:")))


def require_cached(checkpoint: str) -> None:
    """Skip the row rather than download gigabytes mid-check."""
    from huggingface_hub import try_to_load_from_cache

    if try_to_load_from_cache(checkpoint, "config.json") is None:
        raise SkipRow(f"{checkpoint} is not in the local HF cache")


def rolled(model: ModuleType) -> ModuleType:
    """`model` with `synth.roll.roll()`'s smallest config that keeps every layer kind, and
    random weights. Only the four attributes `sdk.run.build` reads are provided."""
    import torch
    from huggingface_hub import hf_hub_download
    from kelpie_models.synth.roll import roll

    require_cached(model.CHECKPOINT)
    with open(hf_hub_download(model.CHECKPOINT, "config.json")) as handle:
        config = model.config_from_hf(roll(json.load(handle)).config)
    weights = random_weights(model, config)

    class Rolled:
        CHECKPOINT = model.CHECKPOINT
        CHAT_FAMILY = getattr(model, "CHAT_FAMILY", "default")
        DTYPE = "float32"
        attn_specs = staticmethod(model.attn_specs)
        forward = staticmethod(model.forward)

        @staticmethod
        def load(device: str = "cpu", dtype: torch.dtype = torch.float32) -> tuple[Any, Any]:
            return weights, config

    Rolled.__name__ = f"rolled_{model.__name__.rsplit('.', 1)[-1]}"
    return Rolled  # type: ignore[return-value]


def random_weights(
    model: ModuleType,
    config: Any,  # the model's own config dataclass (GptOssConfig, ...): one type per model
) -> Any:  # its own weight pytree, likewise
    """The model's own weight pytree, filled with small noise, with no shape table here.

    `from_state_dict` already knows every tensor's shape; it just reads them out of a state
    dict. So this hands it one that INVENTS each tensor on demand, and learns the shape by
    asking the model twice:

    1. Build with a probe dict that records which HF names are asked for and returns a
       0-dim placeholder. `from_state_dict` runs to its first shape assert and tells us the
       name list.
    2. For each name, take the real checkpoint's shape from the safetensors HEADER (a few KB
       of JSON, never the weights) and rewrite each dimension from the FULL config's value to
       the rolled one, resolving a value two config fields share (gpt-oss: hidden ==
       intermediate == 2880) by the axis's position in the full shape.

    Quantized payloads are random CODES: gpt-oss's packed MXFP4 (`*_blocks` / `*_scales`,
    uint8) gets uniform e2m1 nibbles and e8m0 scales near 2^-5, which is a legal table of the
    right shape -- all this row needs.
    """
    import torch
    from kelpie_models.sdk.hf import resolve_hf

    generator = torch.Generator().manual_seed(0)
    config_path, shard_paths = resolve_hf(model.CHECKPOINT)
    with open(config_path) as handle:
        full = model.config_from_hf(json.load(handle))
    header = header_entries(shard_paths)
    shrink = dim_shrinker(full, config)

    def shape_of(name: str) -> tuple[int, ...] | None:
        """The rolled shape. The model's own `shard_specs` names every axis of every weight it
        shards, so it answers exactly; `shrink` is the fallback for the few it does not name
        (the norms, whose single axis is unambiguously `hidden`)."""
        named = axes_of(model, config, name)
        if named is not None:
            return named
        raw = header_shape_raw(header, name)
        return None if raw is None else shrink(raw)

    class Lazy(dict):
        def __contains__(self, name: object) -> bool:
            return shape_of(str(name)) is not None

        def __getitem__(self, name: str) -> torch.Tensor:
            shape = shape_of(name)
            if shape is None:
                raise KeyError(name)
            if name.endswith("_blocks"):
                return torch.randint(0, 256, shape, generator=generator, dtype=torch.uint8)
            if name.endswith("_scales"):
                return torch.randint(*E8M0_NEAR_2_TO_MINUS_5, shape, generator=generator,
                                     dtype=torch.uint8)
            return (torch.randn(*shape, generator=generator) * 0.02).to(torch.float32)

    return model.from_state_dict(Lazy(), config, "cpu", torch.float32)


E8M0_NEAR_2_TO_MINUS_5 = (121, 124)  # [lo, hi) e8m0 codes: 2^-6 .. 2^-4

AXIS_LETTERS = {
    "V": "vocab",
    "M": "hidden",
    "Mg": "hidden_groups",  # MXFP4: hidden / 32 scale groups
    "I": "intermediate",
    "Ig": "intermediate_groups",
    "I2": "intermediate2",
    "E": "n_experts",
    "H": "n_heads",
    "Hd": "n_heads_dim",
    "K": "n_kv_heads",
    "Kd": "n_kv_heads_dim",
}


def axes_of(
    model: ModuleType,
    config: Any,  # the model's own config dataclass; see random_weights
    name: str,
) -> tuple[int, ...] | None:
    """The rolled shape of `name`, read off the model's own `shard_specs` layout string -- the
    one place a model already writes down what each dimension of each weight IS. None when the
    model has no `shard_specs`, or names no field for this tensor."""
    if not hasattr(model, "shard_specs"):
        return None
    from kelpie_models.shard import Mesh

    specs = model.shard_specs(config, Mesh.single("cpu"))
    key = field_of(name, specs)
    if key is None:
        return None
    tokens = [t.split("/")[0] for t in specs[key].split()]
    group = 32  # MXFP4 values per scale; a literal dim ("16") is its own size
    sizes = {
        "vocab": config.vocab,
        "hidden": config.hidden,
        "hidden_groups": config.hidden // group,
        "intermediate": config.intermediate,
        "intermediate_groups": config.intermediate // group,
        "intermediate2": 2 * config.intermediate,
        "n_experts": config.n_experts,
        "n_heads_dim": config.n_heads * config.head_dim,
        "n_kv_heads_dim": config.n_kv_heads * config.head_dim,
        "n_heads": config.n_heads,
        "n_kv_heads": config.n_kv_heads,
    }
    return tuple(int(t) if t.isdigit() else sizes[AXIS_LETTERS[t]] for t in tokens)


# shard_specs field -> the HF suffix that identifies it. The model names the axes; this names
# the tensors, which is the one thing the layout strings cannot say.
SPEC_SUFFIXES = {
    "embed": "embed_tokens.weight",
    "lm_head": "lm_head.weight",
    "layers.q": "q_proj.weight",
    "layers.q_b": "q_proj.bias",
    "layers.k": "k_proj.weight",
    "layers.k_b": "k_proj.bias",
    "layers.v": "v_proj.weight",
    "layers.v_b": "v_proj.bias",
    "layers.o": "o_proj.weight",
    "layers.sinks": "sinks",
    "layers.gate_up.blocks": "gate_up_proj_blocks",
    "layers.gate_up.scales": "gate_up_proj_scales",
    "layers.gate_up_b": "gate_up_proj_bias",
    "layers.down.blocks": "down_proj_blocks",
    "layers.down.scales": "down_proj_scales",
    "layers.down_b": "down_proj_bias",
}


def field_of(name: str, specs: dict[str, str]) -> str | None:
    """`model.layers.7.mlp.experts.down_proj` -> the `shard_specs` key it names
    (`layers.down`), or None when the model shards no such tensor."""
    for key, suffix in SPEC_SUFFIXES.items():
        if key in specs and name.endswith(suffix):
            return key
    return None


def header_shape_raw(
    header: dict[str, tuple[tuple[int, ...], Any]], name: str
) -> tuple[int, ...] | None:
    """The checkpoint's own shape for `name`, unshrunk, matching any layer index."""
    entry = header.get(name)
    if entry is None:
        generic = layer_generic(name)
        entry = next((v for k, v in header.items() if layer_generic(k) == generic), None)
    return None if entry is None else entry[0]


def dim_shrinker(
    full: Any,  # the checkpoint's own config dataclass; see random_weights
    small: Any,  # the same class, rolled down
) -> Any:  # -> shrink(shape) -> shape
    """-> shrink(full shape) -> rolled shape. Every dimension the config names, mapped from
    the full config's value to the rolled one. A value two fields share (gpt-oss:
    hidden == intermediate == 2880) resolves to `hidden`: it is the residual width, so it is
    the dimension that appears in almost every tensor, and the intermediate-only tensors
    (`gate`/`up`/`down`) stay legal because the model's own asserts check them against the
    rolled config, which is where the run would fail loudly rather than quietly.

    The rolled model does not have to MEAN anything: its row asserts batched == solo, never a
    golden string. It only has to be a legal model of the right SHAPE."""
    pairs: list[tuple[int, int]] = []
    for heads in ("n_heads", "n_kv_heads"):
        pairs.append((getattr(full, heads) * full.head_dim, getattr(small, heads) * small.head_dim))
        pairs.append((getattr(full, heads), getattr(small, heads)))
    pairs.append((2 * full.intermediate, 2 * small.intermediate))
    # Later pairs win, so the order here IS the tie-break: hidden last, and thus strongest.
    for name in ("vocab", "n_experts", "head_dim", "intermediate", "hidden"):
        big, little = getattr(full, name, None), getattr(small, name, None)
        if isinstance(big, int) and isinstance(little, int):
            pairs.append((big, little))
    table: dict[int, int] = dict(pairs)

    def shrink(shape: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(table.get(dim, dim) for dim in shape)

    return shrink


def layer_generic(name: str) -> str:
    """`model.layers.7.self_attn.q_proj.weight` -> `model.layers.N.self_attn.q_proj.weight`,
    so a rolled 3-layer model can read layer 40's shape off the real checkpoint's header."""
    return ".".join("N" if part.isdigit() else part for part in name.split("."))


SAFETENSORS_DTYPES = {
    "F64": "float64",
    "F32": "float32",
    "F16": "float16",
    "BF16": "bfloat16",
    "I64": "int64",
    "I32": "int32",
    "I16": "int16",
    "I8": "int8",
    "U8": "uint8",
    "BOOL": "bool",
}


def header_entries(shard_paths: list[str]) -> dict[str, tuple[tuple[int, ...], Any]]:
    """Every tensor's (shape, dtype) from the safetensors headers -- the JSON prefix only, a
    few KB, never the weights. This is what lets a 20B checkpoint seed a 3-layer fake."""
    import struct

    import torch

    out: dict[str, tuple[tuple[int, ...], Any]] = {}
    for path in shard_paths:
        with open(path, "rb") as f:
            (length,) = struct.unpack("<Q", f.read(8))
            header = json.loads(f.read(length))
        for name, entry in header.items():
            if name != "__metadata__":
                dtype = getattr(torch, SAFETENSORS_DTYPES[entry["dtype"]])
                out[name] = (tuple(entry["shape"]), dtype)
    return out


def chat_codec(model: ModuleType) -> object | None:
    """The chat codec for /v1/chat/completions; None serves completions only, which is all
    these rows ask for."""
    del model
    return None


def shorten(texts: tuple[str, ...], width: int = 60) -> str:
    joined = " | ".join(repr(t) for t in texts)
    return joined if len(joined) <= width else joined[: width - 3] + "..."


if __name__ == "__main__":
    sys.exit(main(sys.argv))
