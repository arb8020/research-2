"""The Modal provider: a machine is a Modal Sandbox whose entrypoint is the supervisor.

A sandbox lives exactly as long as its entrypoint, so when the supervisor exits the sandbox ends
by itself (no BOX_ON_SHUTDOWN needed), and its files go with it. Sandbox.create's `timeout` is
Modal's hard backstop past the supervisor's deadline (Modal caps it at 24 h). labels are sandbox
tags; list()/get() only see sandboxes tagged box.by=box under the "box" app.

Credentials are an argument, never looked up here: every Modal call goes through a client built
from the token the caller passes (the CLI reads ~/.modal.toml with ModalToken.from_config).

    Modal(token=ModalToken.from_config(), volumes={"/data": "kelpie-a1"})  # volumes: {mount path: name}, created if missing
"""

from __future__ import annotations

import contextlib
import threading
import time
import tomllib
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import modal

from box import gpus
from box.sdk import LABEL_BY, Gone

APP = "box"
# TODO(handoff): region. Unpinned, Modal placed L4s in Tokyo (~330-375 s to start, ~390 ms/exec);
# tests pin region="us" (providers.py). Pinned regions cost more (amount not checked). Default it?
# TODO(handoff): T below is a TypeVar (ruff UP047); left for the generics/TypeVar decision.
# TODO(handoff): calls after the first are bounded at 60 s; a large put/get tar could exceed that.
ROOT = "/box"
MAX_TIMEOUT_S = 24 * 3600  # Modal refuses a longer sandbox timeout
DEFAULT_PYTHON = "3.13"
T = TypeVar("T")
ENDING_S = 10.0  # how long a sandbox mid-shutdown takes to report it has ended
BOOT_TIMEOUT_S = 900.0  # the first call after create: Modal schedules the sandbox (an L4 took 330 s unpinned)
CALL_TIMEOUT_S = 60.0  # every later call (a healthy exec is 20-400 ms)
MODAL_TOML = Path.home() / ".modal.toml"  # where `modal token set` keeps profiles


@dataclass(frozen=True)
class ModalToken:
    """A Modal API token: id "ak-...", secret "as-..." (modal.com -> Settings -> API tokens).
    It acts as its owner in that whole workspace (Modal has no sandbox-only scope). Never printed."""

    id: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_config(cls, path: Path = MODAL_TOML) -> ModalToken:
        """The profile marked `active = true` in Modal's config file (what `modal profile activate`
        sets). Exactly one must be active: picking one for the caller would pick a workspace."""
        profiles = tomllib.loads(path.read_text())
        active = [name for name, p in profiles.items() if isinstance(p, dict) and p.get("active") is True]
        if len(active) != 1:
            raise ValueError(f"{path}: {len(active)} active profiles {active}; want exactly one (`modal profile activate`)")
        profile = profiles[active[0]]
        if not (isinstance(profile.get("token_id"), str) and isinstance(profile.get("token_secret"), str)):
            raise ValueError(f"{path}: profile {active[0]!r} has no token_id/token_secret")
        return cls(profile["token_id"], profile["token_secret"])


class Modal:
    name = "modal"

    def __init__(self, *, token: ModalToken, volumes: dict[str, str] | None = None, region: str | None = None) -> None:
        """region (e.g. "us"): None lets Modal place the sandbox anywhere, which once put an L4 in
        ap-northeast: ~330 s to start, ~390 ms per exec from California (vs 5 s / 66 ms in "us").
        Modal bills a region-pinned sandbox at a premium."""
        self.token = token
        self.volumes = dict(volumes or {})
        self.region = region
        self._client: modal.Client | None = None
        self._app: modal.App | None = None

    @property
    def client(self) -> modal.Client:
        if self._client is None:  # opens a connection; not at construction, so Modal(...) is free
            self._client = modal.Client.from_credentials(self.token.id, self.token.secret)
        return self._client

    @property
    def app(self) -> modal.App:
        if self._app is None:  # a network call, like client
            self._app = modal.App.lookup(APP, client=self.client, create_if_missing=True)
        return self._app

    def launch(
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int,
    ) -> ModalMachine:  # fmt: skip
        sandbox = modal.Sandbox.create(
            *entrypoint, app=self.app, image=resolve_image(image), gpu=modal_gpu(gpu), region=self.region,
            env={**env, "BOX_ROOT": ROOT}, tags=labels, timeout=min(timeout_s, MAX_TIMEOUT_S), client=self.client,
            volumes={path: modal.Volume.from_name(v, create_if_missing=True, client=self.client) for path, v in self.volumes.items()},
        )  # fmt: skip
        return ModalMachine(sandbox, labels, booting=True)

    def get(self, machine_id: str) -> ModalMachine:
        try:
            sandbox = modal.Sandbox.from_id(machine_id, client=self.client)
            tags = sandbox.get_tags()
        except (modal.exception.NotFoundError, modal.exception.InvalidError) as e:
            raise LookupError(f"modal provider: no sandbox {machine_id}: {e}") from e
        if tags.get(LABEL_BY) != "box":
            raise LookupError(f"modal provider: {machine_id} was not launched by box (no {LABEL_BY}=box tag)")
        return ModalMachine(sandbox, tags)

    def list(self) -> list[ModalMachine]:
        """Running sandboxes only: Modal's list drops a sandbox once it has ended."""
        found = modal.Sandbox.list(app_id=self.app.app_id, tags={LABEL_BY: "box"}, client=self.client)
        return [ModalMachine(s, s.get_tags()) for s in found]


class ModalMachine:
    root = ROOT

    def __init__(self, sandbox: modal.Sandbox, labels: dict[str, str], *, booting: bool = False) -> None:
        self.sandbox = sandbox
        self.id = sandbox.object_id
        self.labels = labels
        self._booting = booting  # create returns before Modal schedules it: the first call waits for that

    def exec(self, cmd: str) -> tuple[int, str, str]:
        def run() -> tuple[int, str, str]:
            p = self.sandbox.exec("bash", "-c", cmd)
            # each of these is a round trip; in parallel an exec costs ~1 RTT after create, not 3
            out, err, done = (_in_thread(f) for f in (p.stdout.read, p.stderr.read, p.wait))
            rc, out, err = done.result(), out.result(), err.result()
            if (rc is None or rc == -1) and self._ends():  # Modal's code for an exec it killed
                raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under `{cmd}`")
            return rc, out, err

        return self._live(run)

    def write(self, path: str, data: bytes) -> None:
        self._live(lambda: self.sandbox.filesystem.write_bytes(data, path))  # creates parent dirs

    def read(self, path: str) -> bytes:
        try:
            return self._live(lambda: self.sandbox.filesystem.read_bytes(path))
        except modal.exception.SandboxFilesystemNotFoundError as e:
            raise FileNotFoundError(path) from e

    def terminate(self) -> None:
        """Idempotent: terminating an ended sandbox is a no-op on Modal."""
        with contextlib.suppress(modal.exception.NotFoundError):
            self.sandbox.terminate()

    def _live(self, call: Callable[[], T]) -> T:
        """call, bounded in time, with Modal's 'this sandbox has ended' errors raised as Gone. Once it
        has ended: NotFoundError ("Task has already finished", "Sandbox is unavailable"). While it
        ends: ConflictError ("Sandbox is shutting down") or a bare SandboxFilesystemError ("unexpected
        error"), which are Gone only if the sandbox then turns out to have ended. A call can also
        hang for good on a sandbox stuck ending (seen live: poll() None minutes after its entrypoint
        exited, every exec stuck in SandboxGetTaskId); past its timeout that is TimeoutError."""
        timeout_s = BOOT_TIMEOUT_S if self._booting else CALL_TIMEOUT_S
        try:
            result = _in_thread(call).result(timeout=timeout_s)
        except FutureTimeout:
            if self._ends():
                raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode})") from None
            raise TimeoutError(f"{self.id}: Modal call hung for {timeout_s:.0f} s; sandbox still reports running") from None
        except (modal.exception.NotFoundError, modal.exception.SandboxTerminatedError) as e:
            raise Gone(f"{self.id}: {e}") from e
        except (modal.exception.ConflictError, modal.exception.SandboxFilesystemError) as e:
            if type(e) in (modal.exception.ConflictError, modal.exception.SandboxFilesystemError) and self._ends():
                raise Gone(f"{self.id}: {e}") from e
            raise
        self._booting = False
        return result

    def _ends(self, within_s: float = ENDING_S) -> bool:
        give_up = time.monotonic() + within_s
        while self.sandbox.poll() is None:
            if time.monotonic() > give_up:
                return False
            time.sleep(0.5)
        return True

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ModalMachine) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)


def _in_thread(call: Callable[[], T]) -> Future[T]:
    """call on its own daemon thread: one stuck in Modal forever then holds only itself."""
    future: Future[T] = Future()

    def run() -> None:
        try:
            future.set_result(call())
        except BaseException as e:  # noqa: BLE001 (handed to the caller via the future)
            future.set_exception(e)

    threading.Thread(target=run, daemon=True, name="box-modal-call").start()
    return future


def modal_gpu(gpu: str | None) -> str | None:
    """A canonical GPU name (box/gpus.py), optionally ':<count>', as Modal's gpu= string."""
    if gpu is None:
        return None
    name, _, count = gpu.partition(":")
    modal_id = gpus.provider_id(gpus.lookup(name), "modal")
    if modal_id is None:
        raise ValueError(f"modal provider: Modal does not rent {name!r}")
    return f"{modal_id}:{count}" if count else modal_id


def resolve_image(image: str | None) -> modal.Image:
    """None: Modal's debian_slim (bash + python3). A path ending in Dockerfile: built with its
    directory as the context. Anything else: an OCI registry ref."""
    if image is None:
        return modal.Image.debian_slim(python_version=DEFAULT_PYTHON)
    if image.lower().endswith("dockerfile"):
        return modal.Image.from_dockerfile(image, context_dir=Path(image).parent)
    return modal.Image.from_registry(image)
