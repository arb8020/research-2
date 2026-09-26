"""Core types for box — Offering, ExecResult, Mount, Job, Box, Volume, Provider.

The protocols are the whole SDK: `box` (box/cli.py) is sugar over them, and nothing above this
file names a provider. What a provider cannot do it refuses with NotImplementedError naming the
missing piece, never with a silent approximation.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


class Status(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    TERMINATED = "terminated"
    FAILED = "failed"


@dataclass(frozen=True)
class Offering:
    """An available GPU configuration from a provider."""

    provider: str
    id: str
    gpu_model: str
    gpu_count: int
    gpu_memory_gb: int  # per GPU
    price_hr: float | None  # USD per hour, total
    region: str = ""


@dataclass
class ExecResult:
    """Result of running a command on a Box."""

    stdout: str
    stderr: str
    returncode: int


@dataclass(frozen=True)
class Mount:
    """A local directory mounted into the box at launch, minus `ignore` (globs relative to it)."""

    local: str
    ignore: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogLine:
    stream: Literal["stdout", "stderr"]
    text: str  # with its newline


class Job(Protocol):
    """The one command a box was spawned with, detached from the process that spawned it: its
    output and exit status are kept by the provider, and any process can reattach with
    `provider.get(box_id).job()`. The box ends when the job does."""

    def logs(self, *, follow: bool) -> Iterator[LogLine]:
        """The job's output from its first line. follow=True streams until the job exits;
        follow=False returns what exists now (the whole log, once the job has exited)."""
        ...

    def poll(self) -> int | None:
        """The exit status, or None while it runs."""
        ...

    def wait(self) -> int:
        """Block until the job exits; its exit status."""
        ...

    def kill(self) -> None:
        """Stop the job (and so the box). Idempotent."""
        ...


class Box(Protocol):
    """A running machine you can use. Created by Provider.launch(), or reattached by
    Provider.get() from another process."""

    provider_id: str
    status: Status
    offering: Offering
    labels: dict[str, str]  # set at launch; how a later process tells whose box this is

    def wait(self, timeout: float = 900.0) -> None:
        """Block until the box is ready for exec. Raises on failure/timeout."""
        ...

    def exec(
        self,
        cmd: str,
        *,
        env: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run a command on the box. env is per-command, explicit, not ambient.
        stream=True also tees output to the local terminal as it arrives; timeout is seconds."""
        ...

    def upload(self, local: str, remote: str) -> None:
        """Upload a local file or directory to the box."""
        ...

    def download(self, remote: str, local: str) -> None:
        """Download a file or directory from the box."""
        ...

    def terminate(self) -> None:
        """Terminate the box. Idempotent."""
        ...

    def spawn(self, cmd: str, *, env: dict[str, str] | None = None, timeout: int | None = None) -> Job:
        """Start `cmd` (bash) as the box's job and return without waiting. At most once per box.
        timeout (seconds) kills it with status 124."""
        ...

    def job(self) -> Job:
        """The job spawned on this box, from any process."""
        ...


@dataclass(frozen=True)
class VolumeEntry:
    path: str  # relative to the volume root
    mtime: float  # unix seconds
    is_dir: bool


class Volume(Protocol):
    """A provider's persistent volume, by name, from outside any box."""

    name: str

    def ls(self, path: str, *, recursive: bool = False) -> list[VolumeEntry]: ...

    def read(self, path: str) -> bytes: ...

    def rm(self, path: str) -> None:
        """Remove a file or directory tree."""
        ...


class Provider(Protocol):
    """Structural interface for a GPU cloud provider."""

    name: str

    def search(
        self,
        *,
        gpu_model: str | None = None,
        gpu_count: int = 1,
    ) -> list[Offering]: ...

    def launch(self, offering: Offering, **kwargs) -> Box:
        """Launch a box from an offering.

        Providers accept these optional kwargs (lowered to provider-specific
        primitives):

            image:   str | None — environment image. Dockerfile path (built with
                     its own directory as context), OCI ref, or provider-native
                     name. None = provider default.
            mounts:  {remote_path: local_dir | Mount} — code. Swapped every launch.
            volumes: {name: mount_path} — data. Persistent across launches.
            setup:   str | None — shell script path (in the box) to run once
                     after image+mounts+volumes are ready.
            resume:  str | None — shell script path stored on the box for the
                     caller to exec on subsequent wakes.
            labels:  {key: value} — kept with the box; read back by list()/get().
            timeout: int — seconds the box may live at most.
        """
        ...

    def list(self) -> list[Box]:
        """Running boxes this provider launched through box (any process, any caller)."""
        ...

    def get(self, box_id: str) -> Box:
        """Reattach to a box by id. Raises LookupError for an id box did not launch."""
        ...

    def volumes(self) -> list[tuple[str, float]]:
        """(name, created unix seconds) of every volume on the account."""
        ...

    def volume(self, name: str) -> Volume: ...

    def delete_volume(self, name: str) -> None: ...
