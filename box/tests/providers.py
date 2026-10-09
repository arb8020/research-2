"""Which provider the feature tests run against: `pytest --provider local` (default), `modal`, or
`runpod`. Each provider says what a test machine is (gpu, image) and how slow it is (SCALE
multiplies every timing in the tests, since a cloud exec takes ~0.5 s and a local one ~5 ms)."""

from __future__ import annotations

import contextlib
import os
import signal
from pathlib import Path

from box.sdk import Gone, Machine, Provider
from box.store import DirStore, Store

IMAGE = "python:3.13-slim"  # any image with bash + python3 is a box image
SCALE = {"local": 1.0, "modal": 10.0, "runpod": 30.0}  # runpod: ~30 s boot comes out of the lease (it counts from create)
PURPOSE = {"box.purpose": "reader-path-dev"}  # every test machine carries it, so a sweep finds strays
MAX_BACKSTOP_S = 900  # a test machine whose supervisor fails is still gone (and unbilled) after 15 min


def make(name: str, base: Path) -> Provider:
    return Tested(_make(name, base))


def _make(name: str, base: Path) -> Provider:
    if name == "local":
        from box.providers.local import Local

        return Local(base)
    if name == "modal":
        from box.providers.modal import Modal, ModalToken

        return Modal(token=ModalToken.from_config(), region="us")  # unpinned, Modal has placed an L4 in Tokyo (~330 s boot, ~390 ms/exec)
    if name == "runpod":
        from box.providers.runpod import RunPod

        return RunPod.from_env()
    raise ValueError(f"unknown provider {name!r}")


def make_store(name: str, base: Path, provider: Provider) -> Store:
    """Where a test session records itself: a store its provider can mount."""
    if name == "local":
        return DirStore(base)
    if name == "modal":
        from box.providers.modal import ModalVolumeStore

        return ModalVolumeStore(RECORD_VOLUME, client=provider.client)
    raise ValueError(f"no store for provider {name!r}")


RECORD_VOLUME = "box-sessions"  # a v2 Volume in the tester's own Modal workspace


def kill_supervisor(machine: Machine) -> None:
    """SIGKILL the machine's supervisor: no ended.json, no final flush. A local machine's
    supervisor is the pid it launched; elsewhere it is the machine's PID 1."""
    pid_file = getattr(machine, "dir", None)
    if pid_file is not None:
        os.kill(int((pid_file / "pid").read_text()), signal.SIGKILL)
    else:
        with contextlib.suppress(Gone):  # the exec may die with it
            machine.exec("kill -9 1")


class Tested:
    """A provider whose machines carry PURPOSE and a provider backstop of at most MAX_BACKSTOP_S."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.name = inner.name

    def launch(self, *, labels: dict[str, str], timeout_s: int, **kw: object) -> Machine:
        return self.inner.launch(labels={**labels, **PURPOSE}, timeout_s=min(timeout_s, MAX_BACKSTOP_S), **kw)

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


def launch_kw(name: str) -> dict:
    """gpu/image a test machine is launched with (the local provider takes neither)."""
    if name == "runpod":  # a CPU pod ($0.06/hr; gpu=None) on RunPod's base image (bash, python3, sshd)
        return {"gpu": None, "image": "runpod/base:1.4.0-ubuntu2404"}
    if name == "modal":  # a CPU sandbox: boots in ~2 s; an L4 took 5-375 s to be scheduled, past short test deadlines
        return {"gpu": None, "image": IMAGE}
    return {} if name == "local" else {"gpu": "L4", "image": IMAGE}
