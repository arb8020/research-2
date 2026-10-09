"""The Modal provider: a machine is a Modal Sandbox whose entrypoint is the supervisor.

A sandbox lives exactly as long as its entrypoint, so when the supervisor exits the sandbox ends
by itself (no BOX_ON_SHUTDOWN needed), and its files go with it. Sandbox.create's `timeout` is
Modal's hard backstop past the session's ceiling (Modal caps it at 24 h, so a ceiling past
24 h - 600 s is refused here, never clamped). No Modal
`idle_timeout`, on purpose: Modal counts only connections and execs as activity, never work inside
the sandbox, so it would reap a long job nobody watches; the supervisor owns idleness. labels are sandbox
tags; list()/get() only see sandboxes tagged box.by=box under the "box" app.

Credentials are an argument, never looked up here: every Modal call goes through a client built
from the token the caller passes (the CLI reads ~/.modal.toml with ModalToken.from_config).

    Modal(token=ModalToken.from_config(), volumes={"/data": "kelpie-a1"})  # volumes: {mount path: name}, created if missing
    ModalVolumeStore("box-sessions", client=provider.client)    # a Store (box/store.py): launch(record=)
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import math
import secrets
import time
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import modal

from box import gpus
from box.providers.pump import Closed, Emit, Pumped, kill_pid_file, with_pid_file
from box.sdk import LABEL_BY, Endpoint, Gone
from box.store import Mount

APP = "box"
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
        return cls.from_profile(active[0], path)

    @classmethod
    def from_profile(cls, name: str, path: Path = MODAL_TOML) -> ModalToken:
        """The named profile of Modal's config file, active or not (a script pinned to one workspace)."""
        profile = tomllib.loads(path.read_text()).get(name)
        if not (isinstance(profile, dict) and isinstance(profile.get("token_id"), str) and isinstance(profile.get("token_secret"), str)):
            raise ValueError(f"{path}: no profile {name!r} with token_id/token_secret")
        return cls(profile["token_id"], profile["token_secret"])


class Modal:
    name = "modal"

    def __init__(self, *, token: ModalToken, region: str | None, volumes: dict[str, str] | None = None) -> None:
        """region (e.g. "us"), no default: every caller chooses. None lets Modal place the sandbox
        anywhere, which once put an L4 in ap-northeast: ~330 s to start, ~390 ms per exec from
        California (vs 5 s / 66 ms in "us"). Modal bills a region-pinned sandbox at a premium."""
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

    def close(self) -> None:
        """Close the client (its gRPC channel), if one was opened; this Modal makes no calls after."""
        if self._client is not None:
            self._client.__exit__(None, None, None)  # modal.Client's own close (it has no public close())

    @property
    def app(self) -> modal.App:
        if self._app is None:  # a network call, like client
            self._app = modal.App.lookup(APP, client=self.client, create_if_missing=True)
        return self._app

    def launch(  # noqa: PLR0913 (keyword-only: what a machine is made with)
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> ModalMachine:  # fmt: skip
        """mounts: ModalVolumeStores only, each a sub_path of its Volume (created on start if missing)."""
        if foreign := [m.store.uri for m in mounts if not isinstance(m.store, ModalVolumeStore)]:
            raise ValueError(f"modal provider: mounts only a ModalVolumeStore (got {foreign})")
        if timeout_s > MAX_TIMEOUT_S:  # refused, not clamped: a clamped backstop would end the sandbox before the session's ceiling
            raise ValueError(f"modal provider: timeout_s={timeout_s} past Modal's {MAX_TIMEOUT_S} s cap (a ceiling over {MAX_TIMEOUT_S - 600} s)")
        stores = {f"{ROOT}/{m.path}": m.store.volume.with_mount_options(sub_path=f"/{m.prefix}") for m in mounts}
        sandbox = modal.Sandbox.create(
            *entrypoint, app=self.app, image=resolve_image(image), gpu=modal_gpu(gpu), region=self.region,
            env={**env, "BOX_ROOT": ROOT}, tags=labels, timeout=timeout_s, client=self.client,
            encrypted_ports=ports,
            volumes={**{path: modal.Volume.from_name(v, create_if_missing=True, client=self.client) for path, v in self.volumes.items()}, **stores},
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

    def list(self, labels: dict[str, str] | None = None) -> list[ModalMachine]:
        """Running sandboxes only: Modal's list drops a sandbox once it has ended."""
        tags = {**(labels or {}), LABEL_BY: "box"}
        found = modal.Sandbox.list(app_id=self.app.app_id, tags=tags, client=self.client)
        return [ModalMachine(s, s.get_tags()) for s in found]


class ModalVolumeStore:
    """A Modal Volume (v2: concurrent writers, per-file commits) as a Store. Readers see what has
    been committed. Seen live (2026-10-09, CPU sandboxes in "us", a sub_path mount): a sandbox's
    `sync <mount>` commits (~70 ms); unsynced writes commit by themselves within ~5 s, and also land
    when the sandbox is terminate()d, its entrypoint exits, or its PID 1 is SIGKILLed.
    The Volume is in the client's workspace: whoever holds that token can read every session in it."""

    sync_writes = True

    def __init__(self, name: str, *, client: modal.Client) -> None:
        self.name = name
        self.uri = f"modal-volume://{name}"
        self.volume = modal.Volume.from_name(name, version=2, create_if_missing=True, client=client)

    def get(self, key: str) -> bytes:
        return b"".join(self.volume.read_file(key))  # FileNotFoundError if absent

    def list(self, prefix: str) -> list[str]:
        try:
            entries = self.volume.listdir(prefix, recursive=True)
        except modal.exception.NotFoundError:
            return []
        files = [e.path.lstrip("/") for e in entries if e.type == modal.volume.FileEntryType.FILE]
        return sorted(f for f in files if not f.endswith(".tmp"))

    def put(self, key: str, data: bytes) -> None:
        with self.volume.batch_upload(force=True) as batch:
            batch.put_file(io.BytesIO(data), key)


class ModalMachine:
    root = ROOT

    def __init__(self, sandbox: modal.Sandbox, labels: dict[str, str], *, booting: bool = False) -> None:
        self.sandbox = sandbox
        self.id = sandbox.object_id
        self.labels = labels
        self._booting = booting  # create returns before Modal schedules it: the first call waits for that

    def exec(self, cmd: str) -> tuple[int, str, str]:
        async def run() -> tuple[int, str, str]:
            p = await self.sandbox.exec.aio("bash", "-c", cmd)
            # each of these is a round trip; together an exec costs ~1 RTT after create, not 3
            out, err, rc = await asyncio.gather(p.stdout.read.aio(), p.stderr.read.aio(), p.wait.aio())
            return rc, out, err

        rc, out, err = self._live(run)
        if (rc is None or rc == -1) and self._ends():  # Modal's code for an exec it killed
            raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under `{cmd}`")
        return rc, out, err

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None) -> Pumped:
        """An exec whose stdout and stderr are read as they arrive, on one reader thread running its own
        event loop (so close() can cancel the read, which a sync Modal call cannot be). Modal has no
        kill for an exec: close() kills it by the pid it noted, in another exec, and Modal ends it
        anyway at timeout_s (exec's own timeout). An open exec does not keep the sandbox up: it
        ends (rc 137) when the supervisor exits, seen live; and it is not a connection to an exposed
        port, so the supervisor never counts it against idleness."""
        pid_file = f"/tmp/box-stream-{secrets.token_hex(6)}.pid"
        loop: list[tuple[asyncio.AbstractEventLoop, asyncio.Task]] = []  # the reader's, once it runs
        rc: list[int | None] = []

        def read(emit: Emit) -> None:
            async def pump() -> None:
                p = await self.sandbox.exec.aio("bash", "-c", with_pid_file(cmd, pid_file), text=False, timeout=math.ceil(timeout_s))

                async def drain(name: str, source: AsyncIterator[bytes]) -> None:
                    async for data in source:
                        emit(name, data)  # blocks this loop while the caller is behind: backpressure

                await asyncio.gather(drain("stdout", p.stdout), drain("stderr", p.stderr))
                rc.append(await p.wait.aio())

            runner = asyncio.new_event_loop()
            try:
                task = runner.create_task(pump())
                loop.append((runner, task))
                runner.run_until_complete(task)
            except asyncio.CancelledError:
                raise Closed from None
            except (modal.exception.NotFoundError, modal.exception.SandboxTerminatedError) as e:
                raise Gone(f"{self.id}: {e}") from e
            finally:
                runner.close()

        def kill() -> None:
            with contextlib.suppress(Gone):
                self.exec(kill_pid_file(pid_file))
            for runner, task in loop:  # if the read is still waiting on Modal, stop waiting
                with contextlib.suppress(RuntimeError):  # its loop already closed: it ended by itself
                    runner.call_soon_threadsafe(task.cancel)

        def wait() -> int | None:
            code = rc[0] if rc else None
            if code != 0 and self._ends():  # 137 (or -1) is how an exec ends with its sandbox
                raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under a stream of `{cmd}`")
            return code

        return Pumped([read], kill=kill, wait=wait, timeout_s=timeout_s, quiet_s=quiet_s, label=self.id)

    def write(self, path: str, data: bytes) -> None:
        self._live(lambda: self.sandbox.filesystem.write_bytes.aio(data, path))  # creates parent dirs

    def read(self, path: str) -> bytes:
        try:
            return self._live(lambda: self.sandbox.filesystem.read_bytes.aio(path))
        except modal.exception.SandboxFilesystemNotFoundError as e:
            raise FileNotFoundError(path) from e

    def terminate(self) -> None:
        """Idempotent: terminating an ended sandbox is a no-op on Modal."""
        with contextlib.suppress(modal.exception.NotFoundError):
            self.sandbox.terminate()

    def expose(self, port: int) -> Endpoint:
        """The port's Modal tunnel (encrypted_ports at create): an open https URL, websockets too.
        Not Sandbox.create_connect_token, which needs no declaring but gates every request on a
        token (header or ?_modal_connect_token=); see box/NOTES-sessions.md."""
        tunnels = self._live(self.sandbox.tunnels.aio)
        if port not in tunnels:
            raise ValueError(f"modal provider: port {port} was not declared at launch (ports={sorted(tunnels)})")
        return Endpoint(tunnels[port].url)

    def _live(self, call: Callable[[], Awaitable[T]]) -> T:
        """call, bounded in time, with Modal's 'this sandbox has ended' errors raised as Gone. Once it
        has ended: NotFoundError ("Task has already finished", "Sandbox is unavailable"). While it
        ends: ConflictError ("Sandbox is shutting down") or a bare SandboxFilesystemError ("unexpected
        error"), which are Gone only if the sandbox then turns out to have ended. A call can also
        hang for good on a sandbox stuck ending (seen live: poll() None minutes after its entrypoint
        exited, every exec stuck in SandboxGetTaskId); past its timeout that is TimeoutError.
        On this thread, in an event loop of its own: a call past its timeout is cancelled, so nothing
        is left behind waiting on Modal (before, a daemon watchdog thread per call was)."""
        timeout_s = BOOT_TIMEOUT_S if self._booting else CALL_TIMEOUT_S
        expired = []

        async def bounded() -> T:
            async with asyncio.timeout(timeout_s) as bound:
                try:
                    return await call()
                finally:
                    expired.append(bound.expired())

        try:
            result = asyncio.run(bounded())
        except TimeoutError:
            if not expired or not expired[0]:
                raise  # the call's own TimeoutError, not this bound's
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
