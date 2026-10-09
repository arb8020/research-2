"""The RunPod provider: a machine is a pod whose main process is the supervisor, reached over SSH.

REST v2 (api.runpod.io/v2; v1 and GraphQL are retiring). What the API gives a pod, verified live:
- no TTL field, so nothing at RunPod ends a pod by itself;
- when the main process exits the container is restarted (still RUNNING, still billing), with its
  filesystem kept, so an exiting supervisor does not end a pod;
- every pod gets a pod-scoped RUNPOD_API_KEY that can DELETE that pod (and see nothing else).
So a pod ends itself: BOX_ON_SHUTDOWN (run by the supervisor, last) deletes it with that key.
BOOT, the shell that runs before the supervisor, also starts sshd, arms a backstop delete at
timeout_s, and on a restart (BOX_ROOT/booted exists) deletes the pod instead of supervising again.

A pod carries no labels: box names it `box-...` and keeps the labels in env BOX_LABELS
(urlsafe-base64 JSON). exec is ssh (one multiplexed connection per pod) to the published 22/tcp.
gpu=None rents a CPU pod (2 vCPU), the cheapest machine RunPod has.
"""

from __future__ import annotations

import base64
import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import requests

from box import gpus
from box.sdk import LABEL_BY, LABEL_SESSION, Endpoint, Gone

# TODO(handoff): seen live: a pod whose client died before attaching deleted itself at its boot
# timeout (UP_TIMEOUT_S). Not yet seen live on the current sdk: the normal path, where the
# supervisor ends after a job and BOX_ON_SHUTDOWN deletes the pod; and the full test suite.
API = "https://api.runpod.io/v2"
ROOT = "/box"
IMAGE = "runpod/base:1.4.0-ubuntu2404"  # bash, python3, sshd, curl; 0.7 GB
CPU = {"id": "cpu3c", "vcpuCount": 2}  # $0.06/hr
DISK_GB = 20
UP_TIMEOUT_S = 900.0  # image pull + boot, before ssh answers
EXEC_TIMEOUT_S = 600  # one exec/read/write; a dead connection is dropped sooner (ServerAlive: 45 s)
SSH_GRACE_S = 60  # once the container runs, sshd answers within this (~2 s; ~15 s if apt installs it)
LAUNCH_TRIES = 3
UNREACHABLE: set[str] = set()  # data centers where a pod's ssh port never answered (seen live: EU-SE-1)
SSH_OPTS = [
    "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
    "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/box-rp-%C", "-o", "ControlPersist=120",
]  # fmt: skip

# Deletes this pod with its own key; retried, since a container that exits instead is restarted.
# python3 because the supervisor guarantees it (curl may be missing); a User-Agent because
# RunPod's CDN refuses urllib's default one (403, error 1010).
SHUTDOWN = r"""python3 - <<'PY' >> "$BOX_ROOT/shutdown.log" 2>&1
import os, time, urllib.request as u
req = u.Request("API/pods/" + os.environ["RUNPOD_POD_ID"], method="DELETE",
                headers={"Authorization": "Bearer " + os.environ["RUNPOD_API_KEY"], "User-Agent": "box"})
for _ in range(60):
    try:
        print(time.ctime(), "delete", u.urlopen(req, timeout=30).status, flush=True); break
    except u.HTTPError as e:
        print(time.ctime(), "delete", e.code, flush=True)
        if e.code == 404: break
    except Exception as e:
        print(time.ctime(), "delete", e, flush=True)
    time.sleep(10)
PY""".replace("API/", API + "/")

# Runs as `bash -c BOOT boot <supervisor argv...>`, with BOX_TIMEOUT_S and BOX_UP_TIMEOUT_S in its env.
BOOT = r"""mkdir -p "$BOX_ROOT"
if [ -e "$BOX_ROOT/booted" ]; then  # the container restarted: the session is over, end the pod
    echo "$(date) restarted; deleting the pod" >> "$BOX_ROOT/shutdown.log"; bash -c "$BOX_ON_SHUTDOWN"; sleep 600; exit 1
fi
touch "$BOX_ROOT/booted"
( sleep "$BOX_TIMEOUT_S"; echo "$(date) backstop timeout" >> "$BOX_ROOT/shutdown.log"; bash -c "$BOX_ON_SHUTDOWN" ) &
{
    if ! command -v sshd >/dev/null && [ ! -x /usr/sbin/sshd ]; then
        if command -v apt-get >/dev/null; then
            apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openssh-server
        elif command -v apk >/dev/null; then apk add --no-cache openssh-server; fi
    fi
    mkdir -p /root/.ssh /run/sshd && chmod 700 /root/.ssh && echo "$PUBLIC_KEY" >> /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys && ssh-keygen -A && /usr/sbin/sshd
} > "$BOX_ROOT/boot.log" 2>&1
# Start the supervisor only once the client reached us (RunPod publishes the ssh port ~20 s after
# the container starts): its lease and deadline clocks run from when a client can heartbeat.
for _ in $(seq "$((BOX_UP_TIMEOUT_S / 2))"); do [ -e "$BOX_ROOT/attached" ] && break; sleep 2; done
if [ ! -e "$BOX_ROOT/attached" ]; then
    echo "$(date) no client attached" >> "$BOX_ROOT/shutdown.log"; bash -c "$BOX_ON_SHUTDOWN"; sleep 600; exit 1
fi
"$@" &  # not exec: bash as PID 1 reaps the orphans a killed job leaves
wait $!
"""


class Unreachable(TimeoutError):
    """The pod runs but its published ssh port never answers (a bad host): retried elsewhere."""


class RunPod:
    name = "runpod"

    def __init__(self, api_key: str, cloud: str = "SECURE") -> None:
        self.http = requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {api_key}", "User-Agent": "box"})
        self.cloud = cloud

    @classmethod
    def from_env(cls) -> RunPod:
        """RUNPOD_API_KEY from the environment, else from the nearest .env above this file."""
        key = os.environ.get("RUNPOD_API_KEY")
        for env_file in [] if key else [d / ".env" for d in Path(__file__).resolve().parents]:
            for line in env_file.read_text().splitlines() if env_file.is_file() else []:
                name, _, value = line.partition("=")
                key = value.strip().strip("'\"") if name.strip() == "RUNPOD_API_KEY" else key
            if key:
                break
        if not key:
            raise SystemExit("runpod: set RUNPOD_API_KEY (or put it in a .env above box/)")
        return cls(key)

    def api(self, method: str, path: str, body: dict | None = None) -> dict | None:
        """The response's JSON (None for 204 No Content, or a 404 on GET/DELETE)."""
        r = self.http.request(method, API + path, json=body, timeout=60)
        if r.status_code == 404 and method in ("GET", "DELETE"):
            return None
        if not r.ok:
            raise RuntimeError(f"runpod: {method} {path} -> {r.status_code}: {r.text[:500]}")
        return r.json() if r.content else None

    def launch(
        self, *, gpu: str | None, image: str | None, entrypoint: list[str], env: dict[str, str],
        labels: dict[str, str], timeout_s: int, ports: list[int],
    ) -> RunPodMachine:  # fmt: skip
        """Returns once ssh answers (the supervisor may still be starting)."""
        body: dict = {
            "name": f"box-{labels[LABEL_SESSION]}", "image": image or IMAGE, "cloud": self.cloud,
            "disk": DISK_GB, "ports": ["22/tcp", *(f"{p}/http" for p in ports)], "entrypoint": ["bash", "-c", BOOT, "boot", *entrypoint],
            "env": {
                **env, "BOX_ROOT": ROOT, "BOX_ON_SHUTDOWN": SHUTDOWN, "BOX_TIMEOUT_S": str(timeout_s),
                "BOX_UP_TIMEOUT_S": str(int(UP_TIMEOUT_S)),
                "BOX_LABELS": base64.urlsafe_b64encode(json.dumps(labels).encode()).decode(), "PUBLIC_KEY": _pubkey(),
            },
        }  # fmt: skip
        if gpu is None:
            body["cpu"] = CPU
        else:
            gpu_id = gpus.provider_id(gpus.lookup(gpu), "runpod")
            if gpu_id is None:
                raise ValueError(f"runpod: no RunPod id for GPU {gpu!r} in box/gpus.py")
            body["gpu"] = {"id": gpu_id, "count": 1}
        for attempt in range(LAUNCH_TRIES):
            if UNREACHABLE:  # "preferred" data centers: every one but those
                dcs = (self.api("GET", "/catalog/datacenters") or {})["dataCenters"]
                body["dataCenterIds"] = [dc["id"] for dc in dcs if dc["id"] not in UNREACHABLE]
            pod = self.api("POST", "/pods", body)
            assert pod is not None
            m = RunPodMachine(self, pod)
            try:
                m.wait_up(UP_TIMEOUT_S)
                return m
            except Unreachable:
                m.terminate()
                UNREACHABLE.add(m._pod_dc or "")
                if attempt == LAUNCH_TRIES - 1:
                    raise
            except BaseException:
                m.terminate()  # no supervisor will ever end this pod
                raise
        raise AssertionError("unreachable")

    def get(self, machine_id: str) -> RunPodMachine:
        pod = self.api("GET", f"/pods/{machine_id}") if machine_id.isalnum() else None
        if pod is None or not _ours(pod):
            raise LookupError(f"runpod: no pod {machine_id} launched by box")
        return RunPodMachine(self, pod)

    def list(self, labels: dict[str, str] | None = None) -> list[RunPodMachine]:
        want = (labels or {}).items()
        pods, cursor = [], None
        while True:
            page = self.api("GET", "/pods" + (f"?cursor={cursor}" if cursor else "")) or {}
            pods += page.get("pods", [])
            cursor = (page.get("pagination") or {}).get("nextCursor")
            if not cursor:
                break
        return [RunPodMachine(self, p) for p in pods if _ours(p) and p["status"] != "TERMINATED" and want <= _labels(p).items()]


class RunPodMachine:
    def __init__(self, rp: RunPod, pod: dict) -> None:
        self.rp = rp
        self.id: str = pod["id"]
        self.labels: dict[str, str] = _labels(pod)
        self.root = ROOT
        self._direct = (pod.get("ssh") or {}).get("direct")
        self._pod_dc: str | None = pod.get("dataCenterId")
        self._http_ports = [int(p.split("/")[0]) for p in pod.get("ports") or [] if p.endswith("/http")]

    def _pod(self) -> dict:
        """The pod as the API sees it now; Gone if it no longer exists."""
        pod = self.rp.api("GET", f"/pods/{self.id}")
        if pod is None or pod["status"] == "TERMINATED":
            raise Gone(self.id)
        return pod

    def wait_up(self, timeout_s: float) -> None:
        give_up = time.monotonic() + timeout_s
        while self._direct is None or self._ssh(f"touch {ROOT}/attached", retries=0).returncode != 0:
            if time.monotonic() > give_up:
                raise TimeoutError(f"runpod: {self.id}: no ssh after {timeout_s:.0f} s")
            time.sleep(3)
            pod = self._pod()
            self._direct, self._pod_dc = pod["ssh"]["direct"], pod.get("dataCenterId")
            if ((pod.get("runtime") or {}).get("uptime") or 0) > SSH_GRACE_S:
                raise Unreachable(f"runpod: {self.id} ({self._pod_dc}): container up {SSH_GRACE_S} s, ssh does not answer")

    def _ssh(self, cmd: str, data: bytes | None = None, retries: int = 3) -> subprocess.CompletedProcess:
        """cmd over ssh. ssh's own failure is exit 255: then Gone if the pod is gone, else retry."""
        done = None
        for attempt in range(retries + 1):
            if attempt or self._direct is None:
                time.sleep(2 if attempt else 0)
                self._direct = self._pod()["ssh"]["direct"]  # raises Gone; else the port may have moved
            if (d := self._direct) is None:
                continue
            argv = ["ssh", *SSH_OPTS, "-p", str(d["port"]), f"{d['username']}@{d['host']}", cmd]
            try:
                done = subprocess.run(argv, input=data, capture_output=True, check=False, timeout=EXEC_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._pod()  # Gone if the pod went away under us
                raise TimeoutError(f"runpod: {self.id}: ssh `{cmd[:80]}` ran past {EXEC_TIMEOUT_S} s") from None
            if done.returncode != 255:
                break
        if done is None:
            raise TimeoutError(f"runpod: {self.id}: no ssh endpoint yet")
        return done

    def exec(self, cmd: str) -> tuple[int, str, str]:
        done = self._ssh(cmd)
        return done.returncode, done.stdout.decode(errors="replace"), done.stderr.decode(errors="replace")

    def write(self, path: str, data: bytes) -> None:
        p = shlex.quote(path)
        self._file(f'mkdir -p "$(dirname {p})" && cat > {p}.part && mv {p}.part {p}', path, data)

    def read(self, path: str) -> bytes:
        p = shlex.quote(path)
        return self._file(f"if [ -e {p} ]; then cat {p}; else exit 44; fi", path)

    def _file(self, cmd: str, path: str, data: bytes | None = None) -> bytes:
        done = self._ssh(cmd, data=data)
        if done.returncode == 44:
            raise FileNotFoundError(path)
        if done.returncode != 0:
            raise RuntimeError(f"runpod: {self.id}: `{cmd}` exited {done.returncode}: {done.stderr.decode().strip()}")
        return done.stdout

    def terminate(self) -> None:
        self.rp.api("DELETE", f"/pods/{self.id}")  # a 404 (already gone) is fine

    def expose(self, port: int) -> Endpoint:
        """RunPod's HTTP proxy for a port declared at launch (as <port>/http). Not seen live yet:
        the service must listen on 0.0.0.0, and the proxy (Cloudflare) cuts requests at ~100 s."""
        if port not in self._http_ports:
            raise ValueError(f"runpod: port {port} was not declared at launch (ports={self._http_ports})")
        return Endpoint(f"https://{self.id}-{port}.proxy.runpod.net")


def _labels(pod: dict) -> dict[str, str]:
    raw = (pod.get("env") or {}).get("BOX_LABELS")
    return json.loads(base64.urlsafe_b64decode(raw)) if raw else {}


def _ours(pod: dict) -> bool:
    return pod.get("name", "").startswith("box-") and _labels(pod).get(LABEL_BY) == "box"


def _pubkey() -> str:
    for name in ("id_ed25519.pub", "id_rsa.pub"):
        if (path := Path.home() / ".ssh" / name).exists():
            return path.read_text().strip()
    raise FileNotFoundError("runpod: no ~/.ssh/id_ed25519.pub or id_rsa.pub to ssh into pods with")
