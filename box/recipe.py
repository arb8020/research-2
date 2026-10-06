"""What `box run` launches and spawns, in the SDK's own terms (Provider.launch kwargs, Box.spawn).

A recipe is how a layer above the SDK (box/kelpie) says "this image, these mounts, this command"
without the CLI knowing anything about it. `plain` is the recipe with no layer at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from box.provider import Mount

GRACE_S = 1800  # box lifetime beyond the job's timeout: image pull, setup, HF warm, teardown


@dataclass(frozen=True)
class Recipe:
    image: str | None  # Provider.launch(image=): Dockerfile path, OCI ref, provider name, None
    mounts: dict[str, str | Mount]
    volumes: dict[str, str]  # {volume name: mount path}
    cmd: str  # what Box.spawn runs; the env var BOX_ID holds the box's id
    job_timeout: int | None  # Box.spawn(timeout=); None when cmd enforces its own
    box_timeout: int  # Provider.launch(timeout=): the most the box may live
    labels: dict[str, str] = field(default_factory=dict)
    spans: tuple[str, str] | None = None  # (volume, path with {box_id}): JSONL for --log-file
    pull: tuple[str, str, str] | None = None  # (volume, dir with {box_id}, local dir): copied home after the job


def plain(image: str | None, volumes: dict[str, str], cmd: str, timeout: int) -> Recipe:
    return Recipe(image, {}, volumes, cmd, timeout, timeout + GRACE_S)
