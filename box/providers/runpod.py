"""RunPod provider — GraphQL API at https://api.runpod.io/graphql."""

from __future__ import annotations

import os
import subprocess
import time

import requests

from box.provider import Box, ExecResult, Job, Offering, Status, Volume
from observe import span

_ENDPOINT = "https://api.runpod.io/graphql"

_SEARCH_QUERY = """
query {
    gpuTypes {
        id
        displayName
        memoryInGb
        secureCloud
        lowestPrice(input: { gpuCount: %(gpu_count)d, secureCloud: true }) {
            uninterruptablePrice
            stockStatus
        }
    }
}
"""

_LAUNCH_MUTATION = """
mutation podFindAndDeployOnDemand($input: PodFindAndDeployOnDemandInput!) {
    podFindAndDeployOnDemand(input: $input) {
        id
        machineId
    }
}
"""

_GET_QUERY = """
query pod($input: PodFilter!) {
    pod(input: $input) {
        id
        desiredStatus
        costPerHr
        gpuCount
        runtime {
            ports {
                ip
                isIpPublic
                privatePort
                publicPort
                type
            }
        }
        machine {
            gpuType {
                displayName
                memoryInGb
            }
        }
    }
}
"""

_TERMINATE_MUTATION = """
mutation podTerminate($input: PodTerminateInput!) {
    podTerminate(input: $input)
}
"""


class _RunPodAPI:
    """Thin GraphQL client for RunPod."""

    def __init__(self, api_key: str):
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {api_key}"

    def gql(self, query: str, variables: dict | None = None) -> dict:
        body = {"query": query}
        if variables:
            body["variables"] = variables
        resp = self._session.post(_ENDPOINT, json=body)
        resp.raise_for_status()
        result = resp.json()
        if "errors" in result:
            raise RuntimeError(f"RunPod API error: {result['errors']}")
        return result["data"]


class RunPodBox:
    """A running RunPod pod. Exec via SSH."""

    def __init__(self, api: _RunPodAPI, pod_id: str, offering: Offering):
        self._api = api
        self.provider_id = pod_id
        self.offering = offering
        self.status = Status.PENDING
        self.labels: dict[str, str] = {}  # RunPod pods carry a name, not labels; not implemented
        self._ssh_host: str | None = None
        self._ssh_port: int | None = None

    def wait(self, timeout: float = 900.0) -> None:
        with span("box.wait", attributes={"provider": "runpod", "pod_id": self.provider_id}) as s:
            deadline = time.monotonic() + timeout
            poll_interval = 10.0
            n_polls = 0
            while time.monotonic() < deadline:
                self._refresh()
                n_polls += 1
                if self.status == Status.FAILED:
                    raise RuntimeError(f"Pod {self.provider_id} failed")
                if self.status == Status.TERMINATED:
                    raise RuntimeError(f"Pod {self.provider_id} terminated")
                if (
                    self.status == Status.RUNNING
                    and self._ssh_host is not None
                    and self._ssh_port is not None
                ):
                    if self._ssh_connectable():
                        s.set_attrs(
                            n_polls=n_polls,
                            ssh_host=self._ssh_host,
                            ssh_port=self._ssh_port,
                        )
                        return
                time.sleep(poll_interval)
            raise TimeoutError(
                f"SSH not available after {timeout}s for pod {self.provider_id}"
            )

    def exec(
        self,
        cmd: str,
        *,
        env: dict[str, str] | None = None,
        stream: bool = False,
        timeout: int | None = None,
    ) -> ExecResult:
        import shlex
        import sys

        if self._ssh_host is None or self._ssh_port is None:
            raise RuntimeError("Box not ready — call wait() first")
        logged = cmd[:200]  # before env is inlined: env values may be secrets
        if env:
            cmd = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items()) + f" bash -c {shlex.quote(cmd)}"
        if timeout:
            cmd = f"timeout {timeout} bash -c {shlex.quote(cmd)}"
        argv = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-p", str(self._ssh_port),
            f"root@{self._ssh_host}",
            cmd,
        ]
        with span("box.exec", attributes={"provider": "runpod", "pod_id": self.provider_id, "cmd": logged,
                                      "env_keys": ",".join(env or {})}) as s:
            if stream:
                import threading

                proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                chunks: dict[str, list[str]] = {"out": [], "err": []}

                def pump(src, key, sink):
                    for line in src:
                        chunks[key].append(line)
                        sink.write(line)
                        sink.flush()

                t_err = threading.Thread(target=pump, args=(proc.stderr, "err", sys.stderr), daemon=True)
                t_err.start()
                pump(proc.stdout, "out", sys.stdout)
                t_err.join()
                proc.wait()
                stdout, stderr, rc = "".join(chunks["out"]), "".join(chunks["err"]), proc.returncode
            else:
                done = subprocess.run(argv, capture_output=True, text=True)
                stdout, stderr, rc = done.stdout, done.stderr, done.returncode
            s.set_attrs(returncode=rc, stdout_bytes=len(stdout), stderr_bytes=len(stderr))
            return ExecResult(stdout=stdout, stderr=stderr, returncode=rc)

    def upload(self, local: str, remote: str) -> None:
        if self._ssh_host is None or self._ssh_port is None:
            raise RuntimeError("Box not ready — call wait() first")
        subprocess.run(
            [
                "rsync", "-az", "-e",
                f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p {self._ssh_port}",
                local,
                f"root@{self._ssh_host}:{remote}",
            ],
            check=True,
        )

    def download(self, remote: str, local: str) -> None:
        if self._ssh_host is None or self._ssh_port is None:
            raise RuntimeError("Box not ready — call wait() first")
        subprocess.run(
            [
                "rsync", "-az", "-e",
                f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -p {self._ssh_port}",
                f"root@{self._ssh_host}:{remote}",
                local,
            ],
            check=True,
        )

    def terminate(self) -> None:
        with span("box.terminate", attributes={"provider": "runpod", "pod_id": self.provider_id}):
            self._api.gql(_TERMINATE_MUTATION, {"input": {"podId": self.provider_id}})
            self.status = Status.TERMINATED

    def spawn(self, cmd: str, *, env: dict[str, str] | None = None, timeout: int | None = None) -> Job:
        raise NotImplementedError(
            "runpod: no detached job yet. Needs the command started under nohup over ssh with its "
            "output and exit status written on the pod, and a Job that reads them back by pod id."
        )

    def job(self) -> Job:
        raise NotImplementedError("runpod: no detached job yet (see RunPodBox.spawn)")

    def _refresh(self) -> None:
        data = self._api.gql(_GET_QUERY, {"input": {"podId": self.provider_id}})
        pod = data["pod"]
        if pod is None:
            self.status = Status.TERMINATED
            return

        status_map = {
            "RUNNING": Status.RUNNING,
            "PENDING": Status.PENDING,
            "STOPPED": Status.TERMINATED,
            "TERMINATED": Status.TERMINATED,
            "FAILED": Status.FAILED,
        }
        self.status = status_map.get(pod["desiredStatus"], Status.PENDING)

        # Reset SSH info on each refresh — RunPod can revoke assignments
        self._ssh_host = None
        self._ssh_port = None
        if pod.get("runtime") and pod["runtime"].get("ports"):
            for port in pod["runtime"]["ports"]:
                if (
                    port.get("privatePort") == 22
                    and port.get("isIpPublic")
                    and port.get("type") == "tcp"
                    and port.get("ip")
                    # Reject RunPod proxy (ssh.runpod.io) — not a direct transport
                    and port.get("ip") != "ssh.runpod.io"
                ):
                    self._ssh_host = port["ip"]
                    self._ssh_port = port["publicPort"]
                    break

    def _ssh_connectable(self) -> bool:
        """Check that SSH is actually ready — not just TCP open, but sshd responding."""
        result = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR",
                "-o", "ConnectTimeout=5",
                "-p", str(self._ssh_port),
                f"root@{self._ssh_host}",
                "echo ssh_ready",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0 and "ssh_ready" in result.stdout


class RunPod:
    """RunPod provider. launch() returns a RunPodBox."""

    name = "runpod"

    def __init__(self, api_key: str):
        self._api = _RunPodAPI(api_key)

    def search(
        self,
        *,
        gpu_model: str | None = None,
        gpu_count: int = 1,
    ) -> list[Offering]:
        with span("box.search", attributes={"provider": "runpod", "gpu_model": gpu_model, "gpu_count": gpu_count}) as s:
            return self._search_inner(gpu_model=gpu_model, gpu_count=gpu_count, _span=s)

    def _search_inner(self, *, gpu_model, gpu_count, _span) -> list[Offering]:
        query = _SEARCH_QUERY % {"gpu_count": gpu_count}
        data = self._api.gql(query)
        offerings = []
        for gpu in data["gpuTypes"]:
            if not gpu["secureCloud"]:
                continue
            price_info = gpu["lowestPrice"]
            if not price_info or price_info["stockStatus"] == "unavailable":
                continue
            if gpu_model and gpu_model.lower() not in gpu["id"].lower():
                continue
            offerings.append(
                Offering(
                    provider=self.name,
                    id=gpu["id"],
                    gpu_model=gpu["displayName"],
                    gpu_count=gpu_count,
                    gpu_memory_gb=gpu["memoryInGb"],
                    price_hr=price_info["uninterruptablePrice"],
                )
            )
        offerings.sort(key=lambda o: o.price_hr or float("inf"))
        _span.set_attr("n_results", len(offerings))
        return offerings

    @classmethod
    def from_env(cls) -> RunPod:
        key = os.environ.get("RUNPOD_API_KEY")
        if not key:
            raise SystemExit("runpod: set RUNPOD_API_KEY")
        return cls(api_key=key)

    def launch(self, offering: Offering, *, ssh_pubkey: str | None = None, **kwargs: object) -> RunPodBox:
        """Only ssh_pubkey is lowered today; refused before a paid pod exists."""
        if kwargs or ssh_pubkey is None:
            raise NotImplementedError(
                f"runpod: launch lowers only ssh_pubkey; not {sorted(kwargs)} (image needs an OCI ref, "
                "mounts an upload step, volumes network volumes, labels the pod name/env, timeout a reaper)"
            )
        with span("box.launch", attributes={
            "provider": "runpod",
            "offering_id": offering.id,
            "gpu_model": offering.gpu_model,
            "gpu_count": offering.gpu_count,
            "price_hr": offering.price_hr,
        }) as s:
            variables = {
                "input": {
                    "gpuCount": offering.gpu_count,
                    "gpuTypeId": offering.id,
                    "cloudType": "SECURE",
                    "name": f"box-{offering.id[:20]}",
                    "imageName": "runpod/pytorch:2.1.0-py3.10-cuda11.8.0-devel",
                    "containerDiskInGb": 50,
                    "volumeInGb": 100,
                    "volumeMountPath": "/workspace",
                    "ports": "22/tcp",
                    "startSsh": True,
                    "supportPublicIp": True,
                    "env": [{"key": "PUBLIC_KEY", "value": ssh_pubkey}],
                }
            }
            data = self._api.gql(_LAUNCH_MUTATION, variables)
            pod = data["podFindAndDeployOnDemand"]
            s.set_attr("pod_id", pod["id"])
            return RunPodBox(api=self._api, pod_id=pod["id"], offering=offering)

    def list(self) -> list[Box]:
        raise NotImplementedError("runpod: list needs the `myself { pods }` query and labels stored on the pod (name or env)")

    def get(self, box_id: str) -> RunPodBox:
        raise NotImplementedError("runpod: get needs the pod's offering and labels stored on the pod to rebuild a RunPodBox")

    def volumes(self) -> list[tuple[str, float]]:
        raise NotImplementedError("runpod: network volumes are not wired into box")

    def volume(self, name: str) -> Volume:
        raise NotImplementedError("runpod: network volumes are not wired into box")

    def delete_volume(self, name: str) -> None:
        raise NotImplementedError("runpod: network volumes are not wired into box")
