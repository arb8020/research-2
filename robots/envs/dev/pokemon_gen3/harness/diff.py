#!/usr/bin/env python3
"""
Diff harness: run the same battle through our C engine and Showdown,
compare protocol output + PRNG seed after each turn.

    python harness/diff.py --battles 10 --seed 42 --format gen3ou

Exit 0 = all modeled semantics match. Exit 1 writes a replayable first-divergence
artifact. The native engine rejects the first boundary outside its explicit
mechanic slices without mutating state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any

from c_engine import (
    IsolatedNativeEngine,
    NativeEngineCrash,
    build_engine_library,
)
from teams import (
    ExplicitTeamSource,
    PoolSampleTeamSource,
    ShowdownTeamValidator,
    TeamSpec,
    default_showdown_dir,
)

SHOWDOWN_DIR = default_showdown_dir()
MAX_TURNS = 500
MIN_SIDEUPDATE_LINES = 3
DEFAULT_TEAM_POOL = (
    Path(__file__).parent.parent / "fixtures" / "gen3ou"
)
PROJECT_ROOT = Path(__file__).parent.parent
PINNED_SHOWDOWN_COMMIT = "6e71625b9e6cffeda268b548ae7f43a7643fc3f0"


# ── Entry point ─────────────────────────────────────────────────────

def main():
    args = parse_args()
    build_engine_library()
    if args.corpus is not None:
        if args.team_p1 is not None or args.team_p2 is not None:
            raise ValueError("--corpus cannot be combined with explicit teams")
        battle_specs = load_corpus(args.corpus)
    elif args.case is not None:
        battle_specs = [load_case(args.case)]
    else:
        battle_specs = resolve_battle_specs(args)

    jobs = args.jobs if args.jobs > 0 else max(1, os.cpu_count() // 2)
    if jobs == 1:
        results = _run_sequential(battle_specs)
    else:
        results = _run_parallel(battle_specs, jobs)

    r = build_report(results, len(battle_specs))
    print(r.format())
    first_failure = next((result for result in results if not result.ok), None)
    if first_failure is not None:
        write_artifact(args.artifact, first_failure.artifact)
        print(f"\nreplay artifact: {args.artifact}")
    sys.exit(0 if r.ok else 1)


@dataclass(frozen=True)
class BattleSpec:
    index: int
    action_seed: int
    format_id: str
    battle_seed: tuple[int, int, int, int]
    teams: tuple[TeamSpec, TeamSpec]
    recorded_choices: tuple[tuple[str | None, str | None], ...]
    case_name: str | None = None
    stop_after_recorded: bool = False
    expected_terminal: bool | None = None
    expected_winner: str | None = None

    @property
    def teams_packed(self) -> tuple[str, str]:
        return self.teams[0].packed, self.teams[1].packed


def _run_one_battle(spec: BattleSpec) -> BattleResult:
    """Run a single battle. Each call owns its own oracle + engine.
    Thread-safe: no shared mutable state."""
    oracle = ShowdownOracle()
    engine = CEngine()
    picker = SeededPicker(spec.action_seed ^ spec.index)
    try:
        result = run_battle(oracle, engine, picker, spec)
        result.case_name = spec.case_name
        return result
    finally:
        oracle.close()
        engine.close()


def _run_sequential(specs: list[BattleSpec]) -> list[BattleResult]:
    return [_run_one_battle(spec) for spec in specs]


def _run_parallel(
    specs: list[BattleSpec], jobs: int,
) -> list[BattleResult]:
    results: list[BattleResult] = [None] * len(specs)  # type: ignore[list-item]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(_run_one_battle, spec): idx
            for idx, spec in enumerate(specs)
        }
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()
    return results


def parse_args():
    p = argparse.ArgumentParser(description="Diff harness: C engine vs Showdown")
    p.add_argument("--battles", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--format", default="gen3ou")
    p.add_argument("--jobs", "-j", type=int, default=0,
                   help="parallel battles, 0=auto (half of CPU cores)")
    p.add_argument("--verbose", "-v", action="store_true")
    replay = p.add_mutually_exclusive_group()
    replay.add_argument("--case", type=Path,
                        help="replay a divergence artifact and continue")
    replay.add_argument("--corpus", type=Path,
                        help="replay the named cases in a regression manifest")
    p.add_argument("--team-p1", type=Path, help="explicit p1 Showdown export")
    p.add_argument("--team-p2", type=Path, help="explicit p2 Showdown export")
    p.add_argument(
        "--team-pool", type=Path, default=DEFAULT_TEAM_POOL,
        help="directory of complete Showdown team exports",
    )
    p.add_argument("--artifact", type=Path,
                   default=Path("failures/first-divergence.json"))
    return p.parse_args()


def resolve_battle_specs(args: argparse.Namespace) -> list[BattleSpec]:
    """Resolve untrusted TeamSources once, before parallel battle execution."""
    if args.format != "gen3ou":
        raise ValueError("this vertical slice supports only gen3ou")
    if not 1 <= args.battles <= 0x10000:
        raise ValueError("--battles must be between 1 and 65536")
    explicit = args.team_p1 is not None or args.team_p2 is not None
    if explicit and (args.team_p1 is None or args.team_p2 is None):
        raise ValueError("--team-p1 and --team-p2 must be supplied together")
    pool = () if explicit else load_team_pool(args.team_pool)
    cache: dict[str, TeamSpec] = {}
    specs: list[BattleSpec] = []
    with ShowdownTeamValidator() as validator:
        for index in range(args.battles):
            if explicit:
                sources = (
                    ExplicitTeamSource(args.team_p1.read_text()),
                    ExplicitTeamSource(args.team_p2.read_text()),
                )
            else:
                sources = (
                    PoolSampleTeamSource(pool, args.seed ^ (index * 2)),
                    PoolSampleTeamSource(pool, args.seed ^ (index * 2 + 1)),
                )
            raw = (sources[0].read(), sources[1].read())
            missing = [value for value in raw if value not in cache]
            for value in missing:
                cache[value] = validator.normalize(ExplicitTeamSource(value))
            teams = cache[raw[0]], cache[raw[1]]
            specs.append(BattleSpec(
                index=index,
                action_seed=args.seed,
                format_id="gen3ou",
                battle_seed=(
                    (args.seed ^ index) & 0xFFFF,
                    args.seed & 0xFFFF,
                    index & 0xFFFF,
                    0,
                ),
                teams=teams,
                recorded_choices=(),
            ))
    return specs


def load_team_pool(path: Path) -> tuple[str, ...]:
    if not path.is_dir():
        raise ValueError(f"team pool must be a directory: {path}")
    teams = tuple(file.read_text() for file in sorted(path.glob("*.txt")))
    if not teams:
        raise ValueError(f"team pool contains no .txt exports: {path}")
    return teams


# ── Battle result + reporting ───────────────────────────────────────

@dataclass
class BattleResult:
    index: int
    divs: list[Divergence]
    turns: int
    artifact: dict[str, Any]
    case_name: str | None = None

    @property
    def ok(self) -> bool:
        return not self.divs


@dataclass
class Report:
    total_divs: int
    passed: int
    n_battles: int
    first_div: Divergence | None
    first_fail_index: int | None
    first_fail_name: str | None
    by_kind: dict[str, int]
    per_battle: list[tuple[str | None, int, int, int]]

    @property
    def ok(self) -> bool:
        return self.total_divs == 0

    def format(self) -> str:
        lines: list[str] = []

        if self.ok:
            lines.append(f"PASS  {self.n_battles} battles, 0 divergences")
            for name, idx, _, turns in self.per_battle:
                if name is not None:
                    lines.append(f"  case {name}: PASS ({turns} boundaries, battle {idx})")
            return "\n".join(lines)

        lines.append(
            f"FAIL  {self.passed}/{self.n_battles} passed, "
            f"{self.total_divs} divergences"
        )
        lines.append("")

        if self.first_div is not None:
            subject = (
                f"case {self.first_fail_name} (battle {self.first_fail_index})"
                if self.first_fail_name is not None
                else f"battle {self.first_fail_index}"
            )
            lines.append(
                f"first divergence: {subject}, "
                f"turn {self.first_div.turn}, {self.first_div.kind}"
            )
            lines.append(f"  engine: {self.first_div.engine_value}")
            lines.append(f"  oracle: {self.first_div.oracle_value}")
            lines.append("")

        lines.append("by kind:")
        for kind, count in sorted(
            self.by_kind.items(), key=lambda kv: -kv[1],
        ):
            lines.append(f"  {kind}: {count}")
        lines.append("")

        for name, idx, n_divs, turns in self.per_battle:
            subject = f"case {name} (battle {idx})" if name is not None else f"battle {idx}"
            if n_divs == 0:
                lines.append(f"  {subject}: PASS ({turns} turns)")
            else:
                lines.append(f"  {subject}: FAIL ({n_divs} divs, {turns} turns)")

        return "\n".join(lines)


def build_report(results: list[BattleResult], n_battles: int) -> Report:
    """Summarize battle results into a report. Pure function."""
    total = sum(len(r.divs) for r in results)
    passed = sum(1 for r in results if r.ok)

    first_div = None
    first_fail_index = None
    first_fail_name = None
    for r in results:
        if not r.ok:
            first_div = r.divs[0]
            first_fail_index = r.index
            first_fail_name = r.case_name
            break

    kinds: Counter[str] = Counter()
    for r in results:
        for d in r.divs:
            kinds[d.kind] += 1

    per_battle = [
        (r.case_name, r.index, len(r.divs), r.turns) for r in results
    ]

    return Report(
        total_divs=total,
        passed=passed,
        n_battles=n_battles,
        first_div=first_div,
        first_fail_index=first_fail_index,
        first_fail_name=first_fail_name,
        by_kind=dict(kinds),
        per_battle=per_battle,
    )


# ── Battle loop ─────────────────────────────────────────────────────

def run_battle(
    oracle: ShowdownOracle, engine: CEngine, picker: SeededPicker,
    spec: BattleSpec,
) -> BattleResult:
    """Run one battle until its first semantic divergence."""
    seed = list(spec.battle_seed)
    oracle_state = oracle.start(spec.format_id, seed, spec.teams)
    choices: list[tuple[str | None, str | None]] = []
    try:
        engine_state = engine.start(spec.teams, seed)
    except NativeEngineCrash as error:
        divergence = Divergence(
            -1,
            "native_engine_crash",
            {"error": str(error), "engine_state": "unavailable during startup"},
            "Showdown initialized the same teams and seed",
        )
        unavailable = EngineState(
            protocol_lines=[], prng_seed=SeedStatus.UNAVAILABLE,
            legal_p1=[], legal_p2=[], winner=None, done=False, is_stub=False,
            raw_blocks=[], protocol_available=False,
            unsupported="native engine died during startup",
        )
        return BattleResult(
            spec.index, [divergence], 0,
            build_artifact(
                spec, choices, divergence, unavailable, oracle_state,
            ),
        )
    initial = first_divergence(-1, engine_state, oracle_state)
    if initial is not None:
        artifact = build_artifact(spec, choices, initial, engine_state, oracle_state)
        return BattleResult(spec.index, [initial], 0, artifact)
    if oracle_state.done:
        if spec.stop_after_recorded and spec.recorded_choices:
            divergence = Divergence(
                -1, "regression_case_ended_early", 0,
                len(spec.recorded_choices),
            )
            return BattleResult(
                spec.index, [divergence], 0,
                build_artifact(
                    spec, choices, divergence, engine_state, oracle_state,
                ),
            )
        return BattleResult(spec.index, [], 0, {})

    if spec.stop_after_recorded and not spec.recorded_choices:
        return _finish_regression_case(spec, 0, oracle_state, engine_state, [])

    for turn in range(MAX_TURNS):
        legal_p1 = oracle_state.legal_p1
        legal_p2 = oracle_state.legal_p2

        if not legal_p1 and not legal_p2:
            divergence = Divergence(
                turn, "invalid_decision_boundary", "no native actions",
                "Showdown has no actions but did not end",
            )
            artifact = build_artifact(
                spec, choices, divergence, engine_state, oracle_state,
            )
            return BattleResult(spec.index, [divergence], turn, artifact)

        if turn < len(spec.recorded_choices):
            choice_p1, choice_p2 = spec.recorded_choices[turn]
            _assert_recorded_choice(choice_p1, legal_p1, "p1", turn)
            _assert_recorded_choice(choice_p2, legal_p2, "p2", turn)
        else:
            choice_p1 = picker.pick(legal_p1) if legal_p1 else None
            choice_p2 = picker.pick(legal_p2) if legal_p2 else None
        choices.append((choice_p1, choice_p2))

        oracle_state = oracle.step(choice_p1, choice_p2)

        action_p1 = showdown_to_action(choice_p1) if choice_p1 else -1
        action_p2 = showdown_to_action(choice_p2) if choice_p2 else -1
        try:
            engine_state = engine.step(action_p1, action_p2)
        except NativeEngineCrash as error:
            # The oracle has already committed this boundary. Keep its
            # resulting state, the submitted pair, and the engine's last
            # valid state; the native assertion remains fatal in its worker.
            divergence = Divergence(
                turn,
                "native_engine_crash",
                {
                    "error": str(error),
                    "action_p1": action_p1,
                    "action_p2": action_p2,
                    "engine_state": "last valid state before submitted actions",
                },
                "Showdown accepted the action pair",
            )
            artifact = build_artifact(
                spec, choices, divergence, engine_state, oracle_state,
            )
            return BattleResult(
                spec.index, [divergence], turn + 1, artifact,
            )

        divergence = first_divergence(turn, engine_state, oracle_state)
        if divergence is not None:
            artifact = build_artifact(
                spec, choices, divergence, engine_state, oracle_state,
            )
            return BattleResult(spec.index, [divergence], turn + 1, artifact)

        if spec.stop_after_recorded and turn + 1 == len(spec.recorded_choices):
            return _finish_regression_case(
                spec, turn + 1, oracle_state, engine_state, choices,
            )

        if oracle_state.done:
            if spec.stop_after_recorded and turn + 1 < len(spec.recorded_choices):
                divergence = Divergence(
                    turn, "regression_case_ended_early", turn + 1,
                    len(spec.recorded_choices),
                )
                artifact = build_artifact(
                    spec, choices, divergence, engine_state, oracle_state,
                )
                return BattleResult(
                    spec.index, [divergence], turn + 1, artifact,
                )
            return BattleResult(spec.index, [], turn + 1, {})

    divergence = Divergence(
        MAX_TURNS, "turn_limit", f"reached {MAX_TURNS} decision boundaries",
        "battle did not terminate",
    )
    artifact = build_artifact(
        spec, choices, divergence, engine_state, oracle_state,
    )
    return BattleResult(spec.index, [divergence], MAX_TURNS, artifact)


def _finish_regression_case(
    spec: BattleSpec,
    boundaries: int,
    oracle: ShowdownState,
    engine: EngineState,
    choices: list[tuple[str | None, str | None]],
) -> BattleResult:
    mismatch: tuple[object, object] | None = None
    if spec.expected_terminal is not None and oracle.done != spec.expected_terminal:
        mismatch = (oracle.done, spec.expected_terminal)
    elif spec.expected_winner is not None and oracle.winner != spec.expected_winner:
        mismatch = (oracle.winner, spec.expected_winner)
    if mismatch is None:
        return BattleResult(spec.index, [], boundaries, {})
    divergence = Divergence(
        boundaries - 1, "regression_expectation", mismatch[0], mismatch[1],
    )
    return BattleResult(
        spec.index, [divergence], boundaries,
        build_artifact(spec, choices, divergence, engine, oracle),
    )


def _assert_recorded_choice(
    choice: str | None, legal: list[str], side: str, turn: int,
) -> None:
    if choice is None and not legal:
        return
    if choice not in legal:
        raise ValueError(
            f"recorded {side} choice {choice!r} is illegal at turn {turn}: {legal}"
        )


# ── Diff logic ──────────────────────────────────────────────────────

@dataclass
class Divergence:
    turn: int
    kind: str
    engine_value: object
    oracle_value: object


def first_divergence(
    turn: int, engine: EngineState, oracle: ShowdownState,
) -> Divergence | None:
    divs = diff_states(turn, engine, oracle)
    return divs[0] if divs else None


def diff_states(
    turn: int, engine: EngineState, oracle: ShowdownState,
) -> list[Divergence]:
    """Compare engine and oracle states. Pure function."""
    divs: list[Divergence] = []

    if engine.unsupported is not None:
        divs.append(Divergence(
            turn, "unsupported_action", engine.unsupported,
            "Showdown accepted the action pair",
        ))

    if not engine.protocol_available:
        divs.append(Divergence(
            turn, "protocol_events_engine_unavailable",
            "UNAVAILABLE", oracle.protocol_events,
        ))
    elif engine.protocol_events != oracle.protocol_events:
        divs.append(Divergence(
            turn, "protocol_events",
            engine.protocol_events, oracle.protocol_events,
        ))

    if engine.done != oracle.done:
        divs.append(Divergence(turn, "done", engine.done, oracle.done))
    if engine.winner != oracle.winner:
        divs.append(Divergence(turn, "winner", engine.winner, oracle.winner))

    engine_p1 = sorted(ACTION_TO_SHOWDOWN[a] for a in engine.legal_p1)
    oracle_p1 = sorted(oracle.legal_p1)
    if engine_p1 != oracle_p1:
        divs.append(Divergence(turn, "legal_choices_p1", engine_p1, oracle_p1))

    engine_p2 = sorted(ACTION_TO_SHOWDOWN[a] for a in engine.legal_p2)
    oracle_p2 = sorted(oracle.legal_p2)
    if engine_p2 != oracle_p2:
        divs.append(Divergence(turn, "legal_choices_p2", engine_p2, oracle_p2))

    # Showdown emits no final request and stops servicing eval commands after
    # the terminal block. Its cached request is the pre-turn state, so the
    # terminal correctness surface is protocol events, done/winner, and empty
    # legal choices. Compare request-derived state and live PRNG only while the
    # oracle still has an actual decision boundary.
    if not oracle.done:
        engine_snapshot = (
            _engine_semantic_snapshot(engine.snapshot) if engine.snapshot else {}
        )
        if bool(engine_snapshot) != bool(oracle.snapshot):
            divs.append(Divergence(
                turn, "battle_state_unavailable",
                bool(engine_snapshot), bool(oracle.snapshot),
            ))
        elif engine_snapshot != oracle.snapshot:
            divs.append(Divergence(
                turn, "battle_state", engine_snapshot, oracle.snapshot,
            ))

        match (engine.prng_seed, oracle.prng_seed):
            case (Seed() as e, Seed() as o) if e.values != o.values:
                divs.append(Divergence(turn, "prng_seed", e.values, o.values))
            case (SeedStatus.UNAVAILABLE, Seed()):
                divs.append(Divergence(
                    turn, "prng_seed_engine_unavailable",
                    "UNAVAILABLE", "available",
                ))
            case (Seed(), SeedStatus.UNAVAILABLE):
                divs.append(Divergence(
                    turn, "prng_seed_oracle_unavailable",
                    "available", "UNAVAILABLE",
                ))
            case _:
                pass

    return divs


# ── Action translation ──────────────────────────────────────────────

ACTION_TO_SHOWDOWN = {
    0: "move 1",  1: "move 2",  2: "move 3",  3: "move 4",
    4: "switch 2", 5: "switch 3", 6: "switch 4",
    7: "switch 5", 8: "switch 6",
}
SHOWDOWN_TO_ACTION = {v: k for k, v in ACTION_TO_SHOWDOWN.items()}


def showdown_to_action(s: str) -> int:
    if s == "pass":
        return -1
    if s not in SHOWDOWN_TO_ACTION:
        raise ValueError(f"Unknown Showdown choice: {s!r}")
    return SHOWDOWN_TO_ACTION[s]


# ── PRNG seed variant ──────────────────────────────────────────────

class SeedStatus(Enum):
    UNAVAILABLE = auto()


@dataclass(frozen=True)
class Seed:
    values: tuple[int, ...]


SeedResult = Seed | SeedStatus


# ── Seeded random picker ───────────────────────────────────────────

class SeededPicker:
    """Deterministic LCG, independent of game PRNG.
    Same constants as pkmn/engine's integration harness."""

    def __init__(self, seed: int):
        self.state = (seed * 0x9E3779B1) & 0xFFFFFFFF

    def pick(self, options: list[str]) -> str:
        assert options, "pick() called with empty options"
        self.state = (self.state * 1664525 + 1013904223) & 0xFFFFFFFF
        idx = int((self.state / 0x100000000) * len(options))
        return options[idx]


# ── Showdown oracle ─────────────────────────────────────────────────

@dataclass
class ShowdownState:
    protocol_lines: list[str]
    prng_seed: SeedResult
    legal_p1: list[str]
    legal_p2: list[str]
    winner: str | None
    done: bool
    raw_blocks: list[tuple[str, str]]
    snapshot: dict[str, object] = field(default_factory=dict)
    protocol_events: list[tuple[str, int, int, int, int, int]] = field(default_factory=list)
    protocol_available: bool = True


class ShowdownOracle:
    """Persistent Showdown subprocess."""

    def __init__(self, node_bin: str = "node"):
        self._node_bin = node_bin
        self._proc: subprocess.Popen | None = None
        self._request_p1: dict = {}
        self._request_p2: dict = {}
        self._teams: tuple[TeamSpec, TeamSpec] | None = None
        self._spikes = [0, 0]
        self._leech_seeded = [False, False]
        self._stat_stages = [[0] * 5 for _ in range(2)]

    @property
    def request_p1(self) -> dict:
        return self._request_p1

    @property
    def request_p2(self) -> dict:
        return self._request_p2

    def start(
        self, format_id: str, seed: list[int],
        teams: tuple[TeamSpec, TeamSpec],
    ) -> ShowdownState:
        """Start a new battle. Spawns a fresh subprocess."""
        self.close()
        self._spikes = [0, 0]
        self._leech_seeded = [False, False]
        self._stat_stages = [[0] * 5 for _ in range(2)]
        self._proc = subprocess.Popen(
            [self._node_bin, str(SHOWDOWN_DIR / "pokemon-showdown"),
             "simulate-battle", "--skip-build"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        start_opts: dict = {"formatid": format_id}
        if seed:
            start_opts["seed"] = seed
        self._send(f">start {json.dumps(start_opts)}")
        p1: dict[str, str] = {"name": "p1"}
        p2: dict[str, str] = {"name": "p2"}
        self._teams = teams
        p1["team"], p2["team"] = teams[0].packed, teams[1].packed
        self._send(f">player p1 {json.dumps(p1)}")
        self._send(f">player p2 {json.dumps(p2)}")

        raw = self._read_raw_until_ready()
        parsed = parse_showdown_output(raw)
        self._apply_requests(parsed)
        return self._state_from(parsed)

    def step(self, choice_p1: str | None, choice_p2: str | None) -> ShowdownState:
        """Send choices, return new state."""
        if choice_p1:
            self._send(f">p1 {choice_p1}")
        if choice_p2:
            self._send(f">p2 {choice_p2}")

        raw = self._read_raw_until_ready()
        parsed = parse_showdown_output(raw)

        self._apply_requests(parsed)

        return self._state_from(parsed)

    def _apply_requests(self, parsed: ParsedBlocks) -> None:
        # A terminal sideupdate can carry an empty request. Preserve the last
        # complete side snapshot so the final state remains observable.
        if parsed.request_p1 is not None and "side" in parsed.request_p1:
            self._request_p1 = parsed.request_p1
        if parsed.request_p2 is not None and "side" in parsed.request_p2:
            self._request_p2 = parsed.request_p2

    def _state_from(self, parsed: ParsedBlocks) -> ShowdownState:
        assert self._teams is not None, "Showdown state requested before teams"
        protocol, winner = _extract_protocol(parsed.blocks)
        for line in protocol:
            if line.startswith("|switch|") or line.startswith("|drag|"):
                side, _ = _protocol_actor(line.split("|")[2])
                self._leech_seeded[side] = False
                self._stat_stages[side] = [0] * 5
            if line.startswith("|-sidestart|") and line.split("|")[3] == "Spikes":
                side = int(line.split("|")[2][1]) - 1
                self._spikes[side] += 1
            if line.startswith("|-start|") and line.split("|")[3] == "move: Leech Seed":
                side, _ = _protocol_actor(line.split("|")[2])
                self._leech_seeded[side] = True
            if line.startswith("|-boost|") or line.startswith("|-unboost|"):
                fields = line.split("|")
                side, _ = _protocol_actor(fields[2])
                stat = STAT_STAGE_IDS[fields[3]] - 1
                amount = int(fields[4])
                direction = 1 if fields[1] == "-boost" else -1
                self._stat_stages[side][stat] = max(
                    -6, min(6, self._stat_stages[side][stat] + direction * amount)
                )

        return ShowdownState(
            protocol_lines=protocol,
            # The battle stream stops servicing eval commands after emitting
            # its terminal block, so no live post-battle seed is observable.
            prng_seed=(
                SeedStatus.UNAVAILABLE if parsed.battle_over
                else self._query_seed()
            ),
            legal_p1=(
                [] if parsed.battle_over
                else extract_legal_choices(self._request_p1)
            ),
            legal_p2=(
                [] if parsed.battle_over
                else extract_legal_choices(self._request_p2)
            ),
            winner=winner,
            done=parsed.battle_over,
            raw_blocks=parsed.blocks,
            snapshot=_showdown_snapshot(
                (self._request_p1, self._request_p2), self._teams, self._spikes,
                self._leech_seeded, self._stat_stages,
            ),
            protocol_events=_showdown_protocol_events(protocol, self._teams),
        )

    def _query_seed(self) -> Seed:
        """Read live PRNG state without changing battle semantics or RNG."""
        self._send(">eval battle.prng.getSeed()")
        assert self._proc is not None
        assert self._proc.stdout is not None
        data = b""
        deadline = time.monotonic() + 10.0
        while b"\n\n" not in data:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                raise RuntimeError("Showdown PRNG query timed out")
            ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
            if not ready:
                raise RuntimeError("Showdown PRNG query timed out")
            chunk = os.read(self._proc.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Showdown closed during PRNG query")
            data += chunk
        text = data.decode()
        match = re.fullmatch(
            r'update\n\|\|>>> battle\.prng\.getSeed\(\)\n'
            r'\|\|<<< "([0-9]+(?:,[0-9]+){3})"\n\n',
            text,
        )
        if match is None:
            raise RuntimeError(f"unexpected Showdown PRNG response: {text!r}")
        values = tuple(int(value) for value in match.group(1).split(","))
        if any(value < 0 or value > 0xFFFF for value in values):
            raise RuntimeError(f"invalid Showdown PRNG seed: {values!r}")
        return Seed(values)

    def close(self):
        if self._proc is not None:
            if self._proc.stdin:
                self._proc.stdin.close()
            if self._proc.poll() is None:
                self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            if self._proc.stdout:
                self._proc.stdout.close()
            if self._proc.stderr:
                self._proc.stderr.close()
            self._proc = None
        self._request_p1 = {}
        self._request_p2 = {}
        self._teams = None
        self._spikes = [0, 0]
        self._leech_seeded = [False, False]

    def _send(self, line: str):
        assert self._proc is not None, "no subprocess"
        assert self._proc.stdin is not None
        self._proc.stdin.write((line + "\n").encode())
        self._proc.stdin.flush()

    def _read_raw_until_ready(self) -> str:
        """Read until both sides have requests or battle is over."""
        assert self._proc is not None
        assert self._proc.stdout is not None
        data = b""
        while True:
            r, _, _ = select.select([self._proc.stdout], [], [], 10.0)
            if not r:
                break
            chunk = os.read(self._proc.stdout.fileno(), 65536)
            if not chunk:
                break
            data += chunk
            text = data.decode()
            parsed = parse_showdown_output(text)
            if parsed.battle_over or parsed.requests_complete:
                return text
        stderr = ""
        if self._proc.poll() is not None and self._proc.stderr is not None:
            stderr = self._proc.stderr.read().decode(errors="replace")
        raise RuntimeError(
            "Showdown stopped before a complete decision boundary; "
            f"returncode={self._proc.poll()}, stderr={stderr!r}, output={data!r}"
        )


# ── C engine driver ─────────────────────────────────────────────────

@dataclass
class EngineState:
    protocol_lines: list[str]
    prng_seed: SeedResult
    legal_p1: list[int]
    legal_p2: list[int]
    winner: str | None
    done: bool
    is_stub: bool
    raw_blocks: list[tuple[str, str]]
    snapshot: dict[str, object] = field(default_factory=dict)
    unsupported: str | None = None
    protocol_events: list[tuple[str, int, int, int, int, int]] = field(default_factory=list)
    protocol_available: bool = True


class CEngine:
    """Translate the harness driver contract onto the opaque native ABI."""

    def __init__(self, lib_path: str | None = None):
        library = Path(lib_path) if lib_path is not None else None
        self._native = IsolatedNativeEngine(library)

    def start(
        self, teams: tuple[TeamSpec, TeamSpec], seed: list[int],
    ) -> EngineState:
        native = self._native.start(teams, tuple(seed))
        return self._state(native)

    def step(self, action_p1: int, action_p2: int) -> EngineState:
        return self._state(self._native.turn(action_p1, action_p2))

    @staticmethod
    def _state(native) -> EngineState:
        kinds = {
            1: "switch", 2: "move", 3: "damage", 4: "heal", 5: "fail",
            6: "faint", 7: "protect", 8: "block", 9: "status",
            10: "side_start",
            11: "volatile_start",
            12: "boost", 13: "unboost",
        }
        events = []
        for event in native.snapshot["events"]:
            if event["kind"] not in kinds:
                raise RuntimeError(f"unknown native event kind: {event['kind']}")
            events.append((
                kinds[event["kind"]], event["side"], event["species_id"],
                event["status"] if event["kind"] in (9, 12, 13)
                else event["move_id"],
                event["amount"] if event["kind"] in (12, 13)
                else event["hp"],
                event["max_hp"],
            ))
        return EngineState(
            protocol_lines=[],
            prng_seed=Seed(tuple(native.snapshot["seed"])),
            legal_p1=list(native.legal_p1),
            legal_p2=list(native.legal_p2),
            winner=(
                f"p{native.snapshot['winner_side'] + 1}"
                if native.snapshot["done"] else None
            ),
            done=bool(native.snapshot["done"]),
            is_stub=False,
            raw_blocks=[],
            snapshot=native.snapshot,
            unsupported=native.unsupported,
            protocol_events=events,
            protocol_available=native.unsupported is None,
        )

    def close(self):
        self._native.close()


# ── Showdown protocol parsing (pure functions) ─────────────────────

@dataclass(frozen=True)
class ParsedBlocks:
    blocks: list[tuple[str, str]]
    request_p1: dict | None
    request_p2: dict | None
    battle_over: bool

    @property
    def requests_complete(self) -> bool:
        return self.request_p1 is not None and self.request_p2 is not None


def parse_showdown_output(raw: str) -> ParsedBlocks:
    """Parse block-delimited Showdown output. Pure function."""
    blocks: list[tuple[str, str]] = []
    request_p1: dict | None = None
    request_p2: dict | None = None
    battle_over = False

    remaining = raw
    while "\n\n" in remaining:
        block_text, remaining = remaining.split("\n\n", 1)
        if not block_text.strip():
            continue
        lines = block_text.split("\n")
        block_type = lines[0]
        block_body = "\n".join(lines[1:])
        blocks.append((block_type, block_body))

        if block_type == "sideupdate" and len(lines) >= MIN_SIDEUPDATE_LINES:
            side, req = _parse_sideupdate(lines)
            if req is None:
                continue
            if side == "p1":
                request_p1 = req
            elif side == "p2":
                request_p2 = req

        battle_over = battle_over or _check_battle_over(block_type, lines)

    return ParsedBlocks(blocks, request_p1, request_p2, battle_over)


def _parse_sideupdate(lines: list[str]) -> tuple[str, dict | None]:
    side = lines[1]
    rest = "\n".join(lines[2:])
    if not rest.startswith("|request|"):
        return side, None
    req_json = rest[len("|request|"):]
    return side, json.loads(req_json) if req_json else {}


def _check_battle_over(block_type: str, lines: list[str]) -> bool:
    if block_type == "end":
        return True
    if block_type == "update":
        return any(
            line.startswith("|win|") or line == "|tie"
            for line in lines[1:]
        )
    return False


def _extract_protocol(blocks: list[tuple[str, str]]) -> tuple[list[str], str | None]:
    """Extract protocol lines and winner from update blocks."""
    protocol: list[str] = []
    winner = None
    for btype, bbody in blocks:
        if btype == "update":
            for line in bbody.split("\n"):
                if line.startswith("|"):
                    protocol.append(line)
                    if line.startswith("|win|"):
                        winner = line.split("|")[2]
                    elif line == "|tie":
                        winner = "tie"
    return protocol, winner


def _showdown_protocol_events(
    protocol: list[str], teams: tuple[TeamSpec, TeamSpec],
) -> list[tuple[str, int, int, int, int, int]]:
    """Project Showdown text onto presentation-independent native events."""
    species_ids: dict[str, int] = {}
    species_max_hp: dict[int, int] = {}
    actor_ids: dict[tuple[int, str], int] = {}
    move_ids: dict[str, int] = {}
    for side, team in enumerate(teams):
        normalized = team.normalized()
        payload = team.battle_team()["pokemon"]
        for value, data in zip(normalized, payload, strict=True):
            species_ids[value["species"].casefold()] = data["species_id"]
            if "stats" in data:
                species_max_hp[data["species_id"]] = data["stats"]["hp"]
            actor = (value.get("name") or value["species"]).casefold()
            actor_ids[(side, actor)] = data["species_id"]
            for move, move_id in zip(
                value["moves"], data["move_ids"], strict=True,
            ):
                move_ids[move.casefold()] = move_id
    # Struggle is synthesized by Showdown when no requested move has PP, so
    # it is absent from the submitted team but still part of the protocol.
    move_ids["struggle"] = 165

    events: list[tuple[str, int, int, int, int, int]] = []
    last_move: dict[int, int] = {}
    last_move_actor: dict[int, int] = {}
    for index, line in enumerate(protocol):
        if line.startswith("|move|"):
            fields = line.split("|")
            side, actor = _protocol_actor(fields[2])
            move = fields[3].casefold()
            if (side, actor) not in actor_ids or move not in move_ids:
                raise ValueError(f"unknown Showdown move event: {line!r}")
            events.append((
                "move", side, actor_ids[(side, actor)], move_ids[move], 0, 0,
            ))
            last_move[side] = move_ids[move]
            last_move_actor[side] = actor_ids[(side, actor)]
            continue
        if line.startswith("|-fail|"):
            fields = line.split("|")
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids:
                raise ValueError(f"unknown Showdown failure event: {line!r}")
            failure_side = side
            failure_move = last_move.get(side)
            failure_actor = last_move_actor.get(side)
            status_failure_moves = {
                "tox": "toxic",
                "brn": "will-o-wisp",
            }
            if (failure_move is None and len(fields) >= 4 and
                    fields[3] in status_failure_moves):
                source_side = 1 - side
                status_move_id = move_ids.get(status_failure_moves[fields[3]])
                if last_move.get(source_side) == status_move_id:
                    failure_side = source_side
                    failure_move = status_move_id
                    failure_actor = last_move_actor.get(source_side)
            if failure_move is None or failure_actor is None:
                raise ValueError(f"unknown Showdown failure event: {line!r}")
            events.append((
                "fail", failure_side, failure_actor, failure_move, 0, 0,
            ))
            continue
        if line.startswith("|faint|"):
            fields = line.split("|")
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids:
                raise ValueError(f"unknown Showdown faint event: {line!r}")
            events.append((
                "faint", side, actor_ids[(side, actor)], 0, 0, 0,
            ))
            continue
        if line.startswith("|-singleturn|") or line.startswith("|-activate|"):
            fields = line.split("|")
            if len(fields) < 4 or fields[3] not in ("Protect", "move: Protect"):
                continue
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids:
                raise ValueError(f"unknown Showdown Protect event: {line!r}")
            events.append((
                "protect" if fields[1] == "-singleturn" else "block",
                side, actor_ids[(side, actor)], 182, 0, 0,
            ))
            continue
        if line.startswith("|-status|"):
            fields = line.split("|")
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids or fields[3] not in STATUS_IDS:
                raise ValueError(f"unknown Showdown status event: {line!r}")
            events.append((
                "status", side, actor_ids[(side, actor)], STATUS_IDS[fields[3]], 0, 0,
            ))
            continue
        if line.startswith("|-boost|") or line.startswith("|-unboost|"):
            fields = line.split("|")
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids or fields[3] not in STAT_STAGE_IDS:
                raise ValueError(f"unknown Showdown stat-stage event: {line!r}")
            events.append((
                "boost" if fields[1] == "-boost" else "unboost",
                side, actor_ids[(side, actor)], STAT_STAGE_IDS[fields[3]],
                int(fields[4]), 0,
            ))
            continue
        if line.startswith("|-sidestart|"):
            fields = line.split("|")
            if len(fields) < 4 or fields[3] != "Spikes":
                continue
            side_text = fields[2].split(":", 1)[0]
            if side_text not in ("p1", "p2"):
                raise ValueError(f"unknown Showdown side event: {line!r}")
            events.append((
                "side_start", int(side_text[1]) - 1, 0, 191, 0, 0,
            ))
            continue
        if line.startswith("|-start|"):
            fields = line.split("|")
            if len(fields) < 4 or fields[3] != "move: Leech Seed":
                continue
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids:
                raise ValueError(f"unknown Showdown volatile event: {line!r}")
            events.append((
                "volatile_start", side, actor_ids[(side, actor)], 73, 0, 0,
            ))
            continue
        if line not in ("|split|p1", "|split|p2") or index + 1 >= len(protocol):
            continue
        event = protocol[index + 1]
        fields = event.split("|")
        if event.startswith("|switch|"):
            if len(fields) != 5:
                raise ValueError(f"unexpected Showdown switch event: {event!r}")
            side, _ = _protocol_actor(fields[2])
            species = fields[3].split(",", 1)[0].casefold()
            if species not in species_ids:
                raise ValueError(f"unknown switched species: {fields[3]!r}")
            condition = fields[4].split(" ", 1)[0]
            species_id = species_ids[species]
            kind = "switch"
        elif event.startswith("|-damage|") or event.startswith("|-heal|"):
            if len(fields) < 4:
                raise ValueError(f"unexpected Showdown HP event: {event!r}")
            side, actor = _protocol_actor(fields[2])
            if (side, actor) not in actor_ids:
                raise ValueError(f"unknown Showdown HP event actor: {event!r}")
            condition = fields[3].split(" ", 1)[0]
            species_id = actor_ids[(side, actor)]
            kind = "damage" if fields[1] == "-damage" else "heal"
        else:
            continue
        if condition == "0":
            hp_text, max_hp_text = "0", str(species_max_hp[species_id])
        else:
            hp_text, max_hp_text = condition.split("/", 1)
        events.append((
            kind, side, species_id, 0, int(hp_text), int(max_hp_text),
        ))
    return events


def _protocol_actor(text: str) -> tuple[int, str]:
    side_text, actor = text.split("a:", 1)
    if side_text not in ("p1", "p2"):
        raise ValueError(f"unexpected Showdown actor: {text!r}")
    return int(side_text[1]) - 1, actor.strip().casefold()


STATUS_IDS = {"brn": 1, "par": 2, "psn": 3, "tox": 4, "slp": 5, "frz": 6}
STAT_STAGE_IDS = {"atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5}


# ── Legal choice extraction (pure functions) ────────────────────────

def extract_legal_choices(request: dict) -> list[str]:
    """Extract legal choice strings from a |request| JSON.
    Raises on unexpected structure."""
    if not request or request.get("wait"):
        return []

    assert "side" in request, "request missing 'side'"
    side = request["side"]

    if "forceSwitch" in request:
        switches = _living_switches(side)
        return switches if switches else ["pass"]

    if "active" not in request:
        raise ValueError(f"Unsupported request: {list(request.keys())}")

    switches = _living_switches(side)

    assert request["active"], "active list is empty"
    active = request["active"][0]
    moves = _available_moves(active)
    if active.get("trapped", False):
        return moves

    return switches + moves


def _living_switches(side: dict) -> list[str]:
    assert "pokemon" in side, "side missing 'pokemon'"
    switches: list[str] = []
    for i, mon in enumerate(side["pokemon"]):
        if mon.get("active", False):
            continue
        assert "condition" in mon, f"pokemon {i} missing 'condition'"
        if mon["condition"] != "0 fnt":
            switches.append(f"switch {i + 1}")
    return switches


def _available_moves(active: dict) -> list[str]:
    assert "moves" in active, "active missing 'moves'"
    moves: list[str] = []
    for j, move in enumerate(active["moves"]):
        if not move.get("disabled") and move.get("pp", 0) > 0:
            moves.append(f"move {j + 1}")
    if not moves:
        moves.append("move 1")  # Struggle
    return moves


def _showdown_snapshot(
    requests: tuple[dict, dict], teams: tuple[TeamSpec, TeamSpec],
    spikes: list[int] | tuple[int, int] = (0, 0),
    leech_seeded: list[bool] | tuple[bool, bool] = (False, False),
    stat_stages: list[list[int]] | tuple[list[int], list[int]] = ([0] * 5, [0] * 5),
) -> dict[str, object]:
    """Project private requests onto the state currently modeled by C."""
    sides = []
    for request, team in zip(requests, teams, strict=True):
        normalized = team.normalized()
        payload = team.battle_team()["pokemon"]
        species_ids = {
            value["species"].casefold(): data["species_id"]
            for value, data in zip(normalized, payload, strict=True)
        }
        pokemon = []
        for slot, value in enumerate(request["side"]["pokemon"]):
            species = value["details"].split(",", 1)[0].casefold()
            condition_fields = value["condition"].split()
            condition = condition_fields[0]
            pokemon.append({
                "species_id": species_ids[species],
                "hp": int(condition.split("/", 1)[0]),
                "status": STATUS_IDS.get(condition_fields[1], 0)
                if len(condition_fields) > 1 else 0,
                "leech_seeded": bool(leech_seeded[len(sides)]) if slot == 0 else False,
                "stat_stages": list(stat_stages[len(sides)]) if slot == 0 else [0] * 5,
            })
        active_moves = request.get("active", [{}])[0].get("moves", [])
        if all("pp" in move for move in active_moves):
            active_pp = [move["pp"] for move in active_moves]
        elif (len(active_moves) == 1 and
              active_moves[0].get("id") == "struggle"):
            active_mon = next(
                value for value in request["side"]["pokemon"]
                if value.get("active", False)
            )
            active_pp = [0] * len(active_mon["moves"])
        else:
            raise ValueError(
                f"active move request has missing PP outside Struggle: {active_moves!r}"
            )
        sides.append({"pokemon": pokemon, "active_pp": active_pp})
    return {"sides": sides, "spikes": list(spikes)}


def _engine_semantic_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    sides = []
    for pokemon in snapshot["sides"]:
        sides.append({
            "pokemon": [
                {"species_id": value["species_id"], "hp": value["hp"]}
                | {"status": value["status"], "leech_seeded": bool(value["leech_seeded"]),
                   "stat_stages": value["stat_stages"]}
                for value in pokemon
            ],
            "active_pp": [] if snapshot["force_switch_side"] != -1 else pokemon[0]["pp"],
        })
    return {"sides": sides, "spikes": snapshot["spikes"]}


# ── Failure artifacts ───────────────────────────────────────────────

def build_artifact(
    spec: BattleSpec,
    choices: list[tuple[str | None, str | None]],
    divergence: Divergence,
    engine: EngineState,
    oracle: ShowdownState,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "format": spec.format_id,
        "battle_index": spec.index,
        "battle_seed": list(spec.battle_seed),
        "action_seed": spec.action_seed,
        "teams": [asdict(team) for team in spec.teams],
        "choices": [[p1, p2] for p1, p2 in choices],
        "divergence": {
            "turn": divergence.turn,
            "kind": divergence.kind,
            "engine": divergence.engine_value,
            "oracle": divergence.oracle_value,
        },
        "engine": _state_json(engine),
        "oracle": _state_json(oracle),
    }


def _state_json(state: EngineState | ShowdownState) -> dict[str, Any]:
    prng_seed = (
        list(state.prng_seed.values)
        if isinstance(state.prng_seed, Seed) else "UNAVAILABLE"
    )
    return {
        "protocol_lines": state.protocol_lines,
        "protocol_events": state.protocol_events,
        "protocol_available": state.protocol_available,
        "prng_seed": prng_seed,
        "legal_p1": state.legal_p1,
        "legal_p2": state.legal_p2,
        "winner": state.winner,
        "done": state.done,
        "raw_blocks": state.raw_blocks,
        "snapshot": getattr(state, "snapshot", {}),
        "unsupported": getattr(state, "unsupported", None),
    }


def write_artifact(path: Path, artifact: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(artifact, indent=2) + "\n")
    temporary.replace(path)


def load_case(path: Path, *, validate_teams: bool = True) -> BattleSpec:
    value = json.loads(path.read_text())
    if value.get("schema_version") != 1:
        raise ValueError(f"unsupported artifact schema: {value.get('schema_version')!r}")
    if "team_files" in value:
        name = value.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("regression case name must be a nonempty string")
        validator = ShowdownTeamValidator() if validate_teams else None
        try:
            return _load_regression_case(name, path.resolve(), value, {}, validator)
        finally:
            if validator is not None:
                validator.close()
    teams = tuple(TeamSpec(**team) for team in value["teams"])
    if len(teams) != 2:
        raise ValueError("artifact must contain exactly two teams")
    if any(team.format_id != value["format"] for team in teams):
        raise ValueError("artifact team format does not match battle format")
    if validate_teams:
        with ShowdownTeamValidator() as validator:
            canonical = tuple(
                validator.normalize(ExplicitTeamSource(team.packed))
                for team in teams
            )
        if canonical != teams:
            raise ValueError("artifact team denotations are stale or inconsistent")
    return BattleSpec(
        index=value.get("battle_index", 0),
        action_seed=value["action_seed"],
        format_id=value["format"],
        battle_seed=tuple(value["battle_seed"]),
        teams=teams,
        recorded_choices=tuple(tuple(pair) for pair in value["choices"]),
    )


def load_corpus(
    path: Path, *, validate_teams: bool = True,
) -> list[BattleSpec]:
    """Load named finite replay prefixes from a checked-in manifest."""
    manifest_path = path / "manifest.json" if path.is_dir() else path
    value = json.loads(manifest_path.read_text())
    if value.get("schema_version") != 1:
        raise ValueError(
            f"unsupported corpus manifest schema: {value.get('schema_version')!r}"
        )
    if value.get("format") != "gen3ou":
        raise ValueError("regression corpus must use format gen3ou")
    if value.get("showdown_commit") != PINNED_SHOWDOWN_COMMIT:
        raise ValueError("regression corpus does not name the pinned Showdown commit")
    entries = value.get("cases")
    if not isinstance(entries, list) or not entries:
        raise ValueError("regression corpus manifest must contain cases")

    manifest_root = manifest_path.parent.resolve()
    names: set[str] = set()
    paths: set[Path] = set()
    case_paths: list[tuple[str, Path]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("corpus manifest case entries must be objects")
        name = entry.get("name")
        relative = entry.get("path")
        if not isinstance(name, str) or not name:
            raise ValueError("corpus case name must be a nonempty string")
        if name in names:
            raise ValueError(f"duplicate corpus case name: {name}")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"corpus case {name} has no path")
        case_path = (manifest_root / relative).resolve()
        try:
            case_path.relative_to(manifest_root)
        except ValueError as error:
            raise ValueError(f"corpus case escapes manifest directory: {relative}") from error
        if case_path in paths:
            raise ValueError(f"duplicate corpus case path: {relative}")
        names.add(name)
        paths.add(case_path)
        case_paths.append((name, case_path))

    loaded = [
        (name, case_path, json.loads(case_path.read_text()))
        for name, case_path in case_paths
    ]

    cache: dict[Path, TeamSpec] = {}
    validator = ShowdownTeamValidator() if validate_teams else None
    try:
        specs = [
            _load_regression_case(name, case_path, case, cache, validator)
            for name, case_path, case in loaded
        ]
    finally:
        if validator is not None:
            validator.close()
    return specs


def _load_regression_case(
    manifest_name: str,
    path: Path,
    value: dict[str, Any],
    cache: dict[Path, TeamSpec],
    validator: ShowdownTeamValidator | None,
) -> BattleSpec:
    if value.get("schema_version") != 1:
        raise ValueError(
            f"unsupported regression case schema in {path}: "
            f"{value.get('schema_version')!r}"
        )
    if value.get("name") != manifest_name:
        raise ValueError(f"manifest/case name mismatch for {path}")
    if value.get("format") != "gen3ou":
        raise ValueError(f"regression case must use gen3ou: {manifest_name}")
    team_files = value.get("team_files")
    if not isinstance(team_files, list) or len(team_files) != 2:
        raise ValueError(f"regression case must name two team files: {manifest_name}")
    teams: list[TeamSpec] = []
    for relative in team_files:
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"invalid team file in regression case: {manifest_name}")
        team_path = (path.parent / relative).resolve()
        try:
            team_path.relative_to(PROJECT_ROOT.resolve())
        except ValueError as error:
            raise ValueError(f"team file escapes component root: {relative}") from error
        if team_path not in cache:
            if validator is None:
                cache[team_path] = TeamSpec("gen3ou", team_path.read_text(), "", "[]", "{}")
            else:
                cache[team_path] = validator.normalize(
                    ExplicitTeamSource(team_path.read_text())
                )
        teams.append(cache[team_path])

    seed = value.get("battle_seed")
    if (not isinstance(seed, list) or len(seed) != 4 or
        any(not isinstance(word, int) or not 0 <= word <= 0xFFFF for word in seed)):
        raise ValueError(f"invalid battle seed in regression case: {manifest_name}")
    raw_choices = value.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise ValueError(f"regression case must contain choices: {manifest_name}")
    choices: list[tuple[str | None, str | None]] = []
    for pair in raw_choices:
        if (not isinstance(pair, list) or len(pair) != 2 or
            any(choice is not None and not isinstance(choice, str) for choice in pair)):
            raise ValueError(f"invalid choice pair in regression case: {manifest_name}")
        choices.append((pair[0], pair[1]))
    expected = value.get("expected")
    if not isinstance(expected, dict) or not isinstance(expected.get("terminal"), bool):
        raise ValueError(f"regression case must declare expected.terminal: {manifest_name}")
    winner = expected.get("winner")
    if winner is not None and winner not in ("p1", "p2"):
        raise ValueError(f"invalid expected winner in regression case: {manifest_name}")
    if winner is not None and not expected["terminal"]:
        raise ValueError(f"nonterminal regression case cannot name a winner: {manifest_name}")

    return BattleSpec(
        index=value.get("battle_index", 0),
        action_seed=value.get("action_seed", 0),
        format_id="gen3ou",
        battle_seed=tuple(seed),
        teams=(teams[0], teams[1]),
        recorded_choices=tuple(choices),
        case_name=manifest_name,
        stop_after_recorded=True,
        expected_terminal=expected["terminal"],
        expected_winner=winner,
    )


if __name__ == "__main__":
    main()
