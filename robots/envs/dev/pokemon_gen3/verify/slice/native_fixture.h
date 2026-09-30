#pragma once

#include "gen3_rules.h"
#include "gen3_slice_data.h"
#include "singles2.h"

/* Verifier-owned normalization of case.json and its two exported teams.
 * These are the exact stats produced by the pinned Showdown revision. */
static const PokemonBattleInit SLICE_INIT = {
    .bundle = &POKEMON_GEN3_OU_BUNDLE,
    .team_sizes = {2, 2},
    .teams = {
        {.members = {
            {.species_id = POKEMON_GEN3_SPECIES_PERSIAN,
             .move_ids = {POKEMON_GEN3_MOVE_QUICKATTACK},
             .stats = {271, 176, 156, 166, 166, 266}, .level = 100},
            {.species_id = POKEMON_GEN3_SPECIES_ALAKAZAM,
             .move_ids = {POKEMON_GEN3_MOVE_THIEF},
             .stats = {251, 136, 126, 306, 206, 276}, .level = 100},
        }},
        {.members = {
            {.species_id = POKEMON_GEN3_SPECIES_BANETTE,
             .move_ids = {POKEMON_GEN3_MOVE_THIEF},
             .stats = {12, 7, 6, 6, 6, 6}, .level = 1},
            {.species_id = POKEMON_GEN3_SPECIES_MACHOP,
             .move_ids = {POKEMON_GEN3_MOVE_STRENGTH},
             .stats = {12, 6, 6, 6, 6, 6}, .level = 1},
        }},
    },
    .seed = {1, 2, 3, 4},
};

static const PokemonChoice SLICE_CHOICES[][POKEMON_SIDES] = {
    {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
    {{POKEMON_CHOICE_SWITCH, 1}, {POKEMON_CHOICE_MOVE, 0}},
    {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
    {{POKEMON_CHOICE_NONE, 0}, {POKEMON_CHOICE_SWITCH, 1}},
    {{POKEMON_CHOICE_MOVE, 0}, {POKEMON_CHOICE_MOVE, 0}},
};

#define SLICE_CHOICE_COUNT (sizeof(SLICE_CHOICES) / sizeof(SLICE_CHOICES[0]))
