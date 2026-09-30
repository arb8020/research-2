import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from diff import (
    BattleSpec,
    Divergence,
    EngineState,
    Seed,
    SeedStatus,
    ShowdownState,
    build_artifact,
    extract_legal_choices,
    load_case,
    load_corpus,
    parse_showdown_output,
    run_battle,
    SeededPicker,
    write_artifact,
    diff_states,
    _showdown_protocol_events,
)
from teams import TeamSpec

ROOT = Path(__file__).resolve().parents[1]


def team(packed):
    return TeamSpec("gen3ou", packed, "export", "[]", '{"pokemon":[]}')


def request(*, trapped=False):
    return {
        "side": {
            "pokemon": [
                {"condition": "100/100", "active": False},
                {"condition": "80/100", "active": True},
                {"condition": "0 fnt", "active": False},
            ],
        },
        "active": [{
            "trapped": trapped,
            "moves": [
                {"pp": 10, "disabled": False},
                {"pp": 5, "disabled": False},
                {"pp": 0, "disabled": False},
            ],
        }],
    }


class LegalChoicesTest(unittest.TestCase):
    def test_active_slot_is_not_assumed_to_be_first(self):
        self.assertEqual(
            extract_legal_choices(request()),
            ["switch 1", "move 1", "move 2"],
        )

    def test_trapping_only_removes_switches(self):
        self.assertEqual(
            extract_legal_choices(request(trapped=True)),
            ["move 1", "move 2"],
        )

    def test_force_switch_with_no_bench_requires_pass(self):
        value = request()
        value["forceSwitch"] = [True]
        for pokemon in value["side"]["pokemon"]:
            pokemon["condition"] = "0 fnt"
        self.assertEqual(extract_legal_choices(value), ["pass"])


class ProtocolParserTest(unittest.TestCase):
    def test_empty_wait_requests_are_observed_not_missing(self):
        raw = (
            'sideupdate\np1\n|request|{"wait":true}\n\n'
            'sideupdate\np2\n|request|{"wait":true}\n\n'
        )
        parsed = parse_showdown_output(raw)
        self.assertTrue(parsed.requests_complete)
        self.assertEqual(parsed.request_p1, {"wait": True})
        self.assertEqual(parsed.request_p2, {"wait": True})

    def test_non_request_sideupdates_do_not_complete_a_boundary(self):
        raw = (
            "sideupdate\np1\n|-activate|p1a: Skarmory|move: Struggle\n\n"
            "sideupdate\np2\n|-activate|p2a: Skarmory|move: Struggle\n\n"
        )
        parsed = parse_showdown_output(raw)
        self.assertFalse(parsed.requests_complete)
        self.assertIsNone(parsed.request_p1)
        self.assertIsNone(parsed.request_p2)

    def test_switch_events_ignore_public_percentage_duplicate(self):
        spec = TeamSpec(
            "gen3ou", "packed", "export",
            '[{"species":"Blissey","moves":["Seismic Toss"]}]',
            '{"pokemon":[{"species_id":242,"move_ids":[69]}]}',
        )
        protocol = [
            "|split|p1",
            "|switch|p1a: Egg|Blissey, F|651/651",
            "|switch|p1a: Egg|Blissey, F|100/100",
        ]
        self.assertEqual(
            _showdown_protocol_events(protocol, (spec, spec)),
            [("switch", 0, 242, 0, 651, 651)],
        )


class ArtifactTest(unittest.TestCase):
    def test_single_corpus_case_loads_through_public_replay_loader(self):
        case = ROOT / "regressions" / "gen3ou" / "cases" / \
            "seed42-battle09-tied-double-switch.json"
        replay = load_case(case, validate_teams=False)
        self.assertEqual(replay.case_name, "seed42-battle09-tied-double-switch")
        self.assertEqual(replay.recorded_choices, (("switch 2", "switch 2"),))

    def test_artifact_round_trips_as_a_replay_case(self):
        spec = BattleSpec(
            3, 7, "gen3ou", (1, 2, 3, 4), (team("a"), team("b")), (),
        )
        engine = EngineState([], SeedStatus.UNAVAILABLE, [], [], None, False, True, [])
        oracle = ShowdownState(
            ["|turn|1"], SeedStatus.UNAVAILABLE, ["move 1"], ["move 1"],
            None, False, [("update", "|turn|1")],
        )
        divergence = Divergence(0, "protocol", [], ["|turn|1"])
        artifact = build_artifact(
            spec, [("move 1", "move 1")], divergence, engine, oracle,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "case.json"
            write_artifact(path, artifact)
            replay = load_case(path, validate_teams=False)

        self.assertEqual(replay.teams_packed, ("a", "b"))
        self.assertEqual(replay.battle_seed, (1, 2, 3, 4))
        self.assertEqual(replay.recorded_choices, (("move 1", "move 1"),))
        self.assertEqual(artifact["engine"]["prng_seed"], "UNAVAILABLE")
        self.assertEqual(artifact["oracle"]["prng_seed"], "UNAVAILABLE")

    def test_corpus_manifest_preserves_named_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cases").mkdir()
            (root / "teams").mkdir()
            (root / "teams" / "a.txt").write_text("a")
            (root / "teams" / "b.txt").write_text("b")
            case = {
                "schema_version": 1,
                "name": "second",
                "format": "gen3ou",
                "battle_index": 7,
                "battle_seed": [1, 2, 3, 4],
                "team_files": ["../teams/a.txt", "../teams/b.txt"],
                "choices": [["move 1", "move 1"]],
                "expected": {"terminal": False},
            }
            (root / "cases" / "second.json").write_text(json.dumps(case))
            case["name"] = "first"
            (root / "cases" / "first.json").write_text(json.dumps(case))
            manifest = {
                "schema_version": 1,
                "format": "gen3ou",
                "showdown_commit": "6e71625b9e6cffeda268b548ae7f43a7643fc3f0",
                "cases": [
                    {"name": "second", "path": "cases/second.json"},
                    {"name": "first", "path": "cases/first.json"},
                ],
            }
            (root / "manifest.json").write_text(json.dumps(manifest))
            with patch("diff.PROJECT_ROOT", root):
                specs = load_corpus(root, validate_teams=False)

        self.assertEqual([spec.case_name for spec in specs], ["second", "first"])
        self.assertTrue(all(spec.stop_after_recorded for spec in specs))
        self.assertEqual(specs[0].recorded_choices, (("move 1", "move 1"),))

    def test_corpus_rejects_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "schema_version": 1,
                "format": "gen3ou",
                "showdown_commit": "6e71625b9e6cffeda268b548ae7f43a7643fc3f0",
                "cases": [
                    {"name": "same", "path": "a.json"},
                    {"name": "same", "path": "b.json"},
                ],
            }
            (root / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "duplicate corpus case name"):
                load_corpus(root, validate_teams=False)


class BattleLoopTest(unittest.TestCase):
    def test_regression_case_stops_without_using_picker(self):
        oracle_state = ShowdownState(
            [], SeedStatus.UNAVAILABLE, ["move 1"], ["move 1"],
            None, False, [],
        )
        engine_state = EngineState(
            [], SeedStatus.UNAVAILABLE, [0], [0], None, False, False, [],
        )

        class Oracle:
            def start(self, format_id, seed, teams):
                return oracle_state

            def step(self, p1, p2):
                return oracle_state

        class Engine:
            def start(self, teams, seed):
                return engine_state

            def step(self, p1, p2):
                return engine_state

        class Picker:
            def pick(self, options):
                raise AssertionError("corpus replay must not synthesize choices")

        spec = BattleSpec(
            0, 7, "gen3ou", (1, 2, 3, 4), (team("a"), team("b")),
            (("move 1", "move 1"),), "named-case", True, False,
        )
        result = run_battle(Oracle(), Engine(), Picker(), spec)
        self.assertTrue(result.ok)
        self.assertEqual(result.turns, 1)

    def test_stops_at_first_divergent_boundary(self):
        oracle_initial = ShowdownState(
            [], SeedStatus.UNAVAILABLE, ["move 1"], ["move 1"], None, False, [],
        )
        oracle_after = ShowdownState(
            ["|turn|1"], SeedStatus.UNAVAILABLE,
            ["move 1"], ["move 1"], None, False, [],
        )
        engine_initial = EngineState(
            [], SeedStatus.UNAVAILABLE, [0], [0], None, False, False, [],
        )
        engine_after = EngineState(
            ["|different|"], SeedStatus.UNAVAILABLE,
            [0], [0], None, False, False, [],
            unsupported="move execution is not implemented",
        )

        class Oracle:
            def start(self, format_id, seed, teams):
                return oracle_initial

            def step(self, p1, p2):
                return oracle_after

        class Engine:
            def start(self, teams, seed):
                return engine_initial

            def step(self, p1, p2):
                return engine_after

        spec = BattleSpec(
            0, 7, "gen3ou", (1, 2, 3, 4), (team("a"), team("b")), (),
        )
        result = run_battle(Oracle(), Engine(), SeededPicker(7), spec)

        self.assertEqual(result.turns, 1)
        self.assertEqual(len(result.divs), 1)
        self.assertEqual(result.divs[0].kind, "unsupported_action")

    def test_terminal_disagreement_is_a_divergence(self):
        engine = EngineState(
            [], SeedStatus.UNAVAILABLE, [], [], None, False, False, [],
        )
        oracle = ShowdownState(
            [], SeedStatus.UNAVAILABLE, [], [], "p1", True, [],
        )
        kinds = [value.kind for value in diff_states(3, engine, oracle)]
        self.assertIn("done", kinds)
        self.assertIn("winner", kinds)

    def test_prng_disagreement_is_a_divergence(self):
        engine = EngineState(
            [], Seed((1, 2, 3, 4)), [], [], None, False, False, [],
        )
        oracle = ShowdownState(
            [], Seed((1, 2, 3, 5)), [], [], None, False, [],
        )
        divergences = diff_states(3, engine, oracle)
        self.assertEqual([value.kind for value in divergences], ["prng_seed"])

    def test_protocol_event_disagreement_is_a_divergence(self):
        engine = EngineState(
            [], SeedStatus.UNAVAILABLE, [], [], None, False, False, [],
            protocol_events=[("switch", 0, 1, 0, 100, 100)],
        )
        oracle = ShowdownState(
            [], SeedStatus.UNAVAILABLE, [], [], None, False, [],
            protocol_events=[("switch", 1, 1, 0, 100, 100)],
        )
        divergences = diff_states(3, engine, oracle)
        self.assertEqual(
            [value.kind for value in divergences], ["protocol_events"]
        )

    def test_turn_limit_is_not_reported_as_pass(self):
        state = ShowdownState(
            [], SeedStatus.UNAVAILABLE, ["move 1"], ["move 1"],
            None, False, [],
        )
        native = EngineState(
            [], SeedStatus.UNAVAILABLE, [0], [0], None, False, False, [],
        )

        class Oracle:
            def start(self, format_id, seed, teams):
                return state

            def step(self, p1, p2):
                return state

        class Engine:
            def start(self, teams, seed):
                return native

            def step(self, p1, p2):
                return native

        spec = BattleSpec(
            0, 7, "gen3ou", (1, 2, 3, 4), (team("a"), team("b")), (),
        )
        with patch("diff.MAX_TURNS", 2):
            result = run_battle(Oracle(), Engine(), SeededPicker(7), spec)
        self.assertEqual(result.divs[0].kind, "turn_limit")

    def test_agreed_terminal_state_passes(self):
        terminal = ShowdownState(
            [], SeedStatus.UNAVAILABLE, [], [], "p1", True, [],
        )
        native = EngineState(
            [], SeedStatus.UNAVAILABLE, [], [], "p1", True, False, [],
        )

        class Oracle:
            def start(self, format_id, seed, teams):
                return terminal

        class Engine:
            def start(self, teams, seed):
                return native

        spec = BattleSpec(
            0, 7, "gen3ou", (1, 2, 3, 4), (team("a"), team("b")), (),
        )
        result = run_battle(Oracle(), Engine(), SeededPicker(7), spec)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
