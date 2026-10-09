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

A Modal owns a thread running one event loop, where every one of its calls runs (see Modal): it is
opened by its first call and must be closed by whoever made it.

    with Modal(token=ModalToken.from_config(), region="us", volumes={"/data": "kelpie-a1"}) as provider:  # volumes: {mount path: name}, created if missing
        store = ModalVolumeStore("box-sessions", provider=provider)  # a Store (box/store.py): launch(record=)
"""

from __future__ import annotations

import contextlib
import io
import math
import secrets
import threading
import tomllib
from collections.abc import AsyncIterator, Awaitable, Callable
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar

import anyio
import modal
from anyio.from_thread import BlockingPortal, start_blocking_portal

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
CREATE_TIMEOUT_S = 3600.0  # Sandbox.create, which builds the image first (a Dockerfile with CUDA builds for many minutes)
POLL_S = 0.5  # how often _ends asks a sandbox mid-shutdown whether it has finished
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


class ProviderClosed(RuntimeError):
    """This Modal was closed: it makes no more calls, and neither do its machines or stores. Never
    reopened behind the caller's back: whoever closed it owns that; a later user opens a new Modal."""


class Hung(TimeoutError):
    """A Modal call ran past its bound and was cancelled (not a TimeoutError of the call's own)."""


class Modal:
    """Owns one event loop on one thread (an anyio BlockingPortal, asyncio backend: Modal's .aio
    needs asyncio). Every Modal call made for it, its machines and its stores is a task on that loop,
    bounded by a cancel scope; a caller already inside an event loop (a Jupyter cell) is never asked
    to run one. Open on first use; close() (or leaving `with`) cancels what is pending, closes the
    client and joins the thread. Closed is final: ProviderClosed after."""

    name = "modal"

    def __init__(self, *, token: ModalToken, region: str | None, volumes: dict[str, str] | None = None) -> None:
        """region (e.g. "us"), no default: every caller chooses. None lets Modal place the sandbox
        anywhere, which once put an L4 in ap-northeast: ~330 s to start, ~390 ms per exec from
        California (vs 5 s / 66 ms in "us"). Modal bills a region-pinned sandbox at a premium."""
        self.token = token
        self.volumes = dict(volumes or {})
        self.region = region
        self._client: modal.Client | None = None  # opened on the loop by the first call that needs it
        self._app: modal.App | None = None
        self._lock = threading.Lock()  # guards the fields below (portal start, close, pumps)
        self._portal: BlockingPortal | None = None
        self._portal_cm: contextlib.AbstractContextManager[BlockingPortal] | None = None
        self._connect: anyio.Lock | None = None  # on the loop: one task opens the client and app
        self._pumps: set[Future[None]] = set()  # open streams' pump tasks: close() cancels them first
        self._closed = False

    def __enter__(self) -> Modal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        """Idempotent. Open streams end (their readers raise ProviderClosed; their commands run on
        until killed by Modal's exec timeout or the sandbox ending, since killing them is a call),
        the client closes, anything else still on the loop is cancelled, the thread is joined."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            portal, portal_cm, pumps = self._portal, self._portal_cm, list(self._pumps)
        if portal is None or portal_cm is None:
            return  # never used: no thread, no client
        for pump in pumps:
            pump.cancel()  # first, so a stream ends cancelled, not with a closed client's error
        try:
            if self._client is not None:
                portal.call(self._close_client)
        finally:
            portal.call(portal.stop, True)  # cancel_remaining: e.g. another thread's call in flight
            portal_cm.__exit__(None, None, None)  # joins the portal's thread

    async def _close_client(self) -> None:
        assert self._client is not None
        with anyio.fail_after(CALL_TIMEOUT_S):
            await self._client.__aexit__(None, None, None)  # modal.Client's own close (it has no public close())

    def _open(self) -> BlockingPortal:
        with self._lock:
            if self._closed:
                raise ProviderClosed("modal provider: closed (a Machine or store outlived the Modal it came from?)")
            if self._portal is None:
                # One owned thread, one loop, for this provider's life. A future async mode (an async
                # relay) would await these same coroutines directly on its own loop, with no portal:
                # anyio, trio-style, so the bodies here already are what it would run.
                self._portal_cm = start_blocking_portal(backend="asyncio", name=f"box-modal-{id(self):x}")
                self._portal = self._portal_cm.__enter__()
                self._connect = self._portal.call(anyio.Lock)
            return self._portal

    def _call(self, call: Callable[[], Awaitable[T]], *, timeout_s: float) -> T:
        """call() on the loop, cancelled past timeout_s (Hung). ProviderClosed if closed before or during."""
        portal = self._open()

        async def bounded() -> T:
            scope = None
            try:
                with anyio.fail_after(timeout_s) as scope:
                    return await call()
            except TimeoutError:
                if scope is not None and scope.cancelled_caught:
                    raise Hung(f"modal provider: call cancelled past its {timeout_s:.0f} s bound") from None
                raise  # the call's own TimeoutError, not this bound's

        try:
            return portal.call(bounded)
        except (CancelledError, RuntimeError) as e:  # cancelled by close(), or the portal stopped under it
            if self._closed:
                raise ProviderClosed(f"modal provider: closed during a call: {e!r}") from e
            raise

    def _start(self, pump: Callable[[], Awaitable[None]]) -> Future[None]:
        """pump as a task on the loop, unbounded (a stream's own bounds kill it): close() cancels it."""
        portal = self._open()
        with self._lock:
            if self._closed:
                raise ProviderClosed("modal provider: closed")
            future = portal.start_task_soon(pump)
            self._pumps.add(future)
        future.add_done_callback(self._pumps.discard)
        return future

    def _wait(self, call: Callable[[], Awaitable[T]]) -> T:
        """An unbounded call on the loop (a stream's next chunk), for _start's readers only."""
        try:
            return self._open().call(call)
        except (CancelledError, RuntimeError) as e:
            if self._closed:
                raise ProviderClosed(f"modal provider: closed under a stream: {e!r}") from e
            raise

    async def client(self) -> modal.Client:
        """On the loop. Opens a connection on first use: not at construction, so Modal(...) is free."""
        assert self._connect is not None
        async with self._connect:
            if self._client is None:
                self._client = await modal.Client.from_credentials.aio(self.token.id, self.token.secret)
            return self._client

    async def app(self) -> modal.App:
        """On the loop. A network call, like client."""
        client = await self.client()
        assert self._connect is not None
        async with self._connect:
            if self._app is None:
                self._app = await modal.App.lookup.aio(APP, client=client, create_if_missing=True)
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
        stores: list[ModalVolumeStore] = [m.store for m in mounts]  # type: ignore[misc] (checked above)
        modal_image, modal_gpu_ = resolve_image(image), modal_gpu(gpu)

        async def create() -> modal.Sandbox:
            client = await self.client()
            volumes = {path: modal.Volume.from_name(v, create_if_missing=True, client=client) for path, v in self.volumes.items()}
            for m, store in zip(mounts, stores, strict=True):
                volumes[f"{ROOT}/{m.path}"] = (await store.volume()).with_mount_options(sub_path=f"/{m.prefix}")
            return await modal.Sandbox.create.aio(
                *entrypoint, app=await self.app(), image=modal_image, gpu=modal_gpu_, region=self.region,
                env={**env, "BOX_ROOT": ROOT}, tags=labels, timeout=timeout_s, client=client,
                encrypted_ports=ports, volumes=volumes,
            )  # fmt: skip

        return ModalMachine(self, self._call(create, timeout_s=CREATE_TIMEOUT_S), labels, booting=True)

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
        """Running sandboxes only: Modal's list drops a sandbox once it has ended."""
        tags = {**(labels or {}), LABEL_BY: "box"}

        async def found() -> list[tuple[modal.Sandbox, dict[str, str]]]:
            app = await self.app()
            return [(s, await s.get_tags.aio()) async for s in modal.Sandbox.list.aio(app_id=app.app_id, tags=tags, client=await self.client())]

        return [ModalMachine(self, s, t) for s, t in self._call(found, timeout_s=CALL_TIMEOUT_S)]


class ModalVolumeStore:
    """A Modal Volume (v2: concurrent writers, per-file commits) as a Store. Readers see what has
    been committed. Seen live (2026-10-09, CPU sandboxes in "us", a sub_path mount): a sandbox's
    `sync <mount>` commits (~70 ms); unsynced writes commit by themselves within ~5 s, and also land
    when the sandbox is terminate()d, its entrypoint exits, or its PID 1 is SIGKILLed.
    The Volume is in the provider's workspace: whoever holds that token can read every session in it.
    Its calls run on the provider's loop, so it is usable only while that Modal is open."""

    sync_writes = True

    def __init__(self, name: str, *, provider: Modal) -> None:
        self.name = name
        self.uri = f"modal-volume://{name}"
        self.provider = provider
        self._volume: modal.Volume | None = None

    async def volume(self) -> modal.Volume:
        """On the provider's loop. A handle only (from_name is lazy): created on the first call that uses it."""
        if self._volume is None:
            self._volume = modal.Volume.from_name(self.name, version=2, create_if_missing=True, client=await self.provider.client())
        return self._volume

    def get(self, key: str) -> bytes:
        async def read() -> bytes:
            return b"".join([chunk async for chunk in (await self.volume()).read_file.aio(key)])

        return self.provider._call(read, timeout_s=CALL_TIMEOUT_S)  # FileNotFoundError if absent

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
    """A sandbox, reached through the Modal that found or made it. Never owns that Modal: once it is
    closed, every call here raises ProviderClosed (attach a new Modal to reach the sandbox again)."""

    root = ROOT

    def __init__(self, provider: Modal, sandbox: modal.Sandbox, labels: dict[str, str], *, booting: bool = False) -> None:
        self.provider = provider
        self.sandbox = sandbox
        self.id = sandbox.object_id
        self.labels = labels
        self._booting = booting  # create returns before Modal schedules it: the first call waits for that

    def exec(self, cmd: str) -> tuple[int, str, str]:
        async def run() -> tuple[int, str, str]:
            p = await self.sandbox.exec.aio("bash", "-c", cmd)
            # each of these is a round trip; together an exec costs ~1 RTT after create, not 3
            results: dict[str, object] = {}

            async def get(key: str, call: Callable[[], Awaitable[object]]) -> None:
                results[key] = await call()

            async with anyio.create_task_group() as tg:
                tg.start_soon(get, "out", p.stdout.read.aio)
                tg.start_soon(get, "err", p.stderr.read.aio)
                tg.start_soon(get, "rc", p.wait.aio)
            return results["rc"], results["out"], results["err"]  # type: ignore[return-value]

        rc, out, err = self._live(run)
        # None, -1: Modal's code for an exec it killed. 137: an exec in a sandbox mid-death (seen live
        # after `kill -9 1`: "FetchSpec failed: loading container: file does not exist"). box's own
        # execs never exit 137 on a live sandbox, so the ENDING_S wait that rules it out is rare.
        if rc in (None, -1, 137) and self._ends():
            raise Gone(f"{self.id}: sandbox ended (exit {self.sandbox.returncode}) under `{cmd}`")
        return rc, out, err

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None) -> Pumped:
        """An exec whose stdout and stderr are read as they arrive: a pump task on the provider's loop
        hands chunks through a zero-buffer channel to the reader thread Pumped owns (the loop never
        blocks on a slow caller: backpressure is the pump awaiting its send). close() cancels the
        pump, which a sync Modal call could not be. Modal has no kill for an exec: close() kills it by
        the pid it noted, in another exec, and Modal ends it anyway at timeout_s (exec's own
        timeout). An open exec does not keep the sandbox up: it ends (rc 137) when the supervisor
        exits, seen live; and it is not a connection to an exposed port, so the supervisor never
        counts it against idleness."""
        self.provider._open()  # ProviderClosed now, not at the stream's first chunk
        pid_file = f"/tmp/box-stream-{secrets.token_hex(6)}.pid"
        pumping: list[Future[None]] = []  # the pump, once started
        rc: list[int | None] = []

        def read(emit: Emit) -> None:
            send, receive = anyio.create_memory_object_stream[tuple[str, bytes]](0)

            async def pump() -> None:
                async with send:  # however the pump ends, the reader's next receive sees EndOfStream
                    p = await self.sandbox.exec.aio("bash", "-c", with_pid_file(cmd, pid_file), text=False, timeout=math.ceil(timeout_s))

                    async def drain(name: str, source: AsyncIterator[bytes]) -> None:
                        async for data in source:
                            await send.send((name, data))  # waits while the reader is behind

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
                        emit(name, data)  # raises Closed once the stream is closed
                future.result()  # the pump's own end: its error, or cancelled
            except CancelledError:
                if self.provider.closed:
                    raise ProviderClosed(f"{self.id}: modal provider closed under a stream of `{cmd}`") from None
                raise Closed from None  # cancelled by kill(): the stream was closed
            except (modal.exception.NotFoundError, modal.exception.SandboxTerminatedError) as e:
                raise Gone(f"{self.id}: {e}") from e
            finally:
                future.cancel()  # a no-op once it has ended

        def kill() -> None:
            try:
                with contextlib.suppress(Gone):
                    self.exec(kill_pid_file(pid_file))
            finally:
                for future in pumping:  # if the pump is still waiting on Modal, stop waiting
                    future.cancel()

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
            self.provider._call(self.sandbox.terminate.aio, timeout_s=CALL_TIMEOUT_S)

    def gone(self) -> bool:
        """Modal has a return code for the sandbox (poll(): it has finished, by exiting or by
        terminate), or no longer knows it (NotFoundError, as Gone). Bounded as every call is (_live)."""
        try:
            return self._live(self.sandbox.poll.aio) is not None
        except Gone:
            return True

    def expose(self, port: int) -> Endpoint:
        """The port's Modal tunnel (encrypted_ports at create): an open https URL, websockets too.
        Not Sandbox.create_connect_token, which needs no declaring but gates every request on a
        token (header or ?_modal_connect_token=); see box/NOTES-sessions.md."""
        tunnels = self._live(self.sandbox.tunnels.aio)
        if port not in tunnels:
            raise ValueError(f"modal provider: port {port} was not declared at launch (ports={sorted(tunnels)})")
        return Endpoint(tunnels[port].url)

    def _live(self, call: Callable[[], Awaitable[T]]) -> T:
        """call on the provider's loop, bounded in time, with Modal's 'this sandbox has ended' errors
        raised as Gone. Once it has ended: NotFoundError ("Task has already finished", "Sandbox is
        unavailable"). While it ends: ConflictError ("Sandbox is shutting down") or a bare
        SandboxFilesystemError ("unexpected error"), which are Gone only if the sandbox then turns out
        to have ended. A call can also hang for good on a sandbox stuck ending (seen live: poll() None
        minutes after its entrypoint exited, every exec stuck in SandboxGetTaskId); past its timeout
        it is cancelled (its cancel scope), so nothing is left waiting on Modal, and it is TimeoutError."""
        timeout_s = BOOT_TIMEOUT_S if self._booting else CALL_TIMEOUT_S
        try:
            result = self.provider._call(call, timeout_s=timeout_s)
        except Hung:
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

    def _ends(self) -> bool:
        """Whether Modal reports the sandbox finished within ENDING_S (polled on the loop)."""
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
