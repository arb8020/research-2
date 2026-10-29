#include "gen3_abi.c"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static Gen3PokemonSet effect_set(
    uint16_t species, uint16_t ability, uint16_t item, uint16_t max_hp
) {
    Gen3PokemonSet set = {0};
    set.abi_version = GEN3_ABI_VERSION;
    set.struct_size = sizeof(set);
    set.species_id = species;
    set.ability_id = ability;
    set.item_id = item;
    set.stats[0] = max_hp;
    set.stats[5] = 100;
    set.level = 100;
    return set;
}

static void assert_seed_equal(
    const uint16_t left[4], const uint16_t right[4]
) {
    assert(memcmp(left, right, sizeof(uint16_t) * 4) == 0);
}

static void test_descriptor_lookup(void) {
    const Gen3EffectDescriptor *spikes = find_effect_descriptor(
        (Gen3EffectRef){GEN3_EFFECT_SIDE_CONDITION, GEN3_CONDITION_SPIKES}
    );
    assert(spikes != NULL);
    assert(find_effect_handler(
        spikes, GEN3_EFFECT_EVENT_ENTRY_HAZARD
    )->native_handler_id == GEN3_NATIVE_HANDLER_SPIKES_ENTRY);

    const Gen3EffectDescriptor *leftovers = find_effect_descriptor(
        (Gen3EffectRef){GEN3_EFFECT_ITEM, GEN3_ITEM_LEFTOVERS}
    );
    assert(leftovers != NULL);
    const Gen3HandlerDescriptor *residual = find_effect_handler(
        leftovers, GEN3_EFFECT_EVENT_RESIDUAL
    );
    assert(residual != NULL);
    assert(residual->order == 10);
    assert(residual->priority == 0);
    assert(residual->sub_order == 4);

    const Gen3EffectDescriptor *natural_cure = find_effect_descriptor(
        (Gen3EffectRef){GEN3_EFFECT_ABILITY, GEN3_ABILITY_NATURAL_CURE}
    );
    assert(natural_cure != NULL);
    assert(find_effect_handler(
        natural_cure, GEN3_EFFECT_EVENT_SWITCH_OUT
    )->native_handler_id == GEN3_NATIVE_HANDLER_NATURAL_CURE_SWITCH_OUT);
    assert(find_effect_handler(
        natural_cure, GEN3_EFFECT_EVENT_RESIDUAL
    ) == NULL);

    assert(find_effect_descriptor(
        (Gen3EffectRef){GEN3_EFFECT_ABILITY, 65535}
    ) == NULL);

    Gen3Battle battle = {0};
    Gen3RuntimeEvent event = {
        .event_id = GEN3_EFFECT_EVENT_RESIDUAL,
        .effect = {GEN3_EFFECT_ABILITY, GEN3_ABILITY_NATURAL_CURE},
        .holder = {GEN3_HOLDER_POKEMON, 0, 0},
        .target = {GEN3_HOLDER_POKEMON, 0, 0},
    };
    assert(dispatch_effect_event(&battle, &event) ==
        GEN3_EFFECT_DISPATCH_NO_HANDLER);
    event.effect.id = 65535;
    assert(dispatch_effect_event(&battle, &event) ==
        GEN3_EFFECT_DISPATCH_UNKNOWN);
}

static void test_handler_materialization_and_capacity(void) {
    Gen3RuntimeEvent events[2] = {0};
    Gen3OrderedRecord records[2] = {0};
    size_t count = 0;
    Gen3RuntimeEvent residual = {
        .event_id = GEN3_EFFECT_EVENT_RESIDUAL,
        .effect = {GEN3_EFFECT_ITEM, GEN3_ITEM_LEFTOVERS},
        .holder = {GEN3_HOLDER_POKEMON, 0, 0},
        .target = {GEN3_HOLDER_POKEMON, 0, 0},
        .source = {GEN3_HOLDER_NONE, 0, 0},
    };
    assert(append_materialized_handler(
        events, records, 2, &count, residual, 123, 0
    ) == GEN3_MATERIALIZE_OK);
    assert(count == 1);
    assert(events[0].insertion_order == 0);
    assert(records[0].payload_index == 0);
    assert(records[0].key.order == 10);
    assert(records[0].key.priority == 0);
    assert(records[0].key.speed == 123);
    assert(records[0].key.sub_order == 4);

    residual.holder.side = 1;
    residual.target.side = 1;
    assert(append_materialized_handler(
        events, records, 2, &count, residual, 99, 0
    ) == GEN3_MATERIALIZE_OK);
    assert(count == 2 && events[1].insertion_order == 1);
    assert(compare_ordered_records(&records[0], &records[1]) < 0);

    /* Exhaustion is explicit and leaves the existing materialization intact. */
    assert(append_materialized_handler(
        events, records, 2, &count, residual, 1, 0
    ) == GEN3_MATERIALIZE_CAPACITY);
    assert(count == 2);

    count = 0;
    residual.effect.id = 65535;
    assert(append_materialized_handler(
        events, records, 2, &count, residual, 1, 0
    ) == GEN3_MATERIALIZE_UNKNOWN_EFFECT);
    residual.effect = (Gen3EffectRef){
        GEN3_EFFECT_ABILITY, GEN3_ABILITY_NATURAL_CURE
    };
    assert(append_materialized_handler(
        events, records, 2, &count, residual, 1, 0
    ) == GEN3_MATERIALIZE_NO_HANDLER);
    assert(count == 0);
}

static void test_transactional_handler_discovery(void) {
    Gen3Battle battle = {0};
    battle.seed[0] = 1;
    battle.seed[1] = 2;
    battle.seed[2] = 3;
    battle.seed[3] = 4;
    battle.teams[0].pokemon[0] = effect_set(
        242, GEN3_ABILITY_NATURAL_CURE, GEN3_ITEM_LEFTOVERS, 651
    );
    battle.teams[1].pokemon[0] = effect_set(
        242, GEN3_ABILITY_NATURAL_CURE, GEN3_ITEM_LEFTOVERS, 651
    );
    battle.teams[0].pokemon[0].stats[5] = 90;
    battle.teams[1].pokemon[0].stats[5] = 120;

    Gen3RuntimeEvent events[2] = {0};
    Gen3OrderedRecord records[2] = {0};
    size_t count = 0;
    Gen3DiscoveryRequest residual = {
        .event_id = GEN3_EFFECT_EVENT_RESIDUAL,
        .scope = GEN3_DISCOVER_ACTIVE_ITEMS,
    };
    assert(discover_effect_handlers(
        &battle, residual, events, records, 2, &count
    ) == GEN3_DISCOVER_OK);
    assert(count == 2);
    /* Discovery is pure and preserves Showdown holder enumeration. Event
     * execution owns ordering and any exact-tie PRNG. */
    assert(events[records[0].payload_index].holder.side == 0);
    assert(events[records[1].payload_index].holder.side == 1);
    sort_ordered_records(
        &battle, records, count, GEN3_TRACE_PRNG_UNKNOWN
    );
    assert(events[records[0].payload_index].holder.side == 1);
    assert(events[records[1].payload_index].holder.side == 0);

    /* Capacity and unsupported descriptors are rejected before any output is
     * touched, including a nonzero starting count. */
    Gen3RuntimeEvent event_sentinel = events[0];
    Gen3OrderedRecord record_sentinel = records[0];
    count = 1;
    assert(discover_effect_handlers(
        &battle, residual, events, records, 2, &count
    ) == GEN3_DISCOVER_CAPACITY);
    assert(count == 1);
    assert(memcmp(&events[0], &event_sentinel, sizeof(event_sentinel)) == 0);
    assert(memcmp(&records[0], &record_sentinel, sizeof(record_sentinel)) == 0);

    battle.teams[0].pokemon[0].item_id = 65535;
    count = 0;
    memset(events, 0x5a, sizeof(events));
    memset(records, 0xa5, sizeof(records));
    Gen3RuntimeEvent events_before[2];
    Gen3OrderedRecord records_before[2];
    memcpy(events_before, events, sizeof(events));
    memcpy(records_before, records, sizeof(records));
    assert(discover_effect_handlers(
        &battle, residual, events, records, 2, &count
    ) == GEN3_DISCOVER_UNSUPPORTED_EFFECT);
    assert(count == 0);
    assert(memcmp(events, events_before, sizeof(events)) == 0);
    assert(memcmp(records, records_before, sizeof(records)) == 0);
}

static void test_event_owned_discovery_order(void) {
    Gen3Battle battle = {0};
    battle.teams[0].pokemon[0] = effect_set(
        227, GEN3_ABILITY_STURDY, 0, 334
    );
    battle.teams[1].pokemon[0] = effect_set(
        227, GEN3_ABILITY_STURDY, 0, 334
    );
    battle.teams[0].pokemon[0].stats[5] = 80;
    battle.teams[1].pokemon[0].stats[5] = 140;

    Gen3RuntimeEvent events[2] = {0};
    Gen3OrderedRecord records[2] = {0};
    size_t count = 0;
    Gen3DiscoveryRequest try_hit = {
        .event_id = GEN3_EFFECT_EVENT_TRY_HIT,
        .scope = GEN3_DISCOVER_ACTIVE_ABILITIES,
        .target = {GEN3_HOLDER_POKEMON, 0, 0},
        .source = {GEN3_HOLDER_POKEMON, 1, 0},
    };
    assert(event_order_policy(try_hit.event_id) ==
        GEN3_EVENT_ORDER_LEFT_TO_RIGHT);
    assert(discover_effect_handlers(
        &battle, try_hit, events, records, 2, &count
    ) == GEN3_DISCOVER_OK);
    assert(count == 1 && events[0].holder.side == 0);

    battle.spikes[0] = 1;
    battle.spikes[1] = 1;
    count = 0;
    Gen3DiscoveryRequest entry_hazard = {
        .event_id = GEN3_EFFECT_EVENT_ENTRY_HAZARD,
        .scope = GEN3_DISCOVER_SIDE_CONDITIONS,
        .target = {GEN3_HOLDER_POKEMON, 1, 0},
    };
    assert(event_order_policy(entry_hazard.event_id) ==
        GEN3_EVENT_ORDER_LEFT_TO_RIGHT);
    assert(discover_effect_handlers(
        &battle, entry_hazard, events, records, 2, &count
    ) == GEN3_DISCOVER_OK);
    assert(count == 1 && events[0].holder.kind == GEN3_HOLDER_SIDE &&
        events[0].holder.side == 1);
    assert(event_order_policy(GEN3_EFFECT_EVENT_RESIDUAL) ==
        GEN3_EVENT_ORDER_SPEED);
}

static void test_leftovers_dispatch_preserves_seed(void) {
    Gen3Battle battle = {0};
    battle.seed[0] = 1;
    battle.seed[1] = 2;
    battle.seed[2] = 3;
    battle.seed[3] = 4;
    uint16_t seed_before[4];
    memcpy(seed_before, battle.seed, sizeof(seed_before));
    battle.teams[0].pokemon[0] = effect_set(
        242, GEN3_ABILITY_NATURAL_CURE, GEN3_ITEM_LEFTOVERS, 651
    );
    battle.state[0][0].hp = 620;

    apply_leftovers_side(&battle, 0);
    assert(battle.state[0][0].hp == 651);
    assert(battle.event_count == 1);
    assert(battle.events[0].kind == GEN3_EVENT_HEAL);
    assert(battle.events[0].hp == 651);
    assert_seed_equal(battle.seed, seed_before);

    apply_leftovers_side(&battle, 0);
    assert(battle.event_count == 1);
    assert_seed_equal(battle.seed, seed_before);
}

static void test_spikes_dispatch_and_immunities(void) {
    Gen3Battle battle = {0};
    battle.seed[0] = 11;
    battle.seed[1] = 22;
    battle.seed[2] = 33;
    battle.seed[3] = 44;
    uint16_t seed_before[4];
    memcpy(seed_before, battle.seed, sizeof(seed_before));
    battle.spikes[0] = 1;
    battle.teams[0].pokemon[0] = effect_set(
        242, GEN3_ABILITY_NATURAL_CURE, 0, 651
    );
    battle.state[0][0].hp = 100;
    battle.state[0][1].hp = 1;
    assert(!apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].hp == 19);
    assert(battle.event_count == 1);
    assert(battle.events[0].kind == GEN3_EVENT_DAMAGE);
    assert_seed_equal(battle.seed, seed_before);

    battle.event_count = 0;
    battle.spikes[0] = 2;
    battle.state[0][0].hp = 651;
    assert(!apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].hp == 543);
    battle.event_count = 0;
    battle.spikes[0] = 3;
    battle.state[0][0].hp = 651;
    assert(!apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].hp == 489);

    battle.event_count = 0;
    battle.spikes[0] = 1;
    battle.state[0][0].hp = 80;
    battle.state[0][0].status = GEN3_STATUS_TOXIC;
    battle.state[0][0].toxic_counter = 3;
    battle.state[0][0].leech_seeded = 1;
    assert(apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].status == GEN3_STATUS_NONE);
    assert(battle.state[0][0].toxic_counter == 0);
    assert(battle.state[0][0].leech_seeded == 0);
    assert(battle.event_count == 2);
    assert(battle.events[0].kind == GEN3_EVENT_DAMAGE);
    assert(battle.events[1].kind == GEN3_EVENT_FAINT);
    assert_seed_equal(battle.seed, seed_before);

    battle.event_count = 0;
    battle.teams[0].pokemon[0] = effect_set(
        94, GEN3_ABILITY_LEVITATE, 0, 262
    );
    battle.state[0][0].hp = 262;
    assert(!apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].hp == 262);
    assert(battle.event_count == 0);

    battle.teams[0].pokemon[0] = effect_set(
        227, GEN3_ABILITY_STURDY, 0, 334
    );
    battle.state[0][0].hp = 334;
    assert(!apply_spikes_entry_allow_faint(&battle, 0));
    assert(battle.state[0][0].hp == 334);
    assert(battle.event_count == 0);
    assert_seed_equal(battle.seed, seed_before);
}

static void test_natural_cure_dispatch_through_swap(void) {
    Gen3Battle battle = {0};
    battle.seed[0] = 101;
    battle.seed[1] = 202;
    battle.seed[2] = 303;
    battle.seed[3] = 404;
    uint16_t seed_before[4];
    memcpy(seed_before, battle.seed, sizeof(seed_before));
    battle.teams[0].pokemon[0] = effect_set(
        242, GEN3_ABILITY_NATURAL_CURE, 0, 651
    );
    battle.teams[0].pokemon[1] = effect_set(
        227, GEN3_ABILITY_STURDY, 0, 334
    );
    battle.state[0][0].hp = 500;
    battle.state[0][0].status = GEN3_STATUS_TOXIC;
    battle.state[0][0].toxic_counter = 7;
    battle.state[0][1].hp = 334;

    swap_pokemon(&battle, 0, 1);
    assert(battle.teams[0].pokemon[1].ability_id == GEN3_ABILITY_NATURAL_CURE);
    assert(battle.state[0][1].status == GEN3_STATUS_NONE);
    assert(battle.state[0][1].toxic_counter == 0);
    assert(battle.event_count == 0);
    assert_seed_equal(battle.seed, seed_before);

    battle.state[0][0].status = GEN3_STATUS_BURN;
    swap_pokemon(&battle, 0, 1);
    assert(battle.state[0][1].status == GEN3_STATUS_BURN);
    assert_seed_equal(battle.seed, seed_before);
}

static void test_generated_move_programs(void) {
    const Gen3MoveData *toxic = &GEN3_MOVES[GEN3_MOVE_TOXIC];
    assert(toxic->ignore_immunity == 1);
    assert(toxic->primary_program != 0);
    const Gen3MoveProgram *primary =
        &GEN3_MOVE_PROGRAMS[toxic->primary_program];
    assert(primary->chance == 0 && primary->op_count == 1);
    const Gen3MoveProgramOp *operation =
        &GEN3_MOVE_PROGRAM_OPS[primary->first_op];
    assert(operation->opcode == GEN3_PROGRAM_OP_STATUS);
    assert(operation->target == GEN3_PROGRAM_TARGET_TARGET);
    assert(operation->argument == GEN3_PROGRAM_STATUS_TOXIC);

    const Gen3MoveData *ice_beam = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(ice_beam->secondary_program_count == 1);
    const Gen3MoveProgram *freeze =
        &GEN3_MOVE_PROGRAMS[ice_beam->first_secondary_program];
    assert(freeze->chance == 10 && freeze->op_count == 1);
    operation = &GEN3_MOVE_PROGRAM_OPS[freeze->first_op];
    assert(operation->opcode == GEN3_PROGRAM_OP_STATUS);
    assert(operation->argument == GEN3_PROGRAM_STATUS_FREEZE);

    const Gen3MoveData *psychic = &GEN3_MOVES[GEN3_MOVE_PSYCHIC];
    const Gen3MoveProgram *drop =
        &GEN3_MOVE_PROGRAMS[psychic->first_secondary_program];
    operation = &GEN3_MOVE_PROGRAM_OPS[drop->first_op];
    assert(drop->chance == 10 && operation->opcode == GEN3_PROGRAM_OP_BOOST);
    assert(operation->argument == GEN3_PROGRAM_STAT_SPECIAL_DEFENSE);
    assert(operation->amount == -1);

    const Gen3MoveData *earthquake = &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    assert(earthquake->target == GEN3_MOVE_TARGET_ALL_ADJACENT);
    assert(earthquake->primary_program == 0);
    assert(earthquake->secondary_program_count == 0);
    assert(earthquake->ignore_immunity == 0 && earthquake->crit_ratio == 1);
    assert(GEN3_MOVES[GEN3_MOVE_SLASH].crit_ratio == 2);
}

int main(void) {
    test_descriptor_lookup();
    test_handler_materialization_and_capacity();
    test_transactional_handler_discovery();
    test_event_owned_discovery_order();
    test_leftovers_dispatch_preserves_seed();
    test_spikes_dispatch_and_immunities();
    test_natural_cure_dispatch_through_swap();
    test_generated_move_programs();
    puts("gen3 effect runtime tests passed");
    return 0;
}
