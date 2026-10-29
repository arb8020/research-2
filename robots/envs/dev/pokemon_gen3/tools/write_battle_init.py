#!/usr/bin/env python3
"""Normalize two Showdown exports into one Ocean Gen3BattleInit payload."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))

from c_engine import write_battle_init  # noqa: E402
from teams import ExplicitTeamSource, ShowdownTeamValidator  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("team_p1", type=Path)
    parser.add_argument("team_p2", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", nargs=4, type=int, default=(0, 0, 0, 0))
    args = parser.parse_args()
    seed = tuple(args.seed)
    if any(value < 0 or value > 0xFFFF for value in seed):
        parser.error("seed words must be in 0..65535")
    with ShowdownTeamValidator() as validator:
        teams = (
            validator.normalize(ExplicitTeamSource(args.team_p1.read_text())),
            validator.normalize(ExplicitTeamSource(args.team_p2.read_text())),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_battle_init(teams, seed, args.output)


if __name__ == "__main__":
    main()
