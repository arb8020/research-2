from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.teams import (  # noqa: E402
    ExplicitTeamSource,
    PoolSampleTeamSource,
    ShowdownTeamValidator,
    TeamValidationError,
    default_showdown_dir,
)

TEAM = """\
Tyranitar (M) @ Leftovers
Ability: Sand Stream
EVs: 252 HP / 252 Atk / 4 SpD
Adamant Nature
- Rock Slide
- Earthquake
- Brick Break
- Protect

Skarmory (M) @ Leftovers
Ability: Sturdy
EVs: 252 HP / 252 Def / 4 SpD
Impish Nature
- Spikes
- Whirlwind
- Protect
- Toxic

Blissey (F) @ Leftovers
Ability: Natural Cure
EVs: 252 Def / 252 SpD / 4 Spe
Calm Nature
- Soft-Boiled
- Seismic Toss
- Toxic
- Aromatherapy

Gengar (M) @ Leftovers
Ability: Levitate
EVs: 4 HP / 252 SpA / 252 Spe
Timid Nature
- Thunderbolt
- Ice Punch
- Will-O-Wisp
- Explosion

Swampert (M) @ Leftovers
Ability: Torrent
EVs: 252 HP / 216 Def / 40 SpA
Relaxed Nature
- Earthquake
- Ice Beam
- Protect
- Toxic

Celebi @ Leftovers
Ability: Natural Cure
EVs: 252 HP / 220 Def / 36 Spe
Bold Nature
- Recover
- Psychic
- Leech Seed
- Heal Bell
"""


class TeamSourceTests(unittest.TestCase):
    def test_pool_sample_is_deterministic(self) -> None:
        source = PoolSampleTeamSource(("zero", "one", "two"), seed=17)
        self.assertEqual(source.read(), source.read())
        self.assertIn(source.read(), source.teams)

    def test_empty_explicit_team_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ExplicitTeamSource("  ").read()


@unittest.skipUnless(default_showdown_dir().exists(), "Showdown checkout unavailable")
class ShowdownIntegrationTests(unittest.TestCase):
    def test_legal_six_pokemon_team_is_normalized(self) -> None:
        with ShowdownTeamValidator() as validator:
            spec = validator.normalize(ExplicitTeamSource(TEAM))
        self.assertEqual(spec.format_id, "gen3ou")
        self.assertEqual(len(spec.normalized()), 6)
        self.assertEqual(spec.normalized()[0]["species"], "Tyranitar")
        self.assertIn("Tyranitar", spec.packed)

        tyranitar = spec.battle_team()["pokemon"][0]
        self.assertEqual(tyranitar["species_id"], 248)
        self.assertEqual(tyranitar["item_id"], 234)
        self.assertEqual(tyranitar["ability_id"], 45)
        self.assertEqual(tyranitar["move_ids"], [157, 89, 280, 182])
        self.assertEqual(tyranitar["move_max_pp"], [16, 16, 24, 16])
        self.assertEqual(
            tyranitar["stats"],
            {"hp": 404, "atk": 403, "def": 256,
             "spa": 203, "spd": 237, "spe": 158},
        )
        self.assertEqual(tyranitar["level"], 100)
        self.assertEqual(tyranitar["happiness"], 255)
        self.assertEqual(tyranitar["gender"], "M")
        self.assertFalse(tyranitar["shiny"])

    def test_c_payload_has_complete_positive_stats_and_move_metadata(self) -> None:
        with ShowdownTeamValidator() as validator:
            pokemon = validator.normalize(
                ExplicitTeamSource(TEAM)
            ).battle_team()["pokemon"]
        self.assertEqual(len(pokemon), 6)
        for mon in pokemon:
            self.assertGreater(mon["species_id"], 0)
            self.assertGreater(mon["ability_id"], 0)
            self.assertEqual(len(mon["move_ids"]), 4)
            self.assertTrue(all(value > 0 for value in mon["move_ids"]))
            self.assertTrue(all(value > 0 for value in mon["move_max_pp"]))
            self.assertEqual(set(mon["stats"]), {"hp", "atk", "def", "spa", "spd", "spe"})
            self.assertTrue(all(value > 0 for value in mon["stats"].values()))

    def test_five_pokemon_team_is_rejected_even_if_showdown_allows_it(self) -> None:
        five = TEAM.rsplit("\n\n", 1)[0]
        with ShowdownTeamValidator() as validator:
            with self.assertRaisesRegex(TeamValidationError, "exactly 6"):
                validator.normalize(ExplicitTeamSource(five))

    def test_unspecified_mixed_gender_is_rejected_before_battle(self) -> None:
        unresolved = TEAM.replace("Tyranitar (M)", "Tyranitar", 1)
        with ShowdownTeamValidator() as validator:
            with self.assertRaisesRegex(TeamValidationError, "must specify M or F"):
                validator.normalize(ExplicitTeamSource(unresolved))


if __name__ == "__main__":
    unittest.main()
