import pytest

from box import gpus


def test_names_unique_case_insensitive():
    names = [g.name.lower() for g in gpus.GPUS]
    assert len(names) == len(set(names))


def test_lookup_any_case_and_unknown_lists_known():
    assert gpus.lookup("rtx-5090").runpod == "NVIDIA GeForce RTX 5090"
    with pytest.raises(KeyError, match="known: .*RTX-PRO-6000"):
        gpus.lookup("RTX-9999")


def test_synced_prices_cover_every_modal_gpu():
    """gpus.json came from `box gpus --sync`; a GPU added to the table without a re-sync shows here."""
    modal = gpus.prices()["modal"]
    assert {g.name for g in gpus.GPUS if g.modal} == set(modal)


def test_modal_rate_keys():
    keys = {g.name: gpus.modal_rate_key(g) for g in gpus.GPUS if g.modal}
    assert keys["A100-80GB"] == "gpu_hour_cost_a100_80gb"
    assert keys["RTX-PRO-6000"] == "gpu_hour_cost_rtx6000"
    assert keys["A10G"] == "gpu_hour_cost_a10g"
