#include "gen3_abi.c"

#include <assert.h>
#include <string.h>

typedef struct {
    Gen3TraceRecord records[64];
    size_t count;
    size_t snapshot_queries;
    size_t legal_queries;
} Capture;

static Gen3PokemonSet make_set(uint16_t species, uint16_t speed) {
    Gen3PokemonSet set = {0};
    set.abi_version = GEN3_ABI_VERSION;
    set.struct_size = sizeof(set);
    set.species_id = species;
    set.ability_id = 5; /* Sturdy */
    set.level = 100;
    set.gender = 0;
    set.happiness = 255;
    for (size_t move = 0; move < GEN3_MOVE_SLOTS; move++) {
        set.move_ids[move] = (uint16_t)(move + 1);
        set.max_pp[move] = 10;
    }
    for (size_t stat = 0; stat < 6; stat++) set.stats[stat] = 200;
    set.stats[5] = speed;
    return set;
}

static Gen3BattleInit make_init(void) {
    Gen3BattleInit init = {0};
    init.abi_version = GEN3_ABI_VERSION;
    init.struct_size = sizeof(init);
    init.seed[0] = 1;
    init.seed[1] = 2;
    init.seed[2] = 3;
    init.seed[3] = 4;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].abi_version = GEN3_ABI_VERSION;
        init.teams[side].struct_size = sizeof(init.teams[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            init.teams[side].pokemon[slot] = make_set(
                (uint16_t)(side * GEN3_TEAM_SIZE + slot + 1),
                (uint16_t)(100 + side * 20 + slot)
            );
        }
    }
    return init;
}

static void capture_emit(
    void *context, const Gen3Battle *battle, const Gen3TraceRecord *record
) {
    Capture *capture = context;
    assert(capture->count < sizeof(capture->records) / sizeof(capture->records[0]));
    capture->records[capture->count++] = *record;

    Gen3BattleSnapshot snapshot;
    assert(gen3_battle_snapshot(battle, &snapshot) == GEN3_OK);
    capture->snapshot_queries++;
    for (uint8_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t mask = 0;
        assert(gen3_battle_legal_actions(battle, side, &mask) == GEN3_OK);
        capture->legal_queries++;
    }
}

static void test_streaming_trace_is_ordered_and_observational(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *traced = NULL;
    Gen3Battle *plain = NULL;
    assert(gen3_battle_create(&init, &traced, NULL, 0) == GEN3_OK);
    assert(gen3_battle_create(&init, &plain, NULL, 0) == GEN3_OK);

    Capture capture = {0};
    Gen3TraceSink sink = {
        .abi_version = GEN3_TRACE_ABI_VERSION,
        .struct_size = sizeof(sink),
        .context = &capture,
        .emit = capture_emit,
    };
    assert(gen3_battle_set_trace_sink(traced, &sink) == GEN3_OK);
    assert(capture.count == 2);
    assert(capture.records[0].kind == GEN3_TRACE_CHECKPOINT);
    assert(capture.records[0].semantic_point == GEN3_TRACE_POINT_INSTALL);
    assert(capture.records[1].kind == GEN3_TRACE_REQUEST);
    assert(capture.records[1].value.request.legal_mask[0] == 0x1ff);
    assert(capture.records[1].value.request.legal_mask[1] == 0x1ff);

    assert(gen3_battle_turn(traced, 4, 4) == GEN3_OK);
    assert(gen3_battle_turn(plain, 4, 4) == GEN3_OK);
    assert(capture.count == 7);
    assert(capture.records[2].kind == GEN3_TRACE_CHECKPOINT);
    assert(capture.records[2].semantic_point == GEN3_TRACE_POINT_DECISION_BEGIN);
    assert(capture.records[3].kind == GEN3_TRACE_PROTOCOL);
    assert(capture.records[3].value.protocol.kind == GEN3_EVENT_SWITCH);
    assert(capture.records[3].value.protocol.side == 1);
    assert(capture.records[4].kind == GEN3_TRACE_PROTOCOL);
    assert(capture.records[4].value.protocol.side == 0);
    assert(capture.records[5].kind == GEN3_TRACE_CHECKPOINT);
    assert(capture.records[5].semantic_point == GEN3_TRACE_POINT_DECISION_END);
    assert(capture.records[6].kind == GEN3_TRACE_REQUEST);

    for (size_t index = 0; index < capture.count; index++) {
        assert(capture.records[index].abi_version == GEN3_TRACE_ABI_VERSION);
        assert(capture.records[index].struct_size == sizeof(Gen3TraceRecord));
        assert(capture.records[index].sequence == index);
        assert(capture.records[index].boundary == (index < 2 ? 0u : 1u));
    }
    assert(capture.snapshot_queries == capture.count);
    assert(capture.legal_queries == capture.count * GEN3_SIDE_COUNT);

    Gen3BattleSnapshot traced_state;
    Gen3BattleSnapshot plain_state;
    assert(gen3_battle_snapshot(traced, &traced_state) == GEN3_OK);
    assert(gen3_battle_snapshot(plain, &plain_state) == GEN3_OK);
    assert(memcmp(&traced_state, &plain_state, sizeof(traced_state)) == 0);

    assert(gen3_battle_set_trace_sink(traced, NULL) == GEN3_OK);
    size_t stopped_at = capture.count;
    assert(gen3_battle_turn(traced, 4, 4) == GEN3_OK);
    assert(capture.count == stopped_at);
    gen3_battle_destroy(traced);
    gen3_battle_destroy(plain);
}

static void test_sink_layout_is_rejected(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    Gen3TraceSink sink = {0};
    assert(gen3_battle_set_trace_sink(battle, &sink) == GEN3_INVALID_LAYOUT);
    gen3_battle_destroy(battle);
}

static void clear_capture(Capture *capture) {
    memset(capture, 0, sizeof(*capture));
}

static void assert_prng_record(
    const Gen3TraceRecord *record, uint16_t label,
    const uint16_t before[4], const uint16_t after[4],
    uint32_t raw, uint32_t limit
) {
    assert(record->kind == GEN3_TRACE_PRNG);
    assert(record->value.prng.label == label);
    assert(record->value.prng.operation == GEN3_TRACE_PRNG_BELOW);
    assert(memcmp(record->value.prng.seed_before, before, sizeof(uint16_t) * 4) == 0);
    assert(memcmp(record->value.prng.seed_after, after, sizeof(uint16_t) * 4) == 0);
    assert(record->value.prng.argument0 == limit);
    assert(record->value.prng.argument1 == 0);
    assert(record->value.prng.raw_output == raw);
    assert(record->value.prng.result == random_below(raw, limit));
}

static void assert_queue_record(
    const Gen3TraceRecord *record, uint16_t operation, uint32_t stable_id,
    uint8_t action_kind, uint8_t side, uint8_t queue_count
);

static void test_scheduler_prng_staging(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *battle = NULL;
    Gen3Battle *plain = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    assert(gen3_battle_create(&init, &plain, NULL, 0) == GEN3_OK);
    Capture capture = {0};
    Gen3TraceSink sink = {
        .abi_version = GEN3_TRACE_ABI_VERSION,
        .struct_size = sizeof(sink),
        .context = &capture,
        .emit = capture_emit,
    };
    assert(gen3_battle_set_trace_sink(battle, &sink) == GEN3_OK);
    clear_capture(&capture);

    cancel_action_queue(battle);
    cancel_action_queue(plain);
    push_action(battle, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 0,
        .key = {.order = 103, .speed = 200},
    });
    push_action(plain, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 0,
        .key = {.order = 103, .speed = 200},
    });
    push_action(battle, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 1,
        .key = {.order = 103, .speed = 200},
    });
    push_action(plain, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = 1,
        .key = {.order = 103, .speed = 200},
    });
    clear_capture(&capture);
    uint16_t sort_before[4];
    uint16_t sort_after[4];
    memcpy(sort_before, battle->seed, sizeof(sort_before));
    memcpy(sort_after, sort_before, sizeof(sort_after));
    uint32_t sort_raw = 0;
    assert(gen3_prng_next(sort_after, &sort_raw) == GEN3_OK);
    sort_action_queue(battle);
    sort_action_queue(plain);
    assert(capture.count == 3);
    assert_prng_record(
        &capture.records[0], GEN3_TRACE_PRNG_QUEUE_TIE_SHUFFLE,
        sort_before, sort_after, sort_raw, 2
    );
    for (size_t index = 0; index < 2; index++) {
        const Gen3TraceRecord *record = &capture.records[index + 1];
        assert(record->kind == GEN3_TRACE_QUEUE_ITEM);
        assert(record->value.queue.operation == GEN3_TRACE_QUEUE_SORT);
        assert(record->value.queue.index == index);
        assert(record->value.queue.queue_count == 2);
    }
    assert(memcmp(battle->seed, sort_after, sizeof(sort_after)) == 0);

    clear_capture(&capture);
    Gen3Action tied = {
        .kind = GEN3_ACTION_RUN_SWITCH,
        .side = 0,
        .key = {.order = 103, .speed = 200},
    };
    uint16_t insert_before[4];
    uint16_t insert_after[4];
    memcpy(insert_before, battle->seed, sizeof(insert_before));
    memcpy(insert_after, insert_before, sizeof(insert_after));
    uint32_t insert_raw = 0;
    assert(gen3_prng_next(insert_after, &insert_raw) == GEN3_OK);
    insert_action(battle, tied);
    insert_action(plain, tied);
    assert(capture.count == 2);
    assert_prng_record(
        &capture.records[0], GEN3_TRACE_PRNG_QUEUE_TIE_INSERT,
        insert_before, insert_after, insert_raw, 3
    );
    assert(capture.records[1].kind == GEN3_TRACE_QUEUE_ITEM);
    assert(capture.records[1].value.queue.operation == GEN3_TRACE_QUEUE_INSERT);
    assert(capture.records[1].value.queue.index <= 2);
    assert(capture.records[1].value.queue.queue_count == 3);
    assert(memcmp(battle->seed, insert_after, sizeof(insert_after)) == 0);
    Gen3BattleSnapshot traced_state;
    Gen3BattleSnapshot plain_state;
    assert(gen3_battle_snapshot(battle, &traced_state) == GEN3_OK);
    assert(gen3_battle_snapshot(plain, &plain_state) == GEN3_OK);
    assert(memcmp(&traced_state, &plain_state, sizeof(traced_state)) == 0);

    uint32_t cancelled_ids[3];
    uint8_t cancelled_kinds[3];
    uint8_t cancelled_sides[3];
    for (size_t index = 0; index < 3; index++) {
        const Gen3OrderedRecord *record =
            &battle->action_queue.order[battle->action_queue.head + index];
        const Gen3Action *action =
            &battle->action_queue.values[record->payload_index];
        cancelled_ids[index] = action->trace_stable_id;
        cancelled_kinds[index] = (uint8_t)action->kind;
        cancelled_sides[index] = action->side;
    }
    clear_capture(&capture);
    cancel_action_queue(battle);
    cancel_action_queue(plain);
    assert(capture.count == 3);
    for (size_t index = 0; index < 3; index++) {
        assert_queue_record(&capture.records[index], GEN3_TRACE_QUEUE_CANCEL,
            cancelled_ids[index], cancelled_kinds[index],
            cancelled_sides[index], 3);
        assert(capture.records[index].value.queue.index == index);
    }
    gen3_battle_destroy(battle);
    gen3_battle_destroy(plain);
}

static void assert_queue_record(
    const Gen3TraceRecord *record, uint16_t operation, uint32_t stable_id,
    uint8_t action_kind, uint8_t side, uint8_t queue_count
) {
    assert(record->kind == GEN3_TRACE_QUEUE_ITEM);
    assert(record->value.queue.operation == operation);
    assert(record->value.queue.stable_id == stable_id);
    assert(record->value.queue.action_kind == action_kind);
    assert(record->value.queue.side == side);
    assert(record->value.queue.queue_count == queue_count);
}

static void test_forced_replacement_suspends_and_resumes_residual(void) {
    Gen3BattleInit init = make_init();
    Gen3Battle *traced = NULL;
    Gen3Battle *plain = NULL;
    assert(gen3_battle_create(&init, &traced, NULL, 0) == GEN3_OK);
    assert(gen3_battle_create(&init, &plain, NULL, 0) == GEN3_OK);
    Capture capture = {0};
    Gen3TraceSink sink = {
        .abi_version = GEN3_TRACE_ABI_VERSION,
        .struct_size = sizeof(sink),
        .context = &capture,
        .emit = capture_emit,
    };
    assert(gen3_battle_set_trace_sink(traced, &sink) == GEN3_OK);
    clear_capture(&capture);

    Gen3Battle *battles[] = {traced, plain};
    for (size_t index = 0; index < 2; index++) {
        Gen3Battle *battle = battles[index];
        battle->force_switch_side = 0;
        battle->resume_residuals = 1;
        battle->spikes[0] = 3;
        battle->state[0][1].hp = 1;
        sync_phase_from_legacy_request(battle);
    }
    /* Ignore the setup's continuation compilation. Its stable ID remains 1
     * and lets the lifecycle below prove identity across two requests. */
    clear_capture(&capture);

    Gen3Choice first[GEN3_SIDE_COUNT] = {
        {.kind = GEN3_CHOICE_SWITCH, .side = 0, .slot = 1},
        {.kind = GEN3_CHOICE_NONE, .side = 1},
    };
    assert(compile_single_forced_switch(traced, first) == GEN3_OK);
    assert(compile_single_forced_switch(plain, first) == GEN3_OK);
    assert(execute_single_forced_switch(traced) == GEN3_OK);
    assert(execute_single_forced_switch(plain) == GEN3_OK);
    assert(traced->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(action_queue_is_residual_continuation(&traced->action_queue));

    Gen3Choice second[GEN3_SIDE_COUNT] = {
        {.kind = GEN3_CHOICE_SWITCH, .side = 0, .slot = 2},
        {.kind = GEN3_CHOICE_NONE, .side = 1},
    };
    assert(compile_single_forced_switch(traced, second) == GEN3_OK);
    assert(compile_single_forced_switch(plain, second) == GEN3_OK);
    assert(execute_single_forced_switch(traced) == GEN3_OK);
    assert(execute_single_forced_switch(plain) == GEN3_OK);

    const uint16_t operations[] = {
        GEN3_TRACE_QUEUE_SUSPEND, GEN3_TRACE_QUEUE_COMPILE,
        GEN3_TRACE_QUEUE_RESUME, GEN3_TRACE_QUEUE_POP,
        GEN3_TRACE_QUEUE_SUSPEND, GEN3_TRACE_QUEUE_COMPILE,
        GEN3_TRACE_QUEUE_RESUME, GEN3_TRACE_QUEUE_POP,
        GEN3_TRACE_QUEUE_POP,
    };
    const uint32_t ids[] = {1, 2, 1, 2, 1, 3, 1, 3, 1};
    const uint8_t kinds[] = {
        GEN3_ACTION_RESIDUAL, GEN3_ACTION_SWITCH, GEN3_ACTION_RESIDUAL,
        GEN3_ACTION_SWITCH, GEN3_ACTION_RESIDUAL, GEN3_ACTION_SWITCH,
        GEN3_ACTION_RESIDUAL, GEN3_ACTION_SWITCH, GEN3_ACTION_RESIDUAL,
    };
    const uint8_t counts[] = {0, 1, 2, 1, 0, 1, 2, 1, 0};
    size_t queue_index = 0;
    for (size_t index = 0; index < capture.count; index++) {
        if (capture.records[index].kind != GEN3_TRACE_QUEUE_ITEM) continue;
        assert(queue_index < sizeof(operations) / sizeof(operations[0]));
        assert_queue_record(&capture.records[index], operations[queue_index],
            ids[queue_index], kinds[queue_index],
            0, counts[queue_index]);
        queue_index++;
    }
    assert(queue_index == sizeof(operations) / sizeof(operations[0]));

    Gen3BattleSnapshot traced_state;
    Gen3BattleSnapshot plain_state;
    assert(gen3_battle_snapshot(traced, &traced_state) == GEN3_OK);
    assert(gen3_battle_snapshot(plain, &plain_state) == GEN3_OK);
    assert(memcmp(&traced_state, &plain_state, sizeof(traced_state)) == 0);
    assert(memcmp(traced->seed, plain->seed, sizeof(traced->seed)) == 0);
    gen3_battle_destroy(traced);
    gen3_battle_destroy(plain);
}

int main(void) {
    test_streaming_trace_is_ordered_and_observational();
    test_sink_layout_is_rejected();
    test_scheduler_prng_staging();
    test_forced_replacement_suspends_and_resumes_residual();
    return 0;
}
