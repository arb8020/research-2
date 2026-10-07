"""Which provider the feature tests run against: `pytest --provider local` (default), `modal`, or
`runpod`. Each provider says what a test machine is (gpu, image) and how slow it is (SCALE
multiplies every timing in the tests, since a cloud exec takes ~0.5 s and a local one ~5 ms)."""

from __future__ import annotations

from pathlib import Path

from box.sdk import Provider

IMAGE = "python:3.13-slim"  # any image with bash + python3 is a box image
SCALE = {"local": 1.0, "modal": 10.0, "runpod": 30.0}  # runpod: ~30 s boot comes out of box.deadline


def make(name: str, base: Path) -> Provider:
    if name == "local":
        from box.local_provider import Local

        return Local(base)
    if name == "modal":
        from box.modal_provider import Modal

        return Modal(region="us")  # unpinned, Modal has placed an L4 in Tokyo (~330 s boot, ~390 ms/exec)
    if name == "runpod":
        from box.runpod_provider import RunPod

        return RunPod.from_env()
    raise ValueError(f"unknown provider {name!r}")


def launch_kw(name: str) -> dict:
    """gpu/image a test machine is launched with (the local provider takes neither)."""
    if name == "runpod":  # a CPU pod ($0.06/hr; gpu=None) on RunPod's base image (bash, python3, sshd)
        return {"gpu": None, "image": "runpod/base:1.4.0-ubuntu2404"}
    if name == "modal":  # a CPU sandbox: boots in ~2 s; an L4 took 5-375 s to be scheduled, past short test deadlines
        return {"gpu": None, "image": IMAGE}
    return {} if name == "local" else {"gpu": "L4", "image": IMAGE}
