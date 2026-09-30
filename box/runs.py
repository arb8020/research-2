"""What `box run` records on a box (labels) and reads back: whose run it is, what it runs.

Ownership is labels. Every box `box run` launches carries LABEL_BY=BY plus who/what/limit; `who`
lists only those, and `kill` refuses any box without them. Nothing looks a box up by name.
"""

from __future__ import annotations

import getpass
import socket
from dataclasses import dataclass
from datetime import datetime

from box.provider import Box
from box.recipe import Recipe

LABEL_BY = "box.by"
BY = "box run"
KEYS = ("box.cmd", "box.started", "box.user", "box.limit")
CMD_LABEL_LIMIT = 200  # characters of the command kept in its label; `box logs` has the rest


@dataclass(frozen=True)
class Run:
    """A box `box run` launched, as its labels describe it."""

    box_id: str
    gpu: str
    cmd: str
    started: datetime
    user: str
    limit_s: int  # the box's own timeout: past it, the provider should have ended it
    extra: dict[str, str]  # the recipe's labels (tree, volume, ...)


def labels(recipe: Recipe, cmd: str, now: datetime) -> dict[str, str]:
    return {
        **recipe.labels,
        LABEL_BY: BY,
        "box.cmd": cmd[:CMD_LABEL_LIMIT],
        "box.started": now.isoformat(timespec="seconds"),
        "box.user": f"{getpass.getuser()}@{socket.gethostname()}",
        "box.limit": str(recipe.box_timeout),
    }


def parse(box: Box) -> Run | None:
    """The Run a box's labels describe, or None when `box run` did not launch it."""
    raw = box.labels
    if raw.get(LABEL_BY) != BY:
        return None
    missing = [k for k in KEYS if k not in raw]
    if missing:
        raise ValueError(f"{box.provider_id} is labelled {LABEL_BY}={BY} but lacks {missing}: {raw}")
    gpu = box.offering.id if box.offering.gpu_count == 1 else f"{box.offering.id}:{box.offering.gpu_count}"
    extra = {k: v for k, v in raw.items() if k not in (LABEL_BY, *KEYS)}
    return Run(
        box.provider_id, gpu, raw["box.cmd"], datetime.fromisoformat(raw["box.started"]),
        raw["box.user"], int(raw["box.limit"]), extra,
    )  # fmt: skip


def describe(run: Run, now: datetime) -> str:
    minutes = int((now - run.started).total_seconds() // 60)
    extra = "  ".join(f"{k.removeprefix('box.')}={v}" for k, v in sorted(run.extra.items()))
    return f"{run.box_id}  {run.gpu:<10} {minutes:>4}m  {run.user}\n    {extra}\n    cmd: {run.cmd}"


def hints(box_id: str) -> str:
    return f"box logs {box_id} -f    # follow\nbox kill {box_id}       # stop"
