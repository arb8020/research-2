from __future__ import annotations

import argparse
import os
import secrets
import shlex
import time
import urllib.request
import warnings

os.environ.setdefault("MODAL_PROFILE", "arb8020")
assert os.environ["MODAL_PROFILE"] != "herdora", "verify_workspace never runs on the herdora workspace"
import modal  # noqa: E402

warnings.filterwarnings("ignore", category=modal.exception.AsyncUsageWarning)

APP = "blogs-verify-workspace"
TAG = {"blogs": "verify-workspace"}
PORT = 8888
ROOT = "/work"
PERSIST = "/vol/ws"
SANDBOX_TIMEOUT_S = 20 * 60
JUPYTER_UP_S = 180
IMAGE = (modal.Image.from_registry("pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime")
         .pip_install("jupyter_server~=2.17", "ipykernel~=7.1")
         .apt_install("git", "clang", "make", "ccache", "g++", "libc6-dev"))  # fmt: skip


def jupyter_cmd(origin: str) -> str:
    settings = {"websocket_ping_interval": 20}
    return " ".join(["exec", "python3", "-m", "jupyter_server", "--no-browser", "--allow-root", "--ip=0.0.0.0", f"--port={PORT}",
                     f"--ServerApp.root_dir={ROOT}", f"--ServerApp.allow_origin={shlex.quote(origin)}", "--ServerApp.allow_remote_access=True",
                     "--ServerApp.disable_check_xsrf=True", shlex.quote(f"--ServerApp.tornado_settings={settings}")])  # fmt: skip


def app() -> modal.App:
    return modal.App.lookup(APP, create_if_missing=True)


class ModalBox:
    persist = PERSIST

    def __init__(self, name: str, volume: modal.Volume, origin: str) -> None:
        t0 = time.monotonic()
        self.name = name
        self.sb = modal.Sandbox.create("sleep", "infinity", app=app(), image=IMAGE, timeout=SANDBOX_TIMEOUT_S,
                                       encrypted_ports=[PORT], volumes={"/vol": volume})  # fmt: skip
        self.sb.set_tags(TAG)
        self.token = secrets.token_hex(16)
        self.sh(f"mkdir -p {ROOT} {PERSIST}", cwd="/")
        self.sb.exec("bash", "-c", f"cd {ROOT} && JUPYTER_TOKEN={self.token} BLOGS_WS_PERSIST={PERSIST} {jupyter_cmd(origin)}")
        self.url = self.sb.tunnels()[PORT].url.rstrip("/")
        wait_up(self.url, self.token)
        self.up_s = round(time.monotonic() - t0, 1)
        print(f"  [modal] {name}: sandbox {self.sb.object_id}, Jupyter at {self.url} in {self.up_s}s", flush=True)

    def gateway_args(self) -> list[str]:
        return ["--attach-kernel", self.url, "--attach-token", self.token]

    def sh(self, cmd: str, cwd: str = ROOT) -> str:
        p = self.sb.exec("bash", "-c", f"cd {cwd} && {cmd} 2>&1")
        out = p.stdout.read()
        if p.wait() != 0:
            raise RuntimeError(f"[modal {self.name}] `{cmd}` exited {p.returncode}:\n{out}")
        return out

    def close(self) -> None:
        self.sb.terminate()
        self.sb.wait(raise_on_termination=False)
        print(f"  [modal] {self.name}: sandbox {self.sb.object_id} terminated", flush=True)


def wait_up(url: str, token: str) -> None:
    deadline = time.monotonic() + JUPYTER_UP_S
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/status?token={token}", timeout=5) as r:
                if r.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise TimeoutError(f"Jupyter at {url} never answered in {JUPYTER_UP_S}s")


def leftovers(kill: bool = False) -> int:
    try:
        app_id = modal.App.lookup(APP).app_id
    except modal.exception.NotFoundError:
        return 0
    found = list(modal.Sandbox.list(app_id=app_id, tags=TAG))
    for sb in found:
        print(f"  [modal] leftover sandbox {sb.object_id}{' (terminating)' if kill else ''}", flush=True)
        if kill:
            sb.terminate()
    return len(found)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=f"List the workspace sandboxes verify_workspace.py --modal left on Modal (tagged {TAG} under app {APP}).",
        epilog="uv run --with modal ws_modal.py [--kill]")
    ap.add_argument("--kill", action="store_true", help="also terminate them")
    print(f"{leftovers(kill=ap.parse_args().kill)} sandbox(es) tagged {TAG} under app {APP}")
