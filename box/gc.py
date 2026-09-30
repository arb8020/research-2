"""`box gc`: what `box run` left behind, and (only with --yes) deleting it. Provider-generic.

    box       a box `box run` launched (labelled) that is past its own limit (box.limit) by more
              than LIMIT_MARGIN_S, which the provider should have enforced. One running longer than --sandbox-hours but
              within its limit is noted, never a candidate: it is someone's long run. Boxes box
              did not launch are invisible here (Provider.list), so never touched.
    volume    a scratch volume: named box-*, created more than --cache-days ago. Every other
              volume is left alone; a layer above (box/kelpie/gc.py) may sweep its own.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from box import runs
from box.provider import Box, Provider

SCRATCH_PREFIX = "box-"
DAY_S = 86400
HOUR_S = 3600
LIMIT_MARGIN_S = 2 * 3600  # longer than any image build between stamping and create


@dataclass(frozen=True)
class Candidate:
    kind: str  # box | volume | cache | local
    what: str
    why: str
    delete: Callable[[], None]


def boxes(provider: Provider, max_age_s: float, now: float) -> tuple[list[Candidate], list[str]]:
    found: list[Candidate] = []
    notes: list[str] = []
    for box in provider.list():
        run = runs.parse(box)
        if run is None:
            notes.append(f"box {box.provider_id}: launched by box, not by `box run`; left alone")
            continue
        age = now - run.started.timestamp()
        what = f"running {age / HOUR_S:.1f} h: {run.cmd[:80]} ({run.user})"
        # box.started is stamped before launch (image build included) and the provider counts
        # from create, so a live box can look past its limit by that much: allow a margin.
        if age > run.limit_s + LIMIT_MARGIN_S:
            found.append(Candidate("box", run.box_id, f"past its {run.limit_s} s limit, {what}", _terminator(box)))
        elif age > max_age_s:
            notes.append(f"long run within its limit (box kill {run.box_id} if yours): {what}")
    return found, notes


def _terminator(box: Box) -> Callable[[], None]:
    return box.terminate


def scratch_volumes(provider: Provider, max_age_s: float, now: float) -> list[Candidate]:
    found = []
    for name, created in provider.volumes():
        age = now - created
        if name.startswith(SCRATCH_PREFIX) and age > max_age_s:
            why = f"scratch volume created {age / DAY_S:.0f} d ago"
            found.append(Candidate("volume", name, why, _volume_deleter(provider, name)))
    return found


def _volume_deleter(provider: Provider, name: str) -> Callable[[], None]:
    return lambda: provider.delete_volume(name)


def collect(provider: Provider, box_hours: float, cache_days: float) -> tuple[list[Candidate], list[str]]:
    now = time.time()
    found, notes = boxes(provider, box_hours * HOUR_S, now)
    found += scratch_volumes(provider, cache_days * DAY_S, now)
    rules = [
        f"boxes: `box run` ones past their own limit; noted if running > {box_hours:g} h",
        f"volumes: {SCRATCH_PREFIX}* created > {cache_days:g} d ago",
    ]
    return found, [*rules, *notes]
