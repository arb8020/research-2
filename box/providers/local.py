"""The local provider: a "machine" is a directory on this computer with the supervisor running in it.

It exists so the SDK and the supervisor can be run and tested end to end without a cloud: same
entrypoint, same files, same exec, and like a cloud machine, nothing is reachable (Gone) once the
supervisor has exited. What it cannot be is a separate computer: `gpu` and `image`
are refused, and on macOS (no PR_SET_PDEATHSIG) a job outlives a supervisor killed with SIGKILL.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import shlex
import signal
import subprocess
import termios
from pathlib import Path

from box.providers.pump import JOIN_S, Pty, Pumped, pipe_reader
from box.sdk import LABEL_BY, LABEL_NAME, Endpoint, Gone, NameTaken
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
        del timeout_s  # the supervisor's ceiling is the only clock here; a VM provider enforces this
        del ports  # every port of this computer is reachable (expose): nothing to declare
        if gpu or image:
            raise NotImplementedError(f"local provider: no gpu/image (got gpu={gpu!r}, image={image!r})")
        if foreign := [m.store.uri for m in mounts if not isinstance(m.store, DirStore)]:
            raise ValueError(f"local provider: mounts only a DirStore (got {foreign})")
        self.base.mkdir(parents=True, exist_ok=True)
        # A name is unique among live machines, race-free on this computer: the check and the launch
        # happen under one lock, and a launched machine is live (its labels and pid written) before it
        # is released. Not across computers: local machines are this computer's alone.
        with (self.base / "names.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # released when the file closes
            if LABEL_NAME in labels and self.list({LABEL_NAME: labels[LABEL_NAME]}):
                raise NameTaken(f"local provider: a live machine is named {labels[LABEL_NAME]!r}")
            return self._launch(entrypoint, env, labels, mounts)

    def _launch(self, entrypoint: list[str], env: dict[str, str], labels: dict[str, str], mounts: list[Mount]) -> LocalMachine:
        m = LocalMachine(self.base / f"local-{secrets.token_hex(4)}")
        m.dir.mkdir(parents=True)
        for mount in mounts:
            link = Path(m.root, mount.path)
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(mount.store.dir(mount.prefix), target_is_directory=True)
        (m.dir / "labels.json").write_text(json.dumps(labels))
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

    def close(self) -> None:
        """Holds nothing open: its machines are directories and processes, reachable after."""


class LocalMachine:
    def __init__(self, path: Path) -> None:
        self.dir = path
        self.id = path.name
        self.root = str(path / "box")
        self.work = str(path / "work")

    @property
    def labels(self) -> dict[str, str]:
        return json.loads((self.dir / "labels.json").read_text())

    def exec(self, cmd: str) -> tuple[int, str, str]:
        self._check_alive()
        done = subprocess.run(["bash", "-c", cmd], cwd=self.dir, capture_output=True, text=True, check=False)
        return done.returncode, done.stdout, done.stderr

    def stream(self, cmd: str, *, timeout_s: float, quiet_s: float | None = None, pty: bool = False) -> Pumped:
        """cmd's output as it arrives: two pipes, a reader thread each; or, pty=True, a new pty that
        is its controlling terminal (b"\x03" written to it is a SIGINT to its foreground group, as
        on a cloud machine's pty), one reader. Its own process group, so a close kills all of it.
        Gone, while it runs too, once the supervisor has exited (nothing on this computer ends the
        command with it, as a cloud machine's end does). rc: a signal's death is the shell's 128+N,
        as Modal and ssh report it."""
        self._check_alive()
        if pty:
            master, slave = os.openpty()
            try:
                proc = subprocess.Popen(
                    ["bash", "-c", cmd], cwd=self.dir, stdin=slave, stdout=slave, stderr=slave,
                    start_new_session=True, preexec_fn=_take_terminal,
                )  # fmt: skip
            except BaseException:
                os.close(master)
                raise
            finally:
                os.close(slave)  # the child holds it now: the master reads its end once the child side closes
            terminal = Pty(master)
            readers, send = [terminal.reader()], terminal.send
        else:
            proc = subprocess.Popen(
                ["bash", "-c", cmd], cwd=self.dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )  # fmt: skip
            terminal, readers, send = None, [pipe_reader("stdout", proc.stdout), pipe_reader("stderr", proc.stderr)], None

        def kill() -> None:
            _killpg(proc.pid)
            if terminal is not None:
                terminal.stop.set()  # a process outside the group (setsid) may still hold the terminal
            proc.wait(JOIN_S)

        def wait() -> int:
            rc = proc.wait(JOIN_S)
            return rc if rc >= 0 else 128 - rc

        return Pumped(
            readers, kill=kill, wait=wait, timeout_s=timeout_s, quiet_s=quiet_s, check=self._check_alive, label=self.id, send=send,
        )  # fmt: skip

    def shell_argv(self, cmd: str) -> list[str]:
        """bash here, in the machine's directory: this computer is the machine."""
        self._check_alive()
        return ["bash", "-c", f"cd {shlex.quote(str(self.dir))} && {cmd}"]

    def write(self, path: str, data: bytes) -> None:
        self._check_alive()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)

    def read(self, path: str) -> bytes:
        self._check_alive()
        return Path(path).read_bytes()

    def expose(self, port: int) -> Endpoint:
        """This computer's own port, declared or not: a local machine shares its network, so there
        is nothing to gate and no headers either way."""
        self._check_alive()
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
        for pgid in self._groups():
            _killpg(pgid)

    def gone(self) -> bool:
        """No live process (a zombie is dead) in the supervisor's process group or any job's or
        service's: what a VM's "terminated" is here. Not alive(): a supervisor SIGKILLed on macOS
        leaves its job running (no PDEATHSIG), and that machine is not gone until terminate()."""
        groups = set(self._groups())
        assert groups, self.id  # the supervisor's own, at least
        listing = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True, check=True).stdout
        rows = [line.split() for line in listing.splitlines() if line.strip()]
        live = {int(row[0]) for row in rows if not row[1].startswith("Z")}
        return not groups & live

    def _groups(self) -> list[int]:
        """The supervisor's process group (its pid: launched in a session of its own), then every job's
        and service's (status.json's pgid, from when it started; a hook's group is not recorded)."""
        jobs = [json.loads(status.read_text()).get("pgid") for status in Path(self.root).glob("*/*/status.json")]
        return [int((self.dir / "pid").read_text()), *(pgid for pgid in jobs if pgid is not None)]


def _take_terminal() -> None:
    """In the child, after setsid (start_new_session): make stdin (the pty) its controlling terminal."""
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _killpg(pgid: int | None) -> None:
    if pgid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
