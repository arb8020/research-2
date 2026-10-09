"""The local provider: a "machine" is a directory on this computer with the supervisor running in it.

It exists so the SDK and the supervisor can be run and tested end to end without a cloud: same
entrypoint, same files, same exec, and like a cloud machine, nothing is reachable (Gone) once the
supervisor has exited. What it cannot be is a separate computer: `gpu` and `image`
are refused, and on macOS (no PR_SET_PDEATHSIG) a job outlives a supervisor killed with SIGKILL.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import subprocess
from pathlib import Path

from box.providers.pump import JOIN_S, Pumped, pipe_reader
from box.sdk import LABEL_BY, Endpoint, Gone
from box.store import DirStore, Mount

BASE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "box" / "local"


class Local:
    name = "local"

    def __init__(self, base: Path = BASE) -> None:
        self.base = base

    def launch(  # noqa: PLR0913 (keyword-only: what a machine is made with)
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> LocalMachine:  # fmt: skip
        """mounts: DirStores only, as symlinks (a local machine shares this computer's disk)."""
        del timeout_s  # the supervisor's deadline is the only clock here; a VM provider enforces this
        if gpu or image:
            raise NotImplementedError(f"local provider: no gpu/image (got gpu={gpu!r}, image={image!r})")
        if foreign := [m.store.uri for m in mounts if not isinstance(m.store, DirStore)]:
            raise ValueError(f"local provider: mounts only a DirStore (got {foreign})")
        m = LocalMachine(self.base / f"local-{secrets.token_hex(4)}")
        m.dir.mkdir(parents=True)
        for mount in mounts:
            link = Path(m.root, mount.path)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(mount.store.dir(mount.prefix), target_is_directory=True)
        (m.dir / "labels.json").write_text(json.dumps(labels))
        (m.dir / "ports.json").write_text(json.dumps(ports))
        with (m.dir / "supervisor.log").open("wb") as log:
            proc = subprocess.Popen(
                entrypoint, cwd=m.dir, env={**os.environ, **env, "BOX_ROOT": m.root},
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            )  # fmt: skip
        (m.dir / "pid").write_text(str(proc.pid))
        return m

    def get(self, machine_id: str) -> LocalMachine:
        m = LocalMachine(self.base / machine_id)
        if not (m.dir / "labels.json").exists():
            raise LookupError(f"local provider: no machine {machine_id}")
        return m

    def list(self, labels: dict[str, str] | None = None) -> list[LocalMachine]:
        want = {**(labels or {}), LABEL_BY: "box"}
        found = [LocalMachine(d) for d in sorted(self.base.glob("local-*"))] if self.base.exists() else []
        return [m for m in found if m.alive() and want.items() <= m.labels.items()]


class LocalMachine:
    def __init__(self, path: Path) -> None:
        self.dir = path
        self.id = path.name
        self.root = str(path / "box")

    @property
    def labels(self) -> dict[str, str]:
        return json.loads((self.dir / "labels.json").read_text())

    def exec(self, cmd: str) -> tuple[int, str, str]:
        self._check_alive()
        done = subprocess.run(["bash", "-c", cmd], cwd=self.dir, capture_output=True, text=True, check=False)
        return done.returncode, done.stdout, done.stderr

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None) -> Pumped:
        """cmd's output as it arrives: two pipes, a reader thread each. Its own process group, so a
        close kills all of it. Gone, while it runs too, once the supervisor has exited (nothing on
        this computer ends the command with it, as a cloud machine's end does)."""
        self._check_alive()
        proc = subprocess.Popen(
            ["bash", "-c", cmd], cwd=self.dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True,
        )  # fmt: skip

        def kill() -> None:
            _killpg(proc.pid)
            proc.wait(JOIN_S)

        return Pumped(
            [pipe_reader("stdout", proc.stdout), pipe_reader("stderr", proc.stderr)], kill=kill, wait=lambda: proc.wait(JOIN_S),
            timeout_s=timeout_s, quiet_s=quiet_s, check=self._check_alive, label=self.id,
        )  # fmt: skip

    def write(self, path: str, data: bytes) -> None:
        self._check_alive()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)

    def read(self, path: str) -> bytes:
        self._check_alive()
        return Path(path).read_bytes()

    def expose(self, port: int) -> Endpoint:
        """This computer's own port: a local machine shares its network. Declared ports only, as
        on a cloud machine."""
        self._check_alive()
        declared = json.loads((self.dir / "ports.json").read_text())
        if port not in declared:
            raise ValueError(f"local provider: port {port} was not declared at launch (ports={declared})")
        return Endpoint(f"http://127.0.0.1:{port}")

    def _check_alive(self) -> None:
        """Like a real machine: once its supervisor has exited, it and its files are gone."""
        if not self.alive():
            raise Gone(self.id)

    def alive(self) -> bool:
        """The supervisor is running (a zombie, exited but not yet reaped by its parent, is not)."""
        try:
            pid = (self.dir / "pid").read_text()
        except FileNotFoundError:
            return False
        stat = subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True).stdout.strip()
        return bool(stat) and not stat.startswith("Z")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LocalMachine) and other.dir == self.dir

    def terminate(self) -> None:
        """Like a VM's terminate: every process on the machine dies, no hooks run."""
        for status in Path(self.root).glob("*/*/status.json"):  # jobs and services
            _killpg(json.loads(status.read_text()).get("pgid"))
        _killpg(int((self.dir / "pid").read_text()))


def _killpg(pgid: int | None) -> None:
    if pgid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
