from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "tools" / "generate_slice_data.js"
NATIVE = ROOT / "native"


@unittest.skipUnless(
    os.environ.get("POKEMON_SHOWDOWN_DIR"),
    "POKEMON_SHOWDOWN_DIR is required for regeneration checks",
)
class SliceGeneratedDataTests(unittest.TestCase):
    def test_outputs_are_reproducible_from_pinned_showdown(self) -> None:
        showdown = os.environ["POKEMON_SHOWDOWN_DIR"]
        for output, filename in (
            ("header", "gen3_slice_data.h"),
            ("source", "gen3_slice_data.c"),
        ):
            generated = subprocess.run(
                ["node", str(GENERATOR), showdown, output],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            self.assertEqual(generated, (NATIVE / filename).read_bytes())


if __name__ == "__main__":
    unittest.main()
