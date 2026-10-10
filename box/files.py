from __future__ import annotations

import io
import secrets
import shlex
import tarfile
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from box.sdk import Machine


def put(machine: Machine, local: str | Path, remote: str, ignore: tuple[str, ...] = ()) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for child in sorted(Path(local).iterdir()):
            tar.add(child, arcname=child.name, filter=lambda i: None if ignored(i.name, ignore) else i)
    tmp = f"{machine.root}/put-{secrets.token_hex(3)}.tgz"
    machine.write(tmp, buf.getvalue())
    check(machine, f"mkdir -p {shlex.quote(remote)} && tar xzf {tmp} --no-same-owner -C {shlex.quote(remote)} && rm {tmp}")


def get(machine: Machine, remote: str, local: str | Path) -> None:
    tmp = f"{machine.root}/get-{secrets.token_hex(3)}.tgz"
    check(machine, f"tar czf {tmp} -C {shlex.quote(remote)} .")
    data = machine.read(tmp)
    machine.exec(f"rm -f {tmp}")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(local, filter="data")


def ignored(rel: str, ignore: tuple[str, ...]) -> bool:
    return any(fnmatch(rel, g) or (g.startswith("**/") and fnmatch(rel.rsplit("/", 1)[-1], g[3:])) for g in ignore)


def check(machine: Machine, cmd: str) -> str:
    rc, out, err = machine.exec(cmd)
    if rc != 0:
        raise RuntimeError(f"{machine.id}: `{cmd}` exited {rc}: {err.strip()}")
    return out
