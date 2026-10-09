from __future__ import annotations

import contextlib
import fcntl
import json
import os
import secrets
import shlex
import shutil
import signal
import subprocess
import termios
from pathlib import Path

from box.providers.pump import JOIN_S, Pty, Pumped, pipe_readers
from box.sdk import LABEL_BY, LABEL_NAME, Endpoint, Gone, NameTaken, Refused
from box.store import DirStore, Mount

BASE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "box" / "local"
SNAPSHOT = "local-snapshot:"


class Local:
    name = "local"

    def __init__(self, base: Path = BASE) -> None:
        self.base = base

    def launch(  # noqa: PLR0913
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int], mounts: list[Mount],
    ) -> LocalMachine:  # fmt: skip
        del timeout_s
        del ports
        if gpu or (image and not image.startswith(SNAPSHOT)):
            raise NotImplementedError(f"local provider: no gpu/image (got gpu={gpu!r}, image={image!r})")
        snapshot = self.base / "snapshots" / image.removeprefix(SNAPSHOT) if image else None
        if snapshot is not None and not snapshot.is_dir():
            raise LookupError(f"local provider: no snapshot {image!r}")
        if foreign := [m.store.uri for m in mounts if not isinstance(m.store, DirStore)]:
            raise Refused(f"local provider: mounts only a DirStore (got {foreign})")
        self.base.mkdir(parents=True, exist_ok=True)
        with (self.base / "names.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if LABEL_NAME in labels and self.list({LABEL_NAME: labels[LABEL_NAME]}):
                raise NameTaken(f"local provider: a live machine is named {labels[LABEL_NAME]!r}")
            return self._launch(entrypoint, env, labels, mounts, snapshot)

    def _launch(  # noqa: PLR0913
        self, entrypoint: list[str], env: dict[str, str], labels: dict[str, str], mounts: list[Mount], snapshot: Path | None,
    ) -> LocalMachine:  # fmt: skip
        m = LocalMachine(self.base / f"local-{secrets.token_hex(4)}")
        m.dir.mkdir(parents=True)
        if snapshot is not None:
            restore(snapshot, Path(m.work))
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
        pass

    def snapshot(self, machine: LocalMachine, *, ttl_s: int) -> str:
        del ttl_s
        snapshot_id = secrets.token_hex(6)
        shutil.copytree(machine.work, self.base / "snapshots" / snapshot_id, symlinks=True)
        return SNAPSHOT + snapshot_id


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
                os.close(slave)
            terminal = Pty(master)
            readers, send = [terminal.reader()], terminal.send
        else:
            proc = subprocess.Popen(
                ["bash", "-c", cmd], cwd=self.dir, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=True,
            )  # fmt: skip
            terminal, readers, send = None, pipe_readers(proc), None

        def kill() -> None:
            _killpg(proc.pid)
            if terminal is not None:
                terminal.stop.set()
            proc.wait(JOIN_S)

        def wait() -> int:
            rc = proc.wait(JOIN_S)
            # Popen reports a signal death as -N; Modal and ssh report 128+N
            return rc if rc >= 0 else 128 - rc

        return Pumped(
            readers, kill=kill, wait=wait, timeout_s=timeout_s, quiet_s=quiet_s, check=self._check_alive, label=self.id, send=send,
        )  # fmt: skip

    def shell_argv(self, cmd: str) -> list[str]:
        self._check_alive()
        return ["bash", "-c", f"cd {shlex.quote(str(self.dir))} || exit 1; {cmd}"]

    def write(self, path: str, data: bytes) -> None:
        self._check_alive()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(data)

    def read(self, path: str) -> bytes:
        self._check_alive()
        return Path(path).read_bytes()

    def expose(self, port: int) -> Endpoint:
        self._check_alive()
        return Endpoint(f"http://127.0.0.1:{port}")

    def _check_alive(self) -> None:
        if not self.alive():
            raise Gone(self.id)

    def alive(self) -> bool:
        try:
            pid = (self.dir / "pid").read_text()
        except FileNotFoundError:
            return False
        stat = subprocess.run(["ps", "-o", "stat=", "-p", pid], capture_output=True, text=True).stdout.strip()
        return bool(stat) and not stat.startswith("Z")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LocalMachine) and other.dir == self.dir

    def terminate(self) -> None:
        for pgid in self._groups():
            _killpg(pgid)

    def gone(self) -> bool:
        # macOS has no PR_SET_PDEATHSIG: jobs outlive a SIGKILLed supervisor, so alive() is not gone()
        groups = set(self._groups())
        assert groups, self.id
        listing = subprocess.run(["ps", "-A", "-o", "pgid=,stat="], capture_output=True, text=True, check=True).stdout
        rows = [line.split() for line in listing.splitlines() if line.strip()]
        live = {int(row[0]) for row in rows if not row[1].startswith("Z")}
        return not groups & live

    def _groups(self) -> list[int]:
        statuses = [json.loads(status.read_text()) for status in Path(self.root).glob("*/*/status.json")]
        jobs = [status.get(key) for status in statuses for key in ("pgid", "hook_pgid")]
        return [int((self.dir / "pid").read_text()), *(pgid for pgid in jobs if pgid is not None)]


def restore(snapshot: Path, work: Path) -> None:
    shutil.copytree(snapshot, work, symlinks=True)
    store = work / ".box.git"
    # a linked worktree's .git file holds its git store's absolute path
    trees = [str(dot.parent) for dot in work.glob("*/.git")]
    if trees:
        subprocess.run(["git", "--git-dir", str(store), "worktree", "repair", *trees], check=True, capture_output=True)


def _take_terminal() -> None:
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _killpg(pgid: int | None) -> None:
    if pgid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
