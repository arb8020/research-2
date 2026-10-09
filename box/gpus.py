from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PRICES = Path(__file__).resolve().parent / "gpus.json"
PROVIDERS = ("modal", "runpod", "colab")


@dataclass(frozen=True)
class Gpu:
    name: str
    vram_gb: int
    modal: str | None
    runpod: str | None
    colab: str | None = None


GPUS = (
    Gpu("T4", 16, "T4", None, colab="T4"),
    Gpu("L4", 24, "L4", "NVIDIA L4", colab="L4"),
    Gpu("A10G", 24, "A10", None),
    Gpu("RTX-4090", 24, None, "NVIDIA GeForce RTX 4090"),
    Gpu("RTX-5090", 32, None, "NVIDIA GeForce RTX 5090"),
    Gpu("A100-40GB", 40, "A100-40GB", "NVIDIA A100-SXM4-40GB", colab="A100"),
    Gpu("L40S", 48, "L40S", "NVIDIA L40S"),
    Gpu("A100-80GB", 80, "A100-80GB", "NVIDIA A100-SXM4-80GB"),
    Gpu("H100", 80, "H100", "NVIDIA H100 80GB HBM3", colab="H100"),
    Gpu("RTX-PRO-6000", 96, "RTX-PRO-6000", "NVIDIA RTX PRO 6000 Blackwell Server Edition", colab="G4"),
    Gpu("H200", 141, "H200", "NVIDIA H200"),
    Gpu("B200", 180, "B200", "NVIDIA B200"),
    Gpu("B300", 288, "B300", "NVIDIA B300 SXM6 AC"),
    Gpu("TPU-v5e-1", 16, None, None, colab="V5E1"),
    Gpu("TPU-v6e-1", 32, None, None, colab="V6E1"),
)

# Modal's billing.rates() keys that break the gpu_hour_cost_<modal id> pattern
MODAL_RATE_KEYS = {"A10G": "gpu_hour_cost_a10g", "RTX-PRO-6000": "gpu_hour_cost_rtx6000"}
RUNPOD_GRAPHQL = "https://api.runpod.io/graphql"


def lookup(name: str) -> Gpu:
    found = [g for g in GPUS if g.name.lower() == name.lower()]
    if not found:
        raise KeyError(f"unknown GPU {name!r}; known: {', '.join(g.name for g in GPUS)}")
    return found[0]


def provider_id(gpu: Gpu, provider: str) -> str | None:
    assert provider in PROVIDERS, f"no GPU ids for provider {provider!r}; known: {PROVIDERS}"
    return getattr(gpu, provider)


def prices() -> dict[str, dict[str, float]]:
    return json.loads(PRICES.read_text())


def modal_rate_key(gpu: Gpu) -> str:
    assert gpu.modal is not None, gpu
    return MODAL_RATE_KEYS.get(gpu.name, "gpu_hour_cost_" + gpu.modal.lower().replace("-", "_"))


def sync_modal() -> tuple[dict[str, float], list[str]]:
    import modal

    rates = modal.Workspace.from_context().billing.rates()
    gpu_keys = {k for k in rates if k.startswith("gpu_hour_cost_")}
    synced = {g.name: float(rates[modal_rate_key(g)]) for g in GPUS if g.modal and modal_rate_key(g) in gpu_keys}
    return synced, sorted(gpu_keys - {modal_rate_key(g) for g in GPUS if g.modal})


def sync_runpod() -> tuple[dict[str, float], list[str]]:
    import requests

    query = "{ gpuTypes { id secureCloud securePrice } }"
    resp = requests.post(RUNPOD_GRAPHQL, json={"query": query}, timeout=30)
    resp.raise_for_status()
    types = {t["id"]: t for t in resp.json()["data"]["gpuTypes"] if t["secureCloud"]}
    synced = {g.name: types[g.runpod]["securePrice"] for g in GPUS if g.runpod in types}
    return synced, sorted(set(types) - {g.runpod for g in GPUS})


def sync() -> list[str]:
    modal_prices, modal_unmapped = sync_modal()
    runpod_prices, runpod_unmapped = sync_runpod()
    PRICES.write_text(json.dumps({"modal": modal_prices, "runpod": runpod_prices}, indent=2) + "\n")
    notes = [f"modal rate keys with no GPU here: {', '.join(modal_unmapped) or 'none'}"]
    notes += [f"runpod secure gpuTypeIds with no GPU here: {', '.join(runpod_unmapped) or 'none'}"]
    for provider, synced in (("modal", modal_prices), ("runpod", runpod_prices)):
        notes += [f"{provider}: no live price for {g.name}" for g in GPUS if provider_id(g, provider) and g.name not in synced]
    return notes


def table() -> str:
    p = prices()
    rows = [("name", "vram", "modal", "$/hr", "runpod", "$/hr", "colab")]
    for g in GPUS:
        rows.append((
            g.name, f"{g.vram_gb}G",
            g.modal or "-", _price(p["modal"].get(g.name)),
            g.runpod or "-", _price(p["runpod"].get(g.name)), g.colab or "-",
        ))  # fmt: skip
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip() for r in rows)


def _price(p: float | None) -> str:
    return "-" if p is None else f"{p:.2f}"
