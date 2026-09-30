#include "gen3_rules.h"
#include "gen3_slice_data.h"
#include "pokemon.h"
#include "singles2.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef POKEMON_RANDOM_BATTLE_COUNT
#define POKEMON_RANDOM_BATTLE_COUNT 128u
#endif

#ifndef POKEMON_RANDOM_DECISION_CAP
#define POKEMON_RANDOM_DECISION_CAP 128u
#endif

enum { VOLUNTARY_SWITCH_CAP = 8 };

static PokemonSet make_set(
    uint16_t species, const uint16_t moves[POKEMON_MOVE_CAPACITY],
    uint16_t hp, uint16_t attack, uint16_t defense,
    uint16_t special_attack, uint16_t special_defense, uint16_t speed
) {
    PokemonSet set = {
        .species_id = species,
        .stats = {hp, attack, defense, special_attack, special_defense, speed},
        .level = 100,
        .gender = POKEMON_GENDER_MALE,
    };
    memcpy(set.move_ids, moves, sizeof(set.move_ids));
    return set;
}

static PokemonBattleInit battle_init(uint32_t seed) {
    static const uint16_t physical_moves[POKEMON_MOVE_CAPACITY] = {
        POKEMON_GEN3_MOVE_QUICKATTACK, POKEMON_GEN3_MOVE_TACKLE, 0, 0,
    };
    static const uint16_t special_moves[POKEMON_MOVE_CAPACITY] = {
        POKEMON_GEN3_MOVE_THIEF, POKEMON_GEN3_MOVE_QUICKATTACK,
        POKEMON_GEN3_MOVE_TACKLE, 0,
    };
    PokemonBattleInit init = {
        .bundle = &POKEMON_GEN3_OU_BUNDLE,
        .team_sizes = {2, 2},
        .seed = {
            (uint16_t)(seed >> 16), (uint16_t)seed,
            (uint16_t)(seed ^ UINT32_C(0xa5a5)),
            (uint16_t)((seed * UINT32_C(0x9e37)) >> 8),
        },
    };
    init.teams[0].members[0] = make_set(
        POKEMON_GEN3_SPECIES_PERSIAN, physical_moves, 220, 230, 130, 120, 140, 250
    );
    init.teams[0].members[1] = make_set(
        POKEMON_GEN3_SPECIES_ALAKAZAM, special_moves, 190, 110, 105, 270, 170, 260
    );
    init.teams[1].members[0] = make_set(
        POKEMON_GEN3_SPECIES_BANETTE, physical_moves, 210, 240, 125, 120, 135, 190
    );
    init.teams[1].members[1] = make_set(
        POKEMON_GEN3_SPECIES_MACHOP, physical_moves, 240, 235, 145, 100, 120, 160
    );
    return init;
}

/* Policy randomness is deliberately independent of PokemonBattle.seed. */
static uint32_t policy_next(uint64_t *state) {
    *state = *state * UINT64_C(6364136223846793005) + UINT64_C(1442695040888963407);
    return (uint32_t)(*state >> 32);
}

static uint8_t choose_set_bit(uint8_t bits, uint32_t random) {
    uint8_t count = 0;
    for (uint8_t slot = 0; slot < 8; slot++) count += (bits >> slot) & 1u;
    assert(count != 0);
    uint8_t wanted = (uint8_t)(random % count);
    for (uint8_t slot = 0; slot < 8; slot++) {
        if ((bits & (uint8_t)(1u << slot)) != 0 && wanted-- == 0) return slot;
    }
    assert(0);
    return 0;
}

static PokemonChoice policy_choice(
    const PokemonRequest *request, size_t side, uint64_t *policy_state,
    uint8_t *voluntary_switches
) {
    uint32_t random = policy_next(policy_state);
    switch (request->kind[side]) {
    case POKEMON_REQUEST_WAIT:
        return (PokemonChoice){POKEMON_CHOICE_NONE, 0};
    case POKEMON_REQUEST_SWITCH:
        return (PokemonChoice){
            POKEMON_CHOICE_SWITCH,
            choose_set_bit(request->legal_switches[side], random),
        };
    case POKEMON_REQUEST_MOVE:
        if (*voluntary_switches < VOLUNTARY_SWITCH_CAP &&
            request->legal_switches[side] != 0 && random % 8u == 0) {
            (*voluntary_switches)++;
            return (PokemonChoice){
                POKEMON_CHOICE_SWITCH,
                choose_set_bit(request->legal_switches[side], random >> 3),
            };
        }
        return (PokemonChoice){
            POKEMON_CHOICE_MOVE,
            choose_set_bit(request->legal_moves[side], random),
        };
    case POKEMON_REQUEST_TERMINAL:
        break;
    }
    assert(0);
    return (PokemonChoice){POKEMON_CHOICE_NONE, 0};
}

static void assert_same_observable_battle(
    const PokemonBattle *left, const PokemonBattle *right
) {
    PokemonBattleView left_view;
    PokemonBattleView right_view;
    pokemon_battle_view(left, &left_view);
    pokemon_battle_view(right, &right_view);
    assert(memcmp(&left_view, &right_view, sizeof(left_view)) == 0);
}

static void play_and_replay(uint32_t seed) {
    PokemonBattleInit init = battle_init(seed);
    PokemonBattle first;
    PokemonBattle replay;
    assert(pokemon_battle_init(&first, &init) == POKEMON_OK);
    assert(pokemon_battle_init(&replay, &init) == POKEMON_OK);
    assert(pokemon_battle_check_invariants(&first));
    assert_same_observable_battle(&first, &replay);

    uint64_t policy_state = UINT64_C(0xd1b54a32d192ed03) ^ seed;
    uint8_t voluntary_switches[POKEMON_SIDES] = {0, 0};
    size_t decisions = 0;
    while (!first.terminal && decisions < POKEMON_RANDOM_DECISION_CAP) {
        PokemonRequest request = pokemon_battle_request(&first);
        PokemonChoice choices[POKEMON_SIDES];
        for (size_t side = 0; side < POKEMON_SIDES; side++) {
            choices[side] = policy_choice(
                &request, side, &policy_state, &voluntary_switches[side]
            );
        }
        assert(pokemon_battle_step(&first, choices) == POKEMON_OK);
        assert(pokemon_battle_step(&replay, choices) == POKEMON_OK);
        assert(pokemon_battle_check_invariants(&first));
        assert(pokemon_battle_check_invariants(&replay));
        assert_same_observable_battle(&first, &replay);
        decisions++;
    }
    assert(first.terminal);
    assert(decisions < POKEMON_RANDOM_DECISION_CAP);
    assert(first.winner == 0 || first.winner == 1);
    assert(voluntary_switches[0] <= VOLUNTARY_SWITCH_CAP);
    assert(voluntary_switches[1] <= VOLUNTARY_SWITCH_CAP);
}

int main(void) {
    for (uint32_t seed = 1; seed <= POKEMON_RANDOM_BATTLE_COUNT; seed++) {
        play_and_replay(seed);
    }
    printf(
        "random legal play passed: %u battles, decision cap %u\n",
        POKEMON_RANDOM_BATTLE_COUNT, POKEMON_RANDOM_DECISION_CAP
    );
    return 0;
}
