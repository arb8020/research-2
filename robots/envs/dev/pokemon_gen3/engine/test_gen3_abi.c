#include "gen3_abi.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static Gen3PokemonSet make_set(uint16_t species, uint16_t base) {
    Gen3PokemonSet set = {0};
    set.abi_version = GEN3_ABI_VERSION;
    set.struct_size = sizeof(set);
    set.species_id = species;
    set.item_id = 0;
    set.ability_id = 5; /* Sturdy: inert in the pristine switch-only slice. */
    set.level = (uint8_t)(50 + base % 40);
    set.gender = (uint8_t)(base % 3);
    set.happiness = (uint8_t)(base + 100);
    set.shiny = (uint8_t)(base % 2);
    for (size_t i = 0; i < GEN3_MOVE_SLOTS; i++) {
        set.move_ids[i] = (uint16_t)(i + 1);
        set.max_pp[i] = (uint16_t)(8 + i);
    }
    for (size_t i = 0; i < 6; i++) set.stats[i] = (uint16_t)(150 + base * 6 + i);
    return set;
}

static Gen3BattleInit make_init(void) {
    Gen3BattleInit init = {0};
    init.abi_version = GEN3_ABI_VERSION;
    init.struct_size = sizeof(init);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].abi_version = GEN3_ABI_VERSION;
        init.teams[side].struct_size = sizeof(init.teams[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            uint16_t n = (uint16_t)(side * GEN3_TEAM_SIZE + slot + 1);
            init.teams[side].pokemon[slot] = make_set(n, n);
        }
    }
    init.seed[0] = 1;
    init.seed[1] = 65535;
    init.seed[2] = 42;
    init.seed[3] = 900;
    return init;
}

static void test_showdown_prng_vectors(void) {
    uint16_t seed[4] = {1, 65535, 42, 900};
    const uint32_t outputs[] = {
        UINT32_C(2964340839), UINT32_C(1437576878), UINT32_C(4234578556),
        UINT32_C(10053885), UINT32_C(772423074), UINT32_C(1835670280),
    };
    const uint16_t states[][4] = {
        {45232, 16487, 21815, 42455},
        {21935, 44718, 41916, 7062},
        {64614, 35452, 19770, 50929},
        {153, 26877, 2405, 5336},
        {11786, 15778, 32535, 28667},
        {28010, 6920, 41776, 8138},
    };
    for (size_t i = 0; i < sizeof(outputs) / sizeof(outputs[0]); i++) {
        uint32_t output = 0;
        assert(gen3_prng_next(seed, &output) == GEN3_OK);
        assert(output == outputs[i]);
        assert(memcmp(seed, states[i], sizeof(seed)) == 0);
    }
    uint32_t output = 0;
    assert(gen3_prng_next(NULL, &output) == GEN3_INVALID_ARGUMENT);
    assert(gen3_prng_next(seed, NULL) == GEN3_INVALID_ARGUMENT);
}

static void test_exact_initialization(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = NULL;
    char error[128] = {0};
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_OK);
    assert(battle != NULL);

    /* The battle owns its immutable copy; caller storage is not retained. */
    Gen3BattleInit expected = init;
    init.teams[0].pokemon[0].species_id = 999;
    init.seed[0] = 999;

    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.abi_version == GEN3_ABI_VERSION);
    assert(snapshot.struct_size == sizeof(snapshot));
    assert(snapshot.turn == 1);
    assert(snapshot.done == 0);
    assert(snapshot.winner_side == -1);
    assert(snapshot.event_count == 2);
    assert(snapshot.events[0].kind == GEN3_EVENT_SWITCH);
    assert(snapshot.events[0].side == 0);
    assert(snapshot.events[0].species_id == 1);
    assert(snapshot.events[0].hp == init.teams[0].pokemon[0].stats[0]);
    assert(snapshot.events[0].max_hp == init.teams[0].pokemon[0].stats[0]);
    assert(snapshot.events[1].kind == GEN3_EVENT_SWITCH);
    assert(snapshot.events[1].side == 1);
    assert(snapshot.events[1].species_id == 7);
    uint32_t ignored = 0;
    assert(gen3_prng_next(expected.seed, &ignored) == GEN3_OK);
    assert(memcmp(snapshot.seed, expected.seed, sizeof(expected.seed)) == 0);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            const Gen3PokemonSet *expected_set = &expected.teams[side].pokemon[slot];
            const Gen3PokemonSnapshot *actual = &snapshot.pokemon[side][slot];
            assert(memcmp(&actual->set, expected_set, sizeof(*expected_set)) == 0);
            assert(actual->hp == expected_set->stats[0]);
            assert(memcmp(actual->pp, expected_set->max_pp, sizeof(actual->pp)) == 0);
            assert(actual->status == 0);
        }
    }
    uint16_t mask = 0;
    assert(gen3_battle_legal_actions(battle, 0, &mask) == GEN3_OK);
    assert(mask == 0x1ff);
    assert(gen3_battle_legal_actions(battle, 1, &mask) == GEN3_OK);
    assert(mask == 0x1ff);
    assert(gen3_battle_legal_actions(battle, 2, &mask) == GEN3_INVALID_ARGUMENT);
    gen3_battle_destroy(battle);
}

static void test_missing_move_is_not_legal(void) {
    Gen3BattleInit init = make_init();
    init.teams[0].pokemon[0].move_ids[3] = 0;
    init.teams[0].pokemon[0].max_pp[3] = 0;
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    uint16_t mask = 0;
    assert(gen3_battle_legal_actions(battle, 0, &mask) == GEN3_OK);
    assert(mask == 0x1f7);
    gen3_battle_destroy(battle);
}

static void test_struggle_is_legal_when_all_pp_is_exhausted(void) {
    Gen3BattleInit init = make_init();
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].pokemon[0].move_ids[0] = 182; /* Protect */
        init.teams[side].pokemon[0].max_pp[0] = 1;
        for (size_t slot = 1; slot < GEN3_MOVE_SLOTS; slot++) {
            init.teams[side].pokemon[0].move_ids[slot] = 0;
            init.teams[side].pokemon[0].max_pp[slot] = 0;
        }
    }
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_turn(battle, 0, 0) == GEN3_OK);
    uint16_t mask = 0;
    assert(gen3_battle_legal_actions(battle, 0, &mask) == GEN3_OK);
    assert(mask == 0x1f1);
    gen3_battle_destroy(battle);
}

static void test_simultaneous_switches_preserve_request_order(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);

    /* Action 4 selects request slot 2; action 8 selects request slot 6. */
    assert(gen3_battle_turn(battle, 4, 8) == GEN3_OK);
    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 2);
    assert(snapshot.event_count == 2);
    /* Test data gives p2's outgoing active the higher Speed. */
    assert(snapshot.events[0].side == 1);
    assert(snapshot.events[0].species_id == 12);
    assert(snapshot.events[1].side == 0);
    assert(snapshot.events[1].species_id == 2);
    assert(snapshot.pokemon[0][0].set.species_id == 2);
    assert(snapshot.pokemon[0][1].set.species_id == 1);
    assert(snapshot.pokemon[1][0].set.species_id == 12);
    assert(snapshot.pokemon[1][5].set.species_id == 7);
    assert(snapshot.pokemon[0][0].hp == init.teams[0].pokemon[1].stats[0]);
    assert(snapshot.pokemon[1][0].hp == init.teams[1].pokemon[5].stats[0]);
    uint16_t expected_seed[4];
    memcpy(expected_seed, init.seed, sizeof(expected_seed));
    uint32_t ignored = 0;
    assert(gen3_prng_next(expected_seed, &ignored) == GEN3_OK);
    assert(gen3_prng_next(expected_seed, &ignored) == GEN3_OK);
    assert(memcmp(snapshot.seed, expected_seed, sizeof(expected_seed)) == 0);

    uint16_t mask = 0;
    assert(gen3_battle_legal_actions(battle, 0, &mask) == GEN3_OK);
    assert(mask == 0x1ff);
    assert(gen3_battle_legal_actions(battle, 1, &mask) == GEN3_OK);
    assert(mask == 0x1ff);

    /* Slot numbers are relative to current request order, so switching to
     * slot 2 again returns the original p1 lead to slot 1. */
    assert(gen3_battle_turn(battle, 4, 4) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 3);
    assert(snapshot.pokemon[0][0].set.species_id == 1);
    assert(snapshot.pokemon[0][1].set.species_id == 2);
    assert(snapshot.pokemon[1][0].set.species_id == 8);
    assert(snapshot.pokemon[1][1].set.species_id == 12);
    gen3_battle_destroy(battle);
}

static void test_unsupported_turn_is_atomic(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    Gen3BattleSnapshot before;
    Gen3BattleSnapshot after;
    assert(gen3_battle_snapshot(battle, &before) == GEN3_OK);

    assert(gen3_battle_turn(battle, 0, 4) == GEN3_UNSUPPORTED_ACTION);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);

    assert(gen3_battle_turn(battle, 4, -1) == GEN3_UNSUPPORTED_ACTION);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);

    assert(gen3_battle_turn(battle, 4, 9) == GEN3_INVALID_ARGUMENT);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);

    gen3_battle_destroy(battle);
    init = make_init();
    init.teams[0].pokemon[3].ability_id = 45; /* Sand Stream */
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &before) == GEN3_OK);
    assert(gen3_battle_turn(battle, 4, 4) == GEN3_UNSUPPORTED_ACTION);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);
    gen3_battle_destroy(battle);
}

static void test_seismic_toss_switch_and_leftovers_slice(void) {
    Gen3BattleInit init = make_init();
    init.teams[0].pokemon[0].move_ids[1] = 69;
    init.teams[0].pokemon[0].max_pp[1] = 32;
    init.teams[0].pokemon[0].level = 100;
    init.teams[0].pokemon[0].item_id = 234;
    init.teams[1].pokemon[1].item_id = 234;
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_turn(battle, 1, 4) == GEN3_OK);

    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 2);
    assert(snapshot.pokemon[0][0].pp[1] == 31);
    assert(snapshot.pokemon[1][0].set.species_id == 8);
    assert(snapshot.pokemon[1][0].hp == 110);
    assert(snapshot.event_count == 4);
    assert(snapshot.events[0].kind == GEN3_EVENT_SWITCH);
    assert(snapshot.events[0].side == 1);
    assert(snapshot.events[1].kind == GEN3_EVENT_MOVE);
    assert(snapshot.events[1].side == 0);
    assert(snapshot.events[1].move_id == 69);
    assert(snapshot.events[2].kind == GEN3_EVENT_DAMAGE);
    assert(snapshot.events[2].hp == 98);
    assert(snapshot.events[3].kind == GEN3_EVENT_HEAL);
    assert(snapshot.events[3].hp == 110);

    init.teams[1].pokemon[1].move_ids[2] = 182;
    init.teams[1].pokemon[1].max_pp[2] = 16;
    /* The battle owns its copy, so update the live setup before recreating. */
    gen3_battle_destroy(battle);
    battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_turn(battle, 1, 4) == GEN3_OK);
    assert(gen3_battle_turn(battle, 7, 2) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 3);
    assert(snapshot.pokemon[1][0].pp[2] == 15);
    assert(snapshot.pokemon[1][0].hp == 122);
    assert(snapshot.event_count == 4);
    assert(snapshot.events[0].kind == GEN3_EVENT_SWITCH);
    assert(snapshot.events[0].side == 0);
    assert(snapshot.events[1].kind == GEN3_EVENT_MOVE);
    assert(snapshot.events[1].move_id == 182);
    assert(snapshot.events[2].kind == GEN3_EVENT_FAIL);
    assert(snapshot.events[2].move_id == 182);
    assert(snapshot.events[3].kind == GEN3_EVENT_HEAL);
    assert(snapshot.events[3].hp == 122);
    gen3_battle_destroy(battle);
}

static void test_standard_damage_pair_slice(void) {
    Gen3BattleInit init = make_init();
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        Gen3PokemonSet *set = &init.teams[side].pokemon[0];
        set->species_id = 260; /* Swampert */
        set->item_id = 234; /* Leftovers */
        set->ability_id = 67; /* Torrent */
        set->level = 100;
        const uint16_t moves[4] = {89, 58, 182, 92};
        const uint16_t stats[6] = {404, 256, 297, 216, 216, 140};
        for (size_t slot = 0; slot < 4; slot++) {
            set->move_ids[slot] = moves[slot];
            set->max_pp[slot] = 16;
        }
        memcpy(set->stats, stats, sizeof(stats));
    }
    init.seed[0] = 42;
    init.seed[1] = 42;
    init.seed[2] = 0;
    init.seed[3] = 0;
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_turn(battle, 1, 0) == GEN3_OK);

    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 2);
    assert(snapshot.pokemon[0][0].hp == 321);
    assert(snapshot.pokemon[1][0].hp == 354);
    assert(snapshot.pokemon[0][0].pp[1] == 15);
    assert(snapshot.pokemon[1][0].pp[0] == 15);
    assert(snapshot.event_count == 6);
    assert(snapshot.events[0].kind == GEN3_EVENT_MOVE && snapshot.events[0].side == 1);
    assert(snapshot.events[0].move_id == 89);
    assert(snapshot.events[1].kind == GEN3_EVENT_DAMAGE && snapshot.events[1].hp == 296);
    assert(snapshot.events[2].kind == GEN3_EVENT_MOVE && snapshot.events[2].side == 0);
    assert(snapshot.events[2].move_id == 58);
    assert(snapshot.events[3].kind == GEN3_EVENT_DAMAGE && snapshot.events[3].hp == 329);
    assert(snapshot.events[4].kind == GEN3_EVENT_HEAL && snapshot.events[4].side == 1);
    assert(snapshot.events[5].kind == GEN3_EVENT_HEAL && snapshot.events[5].side == 0);
    gen3_battle_destroy(battle);
}

static void test_explosion_enters_and_completes_forced_switch(void) {
    Gen3BattleInit init = make_init();
    const uint16_t skarmory_stats[6] = {334, 196, 416, 104, 177, 176};
    const uint16_t gengar_stats[6] = {262, 149, 156, 359, 186, 350};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        Gen3PokemonSet *skarmory = &init.teams[side].pokemon[1];
        skarmory->species_id = 227;
        skarmory->item_id = 234;
        memcpy(skarmory->stats, skarmory_stats, sizeof(skarmory_stats));
    }
    Gen3PokemonSet *gengar = &init.teams[1].pokemon[0];
    gengar->species_id = 94;
    gengar->level = 100;
    gengar->move_ids[3] = 153;
    gengar->max_pp[3] = 8;
    memcpy(gengar->stats, gengar_stats, sizeof(gengar_stats));
    init.seed[0] = 42;
    init.seed[1] = 42;
    init.seed[2] = 0;
    init.seed[3] = 0;

    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_turn(battle, 4, 3) == GEN3_OK);
    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 1);
    assert(snapshot.force_switch_side == 1);
    assert(snapshot.pokemon[0][0].set.species_id == 227);
    assert(snapshot.pokemon[0][0].hp == 268);
    assert(snapshot.pokemon[1][0].hp == 0);
    assert(snapshot.event_count == 4);
    assert(snapshot.events[3].kind == GEN3_EVENT_FAINT);
    uint16_t mask = 0;
    assert(gen3_battle_legal_actions(battle, 0, &mask) == GEN3_OK && mask == 0);
    assert(gen3_battle_legal_actions(battle, 1, &mask) == GEN3_OK && mask == 0x1f0);

    Gen3BattleSnapshot before_invalid = snapshot;
    assert(gen3_battle_turn(battle, 0, 4) == GEN3_ILLEGAL_ACTION);
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(memcmp(&snapshot, &before_invalid, sizeof(snapshot)) == 0);

    assert(gen3_battle_turn(battle, -1, 4) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    assert(snapshot.turn == 2);
    assert(snapshot.force_switch_side == -1);
    assert(snapshot.pokemon[1][0].set.species_id == 227);
    assert(snapshot.pokemon[0][0].hp == 288);
    assert(snapshot.event_count == 2);
    assert(snapshot.events[0].kind == GEN3_EVENT_SWITCH);
    assert(snapshot.events[1].kind == GEN3_EVENT_HEAL);
    gen3_battle_destroy(battle);
}

static void test_invalid_input_fails_honestly(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = (Gen3Battle *)(uintptr_t)1;
    char error[128] = {0};
    init.teams[1].pokemon[5].stats[0] = 0;
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_INVALID_TEAM);
    assert(battle == NULL);
    assert(strstr(error, "invalid normalized") != NULL);

    init = make_init();
    init.teams[0].pokemon[0].species_id = 999;
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_INVALID_TEAM);
    assert(battle == NULL);

    init = make_init();
    init.teams[0].pokemon[0].move_ids[0] = 999;
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_INVALID_TEAM);
    assert(battle == NULL);

    init = make_init();
    init.struct_size--;
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_INVALID_LAYOUT);
    assert(battle == NULL);

    init = make_init();
    init.teams[0].pokemon[4].abi_version++;
    assert(gen3_battle_create(&init, &battle, error, sizeof(error)) == GEN3_INVALID_LAYOUT);
    assert(battle == NULL);
}

int main(void) {
    assert(gen3_abi_version() == GEN3_ABI_VERSION);
    assert(gen3_sizeof_pokemon_set() == sizeof(Gen3PokemonSet));
    assert(gen3_sizeof_battle_team() == sizeof(Gen3BattleTeam));
    assert(gen3_sizeof_battle_init() == sizeof(Gen3BattleInit));
    assert(gen3_sizeof_battle_snapshot() == sizeof(Gen3BattleSnapshot));
    test_showdown_prng_vectors();
    test_exact_initialization();
    test_missing_move_is_not_legal();
    test_struggle_is_legal_when_all_pp_is_exhausted();
    test_simultaneous_switches_preserve_request_order();
    test_unsupported_turn_is_atomic();
    test_seismic_toss_switch_and_leftovers_slice();
    test_standard_damage_pair_slice();
    test_explosion_enters_and_completes_forced_switch();
    test_invalid_input_fails_honestly();
    puts("gen3 ABI tests passed");
    return 0;
}
