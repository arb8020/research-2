#include "gen3_abi.c"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static Gen3PokemonSet scheduler_set(uint16_t species, uint16_t speed) {
    Gen3PokemonSet set = {0};
    set.abi_version = GEN3_ABI_VERSION;
    set.struct_size = sizeof(set);
    set.species_id = species;
    set.ability_id = GEN3_ABILITY_STURDY;
    set.item_id = GEN3_ITEM_LEFTOVERS;
    set.move_ids[0] = 1;
    set.max_pp[0] = 8;
    set.level = 100;
    set.happiness = 255;
    for (size_t stat = 0; stat < 6; stat++) set.stats[stat] = 200;
    set.stats[5] = speed;
    return set;
}

static Gen3BattleInit scheduler_init(uint16_t p1_target_speed, uint16_t p2_target_speed) {
    Gen3BattleInit init = {0};
    init.abi_version = GEN3_ABI_VERSION;
    init.struct_size = sizeof(init);
    init.seed[0] = 42;
    init.seed[1] = 42;
    init.seed[2] = 6;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].abi_version = GEN3_ABI_VERSION;
        init.teams[side].struct_size = sizeof(init.teams[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            uint16_t species = (uint16_t)(1 + side * GEN3_TEAM_SIZE + slot);
            uint16_t speed = (uint16_t)(100 + side * 10 + slot);
            init.teams[side].pokemon[slot] = scheduler_set(species, speed);
        }
    }
    init.teams[0].pokemon[0].stats[5] = p1_target_speed;
    init.teams[1].pokemon[0].stats[5] = p2_target_speed;
    init.teams[0].pokemon[1].stats[5] = p1_target_speed;
    init.teams[1].pokemon[1].stats[5] = p2_target_speed;
    return init;
}

static void enter_simultaneous_replacement(Gen3Battle *battle) {
    battle->state[0][0].hp = 0;
    battle->state[1][0].hp = 0;
    battle->force_switch_side = -2;
    battle->resume_residuals = 1;
}

static void enter_single_replacement(Gen3Battle *battle, size_t side) {
    battle->state[side][0].hp = 0;
    battle->force_switch_side = (int8_t)side;
    battle->resume_residuals = 1;
}

static Gen3Action queued_action(const Gen3Battle *battle, size_t offset) {
    assert(offset < battle->action_queue.count);
    const Gen3OrderedRecord *record =
        &battle->action_queue.order[battle->action_queue.head + offset];
    assert(record->payload_index < battle->action_queue.value_count);
    return battle->action_queue.values[record->payload_index];
}

static void test_canonical_order_comparator(void) {
    Gen3OrderKey left = {.order = 103, .speed = 200};
    Gen3OrderKey right = left;
    assert(compare_order_keys(&left, &right) == 0);

    left.order = 102;
    assert(compare_order_keys(&left, &right) < 0);
    left = right;
    left.order = 0;
    assert(compare_order_keys(&left, &right) > 0);
    right.order = UINT32_MAX;
    assert(compare_order_keys(&right, &left) < 0);
    left = right;
    left.priority = 1;
    assert(compare_order_keys(&left, &right) < 0);
    left = right;
    left.speed = 201;
    assert(compare_order_keys(&left, &right) < 0);
    left = right;
    left.sub_order = 1;
    assert(compare_order_keys(&left, &right) > 0);
    left = right;
    left.effect_order = 1;
    assert(compare_order_keys(&left, &right) > 0);
    assert(compare_order_keys(&right, &left) < 0);
}

static void test_physical_insertion_order_is_tie_input(void) {
    Gen3Battle battle = {0};
    Gen3OrderedRecord records[] = {
        {.key = {.order = 103, .speed = 200}, .payload_index = 7},
        {.key = {.order = 103, .speed = 200}, .payload_index = 3},
    };
    uint16_t expected_seed[4] = {0, 0, 0, 0};
    uint32_t output = 0;
    assert(gen3_prng_next(expected_seed, &output) == GEN3_OK);
    assert(random_below(output, 2) == 0);

    sort_ordered_records(
        &battle, records, 2, GEN3_TRACE_PRNG_UNKNOWN
    );
    assert(records[0].payload_index == 7);
    assert(records[1].payload_index == 3);
    assert(memcmp(battle.seed, expected_seed, sizeof(expected_seed)) == 0);
}

static void test_tie_group_shuffle_consumes_one_frame(void) {
    Gen3Battle battle = {0};
    const uint16_t initial_seed[4] = {1, 65535, 42, 900};
    memcpy(battle.seed, initial_seed, sizeof(initial_seed));
    push_action(&battle, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 0,
        .key = {.order = 103, .speed = 200},
    });
    push_action(&battle, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 1,
        .key = {.order = 103, .speed = 200},
    });

    uint16_t expected_seed[4];
    memcpy(expected_seed, initial_seed, sizeof(expected_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(expected_seed, &output) == GEN3_OK);
    uint8_t expected_first = random_below(output, 2) == 0 ? 0 : 1;

    sort_action_queue(&battle);
    assert(memcmp(battle.seed, expected_seed, sizeof(expected_seed)) == 0);
    assert(battle.action_queue.values[
        battle.action_queue.order[0].payload_index
    ].side == expected_first);
    assert(battle.action_queue.values[
        battle.action_queue.order[1].payload_index
    ].side == 1u - expected_first);
}

static void test_distinct_tie_groups_shuffle_independently(void) {
    Gen3Battle battle = {0};
    const uint16_t initial_seed[4] = {1, 65535, 42, 900};
    memcpy(battle.seed, initial_seed, sizeof(initial_seed));
    Gen3OrderedRecord records[] = {
        {.key = {.order = 103, .speed = 100}, .payload_index = 20},
        {.key = {.order = 103, .speed = 200}, .payload_index = 10},
        {.key = {.order = 103, .speed = 100}, .payload_index = 21},
        {.key = {.order = 103, .speed = 200}, .payload_index = 11},
    };
    uint16_t expected_seed[4];
    memcpy(expected_seed, initial_seed, sizeof(expected_seed));
    uint32_t first_output = 0;
    uint32_t second_output = 0;
    assert(gen3_prng_next(expected_seed, &first_output) == GEN3_OK);
    assert(gen3_prng_next(expected_seed, &second_output) == GEN3_OK);

    sort_ordered_records(
        &battle, records, 4, GEN3_TRACE_PRNG_UNKNOWN
    );
    uint8_t fast_first = random_below(first_output, 2) == 0 ? 10 : 11;
    uint8_t slow_first = random_below(second_output, 2) == 0 ? 20 : 21;
    assert(records[0].payload_index == fast_first);
    assert(records[1].payload_index == (uint8_t)(21 - fast_first));
    assert(records[2].payload_index == slow_first);
    assert(records[3].payload_index == (uint8_t)(41 - slow_first));
    assert(memcmp(battle.seed, expected_seed, sizeof(expected_seed)) == 0);
}

static void test_simultaneous_replacement_order_and_atomicity(void) {
    Gen3BattleInit init = scheduler_init(150, 250);
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    enter_simultaneous_replacement(battle);

    Gen3BattleSnapshot before;
    Gen3BattleSnapshot after;
    assert(gen3_battle_snapshot(battle, &before) == GEN3_OK);
    assert(gen3_battle_turn(battle, -1, 4) == GEN3_ILLEGAL_ACTION);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);

    uint16_t expected_seed[4];
    memcpy(expected_seed, before.seed, sizeof(expected_seed));
    uint32_t ignored = 0;
    /* Distinct incoming speeds leave no tie groups; only Quick Claw rolls. */
    assert(gen3_prng_next(expected_seed, &ignored) == GEN3_OK);

    assert(gen3_battle_turn(battle, 4, 4) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(after.turn == before.turn + 1);
    assert(after.force_switch_side == -1);
    assert(after.resume_residuals == 0);
    assert(after.event_count == 2);
    assert(after.events[0].side == 1);
    assert(after.events[1].side == 0);
    assert(after.pokemon[0][0].set.species_id == 2);
    assert(after.pokemon[1][0].set.species_id == 8);
    assert(memcmp(after.seed, expected_seed, sizeof(expected_seed)) == 0);
    gen3_battle_destroy(battle);
}

static void test_simultaneous_replacements_preserve_saved_tail(void) {
    Gen3BattleInit init = scheduler_init(150, 250);
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    enter_simultaneous_replacement(battle);
    sync_phase_from_legacy_request(battle);
    assert(battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(battle->phase.continuation == GEN3_CONTINUE_RESIDUAL);
    assert(action_queue_is_residual_continuation(&battle->action_queue));

    const Gen3Choice choices[GEN3_SIDE_COUNT] = {
        decode_choice(0, 4), decode_choice(1, 4),
    };
    assert(compile_simultaneous_forced_switches(battle, choices) == GEN3_OK);
    assert(battle->phase.kind == GEN3_PHASE_EXECUTING);
    assert(battle->action_queue.count == 3);
    assert(queued_action(battle, 0).kind == GEN3_ACTION_INSTASWITCH);
    assert(queued_action(battle, 1).kind == GEN3_ACTION_INSTASWITCH);
    assert(queued_action(battle, 2).kind == GEN3_ACTION_RESIDUAL);
    gen3_battle_destroy(battle);
}

static void test_single_replacement_preserves_tail_across_hazard_faint(void) {
    Gen3BattleInit init = scheduler_init(150, 250);
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    enter_single_replacement(battle, 0);
    battle->spikes[0] = 1;
    battle->state[0][1].hp = 1;
    uint32_t suspended_turn = battle->turn;

    assert(gen3_battle_turn(battle, 4, -1) == GEN3_OK);
    assert(battle->turn == suspended_turn);
    assert(battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(battle->phase.required_side_mask == 1);
    assert(battle->phase.continuation == GEN3_CONTINUE_RESIDUAL);
    assert(battle->force_switch_side == 0);
    assert(action_queue_is_residual_continuation(&battle->action_queue));

    assert(gen3_battle_turn(battle, 5, -1) == GEN3_OK);
    assert(battle->turn == suspended_turn + 1);
    assert(battle->phase.kind == GEN3_PHASE_NORMAL_REQUEST);
    assert(battle->force_switch_side == -1);
    assert(battle->resume_residuals == 0);
    assert(battle->action_queue.count == 0);
    assert(battle->teams[0].pokemon[0].species_id == 3);
    gen3_battle_destroy(battle);
}

static void test_standalone_forced_replacement_does_not_advance_turn(void) {
    Gen3BattleInit init = scheduler_init(150, 250);
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    battle->state[0][0].hp = 0;
    battle->force_switch_side = 0;
    battle->resume_residuals = 0;
    sync_phase_from_legacy_request(battle);
    assert(battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(battle->phase.continuation == GEN3_CONTINUE_NONE);
    uint32_t turn = battle->turn;

    assert(gen3_battle_turn(battle, 4, -1) == GEN3_OK);
    assert(battle->phase.kind == GEN3_PHASE_NORMAL_REQUEST);
    assert(battle->turn == turn);
    gen3_battle_destroy(battle);
}

static void test_simultaneous_replacement_tie_rng_and_order(void) {
    Gen3BattleInit init = scheduler_init(200, 200);
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    enter_simultaneous_replacement(battle);

    Gen3BattleSnapshot before;
    Gen3BattleSnapshot after;
    assert(gen3_battle_snapshot(battle, &before) == GEN3_OK);
    uint16_t expected_seed[4];
    memcpy(expected_seed, before.seed, sizeof(expected_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(expected_seed, &output) == GEN3_OK);
    uint8_t expected_first = random_below(output, 2) == 0 ? 0 : 1;
    /* The initial instaswitch tie is followed by the runSwitch insertion
     * tie, four Update ties, the residual handler tie, and Quick Claw. */
    for (size_t frame = 0; frame < 7; frame++) {
        assert(gen3_prng_next(expected_seed, &output) == GEN3_OK);
    }

    assert(gen3_battle_turn(battle, 4, 4) == GEN3_OK);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(after.event_count == 2);
    assert(after.events[0].side == expected_first);
    assert(after.events[1].side == 1u - expected_first);
    assert(memcmp(after.seed, expected_seed, sizeof(expected_seed)) == 0);
    gen3_battle_destroy(battle);
}

static void test_frontier_lifecycle_seed(void) {
    Gen3BattleInit init = scheduler_init(350, 361);
    const uint16_t frontier_seed[4] = {17653, 1533, 5116, 58098};
    memcpy(init.seed, frontier_seed, sizeof(frontier_seed));
    /* Unequal fainted owners order p2 before p1; equal replacements exercise
     * insertChoice, three post-action Updates, Residual, final Update and QC. */
    init.teams[0].pokemon[1].stats[5] = 176;
    init.teams[1].pokemon[1].stats[5] = 176;
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    memcpy(battle->seed, frontier_seed, sizeof(frontier_seed));
    enter_simultaneous_replacement(battle);

    assert(gen3_battle_turn(battle, 4, 4) == GEN3_OK);
    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    const uint16_t expected_seed[4] = {21063, 23239, 53173, 47243};
    assert(memcmp(snapshot.seed, expected_seed, sizeof(expected_seed)) == 0);
    assert(snapshot.event_count == 2);
    assert(snapshot.events[0].side == 1);
    assert(snapshot.events[1].side == 0);
    gen3_battle_destroy(battle);
}

int main(void) {
    test_canonical_order_comparator();
    test_physical_insertion_order_is_tie_input();
    test_tie_group_shuffle_consumes_one_frame();
    test_distinct_tie_groups_shuffle_independently();
    test_simultaneous_replacement_order_and_atomicity();
    test_simultaneous_replacements_preserve_saved_tail();
    test_single_replacement_preserves_tail_across_hazard_faint();
    test_standalone_forced_replacement_does_not_advance_turn();
    test_simultaneous_replacement_tie_rng_and_order();
    test_frontier_lifecycle_seed();
    puts("gen3 scheduler tests passed");
    return 0;
}
