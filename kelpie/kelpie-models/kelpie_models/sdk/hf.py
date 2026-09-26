"""Locate and read HF safetensors checkpoints (uses the local hub cache; downloads if absent).

`<repo>@layers=N` names the first N layers of a checkpoint: only the tensors those layers need
(embeddings, lm head, final norm, layers 0..N-1) are fetched, by HTTP range requests against the
hub's safetensors shards, into one local shard. A 40 GB model becomes a few GB on disk, which is
what lets gpt-oss-20b run on a laptop for correctness tests.
"""

from __future__ import annotations

import json
import os
import re
import struct
from pathlib import Path

import torch
from huggingface_hub import hf_hub_download, hf_hub_url
from huggingface_hub.utils import build_hf_headers
from safetensors.torch import load_file, save_file

TRUNCATED_ROOT = Path(
    os.environ.get("KELPIE_TRUNCATED_ROOT", Path.home() / ".cache/huggingface/kelpie-truncated")
)


def resolve_hf(model_id: str) -> tuple[str, list[str]]:
    """-> (config.json path, [safetensors shard paths]). A local directory is used as is."""
    if os.path.isdir(model_id):
        d = Path(model_id)
        return str(d / "config.json"), sorted(str(p) for p in d.glob("*.safetensors"))
    if "@layers=" in model_id:
        repo, n = model_id.split("@layers=")
        return resolve_truncated(repo, int(n))
    cfg = hf_hub_download(model_id, "config.json")
    try:
        index = hf_hub_download(model_id, "model.safetensors.index.json")
        shards = sorted(set(json.load(open(index))["weight_map"].values()))
        paths = [hf_hub_download(model_id, s) for s in shards]
    except Exception:  # single-file checkpoint
        paths = [hf_hub_download(model_id, "model.safetensors")]
    return cfg, paths


def load_safetensors(paths: list[str]) -> dict[str, torch.Tensor]:
    out: dict[str, torch.Tensor] = {}
    for p in paths:
        assert os.path.exists(p), p
        out.update(load_file(p))
    return out


def resolve_truncated(repo: str, n_layers: int) -> tuple[str, list[str]]:
    assert n_layers > 0
    out_dir = TRUNCATED_ROOT / f"{repo.replace('/', '--')}--layers-{n_layers}"
    cfg_path, st_path = out_dir / "config.json", out_dir / "model.safetensors"
    if cfg_path.exists() and st_path.exists():
        return str(cfg_path), [str(st_path)]
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(hf_hub_download(repo, "config.json")) as f:
        cfg = json.load(f)
    keep = keep_tensor(n_layers)
    bigger = local_truncation_at_least(repo, n_layers)
    if bigger is not None:  # slice a larger local truncation instead of refetching
        tensors = {k: v for k, v in load_file(str(bigger / "model.safetensors")).items() if keep(k)}
    else:
        tensors = fetch_tensors(repo, keep)
    save_file(tensors, str(st_path))
    with open(cfg_path, "w") as f:
        json.dump(truncate_config(cfg, n_layers), f, indent=2)
    return str(cfg_path), [str(st_path)]


def local_truncation_at_least(repo: str, n_layers: int) -> Path | None:
    prefix = f"{repo.replace('/', '--')}--layers-"
    found = [
        d for d in TRUNCATED_ROOT.glob(prefix + "*")
        if int(d.name[len(prefix):]) >= n_layers and (d / "model.safetensors").exists()
    ]  # fmt: skip
    return min(found, key=lambda d: int(d.name[len(prefix) :])) if found else None


def keep_tensor(n_layers: int):
    layer_re = re.compile(r"^(?:model\.|transformer\.)?(?:layers|h)\.(\d+)\.")

    def keep(name: str) -> bool:
        m = layer_re.match(name)
        return m is None or int(m.group(1)) < n_layers

    return keep


def truncate_config(cfg: dict, n_layers: int) -> dict:
    c = dict(cfg)
    for key in ("num_hidden_layers", "n_layer"):
        if key in c:
            c[key] = n_layers
    if "layer_types" in c:
        c["layer_types"] = c["layer_types"][:n_layers]
    return c


def fetch_tensors(repo: str, keep) -> dict[str, torch.Tensor]:
    """Range-GET every kept tensor out of the repo's shards; nothing else touches the disk."""
    import httpx

    try:
        index = hf_hub_download(repo, "model.safetensors.index.json")
        shards = sorted(set(json.load(open(index))["weight_map"].values()))
    except Exception:
        shards = ["model.safetensors"]
    out: dict[str, torch.Tensor] = {}
    headers = build_hf_headers()
    with httpx.Client(follow_redirects=True, timeout=600) as client:
        for shard in shards:
            url = hf_hub_url(repo, shard)
            header, base = read_safetensors_header(client, url, headers)
            for name, meta in header.items():
                if name == "__metadata__" or not keep(name):
                    continue
                a, b = meta["data_offsets"]
                rng = {"Range": f"bytes={base + a}-{base + b - 1}"}
                r = client.get(url, headers={**headers, **rng})
                assert r.status_code == PARTIAL_CONTENT, (name, r.status_code)
                assert len(r.content) == b - a, (name, len(r.content), b - a)
                out[name] = tensor_from_bytes(r.content, meta["dtype"], meta["shape"])
                print(f"fetched {name} {meta['dtype']} {meta['shape']} ({(b - a) >> 20} MiB)")
    assert out, "no tensors kept"
    return out


def read_safetensors_header(client, url: str, headers: dict) -> tuple[dict, int]:
    r = client.get(url, headers={**headers, "Range": "bytes=0-7"})
    assert r.status_code == PARTIAL_CONTENT, r.status_code
    (n,) = struct.unpack("<Q", r.content)
    r = client.get(url, headers={**headers, "Range": f"bytes=8-{8 + n - 1}"})
    assert r.status_code == PARTIAL_CONTENT, r.status_code
    return json.loads(r.content), 8 + n


PARTIAL_CONTENT = 206

DTYPES = {
    "BF16": torch.bfloat16,
    "F16": torch.float16,
    "F32": torch.float32,
    "U8": torch.uint8,
    "I64": torch.int64,
    "I32": torch.int32,
}


def tensor_from_bytes(data: bytes, dtype: str, shape: list[int]) -> torch.Tensor:
    t = torch.frombuffer(bytearray(data), dtype=DTYPES[dtype])
    return t.reshape(shape).clone()
