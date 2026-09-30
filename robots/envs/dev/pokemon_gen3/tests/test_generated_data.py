from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDS = ROOT / "data" / "gen3_ids.json"
HEADER = ROOT / "engine" / "data_gen3.h"
GENERATOR = ROOT / "tools" / "generate_gen3_data.js"


class GeneratedIdentityTests(unittest.TestCase):
    def test_species_formes_have_distinct_stable_ids(self) -> None:
        species = json.loads(IDS.read_text())["species"]
        self.assertEqual(species["deoxys"], 386)
        self.assertEqual(species["deoxysattack"], 390)
        self.assertEqual(species["deoxysdefense"], 391)
        self.assertEqual(species["deoxysspeed"], 392)
        self.assertEqual(len(species), len(set(species.values())))

    def test_effect_descriptor_vertical_slice_is_present(self) -> None:
        header = HEADER.read_text()
        self.assertIn("GEN3_EFFECT_DESCRIPTOR_COUNT = 6", header)
        self.assertIn("GEN3_HANDLER_DESCRIPTOR_COUNT = 7", header)
        for name in (
            '"Spikes"',
            '"Leftovers"',
            '"Natural Cure"',
            '"Levitate"',
            '"Sturdy"',
            '"Torrent"',
        ):
            self.assertIn(name, header)
        self.assertIn(
            "GEN3_EFFECT_CAP_AIRBORNE | GEN3_EFFECT_CAP_GROUND_IMMUNE",
            header,
        )
        self.assertIn(
            "GEN3_EFFECT_EVENT_RESIDUAL, GEN3_NATIVE_HANDLER_LEFTOVERS_RESIDUAL, "
            "10, 0, 4",
            header,
        )
        self.assertIn(
            "GEN3_EFFECT_EVENT_BASE_POWER, GEN3_NATIVE_HANDLER_TORRENT_BASE_POWER, "
            "32767, 2, 7",
            header,
        )


@unittest.skipUnless(
    os.environ.get("POKEMON_SHOWDOWN_DIR"),
    "POKEMON_SHOWDOWN_DIR is required for regeneration checks",
)
class GeneratedOracleDataTests(unittest.TestCase):
    def generate(self, output: str) -> bytes:
        return subprocess.run(
            [
                "node",
                str(GENERATOR),
                os.environ["POKEMON_SHOWDOWN_DIR"],
                output,
            ],
            check=True,
            stdout=subprocess.PIPE,
        ).stdout

    def test_header_is_reproducible_from_oracle(self) -> None:
        self.assertEqual(self.generate("header"), HEADER.read_bytes())

    def test_id_map_is_reproducible_from_oracle(self) -> None:
        self.assertEqual(self.generate("ids"), IDS.read_bytes())


if __name__ == "__main__":
    unittest.main()
