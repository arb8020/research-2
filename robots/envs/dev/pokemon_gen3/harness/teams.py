"""Team provenance and Pokemon Showdown normalization boundary."""

from __future__ import annotations

import hashlib
import json
import os
import select
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

FORMAT_ID = "gen3ou"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TeamValidationError(ValueError):
    """A TeamSource did not denote a complete legal Gen 3 OU team."""


class TeamSource(Protocol):
    """Provenance for an untrusted Showdown team representation."""

    def read(self) -> str: ...


@dataclass(frozen=True)
class ExplicitTeamSource:
    team: str

    def read(self) -> str:
        if not self.team.strip():
            raise ValueError("explicit team must not be empty")
        return self.team


@dataclass(frozen=True)
class PoolSampleTeamSource:
    """Deterministically select one complete team from a curated pool."""

    teams: tuple[str, ...]
    seed: int

    def read(self) -> str:
        if not self.teams:
            raise ValueError("team pool must not be empty")
        digest = hashlib.sha256(str(self.seed).encode()).digest()
        index = int.from_bytes(digest[:8], "big") % len(self.teams)
        return self.teams[index]


@dataclass(frozen=True)
class TeamSpec:
    """A complete team after Showdown has normalized and validated it."""

    format_id: str
    packed: str
    exported: str
    normalized_json: str
    battle_team_json: str

    def normalized(self) -> list[dict[str, object]]:
        return json.loads(self.normalized_json)

    def battle_team(self) -> dict[str, object]:
        """Return a fresh copy of the canonical C-facing payload."""
        return json.loads(self.battle_team_json)


def default_showdown_dir() -> Path:
    configured = os.environ.get("POKEMON_SHOWDOWN_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return (_PROJECT_ROOT / "third_party" / "pokemon-showdown").resolve()


class ShowdownTeamValidator:
    """Own one persistent Node process and fail explicitly if it dies."""

    def __init__(self, showdown_dir: Path | None = None) -> None:
        self.showdown_dir = (showdown_dir or default_showdown_dir()).resolve()
        helper = Path(__file__).with_name("showdown_teams.js")
        self._next_id = 0
        self._process = subprocess.Popen(
            ["node", str(helper), str(self.showdown_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def normalize(self, source: TeamSource) -> TeamSpec:
        if self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("Showdown team helper has no protocol streams")
        request_id = self._next_id
        self._next_id += 1
        request = {"id": request_id, "format": FORMAT_ID, "team": source.read()}
        self._process.stdin.write(json.dumps(request) + "\n")
        self._process.stdin.flush()
        ready, _, _ = select.select([self._process.stdout], [], [], 10.0)
        if not ready:
            raise RuntimeError("Showdown team helper timed out")
        response_line = self._process.stdout.readline()
        if not response_line:
            stderr = self._process.stderr.read() if self._process.stderr else ""
            raise RuntimeError(f"Showdown team helper exited: {stderr.strip()}")
        response = json.loads(response_line)
        if response.get("id") != request_id:
            raise RuntimeError("Showdown team helper response ID mismatch")
        if not response.get("ok"):
            detail = response.get("error") or "\n".join(response.get("problems", []))
            raise TeamValidationError(detail)
        normalized_json = json.dumps(
            response["team"], sort_keys=True, separators=(",", ":")
        )
        battle_team_json = json.dumps(
            response["battle_team"], sort_keys=True, separators=(",", ":")
        )
        return TeamSpec(
            format_id=FORMAT_ID,
            packed=response["packed"],
            exported=response["exported"],
            normalized_json=normalized_json,
            battle_team_json=battle_team_json,
        )

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stderr:
            self._process.stderr.close()

    def __enter__(self) -> ShowdownTeamValidator:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def normalize_battle_teams(
    first: TeamSource,
    second: TeamSource,
    validator: ShowdownTeamValidator,
) -> tuple[TeamSpec, TeamSpec]:
    """Normalize both sides through the same pinned Showdown process."""
    return validator.normalize(first), validator.normalize(second)
