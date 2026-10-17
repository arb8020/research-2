"""Which provider the feature tests run against: `pytest --provider local` (default), `modal`,
`runpod`, or `colab-fake` (box/providers/colab.py on a fake Colab account: tests/fake_colab.py).
Each provider says what a test machine is (gpu, image) and how slow it is (SCALE multiplies every
timing in the tests, since a cloud exec takes ~0.5 s and a local one ~5 ms), and what it cannot do
(CANNOT: a test marked @pytest.mark.needs("ports") is skipped on a provider that cannot)."""

from __future__ import annotations

import contextlib
import os
import shlex
import signal
from pathlib import Path

from box.providers.colab import ColabMachine
from box.sdk import Gone, Machine, Provider
from box.store import DirStore, Store

IMAGE = "python:3.13-slim"  # any image with bash + python3 is a box image
SCALE = {"local": 1.0, "modal": 10.0, "runpod": 30.0, "colab-fake": 3.0}  # runpod: ~30 s boot comes out of the lease (it counts from create); colab-fake: each exec is a `python -c`
CANNOT = {
    "colab-fake": {
        "ports": "Colab's terms forbid web services and proxies: no ports, no expose",
        "undeclared-ports": "Colab's terms forbid web services and proxies: no ports, no expose",
        "record": "Colab has no volumes: a Colab session has no durable record",
        "pty": "a Colab kernel cell is not a terminal: no stdin to type into",
        "shell": "Colab's terminal is in its UI only",
        "unique-names": "Colab runtimes have no names: box's name check is best-effort there",
    },
    "runpod": {
        "undeclared-ports": "RunPod has no gated route for a port not declared at create",
        "unique-names": "RunPod has no unique pod names: box's name check is best-effort there",
    },
}
DEV_IMAGE = "python:3.13"  # Session.sync also needs git on the machine; the non-slim image has it
PURPOSE = {"box.purpose": os.environ.get("BOX_TEST_PURPOSE", "reader-path-dev")}  # every test machine carries it, so a sweep finds strays
MAX_BACKSTOP_S = 900  # a test machine whose supervisor fails is still gone (and unbilled) after 15 min


def make(name: str, base: Path) -> Provider:
    return Tested(_make(name, base))


def _make(name: str, base: Path) -> Provider:
    if name == "local":
        from box.providers.local import Local

        return Local(base)
    if name == "modal":
        from box.providers.modal import Modal, ModalToken

        profile = os.environ.get("BOX_MODAL_PROFILE")  # a workspace pinned by name; else the active profile
        token = ModalToken.from_profile(profile) if profile else ModalToken.from_config()
        return Modal(token=token, region="us")  # unpinned, Modal has placed an L4 in Tokyo (~330 s boot, ~390 ms/exec)
    if name == "runpod":
        from box.providers.runpod import RunPod

        return RunPod.from_env()
    if name == "colab-fake":
        from box.providers.colab import Colab
        from box.tests.fake_colab import FakeBackend

        return Colab(FakeBackend(base / "account"))
    raise ValueError(f"unknown provider {name!r}")


def make_store(name: str, base: Path, provider: Provider) -> Store:
    """Where a test session records itself: a store its provider can mount."""
    if name == "local":
        return DirStore(base)
    if name == "modal":
        from box.providers.modal import ModalVolumeStore

        return ModalVolumeStore(RECORD_VOLUME, provider=provider)  # type: ignore[arg-type] (a Tested Modal)
    raise ValueError(f"no store for provider {name!r}")


RECORD_VOLUME = "box-sessions"  # a v2 Volume in the tester's own Modal workspace


def kill_supervisor(machine: Machine) -> None:
    """SIGKILL the machine's supervisor: no ended.json, no final flush. A local machine's
    supervisor is the pid it launched; a Colab one's, a child of its kernel's cell (found by its
    root); elsewhere it is the machine's PID 1."""
    pid_file = getattr(machine, "dir", None)
    if pid_file is not None:
        os.kill(int((pid_file / "pid").read_text()), signal.SIGKILL)
    elif isinstance(machine, ColabMachine):
        machine.exec(by_root(machine, "KILL"))
    else:
        with contextlib.suppress(Gone):  # the exec may die with it
            machine.exec("kill -9 1")


# The supervisor's own process, by its command line (/proc: a slim image has no ps or pgrep). Not
# PID 1: on Modal that is dumb-init, and stopping it leaves the supervisor (PID 2) answering.
STOP_SUPERVISOR = """for d in /proc/[0-9]*; do case "$(tr '\\0' ' ' < $d/cmdline)" in 'python3 '*'/supervisor.py --root '*) kill -STOP ${d#/proc/};; esac; done"""


def freeze_supervisor(machine: Machine) -> None:
    """SIGSTOP the machine's supervisor: alive, but it never answers (a hung host, a wedged process)."""
    pid_file = getattr(machine, "dir", None)
    if pid_file is not None:
        os.kill(int((pid_file / "pid").read_text()), signal.SIGSTOP)
    elif isinstance(machine, ColabMachine):
        rc, _, err = machine.exec(by_root(machine, "STOP"))
        assert rc == 0, err
    else:
        rc, _, err = machine.exec(STOP_SUPERVISOR)
        assert rc == 0, err


def by_root(machine: Machine, signal_name: str) -> str:
    """bash: signal the supervisor running under machine.root (on colab-fake, every test's machine is a
    process on this computer, so never PID 1 and never a pattern another test's supervisor matches).
    [s]: pkill must not match the shell that runs it."""
    return f"pkill -{signal_name} -f {shlex.quote(machine.root + '/[s]upervisor.py --root')}"


class Tested:
    """A provider whose machines carry PURPOSE and a provider backstop of at most MAX_BACKSTOP_S."""

    def __init__(self, inner: Provider) -> None:
        self.inner = inner
        self.name = inner.name
        if hasattr(inner, "snapshot"):  # a capability is seen statically (setup_cache.Snapshotter), not via __getattr__
            self.snapshot = inner.snapshot

    def launch(self, *, labels: dict[str, str], timeout_s: int, **kw: object) -> Machine:
        return self.inner.launch(labels={**labels, **PURPOSE}, timeout_s=min(timeout_s, MAX_BACKSTOP_S), **kw)

    def close(self) -> None:
        self.inner.close()

    def __getattr__(self, attr: str) -> object:
        return getattr(self.inner, attr)


def launch_kw(name: str) -> dict:
    """gpu/image a test machine is launched with (the local provider takes neither)."""
    if name == "runpod":  # a CPU pod ($0.06/hr; gpu=None) on RunPod's base image (bash, python3, sshd)
        return {"gpu": None, "image": "runpod/base:1.4.0-ubuntu2404"}
    if name == "colab-fake":  # the accelerator only names the fake runtime
        return {"gpu": "T4", "image": None}
    if name == "modal":  # a CPU sandbox: boots in ~2 s; an L4 took 5-375 s to be scheduled, past short test deadlines
        return {"gpu": None, "image": IMAGE}
    return {} if name == "local" else {"gpu": "L4", "image": IMAGE}
