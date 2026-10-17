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
import time
from pathlib import Path

from box.providers.pump import JOIN_S, Pty, Pumped, pipe_readers
from box.sdk import (
    LABEL_BY,
    LABEL_NAME,
    Endpoint,
    Gone,
    NameTaken,
    Refused,
    Shell,
    SnapshotImage,
    parse_image,
    snapshot_ref,
)
from box.store import DirStore, Mount

PS_ENV = {**os.environ, "LC_ALL": "C"}
BASE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "box" / "local"


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
        if gpu:
            raise NotImplementedError(f"local provider: no gpu (got gpu={gpu!r})")
        match None if image is None else parse_image(image):
            case None:
                snapshot = None
            case SnapshotImage(provider="local", id=snapshot_id):
                snapshot = self.base / "snapshots" / snapshot_id
            case _:
                raise NotImplementedError(f"local provider: no image but its own snapshots (got image={image!r})")
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
        return snapshot_ref(self.name, snapshot_id)


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

    def shell(self, cmd: str) -> Shell:
        self._check_alive()
        return Shell(["bash", "-c", f"cd {shlex.quote(str(self.dir))} || exit 1; {cmd}"])

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
            pid, recorded_at = int((self.dir / "pid").read_text()), (self.dir / "pid").stat().st_mtime
        except FileNotFoundError:
            return False
        out = subprocess.run(["ps", "-o", "stat=,lstart=", "-p", str(pid)], capture_output=True, text=True, env=PS_ENV).stdout.split()
        return bool(out) and not out[0].startswith("Z") and parse_lstart(out[1:]) <= recorded_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LocalMachine) and other.dir == self.dir

    def terminate(self) -> None:
        for pgid in self._live_groups():
            _killpg(pgid)

    def gone(self) -> bool:
        # macOS has no PR_SET_PDEATHSIG: jobs outlive a SIGKILLed supervisor, so alive() is not gone()
        return not self._live_groups()

    def _live_groups(self) -> set[int]:
        recorded = self._groups()
        assert recorded, self.id
        listing = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,stat=,lstart="], capture_output=True, text=True, check=True, env=PS_ENV).stdout
        rows = [line.split() for line in listing.splitlines() if line.strip()]
        started = {int(row[0]): parse_lstart(row[3:]) for row in rows}
        live = {int(row[1]) for row in rows if not row[2].startswith("Z")}
        return {pgid for pgid, recorded_at in recorded if pgid in live and (pgid not in started or started[pgid] <= recorded_at)}

    def _groups(self) -> list[tuple[int, float]]:
        statuses = [(json.loads(status.read_text()), status.stat().st_mtime) for status in Path(self.root).glob("*/*/status.json")]
        jobs = [(status.get(key), at) for status, at in statuses for key in ("pgid", "hook_pgid")]
        supervisor = (int((self.dir / "pid").read_text()), (self.dir / "pid").stat().st_mtime)
        return [supervisor, *((pgid, at) for pgid, at in jobs if pgid is not None)]


def restore(snapshot: Path, work: Path) -> None:
    shutil.copytree(snapshot, work, symlinks=True)
    store = work / ".box.git"
    # a linked worktree's .git file holds its git store's absolute path
    trees = [str(dot.parent) for dot in work.glob("*/.git")]
    if trees:
        subprocess.run(["git", "--git-dir", str(store), "worktree", "repair", *trees], check=True, capture_output=True)


def parse_lstart(fields: list[str]) -> float:
    return time.mktime(time.strptime(" ".join(fields), "%a %b %d %H:%M:%S %Y"))


def _take_terminal() -> None:
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _killpg(pgid: int | None) -> None:
    if pgid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)
