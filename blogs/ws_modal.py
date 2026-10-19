from __future__ import annotations

import argparse
import os
import tomllib
import warnings
from pathlib import Path

os.environ.setdefault("MODAL_PROFILE", "arb8020")
assert os.environ["MODAL_PROFILE"] != "herdora", "verify_workspace never runs on the herdora workspace"
import modal  # noqa: E402

warnings.filterwarnings("ignore", category=modal.exception.AsyncUsageWarning)

APP = "box"
TAG = {"box.purpose": "verify-workspace"}
ROOT = "/box/services/jupyter"
PERSIST = "/ws/workspace-persist"
IMAGE = Path(__file__).parent / "engine" / "kernel.Dockerfile"


def token() -> tuple[str, str]:
    profile = tomllib.loads((Path.home() / ".modal.toml").read_text())[os.environ["MODAL_PROFILE"]]
    return profile["token_id"], profile["token_secret"]


class ModalBox:
    persist = PERSIST

    def __init__(self, name: str, volume: str) -> None:
        self.name = name
        self.volume = volume
        self.token = token()

    def gateway_args(self) -> list[str]:
        return ["--provider", "modal", "--gpus", "", "--image", str(IMAGE), "--volume", f"/ws={self.volume}",
                "--label", f"box.purpose={TAG['box.purpose']}"]  # fmt: skip

    def sessions(self) -> list[str]:
        return [tags["box.session"] for _, tags in sandboxes()]

    def sh(self, cmd: str) -> str:
        found = sandboxes()
        assert found, f"[modal {self.name}] no session's sandbox to run `{cmd}` in"
        p = found[-1][0].exec("bash", "-c", f"cd {ROOT} && {cmd} 2>&1")
        out = p.stdout.read()
        if p.wait() != 0:
            raise RuntimeError(f"[modal {self.name}] `{cmd}` exited {p.returncode}:\n{out}")
        return out


def sandboxes() -> list[tuple[modal.Sandbox, dict[str, str]]]:
    try:
        app_id = modal.App.lookup(APP).app_id
    except modal.exception.NotFoundError:
        return []
    return [(sb, sb.get_tags()) for sb in modal.Sandbox.list(app_id=app_id, tags=TAG)]


def leftovers(kill: bool = False) -> int:
    found = sandboxes()
    for sb, tags in found:
        print(f"  [modal] leftover sandbox {sb.object_id} ({tags.get('box.session')}){' (terminating)' if kill else ''}", flush=True)
        if kill:
            sb.terminate()
    return len(found)


def delete_volume(name: str) -> None:
    modal.Volume.objects.delete(name)
    print(f"  [modal] volume {name} deleted", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description=f"List the workspace sandboxes verify_workspace.py --modal left on Modal (tagged {TAG} under app {APP}).",
        epilog="uv run --with modal ws_modal.py [--kill]")
    ap.add_argument("--kill", action="store_true", help="also terminate them")
    print(f"{leftovers(kill=ap.parse_args().kill)} sandbox(es) tagged {TAG} under app {APP}")
