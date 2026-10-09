from __future__ import annotations

import contextlib
import io
import math
import secrets
import shlex
import sys
import threading
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import anyio
import grpclib.exceptions
import modal
from anyio.from_thread import BlockingPortal, start_blocking_portal

from box import gpus
from box.providers.pump import MAX_SEND_BYTES, Closed, Emit, Pumped, kill_pid_file, with_pid_file
from box.sdk import LABEL_BY, LABEL_NAME, LABEL_PORTS, Dropped, Endpoint, Gone, NameTaken, Refused, declared_ports
from box.store import Mount

APP = "box"
ROOT = "/box"
WORK = "/work"
MAX_TIMEOUT_S = 24 * 3600  # Modal refuses a sandbox timeout over 24 h
DEFAULT_PYTHON = "3.13"
T = TypeVar("T")
ENDING_S = 10.0
BOOT_TIMEOUT_S = 900.0
CALL_TIMEOUT_S = 60.0  # MUST KILL: one 60 s bound for every call after boot, write/read of a put/get tarball of any size included; size the bound by payload
CREATE_TIMEOUT_S = 3600.0
POLL_S = 0.5
MODAL_TOML = Path.home() / ".modal.toml"
SNAPSHOT = "modal-snapshot:"
SNAPSHOT_TIMEOUT_S = 900.0
STREAM_DROPS = (modal.exception.ConnectionError, grpclib.exceptions.StreamTerminatedError, OSError)


@dataclass(frozen=True)
class ModalToken:
    id: str = field(repr=False)
    secret: str = field(repr=False)

    @classmethod
    def from_config(cls, path: Path = MODAL_TOML) -> ModalToken:
        profiles = tomllib.loads(path.read_text())
        active = [name for name, p in profiles.items() if isinstance(p, dict) and p.get("active") is True]
        if len(active) != 1:
            raise Refused(f"{path}: {len(active)} active profiles {active}; want exactly one (`modal profile activate`)")
        return cls.from_profile(active[0], path)

    @classmethod
    def from_profile(cls, name: str, path: Path = MODAL_TOML) -> ModalToken:
        profile = tomllib.loads(path.read_text()).get(name)
        if not (isinstance(profile, dict) and isinstance(profile.get("token_id"), str) and isinstance(profile.get("token_secret"), str)):
            raise Refused(f"{path}: no profile {name!r} with token_id/token_secret")
        return cls(profile["token_id"], profile["token_secret"])


class ProviderClosed(RuntimeError):
    pass


class Hung(TimeoutError):
    pass


class Modal:
    name = "modal"

    def __init__(self, *, token: ModalToken, region: str | None, volumes: dict[str, str] | None = None) -> None:
        self.token = token
        self.volumes = dict(volumes or {})
        self.region = region
        self._client: modal.Client | None = None
        self._app: modal.App | None = None
        self._lock = threading.Lock()
        self._portal: BlockingPortal | None = None
        self._portal_cm: contextlib.AbstractContextManager[BlockingPortal] | None = None
        self._connect: anyio.Lock | None = None
        self._pumps: set[Future[None]] = set()
        self._closed = False

    def __enter__(self) -> Modal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            portal, portal_cm, pumps = self._portal, self._portal_cm, list(self._pumps)
        if portal is None or portal_cm is None:
            return
        for pump in pumps:
            pump.cancel()
        try:
            if self._client is not None:
                portal.call(self._close_client)
        finally:
            portal.call(portal.stop, True)
            portal_cm.__exit__(None, None, None)

    async def _close_client(self) -> None:
        assert self._client is not None
        with anyio.fail_after(CALL_TIMEOUT_S):
            await self._client.__aexit__(None, None, None)  # modal.Client has no public close()

    def _open(self) -> BlockingPortal:
        with self._lock:
            if self._closed:
                raise ProviderClosed("modal provider: closed (a Machine or store outlived the Modal it came from?)")
            if self._portal is None:
                # Modal's .aio API needs asyncio
                self._portal_cm = start_blocking_portal(backend="asyncio", name=f"box-modal-{id(self):x}")
                self._portal = self._portal_cm.__enter__()
                self._connect = self._portal.call(anyio.Lock)
            return self._portal

    def _call(self, call: Callable[[], Awaitable[T]], *, timeout_s: float) -> T:
        portal = self._open()

        async def bounded() -> T:
            scope = None
            try:
                with anyio.fail_after(timeout_s) as scope:
                    return await call()
            except TimeoutError:
                if scope is not None and scope.cancelled_caught:
                    raise Hung(f"modal provider: call cancelled past its {timeout_s:.0f} s bound") from None
                raise

        try:
            return portal.call(bounded)
        except (CancelledError, RuntimeError) as e:
            if self._closed:
                raise ProviderClosed(f"modal provider: closed during a call: {e!r}") from e
            raise

    def _start(self, pump: Callable[[], Awaitable[None]]) -> Future[None]:
        portal = self._open()
        with self._lock:
            if self._closed:
                raise ProviderClosed("modal provider: closed")
            future = portal.start_task_soon(pump)
            self._pumps.add(future)
        future.add_done_callback(self._pumps.discard)
        return future

    def _wait(self, call: Callable[[], Awaitable[T]]) -> T:
        try:
            return self._open().call(call)
        except (CancelledError, RuntimeError) as e:
            if self._closed:
                raise ProviderClosed(f"modal provider: closed under a stream: {e!r}") from e
            raise

    async def client(self) -> modal.Client:
        assert self._connect is not None
        async with self._connect:
            if self._client is None:
                self._client = await modal.Client.from_credentials.aio(self.token.id, self.token.secret)
            return self._client

    async def app(self) -> modal.App:
        client = await self.client()
        assert self._connect is not None
        async with self._connect:
            if self._app is None:
                self._app = await modal.App.lookup.aio(APP, client=client, create_if_missing=True)
            return self._app

    def launch(  # noqa: PLR0913
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> ModalMachine:  # fmt: skip
        if foreign := [m.store.uri for m in mounts if not isinstance(m.store, ModalVolumeStore)]:
            raise Refused(f"modal provider: mounts only a ModalVolumeStore (got {foreign})")
        if timeout_s > MAX_TIMEOUT_S:
            raise Refused(f"modal provider: timeout_s={timeout_s} past Modal's {MAX_TIMEOUT_S} s cap (a ceiling over {MAX_TIMEOUT_S - 600} s)")
        stores: list[ModalVolumeStore] = [m.store for m in mounts]  # MUST KILL: narrowed by the isinstance check above, which the checker can't see (was type: ignore[misc]); filter with a TypeGuard
        snapshot = image.removeprefix(SNAPSHOT) if image and image.startswith(SNAPSHOT) else None
        modal_image, modal_gpu_ = None if snapshot else resolve_image(image), modal_gpu(gpu)

        async def create() -> modal.Sandbox:
            client = await self.client()
            nonlocal modal_image
            if snapshot is not None:  # Image.from_id is lazy: an unknown id fails at Sandbox.create (NotFoundError)
                modal_image = modal.Image.from_id(snapshot, client=client)
            volumes = {path: modal.Volume.from_name(v, create_if_missing=True, client=client) for path, v in self.volumes.items()}
            for m, store in zip(mounts, stores, strict=True):
                volumes[f"{ROOT}/{m.path}"] = (await store.volume()).with_mount_options(sub_path=f"/{m.prefix}")
            return await modal.Sandbox.create.aio(
                *entrypoint, app=await self.app(), name=labels.get(LABEL_NAME), image=modal_image, gpu=modal_gpu_, region=self.region,
                env={**env, "BOX_ROOT": ROOT}, tags=labels, timeout=timeout_s, client=client,
                encrypted_ports=ports, volumes=volumes,
            )  # fmt: skip

        try:
            sandbox = self._call(create, timeout_s=CREATE_TIMEOUT_S)
        except modal.exception.AlreadyExistsError as e:
            raise NameTaken(f"modal provider: a running sandbox in app {APP!r} is named {labels[LABEL_NAME]!r}") from e
        except modal.exception.NotFoundError as e:
            if snapshot is None:
                raise
            raise LookupError(f"modal provider: no snapshot image {snapshot} (past its ttl, or deleted): {e}") from e
        return ModalMachine(self, sandbox, labels, booting=True)

    def snapshot(self, machine: ModalMachine, *, ttl_s: int) -> str:
        async def snap() -> str:
            image = await machine.sandbox.snapshot_filesystem.aio(timeout=int(SNAPSHOT_TIMEOUT_S), ttl=ttl_s)
            return image.object_id

        return SNAPSHOT + self._call(snap, timeout_s=SNAPSHOT_TIMEOUT_S + CALL_TIMEOUT_S)

    def get(self, machine_id: str) -> ModalMachine:
        async def lookup() -> tuple[modal.Sandbox, dict[str, str]]:
            sandbox = await modal.Sandbox.from_id.aio(machine_id, client=await self.client())
            return sandbox, await sandbox.get_tags.aio()

        try:
            sandbox, tags = self._call(lookup, timeout_s=CALL_TIMEOUT_S)
        except (modal.exception.NotFoundError, modal.exception.InvalidError) as e:
            raise LookupError(f"modal provider: no sandbox {machine_id}: {e}") from e
        if tags.get(LABEL_BY) != "box":
            raise LookupError(f"modal provider: {machine_id} was not launched by box (no {LABEL_BY}=box tag)")
        return ModalMachine(self, sandbox, tags)

    def list(self, labels: dict[str, str] | None = None) -> list[ModalMachine]:
        tags = {**(labels or {}), LABEL_BY: "box"}

        async def found() -> list[tuple[modal.Sandbox, dict[str, str]]]:
            app = await self.app()
            return [(s, await s.get_tags.aio()) async for s in modal.Sandbox.list.aio(app_id=app.app_id, tags=tags, client=await self.client())]

        return [ModalMachine(self, s, t) for s, t in self._call(found, timeout_s=CALL_TIMEOUT_S)]


class ModalVolumeStore:
    # a Modal Volume v2 commits a sandbox's writes on `sync <mount>`
    sync_writes = True

    def __init__(self, name: str, *, provider: Modal) -> None:
        self.name = name
        self.uri = f"modal-volume://{name}"
        self.provider = provider
        self._volume: modal.Volume | None = None

    async def volume(self) -> modal.Volume:
        if self._volume is None:
            self._volume = modal.Volume.from_name(self.name, version=2, create_if_missing=True, client=await self.provider.client())
        return self._volume

    def get(self, key: str) -> bytes:
        async def read() -> bytes:
            return b"".join([chunk async for chunk in (await self.volume()).read_file.aio(key)])

        return self.provider._call(read, timeout_s=CALL_TIMEOUT_S)

    def list(self, prefix: str) -> list[str]:
        async def entries() -> list[modal.volume.FileEntry]:
            return await (await self.volume()).listdir.aio(prefix, recursive=True)

        try:
            found = self.provider._call(entries, timeout_s=CALL_TIMEOUT_S)
        except modal.exception.NotFoundError:
            return []
        files = [e.path.lstrip("/") for e in found if e.type == modal.volume.FileEntryType.FILE]
        return sorted(f for f in files if not f.endswith(".tmp"))

    def put(self, key: str, data: bytes) -> None:
        async def upload() -> None:
            async with (await self.volume()).batch_upload(force=True) as batch:
                batch.put_file(io.BytesIO(data), key)

        self.provider._call(upload, timeout_s=CALL_TIMEOUT_S)


class ModalMachine:
    root = ROOT
    work = WORK

    def __init__(self, provider: Modal, sandbox: modal.Sandbox, labels: dict[str, str], *, booting: bool = False) -> None:
        self.provider = provider
        self.sandbox = sandbox
        self.id = sandbox.object_id
        self.labels = labels
        self._booting = booting

    def exec(self, cmd: str) -> tuple[int, str, str]:
        async def run() -> tuple[int, str, str]:
            p = await self.sandbox.exec.aio("bash", "-c", cmd)
            results: dict[str, object] = {}  # MUST KILL: dict[str, object] loses the types (was type: ignore[return-value]); gather into typed variables

            async def get(key: str, call: Callable[[], Awaitable[object]]) -> None:
                results[key] = await call()

            async with anyio.create_task_group() as tg:
                tg.start_soon(get, "out", p.stdout.read.aio)
                tg.start_soon(get, "err", p.stderr.read.aio)
                tg.start_soon(get, "rc", p.wait.aio)
            return results["rc"], results["out"], results["err"]

        rc, out, err = self._live(run)
        # Modal: rc None or -1 is an exec it killed; 137 is an exec in a sandbox mid-death
        if rc in (None, -1, 137) and self._ends():
            raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under `{cmd}`")
        return rc, out, err

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None, pty: bool = False) -> Pumped:
        self.provider._open()
        pid_file = f"/tmp/box-stream-{secrets.token_hex(6)}.pid"
        pumping: list[Future[None]] = []
        rc: list[int | None] = []
        process: list[modal.container_process.ContainerProcess] = []
        started = threading.Event()

        def read(emit: Emit) -> None:
            send, receive = anyio.create_memory_object_stream[tuple[str, bytes]](0)

            async def pump() -> None:
                async with send:
                    try:
                        p = await self.sandbox.exec.aio("bash", "-c", with_pid_file(cmd, pid_file), text=False, timeout=math.ceil(timeout_s), **({"pty": True} if pty else {}))
                        process.append(p)
                    finally:
                        started.set()

                    async def drain(name: str, source: AsyncIterator[bytes]) -> None:
                        async for data in source:
                            await send.send((name, data))

                    async with anyio.create_task_group() as tg:
                        tg.start_soon(drain, "stdout", p.stdout)
                        tg.start_soon(drain, "stderr", p.stderr)
                    rc.append(await p.wait.aio())

            future = self.provider._start(pump)
            pumping.append(future)
            try:
                with receive:
                    while True:
                        try:
                            name, data = self.provider._wait(receive.receive)
                        except anyio.EndOfStream:
                            break
                        emit(name, data)
                future.result()
            except CancelledError:
                if self.provider.closed:
                    raise ProviderClosed(f"{self.id}: modal provider closed under a stream of `{cmd}`") from None
                raise Closed from None
            except (modal.exception.NotFoundError, modal.exception.SandboxTerminatedError) as e:
                raise Gone(f"{self.id}: {e}") from e
            except STREAM_DROPS as e:
                raise Dropped(f"{self.id}: the stream of `{cmd}` dropped: {e!r}") from e
            finally:
                future.cancel()

        def kill() -> None:
            try:
                with contextlib.suppress(Gone):
                    self.exec(kill_pid_file(pid_file))
            finally:
                for future in pumping:
                    future.cancel()

        def wait() -> int | None:
            code = rc[0] if rc else None
            if code != 0 and self._ends():
                raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under a stream of `{cmd}`")
            return code

        def write(data: bytes) -> None:
            assert len(data) <= MAX_SEND_BYTES, len(data)
            if not started.wait(CALL_TIMEOUT_S) or not process:
                raise TimeoutError(f"{self.id}: the stream's exec did not start in {CALL_TIMEOUT_S:.0f} s")

            async def to_stdin() -> None:
                process[0].stdin.write(data)
                await process[0].stdin.drain.aio()

            self._live(to_stdin)

        return Pumped([read], kill=kill, wait=wait, timeout_s=timeout_s, quiet_s=quiet_s, label=self.id, send=write if pty else None)

    def shell_argv(self, cmd: str) -> list[str]:  # MUST KILL: runs `modal shell` on the CLI's ambient credentials, not this provider's token (maybe another workspace); pass the token in the child's env
        return [sys.executable, "-m", "modal", "shell", self.id, "--cmd", shlex.join(["bash", "-c", cmd])]

    def write(self, path: str, data: bytes) -> None:
        self._live(lambda: self.sandbox.filesystem.write_bytes.aio(data, path))

    def read(self, path: str) -> bytes:
        try:
            return self._live(lambda: self.sandbox.filesystem.read_bytes.aio(path))
        except modal.exception.SandboxFilesystemNotFoundError as e:
            raise FileNotFoundError(path) from e

    def terminate(self) -> None:
        with contextlib.suppress(modal.exception.NotFoundError):
            self.provider._call(self.sandbox.terminate.aio, timeout_s=CALL_TIMEOUT_S)

    def gone(self) -> bool:
        try:
            return self._live(self.sandbox.poll.aio) is not None
        except Gone:
            return True

    def expose(self, port: int) -> Endpoint:  # MUST KILL: falls back to tunnels() for sandboxes from before LABEL_PORTS; drop the back-compat branch
        declared = declared_ports(self.labels) if LABEL_PORTS in self.labels else tuple(self._live(self.sandbox.tunnels.aio))
        if port in declared:
            tunnels = self._live(self.sandbox.tunnels.aio)
            return Endpoint(tunnels[port].url)
        creds = self._live(lambda: self.sandbox.create_connect_token.aio(port=port))
        return Endpoint(creds.url.rstrip("/"), {"Authorization": f"Bearer {creds.token}"})

    def _live(self, call: Callable[[], Awaitable[T]]) -> T:
        timeout_s = BOOT_TIMEOUT_S if self._booting else CALL_TIMEOUT_S
        try:
            result = self.provider._call(call, timeout_s=timeout_s)
        except Hung:
            if self._ends():
                raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode})") from None
            raise TimeoutError(f"{self.id}: Modal call hung for {timeout_s:.0f} s; sandbox still reports running") from None
        except (modal.exception.NotFoundError, modal.exception.SandboxTerminatedError) as e:
            raise Gone(f"{self.id}: {e}") from e
        except modal.exception.ConnectionError as e:
            raise Dropped(f"{self.id}: {e}") from e
        # a sandbox that is ending raises a bare ConflictError or SandboxFilesystemError
        except (modal.exception.ConflictError, modal.exception.SandboxFilesystemError) as e:
            if type(e) in (modal.exception.ConflictError, modal.exception.SandboxFilesystemError) and self._ends():
                raise Gone(f"{self.id}: {e}") from e
            raise
        self._booting = False
        return result

    def _ends(self) -> bool:
        within_s = ENDING_S

        async def ended() -> bool:
            with anyio.move_on_after(within_s):
                while await self.sandbox.poll.aio() is None:
                    await anyio.sleep(POLL_S)
                return True
            return False

        return self.provider._call(ended, timeout_s=within_s + CALL_TIMEOUT_S)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ModalMachine) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)


def modal_gpu(gpu: str | None) -> str | None:
    if gpu is None:
        return None
    name, _, count = gpu.partition(":")
    modal_id = gpus.provider_id(gpus.lookup(name), "modal")
    if modal_id is None:
        raise Refused(f"modal provider: Modal does not rent {name!r}")
    return f"{modal_id}:{count}" if count else modal_id


def resolve_image(image: str | None) -> modal.Image:  # MUST KILL: image is a str sniffed by suffix (Dockerfile path vs OCI ref), and by prefix (SNAPSHOT) in launch; give image a typed union
    if image is None:
        return modal.Image.debian_slim(python_version=DEFAULT_PYTHON)
    if image.lower().endswith("dockerfile"):
        return modal.Image.from_dockerfile(image, context_dir=Path(image).parent)
    return modal.Image.from_registry(image)
