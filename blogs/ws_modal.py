"""verify_workspace.py --modal: box's relay on Modal (CPU, the lesson image engine/kernel.Dockerfile, the persist dir
on a Volume made for the run) in front of the page, and sh() into the session's sandbox.

Modal profile arb8020 (never herdora). Every session is labelled box.purpose=verify-workspace under box's app;
`uv run --with modal ws_modal.py [--kill]` lists (and ends) leftovers, and verify_workspace.py checks there are none
when it finishes.
"""

from __future__ import annotations

import os
import sys
import tomllib
import warnings
from pathlib import Path

os.environ.setdefault("MODAL_PROFILE", "arb8020")
assert os.environ["MODAL_PROFILE"] != "herdora", "verify_workspace never runs on the herdora workspace"
import modal  # noqa: E402 (after the profile is pinned)

# playwright's sync API runs an event loop on this thread, so Modal's blocking calls warn that they are "in an async
# context". They are only ever called from this one thread, between playwright calls: the warning is noise here.
warnings.filterwarnings("ignore", category=modal.exception.AsyncUsageWarning)

APP = "box"
TAG = {"box.purpose": "verify-workspace"}
ROOT = "/box/services/jupyter"  # Jupyter's root_dir and the kernel's cwd (the relay's $BOX_JOB_DIR)
PERSIST = "/ws/workspace-persist"  # $BLOGS_WS_PERSIST in engine/kernel.Dockerfile, on the Volume at /ws
IMAGE = Path(__file__).parent / "engine" / "kernel.Dockerfile"


def token() -> tuple[str, str]:
    profile = tomllib.loads((Path.home() / ".modal.toml").read_text())[os.environ["MODAL_PROFILE"]]
    return profile["token_id"], profile["token_secret"]


class ModalBox:
    """The sessions the relay starts on Modal; sh() runs commands in the newest one's Jupyter root."""

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
    """Sandboxes still running under box's app with TAG. Looks the app up without creating it."""
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
    print(f"{leftovers(kill='--kill' in sys.argv)} sandbox(es) tagged {TAG} under app {APP}")
