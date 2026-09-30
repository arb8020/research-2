from __future__ import annotations

import ctypes
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "tests"))

from c_engine import (  # noqa: E402
    BattleInit,
    BattleSnapshot,
    BattleTeam,
    IsolatedNativeEngine,
    NativeEngine,
    NativeEngineCrash,
    PokemonSet,
    write_battle_init,
)
from teams import (  # noqa: E402
    ExplicitTeamSource,
    ShowdownTeamValidator,
    TeamSpec,
    default_showdown_dir,
)
from test_teams import TEAM  # noqa: E402


class NativeEngineIsolationTest(unittest.TestCase):
    def test_native_abort_is_reported_without_killing_python(self) -> None:
        pokemon = {
            "species_id": 1, "item_id": 0, "ability_id": 1,
            "move_ids": [1, 1, 1, 1], "stats": {
                "hp": 1, "atk": 1, "def": 1, "spa": 1, "spd": 1, "spe": 1,
            },
            "move_max_pp": [1, 1, 1, 1], "level": 100, "gender": "N",
            "happiness": 255, "shiny": False,
        }
        spec = TeamSpec("gen3ou", "", "", "[]", json.dumps({
            "pokemon": [pokemon] * 6,
        }))
        source = r'''#include <stdint.h>
#include <stdlib.h>
#include <string.h>
uint32_t gen3_abi_version(void) { return 12; }
size_t gen3_sizeof_pokemon_set(void) { return SIZE_POKEMON_SET; }
size_t gen3_sizeof_battle_team(void) { return SIZE_BATTLE_TEAM; }
size_t gen3_sizeof_battle_init(void) { return SIZE_BATTLE_INIT; }
size_t gen3_sizeof_battle_snapshot(void) { return SIZE_BATTLE_SNAPSHOT; }
int gen3_battle_create(const void *i, void **out, char *e, size_t n) {
    (void)i; (void)e; (void)n; *out = (void *)1; return 0;
}
void gen3_battle_destroy(void *battle) { (void)battle; }
int gen3_battle_turn(void *battle, int8_t a, int8_t b) {
    (void)battle; (void)a; (void)b; abort();
}
int gen3_battle_legal_actions(void *battle, uint8_t side, uint16_t *mask) {
    (void)battle; (void)side; *mask = 1; return 0;
}
int gen3_battle_switch_slice_supported(void *battle, uint8_t *supported) {
    (void)battle; *supported = 1; return 0;
}
int gen3_battle_snapshot(void *battle, void *snapshot) {
    (void)battle; memset(snapshot, 0, SIZE_BATTLE_SNAPSHOT);
    ((uint32_t *)snapshot)[0] = 12;
    ((uint32_t *)snapshot)[1] = SIZE_BATTLE_SNAPSHOT;
    return 0;
}
'''
        source = source.replace("SIZE_POKEMON_SET", str(ctypes.sizeof(PokemonSet)))
        source = source.replace("SIZE_BATTLE_TEAM", str(ctypes.sizeof(BattleTeam)))
        source = source.replace("SIZE_BATTLE_INIT", str(ctypes.sizeof(BattleInit)))
        source = source.replace(
            "SIZE_BATTLE_SNAPSHOT", str(ctypes.sizeof(BattleSnapshot)),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            c_file = root / "abort_engine.c"
            library = root / "abort_engine.so"
            c_file.write_text(source)
            subprocess.run(
                ["cc", "-std=c11", "-fPIC", "-shared", str(c_file), "-o", str(library)],
                check=True,
            )
            engine = IsolatedNativeEngine(library)
            try:
                initial = engine.start((spec, spec), (1, 2, 3, 4))
                self.assertEqual(initial.legal_p1, (0,))
                with self.assertRaisesRegex(
                    NativeEngineCrash, r"native engine died during turn: signal 6",
                ):
                    engine.turn(0, 0)
            finally:
                engine.close()


@unittest.skipUnless(default_showdown_dir().exists(), "Showdown checkout unavailable")
class NativeEngineIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        team = (ROOT / "fixtures" / "gen3ou" / "balanced-alt.txt").read_text()
        with ShowdownTeamValidator() as validator:
            cls.spec = validator.normalize(ExplicitTeamSource(team))

    def test_normalized_teams_round_trip_and_switch(self) -> None:
        engine = NativeEngine()
        try:
            initial = engine.start((self.spec, self.spec), (3, 2, 3, 4))
            self.assertEqual(initial.legal_p1, tuple(range(9)))
            self.assertEqual(
                initial.snapshot["seed"], [25084, 62519, 52978, 42619]
            )
            self.assertEqual(
                initial.snapshot["sides"][0][0]["species_id"], 94
            )
            for side in range(2):
                expected_team = self.spec.battle_team()["pokemon"]
                for slot, expected in enumerate(expected_team):
                    actual = initial.snapshot["sides"][side][slot]["set"]
                    self.assertEqual(actual["species_id"], expected["species_id"])
                    self.assertEqual(actual["item_id"], expected["item_id"])
                    self.assertEqual(actual["ability_id"], expected["ability_id"])
                    self.assertEqual(actual["move_ids"], expected["move_ids"])
                    self.assertEqual(
                        actual["stats"],
                        [expected["stats"][name] for name in
                         ("hp", "atk", "def", "spa", "spd", "spe")],
                    )
                    self.assertEqual(actual["max_pp"], expected["move_max_pp"])
                    self.assertEqual(actual["level"], expected["level"])
                    self.assertEqual(
                        actual["gender"],
                        {"N": 0, "M": 1, "F": 2}[expected["gender"]],
                    )
                    self.assertEqual(actual["happiness"], expected["happiness"])
                    self.assertEqual(actual["shiny"], int(expected["shiny"]))

            switched = engine.turn(4, 4)
            self.assertIsNone(switched.unsupported)
            self.assertEqual(switched.snapshot["turn"], 2)
            self.assertEqual(
                switched.snapshot["seed"], [50950, 63122, 38965, 57347]
            )
            self.assertEqual(
                switched.snapshot["sides"][0][0]["species_id"], 260
            )
            self.assertEqual(
                switched.snapshot["sides"][0][1]["species_id"], 94
            )

            resolved = engine.turn(0, 0)
            self.assertIsNotNone(resolved.unsupported)
            self.assertEqual(resolved.snapshot["turn"], 2)
        finally:
            engine.close()

    def test_ctypes_boundary_rejects_integer_truncation(self) -> None:
        payload = self.spec.battle_team()
        payload["pokemon"][0]["species_id"] = 0x10000
        corrupt = TeamSpec(
            self.spec.format_id,
            self.spec.packed,
            self.spec.exported,
            self.spec.normalized_json,
            json.dumps(payload),
        )
        engine = NativeEngine()
        try:
            with self.assertRaisesRegex(ValueError, "species_id"):
                engine.start((corrupt, self.spec), (1, 2, 3, 4))
        finally:
            engine.close()

    def test_switch_effect_abilities_are_declared_unsupported(self) -> None:
        with ShowdownTeamValidator() as validator:
            unsafe = validator.normalize(ExplicitTeamSource(TEAM))
        engine = NativeEngine()
        try:
            state = engine.start((unsafe, self.spec), (1, 2, 3, 4))
            self.assertIn("switch-only capability", state.unsupported)
        finally:
            engine.close()

    def test_ocean_init_payload_is_exact_host_abi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "battle.bin"
            write_battle_init((self.spec, self.spec), (1, 2, 3, 4), path)
            payload = path.read_bytes()
        self.assertEqual(len(payload), ctypes.sizeof(BattleInit))
        initial = BattleInit.from_buffer_copy(payload)
        self.assertEqual(initial.abi_version, 12)
        self.assertEqual(list(initial.seed), [1, 2, 3, 4])
        self.assertEqual(initial.teams[0].pokemon[0].species_id, 94)


if __name__ == "__main__":
    unittest.main()
