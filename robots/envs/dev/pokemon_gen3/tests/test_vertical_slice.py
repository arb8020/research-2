from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VerticalSliceTest(unittest.TestCase):
    def test_checked_regression_corpus_matches_showdown(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "harness/diff.py",
                "--corpus", "regressions/gen3ou",
                "-j", "1",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS  5 battles, 0 divergences", completed.stdout)
        self.assertIn(
            "case seed42-battle03-simultaneous-forced-replacement: "
            "PASS (105 boundaries",
            completed.stdout,
        )
        self.assertIn(
            "case seed42-battle04-complete-struggle: PASS (259 boundaries",
            completed.stdout,
        )

    def test_seed_42_battle_matches_showdown_to_completion(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "harness/diff.py",
                "--battles", "1",
                "-j", "1",
                "--seed", "42",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS  1 battles, 0 divergences", completed.stdout)

    def test_first_two_seeded_battles_match_showdown_to_completion(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "harness/diff.py",
                "--battles", "2",
                "-j", "1",
                "--seed", "42",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS  2 battles, 0 divergences", completed.stdout)

    def test_first_three_seeded_battles_match_showdown_to_completion(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "harness/diff.py",
                "--battles", "3",
                "-j", "1",
                "--seed", "42",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("PASS  3 battles, 0 divergences", completed.stdout)


if __name__ == "__main__":
    unittest.main()
