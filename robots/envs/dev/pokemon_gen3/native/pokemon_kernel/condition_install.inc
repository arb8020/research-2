#line 1517 "pokemon.c"
static void append_event(PokemonBattle *battle, PokemonEvent event) {
    assert(battle->event_count < POKEMON_EVENT_CAPACITY);
    PokemonEvent *destination = &battle->events[battle->event_count++];
    memset(destination, 0, sizeof(*destination));
    destination->kind = event.kind;
    destination->side = event.side;
    destination->target_side = event.target_side;
    destination->slot = event.slot;
    destination->species_id = event.species_id;
    destination->move_id = event.move_id;
    destination->amount = event.amount;
    destination->hp = event.hp;
    destination->condition_scope = event.condition_scope;
    destination->condition_id = event.condition_id;
    destination->damage_relative_kind = event.damage_relative_kind;
    destination->immunity_cause = event.immunity_cause;
    destination->handler_id = event.handler_id;
    destination->switch_cause = event.switch_cause;
}

static PokemonSourceEffectRef active_source_effect(
    const PokemonBattle *battle, uint16_t fallback_move_id
) {
    if (battle->move_frame_depth != 0) {
        const PokemonSourceEffectRef source_effect = battle->move_frames[
            battle->move_frame_depth - 1].invocation.source_effect;
        if (source_effect.kind != POKEMON_SOURCE_EFFECT_NONE) return source_effect;
    }
    return (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, fallback_move_id};
}

static uint32_t next_semantic_sequence(PokemonBattle *battle);

static int trace_condition(
    PokemonBattle *battle, PokemonConditionScope scope,
    PokemonConditionOperation operation, PokemonConditionReason reason,
    PokemonConditionValueKind value_kind,
    size_t side, size_t slot, uint16_t id, uint8_t before, uint8_t after
) {
    if (battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    PokemonConditionTrace *trace =
        &battle->condition_traces[battle->condition_trace_count++];
    *trace = (PokemonConditionTrace){
            .semantic_sequence = next_semantic_sequence(battle),
            .scope = scope, .operation = operation, .reason = reason,
            .value_kind = value_kind,
            .side = (uint8_t)side, .slot = (uint8_t)slot,
            .condition_id = id, .before_value = before, .after_value = after,
        };
    uint8_t has_before = operation != POKEMON_CONDITION_ADD;
    uint8_t has_after = operation != POKEMON_CONDITION_REMOVE;
    if (value_kind == POKEMON_CONDITION_VALUE_DURATION) {
        trace->has_duration_before = has_before;
        trace->has_duration_after = has_after;
        trace->duration_before = before;
        trace->duration_after = after;
    } else if (value_kind == POKEMON_CONDITION_VALUE_COUNTER) {
        trace->has_counter_before = has_before;
        trace->has_counter_after = has_after;
        trace->counter_before = before;
        trace->counter_after = after;
    } else if (value_kind == POKEMON_CONDITION_VALUE_STAGE) {
        trace->has_stage_before = has_before;
        trace->has_stage_after = has_after;
        trace->stage_before = before;
        trace->stage_after = after;
    }
    if (operation == POKEMON_CONDITION_REMOVE &&
        reason == POKEMON_CONDITION_REASON_EXPIRY) {
        if (value_kind == POKEMON_CONDITION_VALUE_DURATION) {
            trace->duration_before = after;
        } else if (value_kind == POKEMON_CONDITION_VALUE_COUNTER) {
            trace->counter_before = after;
        } else if (value_kind == POKEMON_CONDITION_VALUE_STAGE) {
            trace->stage_before = after;
        }
    }
    return POKEMON_OK;
}

static int volatile_index(const PokemonMutable *state, PokemonVolatileKind kind) {
    for (size_t i = 0; i < state->volatile_count; i++) {
        if (state->volatiles[i].kind == kind) return (int)i;
    }
    return -1;
}

static int volatile_index_by_identity(
    const PokemonMutable *state, uint16_t descriptor_id,
    uint16_t state_generation, uint16_t effect_order
) {
    for (size_t i = 0; i < state->volatile_count; i++) {
        if (state->volatiles[i].descriptor_id == descriptor_id &&
            state->volatiles[i].state_generation == state_generation &&
            state->volatiles[i].effect_order == effect_order) {
            return (int)i;
        }
    }
    return -1;
}

static uint8_t entity_is_living_active(
    const PokemonBattle *battle, PokemonEntityRef entity
) {
    return entity.kind == POKEMON_ENTITY_POKEMON &&
        entity.side < POKEMON_SIDES &&
        entity.slot < battle->team_sizes[entity.side] &&
        battle->sides[entity.side].active == entity.slot &&
        battle->sides[entity.side].state[entity.slot].hp != 0;
}

/* Showdown's Pokemon.isActive is slot occupancy, not liveness. A fainted
 * source remains active until the replacement transaction changes the slot. */
static uint8_t entity_is_active(
    const PokemonBattle *battle, PokemonEntityRef entity
) {
    return entity.kind == POKEMON_ENTITY_POKEMON &&
        entity.side < POKEMON_SIDES &&
        entity.slot < battle->team_sizes[entity.side] &&
        battle->sides[entity.side].active == entity.slot;
}

static PokemonVolatileState *owner_volatile(
    PokemonBattle *battle, const PokemonHandlerRef *handler
) {
    if (handler->owner.kind != POKEMON_OWNER_VOLATILE) return NULL;
    PokemonMutable *state = &battle->sides[handler->holder_side]
        .state[handler->holder_slot];
    for (size_t i = 0; i < state->volatile_count; i++) {
        if (state->volatiles[i].descriptor_id ==
                handler->descriptor.source_id) return &state->volatiles[i];
    }
    return NULL;
}

static PokemonSideConditionState *owner_side_condition(
    PokemonBattle *battle, const PokemonHandlerRef *handler
) {
    if (handler->owner.kind != POKEMON_OWNER_SIDE ||
        handler->holder_side >= POKEMON_SIDES) return NULL;
    PokemonSide *side = &battle->sides[handler->holder_side];
    for (size_t i = 0; i < side->condition_count; i++) {
        PokemonSideConditionState *condition = &side->conditions[i];
        if (condition->descriptor_id == handler->descriptor.source_id &&
            condition->state_generation == handler->owner.state_generation &&
            condition->effect_order == handler->effect_order) {
            return condition;
        }
    }
    return NULL;
}

static int run_event_inner(
    PokemonBattle *battle, const PokemonEventInput *input,
    PokemonEventFrame *result);
static int run_try_hit_handlers(
    PokemonBattle *battle, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot,
    const PokemonMoveData *move, PokemonImmunityCause *cause,
    uint16_t *effect_id, PokemonHandlerId *handler_id,
    uint8_t *emit_immunity, PokemonEventCancellation *cancellation);
static int resolve_invulnerability(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, uint8_t *admitted);
static int queue_faint(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect);

/* A two-turn action is represented by two identities, matching Showdown:
 * the generic hard lock owns lifecycle callbacks, while the move marker says
 * whether the next invocation is the release and retains its original target.
 * Installation is preflighted as one transaction so half a lock is impossible. */
static int install_two_turn_pair(
    PokemonBattle *battle, PokemonEntityRef user, PokemonEntityRef target,
    uint16_t move_id, uint16_t marker_descriptor_id, uint8_t marker_duration
) {
    PokemonMutable *state = &battle->sides[user.side].state[user.slot];
    if (volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MOVE) >= 0 ||
        volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MARKER) >= 0 ||
        (size_t)state->volatile_count + 2u >
            (size_t)POKEMON_VOLATILE_CAPACITY ||
        battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY ||
        battle->next_holder_effect_order > (uint16_t)(UINT16_MAX - 2u)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    const PokemonConditionRule *rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_TWO_TURN_MOVE);
    uint8_t duration = 0;
    if (fixed_condition_duration(rule, &duration) != POKEMON_OK || duration != 2) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonSourceEffectRef effect = {POKEMON_SOURCE_EFFECT_MOVE, move_id};
    PokemonVolatileState lock = {
        .kind = POKEMON_VOLATILE_TWO_TURN_MOVE,
        .descriptor_id = rule->descriptor_id,
        .duration = duration, .state_generation = 1,
        .effect_order = ++battle->next_holder_effect_order,
        .source = user, .source_effect = effect,
        .payload.two_turn = {.move_id = move_id,
            .target_side = target.side, .target_slot = target.slot,
            .released = 0},
    };
    PokemonVolatileState marker = {
        .kind = POKEMON_VOLATILE_TWO_TURN_MARKER,
        .descriptor_id = marker_descriptor_id,
        .duration = marker_duration, .state_generation = 1,
        .effect_order = ++battle->next_holder_effect_order,
        .source = user, .source_effect = effect,
        .payload.two_turn = {.move_id = move_id,
            .target_side = target.side, .target_slot = target.slot,
            .released = 0},
    };
    int status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_ADD,
        POKEMON_CONDITION_REASON_MOVE, POKEMON_CONDITION_VALUE_DURATION,
        user.side, user.slot, POKEMON_VOLATILE_TWO_TURN_MOVE, 0, duration);
    if (status != POKEMON_OK) return status;
    state->volatiles[state->volatile_count++] = marker;
    state->volatiles[state->volatile_count++] = lock;
    return POKEMON_OK;
}

static const PokemonTwoTurnMoveDescriptor *two_turn_move_descriptor(
    const PokemonBattle *battle, uint16_t move_id
) {
    for (size_t i = 0; i < battle->data->two_turn_move_count; i++) {
        const PokemonTwoTurnMoveDescriptor *descriptor =
            &battle->data->two_turn_moves[i];
        if (descriptor->move_id == move_id) return descriptor;
    }
    return NULL;
}

static const PokemonWeightedMoveOutcomeDistribution *weighted_move_distribution(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0;
         i < battle->data->weighted_move_distribution_count; i++) {
        const PokemonWeightedMoveOutcomeDistribution *distribution =
            &battle->data->weighted_move_distributions[i];
        if (distribution->id == id) return distribution;
    }
    return NULL;
}

static const PokemonStatusDistribution *status_distribution(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->status_distribution_count; i++) {
        const PokemonStatusDistribution *distribution =
            &battle->data->status_distributions[i];
        if (distribution->id == id) return distribution;
    }
    return NULL;
}

static int move_has_dynamic_power_handler(
    const PokemonData *data, uint16_t move_id
) {
    for (size_t i = 0; i < data->handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor = &data->handlers[i];
        if (descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
            descriptor->source_id != move_id ||
            descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
            (size_t)descriptor->program_offset + descriptor->program_count >
                data->handler_program_count) continue;
        for (size_t op = 0; op < descriptor->program_count; op++) {
            PokemonHandlerOpcode opcode = data->handler_programs[
                descriptor->program_offset + op].opcode;
            if ((descriptor->event == POKEMON_HANDLER_EVENT_MODIFY_MOVE &&
                 opcode ==
                    POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED) ||
                (descriptor->event == POKEMON_HANDLER_EVENT_BASE_POWER &&
                 opcode ==
                    POKEMON_HANDLER_OP_SET_RELAY_FROM_HOLDER_VOLATILE_COUNTER_TIMES)) {
                return 1;
            }
        }
    }
    return 0;
}

static void remove_two_turn_marker(PokemonMutable *state) {
    int marker = volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MARKER);
    if (marker >= 0) remove_volatile_at(state, (size_t)marker);
}

static int abort_two_turn_pair(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonConditionReason reason
) {
    PokemonMutable *state = &battle->sides[side].state[slot];
    int lock = volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MOVE);
    if (lock < 0) { remove_two_turn_marker(state); return POKEMON_OK; }
    uint8_t before = state->volatiles[lock].duration;
    int status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_REMOVE,
        reason, POKEMON_CONDITION_VALUE_DURATION, side, slot,
        POKEMON_VOLATILE_TWO_TURN_MOVE, before, 0);
    if (status != POKEMON_OK) return status;
    remove_volatile_at(state, (size_t)lock);
    remove_two_turn_marker(state);
    return POKEMON_OK;
}

static int draw_below(
    PokemonBattle *battle, PokemonDrawLabel label, uint32_t upper,
    uint32_t *value);

static const PokemonEventSpec *event_spec(
    const PokemonBattle *battle, PokemonEventId event);
static int discover_holder_scope(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, size_t side, size_t slot,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count);
static int discover_handlers(
    const PokemonBattle *battle, const PokemonEventInput *input,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count);
static int append_owner_handlers(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, PokemonOwnerKind owner_kind, uint16_t owner_id,
    uint16_t state_generation, size_t side, size_t slot,
    uint16_t holder_speed, uint16_t effect_order,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count);
static int run_move_self_event(
    PokemonBattle *battle, PokemonEventId event, const PokemonMoveData *move,
    PokemonEntityRef user, size_t target_side, size_t target_slot,
    PokemonSourceEffectRef source_effect, PokemonRelay relay,
    PokemonEventFrame *last, uint8_t *ran);
static int residual_damage(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t amount,
    PokemonConditionScope condition_scope, uint16_t condition_id);

/* Install the common fixed-duration volatile product atomically.  Descriptor
 * identity and Start duration belong to generated condition data; callers
 * supply only the semantic participants and effect identity.  Volatiles with
 * bespoke admission/restart rules (notably Protect/Stall) do not use this
 * transaction. */
enum {
    CONDITION_INSTALL_FAILED = 0,
    CONDITION_INSTALL_APPLIED,
	CONDITION_INSTALL_IMMUNE,
    CONDITION_INSTALL_PREVENTED,
    CONDITION_INSTALL_START_REJECTED,
};

/* Showdown's linkedStatus installs a hidden counterpart on the source.  The
 * fixed-capacity kernel stores the relation once, on the visible condition,
 * but still executes the counterpart's admission boundary and consumes its
 * holder effect order.  A later relation from the same source shares that
 * marker, matching Showdown's linkedPokemon list without a second mutable
 * volatile object. */
static int ensure_hidden_source_link_marker(
    PokemonBattle *battle, PokemonEntityRef visible_target,
    PokemonVolatileState *visible, PokemonVolatileKind linked_kind
) {
    if (visible == NULL || linked_kind == POKEMON_VOLATILE_NONE ||
        visible->source.kind != POKEMON_ENTITY_POKEMON ||
        visible->source.side >= POKEMON_SIDES ||
        visible->source.slot >= battle->team_sizes[visible->source.side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
            const PokemonMutable *holder = &battle->sides[side].state[slot];
            for (size_t i = 0; i < holder->volatile_count; i++) {
                const PokemonVolatileState *candidate = &holder->volatiles[i];
                const PokemonConditionRule *candidate_rule =
                    condition_rule_by_descriptor(battle,
                        candidate->descriptor_id);
                if (candidate == visible || candidate_rule == NULL ||
                    candidate_rule->source_linked_kind != linked_kind ||
                    candidate->linked_source_effect_order == 0 ||
                    candidate->source.kind != visible->source.kind ||
                    candidate->source.side != visible->source.side ||
                    candidate->source.slot != visible->source.slot) continue;
                visible->linked_source_state_generation =
                    candidate->linked_source_state_generation;
                visible->linked_source_effect_order =
                    candidate->linked_source_effect_order;
                return POKEMON_OK;
            }
        }
    }
    PokemonMutable *source_state = &battle->sides[visible->source.side].state[
        visible->source.slot];
    if (source_state->hp == 0 || source_state->fainted ||
        battle->next_holder_effect_order == UINT16_MAX) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonEventInput input = {
        .source = visible_target,
        .target_side = visible->source.side,
        .target_slot = visible->source.slot,
        .source_effect = visible->source_effect,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
        .context.volatile_condition = {.kind = linked_kind},
    };
    PokemonEventFrame frame;
    input.event = POKEMON_HANDLER_EVENT_IMMUNITY;
    int status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        !frame.relay.value.boolean) return POKEMON_INVALID_CONFIGURATION;
    input.event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE;
    status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        !frame.relay.value.boolean) return POKEMON_INVALID_CONFIGURATION;
    visible->linked_source_state_generation = 1;
    visible->linked_source_effect_order = ++battle->next_holder_effect_order;
    return POKEMON_OK;
}

static int install_descriptor_volatile(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, PokemonVolatileKind kind,
    uint16_t descriptor_id, PokemonConditionReason reason, uint8_t *installed
) {
    if (installed == NULL) return POKEMON_INVALID_CONFIGURATION;
    *installed = CONDITION_INSTALL_FAILED;
    if (target.kind != POKEMON_ENTITY_POKEMON ||
        target.side >= POKEMON_SIDES ||
        target.slot >= battle->team_sizes[target.side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    const PokemonConditionRule *rule = condition_rule_by_descriptor(
        battle, descriptor_id);
    if (kind == POKEMON_VOLATILE_NONE || descriptor_id == 0 || rule == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *state = &battle->sides[target.side].state[target.slot];
    /* Showdown's addVolatile rejects a fainted target before duplicate,
     * TryAddVolatile, or capacity processing.  The secondary owner has
     * already consumed its chance draw by the time this transaction runs. */
    if (state->hp == 0) return POKEMON_OK;
    int existing = volatile_index(state, kind);
    if (existing >= 0) {
        uint8_t before = state->volatiles[existing].duration;
        uint8_t counter_before = state->volatiles[existing].counter;
        uint8_t restarted = 0;
        const PokemonEventSpec *restart_spec = event_spec(
            battle, POKEMON_HANDLER_EVENT_RESTART);
        if (restart_spec != NULL && restart_spec->supported) {
            PokemonVolatileState *condition = &state->volatiles[existing];
            PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
            size_t count = 0;
            int status = append_owner_handlers(
                battle, POKEMON_HANDLER_EVENT_RESTART,
                POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_VOLATILE,
                condition->descriptor_id, condition->state_generation,
                target.side, target.slot, state->cached_speed,
                condition->effect_order, handlers, &count);
            if (status != POKEMON_OK) return status;
            restarted = count != 0;
            if (restarted &&
                battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            for (size_t i = 0; i < count; i++) {
                PokemonEventFrame restart;
                status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_RESTART,
                    .source = source, .target_side = target.side,
                    .target_slot = target.slot, .source_effect = source_effect,
                    .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                    .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                    .context.volatile_condition = {.kind = kind},
                    .has_only_handler = 1, .only_handler = handlers[i],
                }, &restart);
                if (status != POKEMON_OK) return status;
            }
        }
        if (!restarted) return POKEMON_OK;
        existing = volatile_index(state, kind);
        if (existing < 0) return POKEMON_INVALID_CONFIGURATION;
        int status = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE,
            POKEMON_CONDITION_RESTART, reason,
            before == 0 && state->volatiles[existing].duration == 0 ?
                POKEMON_CONDITION_VALUE_NONE :
                POKEMON_CONDITION_VALUE_DURATION,
            target.side, target.slot,
            kind, before, state->volatiles[existing].duration);
        if (status != POKEMON_OK) return status;
        battle->condition_traces[battle->condition_trace_count - 1u].descriptor_id =
            state->volatiles[existing].descriptor_id;
        PokemonConditionTrace *restart_trace = &battle->condition_traces[
            battle->condition_trace_count - 1u];
        if (counter_before != 0 || state->volatiles[existing].counter != 0) {
            restart_trace->has_counter_before = 1;
            restart_trace->has_counter_after = 1;
            restart_trace->counter_before = counter_before;
            restart_trace->counter_after = state->volatiles[existing].counter;
        }
        *installed = CONDITION_INSTALL_APPLIED;
        return POKEMON_OK;
    }
    {
        PokemonEventFrame immunity;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_IMMUNITY,
            .source = source, .target_side = target.side,
            .target_slot = target.slot, .source_effect = source_effect,
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {.kind = kind},
        }, &immunity);
        if (status != POKEMON_OK) return status;
        if (immunity.cancellation != POKEMON_EVENT_CANCEL_NONE ||
            !immunity.relay.value.boolean) {
            *installed = CONDITION_INSTALL_IMMUNE;
            return POKEMON_OK;
        }
    }
    {
        PokemonEventFrame admission;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
            .source = source, .target_side = target.side,
            .target_slot = target.slot, .source_effect = source_effect,
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {.kind = kind},
        }, &admission);
        if (status != POKEMON_OK) return status;
        if (admission.cancellation != POKEMON_EVENT_CANCEL_NONE ||
            !admission.relay.value.boolean) {
            *installed = CONDITION_INSTALL_PREVENTED;
            return POKEMON_OK;
        }
    }
    if (state->volatile_count == POKEMON_VOLATILE_CAPACITY ||
        battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY ||
        battle->next_holder_effect_order == UINT16_MAX) {
        return POKEMON_CAPACITY_EXCEEDED;
    }

    uint8_t duration = 0;
    int status = POKEMON_OK;
    if (kind == POKEMON_VOLATILE_CONFUSION) {
        uint32_t sample = 0;
        status = draw_below(
            battle, POKEMON_DRAW_CONFUSION_DURATION,
            (uint32_t)(battle->generation->confusion_duration_max -
                battle->generation->confusion_duration_min + 1u), &sample);
        if (status != POKEMON_OK) return status;
        duration = (uint8_t)(battle->generation->confusion_duration_min + sample);
    } else if (kind == POKEMON_VOLATILE_LOCKED_MOVE) {
        uint32_t sample = 0;
        status = draw_below(
            battle, POKEMON_DRAW_LOCKED_MOVE_DURATION,
            (uint32_t)(battle->generation->locked_move_duration_max -
                battle->generation->locked_move_duration_min + 1u), &sample);
        if (status != POKEMON_OK) return status;
        duration = (uint8_t)(battle->generation->locked_move_duration_min + sample);
    } else {
        switch (rule->lifecycle_duration.kind) {
        case POKEMON_CONDITION_DURATION_NONE:
            duration = 0;
            break;
        case POKEMON_CONDITION_DURATION_FIXED:
            duration = rule->lifecycle_duration.minimum;
            break;
        case POKEMON_CONDITION_DURATION_UNIFORM: {
            uint32_t sample = 0;
            if (rule->duration_draw_label == 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            status = draw_below(
                battle, rule->duration_draw_label,
                (uint32_t)(rule->lifecycle_duration.maximum -
                    rule->lifecycle_duration.minimum + 1u), &sample);
            if (status != POKEMON_OK) return status;
            PokemonDraw *draw = &battle->draws[battle->draw_count - 1];
            draw->lower_bound = rule->lifecycle_duration.minimum;
            draw->upper_bound = (uint32_t)rule->lifecycle_duration.maximum + 1u;
            duration = (uint8_t)(rule->lifecycle_duration.minimum + sample);
            draw->result = duration;
            break;
        }
        }
    }
    PokemonVolatileState value = {
        .kind = kind, .descriptor_id = descriptor_id,
        .duration = kind == POKEMON_VOLATILE_CONFUSION ? 0 :
            (kind == POKEMON_VOLATILE_LOCKED_MOVE ?
                rule->lifecycle_duration.minimum : duration),
        .state_generation = 1,
        .effect_order = (uint16_t)(battle->next_holder_effect_order + 1u),
        .source = source, .source_effect = source_effect,
    };
    if (kind == POKEMON_VOLATILE_CONFUSION) {
        value.payload.confusion.time = duration;
    } else if (kind == POKEMON_VOLATILE_LOCKED_MOVE) {
        if (source_effect.kind != POKEMON_SOURCE_EFFECT_MOVE || source_effect.id == 0) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        value.payload.locked_move.move_id = source_effect.id;
        value.payload.locked_move.true_duration = duration;
    }
    battle->next_holder_effect_order = value.effect_order;
    state->volatiles[state->volatile_count++] = value;
    {
        PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
        size_t count = 0;
        status = discover_holder_scope(
            battle, POKEMON_HANDLER_EVENT_START,
            POKEMON_HANDLER_SCOPE_TARGET, target.side, target.slot,
            handlers, &count);
        if (status != POKEMON_OK) return status;
        size_t write = 0;
        for (size_t i = 0; i < count; i++) {
            if (handlers[i].owner.kind == POKEMON_OWNER_VOLATILE &&
                handlers[i].owner.effect_id == descriptor_id &&
                handlers[i].owner.state_generation == value.state_generation) {
                handlers[write++] = handlers[i];
            }
        }
        count = write;
        for (size_t i = 0; i < count; i++) {
            PokemonEventFrame start;
            status = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_START,
                .source = source, .target_side = target.side,
                .target_slot = target.slot, .source_effect = source_effect,
                .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                .context.volatile_condition = {.kind = kind},
                .has_only_handler = 1, .only_handler = handlers[i],
            }, &start);
            if (status != POKEMON_OK) return status;
            if (start.cancellation != POKEMON_EVENT_CANCEL_NONE) {
                int installed_index = -1;
                for (size_t candidate = 0;
                     candidate < state->volatile_count; candidate++) {
                    const PokemonVolatileState *current =
                        &state->volatiles[candidate];
                    if (current->kind == value.kind &&
                        current->descriptor_id == value.descriptor_id &&
                        current->state_generation == value.state_generation &&
                        current->effect_order == value.effect_order) {
                        installed_index = (int)candidate;
                        break;
                    }
                }
                if (installed_index < 0) return POKEMON_INVALID_CONFIGURATION;
                remove_volatile_at(state, (size_t)installed_index);
                /* Distinguish Start rollback from TryAddVolatile prevention:
                 * Showdown's move protocol target projection differs. */
                *installed = CONDITION_INSTALL_START_REJECTED;
                return POKEMON_OK;
            }
        }
    }
    int installed_index = volatile_index(state, kind);
    if (installed_index < 0) return POKEMON_INVALID_CONFIGURATION;
    PokemonVolatileState *installed_state = &state->volatiles[installed_index];
    if (rule->source_linked_kind != POKEMON_VOLATILE_NONE) {
        status = ensure_hidden_source_link_marker(
            battle, target, installed_state,
            (PokemonVolatileKind)rule->source_linked_kind);
        if (status != POKEMON_OK) return status;
    }
    status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_ADD,
        reason,
        installed_state->duration == 0 && kind != POKEMON_VOLATILE_CONFUSION ?
            POKEMON_CONDITION_VALUE_NONE : POKEMON_CONDITION_VALUE_DURATION,
        target.side, target.slot, kind, 0,
        kind == POKEMON_VOLATILE_CONFUSION ? duration :
            installed_state->duration);
    if (status != POKEMON_OK) return status;
    battle->condition_traces[battle->condition_trace_count - 1u].descriptor_id =
        installed_state->descriptor_id;
    if (installed_state->counter != 0 ||
		locked_ramp_policy_for_condition(battle, installed_state) != NULL) {
        PokemonConditionTrace *add_trace = &battle->condition_traces[
            battle->condition_trace_count - 1u];
        add_trace->has_counter_after = 1;
        add_trace->counter_after = installed_state->counter;
    }
    *installed = CONDITION_INSTALL_APPLIED;
    return POKEMON_OK;
}

static int install_condition_volatile(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, PokemonVolatileKind kind,
    PokemonConditionReason reason, uint8_t *installed
) {
    uint16_t descriptor_id = battle->generation->condition_descriptor(
        POKEMON_OWNER_VOLATILE, kind);
    return install_descriptor_volatile(
        battle, target, source, source_effect, kind, descriptor_id,
        reason, installed);
}

int pokemon_try_add_or_restart_volatile(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, PokemonVolatileKind kind,
    PokemonConditionReason reason, PokemonEffectResult *effect_result
) {
    if (battle == NULL || effect_result == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint8_t install_result = CONDITION_INSTALL_FAILED;
    int status = install_condition_volatile(
        battle, target, source, source_effect, kind, reason, &install_result);
    if (status != POKEMON_OK) return status;
    *effect_result = install_result == CONDITION_INSTALL_APPLIED ?
        POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED;
    return POKEMON_OK;
}

static int draw_range(
    PokemonBattle *battle, PokemonDrawLabel label, uint32_t lower,
    uint32_t upper, uint32_t *result
) {
    if (lower >= upper) return POKEMON_INVALID_ARGUMENT;
    uint32_t offset = 0;
    int status = draw_below(battle, label, upper - lower, &offset);
    if (status != POKEMON_OK) return status;
    PokemonDraw *draw = &battle->draws[battle->draw_count - 1];
    draw->lower_bound = lower;
    draw->upper_bound = upper;
    draw->result = lower + offset;
    *result = draw->result;
    return POKEMON_OK;
}

static int side_condition_index(
    const PokemonSide *side, PokemonSideConditionKind kind
) {
    for (size_t i = 0; i < side->condition_count; i++) {
        if (side->conditions[i].kind == kind) return (int)i;
    }
    return -1;
}

static const PokemonConditionRule *side_condition_rule(
    const PokemonBattle *battle, PokemonSideConditionKind kind
) {
    uint16_t descriptor_id = battle->generation->condition_descriptor(
        POKEMON_OWNER_SIDE, kind);
    if (descriptor_id == 0) return NULL;
    return condition_rule_by_descriptor(battle, descriptor_id);
}

static int dispatch_side_condition_handler(
    PokemonBattle *battle, PokemonHandlerEvent event, size_t side,
    PokemonSideConditionState *condition, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, uint8_t *ran
) {
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
    size_t count = 0;
    int status = append_owner_handlers(
        battle, event, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_SIDE,
        condition->descriptor_id, condition->state_generation, side,
        battle->sides[side].active, 0, condition->effect_order,
        handlers, &count);
    if (status != POKEMON_OK) return status;
    if (count > 1) return POKEMON_INVALID_CONFIGURATION;
    *ran = count != 0;
    if (count == 0) return POKEMON_OK;
    PokemonEventFrame frame;
    return run_event_inner(battle, &(PokemonEventInput){
        .event = event, .source = source,
        .target_side = (uint8_t)side,
        .target_slot = battle->sides[side].active,
        .source_effect = source_effect,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .has_only_handler = 1, .only_handler = handlers[0],
    }, &frame);
}

static int install_side_condition(
    PokemonBattle *battle, size_t target_side, PokemonSideConditionKind kind,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    PokemonConditionReason reason, uint8_t *installed
) {
    if (target_side >= POKEMON_SIDES || installed == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *installed = CONDITION_INSTALL_FAILED;
    PokemonSide *side = &battle->sides[target_side];
    const PokemonConditionRule *rule = side_condition_rule(battle, kind);
    if (rule == NULL) return POKEMON_INVALID_CONFIGURATION;
    if (battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    int index = side_condition_index(side, kind);
    if (index >= 0) {
        PokemonSideConditionState *condition = &side->conditions[index];
        uint8_t before = condition->counter;
        uint8_t ran = 0;
        int status = dispatch_side_condition_handler(
            battle, POKEMON_HANDLER_EVENT_RESTART, target_side, condition,
            source, source_effect, &ran);
        if (status != POKEMON_OK) return status;
        if (!ran || condition->counter == before) return POKEMON_OK;
        status = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_SIDE, POKEMON_CONDITION_RESTART,
            reason, POKEMON_CONDITION_VALUE_COUNTER, target_side, 0, kind,
            before, condition->counter);
        if (status != POKEMON_OK) {
            condition->counter = before;
            return status;
        }
        *installed = CONDITION_INSTALL_APPLIED;
        return POKEMON_OK;
    }
    if (side->condition_count == POKEMON_SIDE_CONDITION_CAPACITY ||
        battle->next_holder_effect_order == UINT16_MAX) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    uint8_t duration = 0;
    if (rule->lifecycle_duration.kind != POKEMON_CONDITION_DURATION_NONE &&
        fixed_condition_duration(rule, &duration) != POKEMON_OK) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    size_t installed_index = side->condition_count++;
    PokemonSideConditionState *condition = &side->conditions[installed_index];
    *condition = (PokemonSideConditionState){
        .kind = kind, .descriptor_id = rule->descriptor_id,
        .duration = duration, .state_generation = 1,
        .effect_order = ++battle->next_holder_effect_order,
    };
    uint8_t ran = 0;
    int status = dispatch_side_condition_handler(
        battle, POKEMON_HANDLER_EVENT_START, target_side, condition,
        source, source_effect, &ran);
    if (status != POKEMON_OK) {
        side->condition_count--;
        battle->next_holder_effect_order--;
        return status;
    }
    PokemonConditionValueKind value_kind = condition->counter != 0 ?
        POKEMON_CONDITION_VALUE_COUNTER : POKEMON_CONDITION_VALUE_DURATION;
    uint8_t value = condition->counter != 0 ? condition->counter : duration;
    status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_SIDE, POKEMON_CONDITION_ADD, reason,
        value_kind, target_side, 0, kind, 0, value);
    if (status != POKEMON_OK) {
        side->condition_count--;
        battle->next_holder_effect_order--;
        return status;
    }
    *installed = CONDITION_INSTALL_APPLIED;
    return POKEMON_OK;
}

static int remove_side_condition_by_descriptor(
    PokemonBattle *battle, size_t side_index, uint16_t descriptor_id,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    PokemonConditionReason reason
) {
    const PokemonConditionIdentity *identity = pokemon_condition_identity(
        battle->data, descriptor_id);
    if (side_index >= POKEMON_SIDES || identity == NULL ||
        identity->domain != POKEMON_CONDITION_DOMAIN_SIDE ||
        identity->semantic_kind == 0 ||
        identity->semantic_kind > POKEMON_SIDE_CONDITION_SPIKES) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonSideConditionKind kind =
        (PokemonSideConditionKind)identity->semantic_kind;
    PokemonSide *side = &battle->sides[side_index];
    int position = side_condition_index(side, kind);
    if (position < 0) return POKEMON_OK;
    PokemonSideConditionState before = side->conditions[position];
    if (before.descriptor_id != descriptor_id) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint8_t ran = 0;
    int status = dispatch_side_condition_handler(
        battle, POKEMON_HANDLER_EVENT_END, side_index,
        &side->conditions[position], source, source_effect, &ran);
    if (status != POKEMON_OK) return status;
    position = side_condition_index(side, kind);
    if (position < 0 ||
        side->conditions[position].descriptor_id != descriptor_id ||
        side->conditions[position].state_generation != before.state_generation) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonConditionValueKind value_kind = before.counter != 0 ?
        POKEMON_CONDITION_VALUE_COUNTER : POKEMON_CONDITION_VALUE_DURATION;
    uint8_t value = before.counter != 0 ? before.counter : before.duration;
    status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_SIDE, POKEMON_CONDITION_REMOVE,
        reason, value_kind, side_index, 0, kind, value, 0);
    if (status != POKEMON_OK) return status;
    memmove(&side->conditions[position], &side->conditions[position + 1],
        (side->condition_count - (size_t)position - 1) *
            sizeof(side->conditions[0]));
    side->condition_count--;
    return POKEMON_OK;
}

static uint32_t next_semantic_sequence(PokemonBattle *battle) {
    assert(battle->semantic_sequence != UINT32_MAX);
    return ++battle->semantic_sequence;
}

static const PokemonEffectOp *move_effect(
    const PokemonBattle *battle, const PokemonMoveData *move, size_t index
) {
    assert(index < move->effect_count);
    return &battle->data->effects[move->effect_offset + index];
}

static uint8_t move_effect_secondary_group(
    const PokemonBattle *battle, const PokemonMoveData *move, size_t index
) {
    size_t absolute = (size_t)move->effect_offset + index;
    if (battle->data->effect_secondary_groups == NULL ||
        absolute >= battle->data->effect_secondary_group_count) return 0;
    return battle->data->effect_secondary_groups[absolute];
}

static int trace_effect(
    PokemonBattle *battle, const PokemonEffectOp *op, PokemonEffectResult result,
    uint16_t move_id,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    int16_t before, int16_t after
) {
    if (battle->effect_trace_count == POKEMON_EFFECT_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    battle->effect_traces[battle->effect_trace_count++] = (PokemonEffectTrace){
        .semantic_sequence = next_semantic_sequence(battle),
        .kind = op->kind, .phase = op->phase, .target = op->target,
        .result = result,
        .source_side = (uint8_t)source_side, .source_slot = (uint8_t)source_slot,
        .target_side = (uint8_t)target_side, .target_slot = (uint8_t)target_slot,
        .move_id = move_id, .argument = op->argument, .amount = op->amount,
        .before = before, .after = after,
    };
    return POKEMON_OK;
}

static int run_event_inner(
    PokemonBattle *battle, const PokemonEventInput *input,
    PokemonEventFrame *result
);
static int run_exceptional_handler(
    PokemonBattle *battle, const PokemonEventInput *input,
    const PokemonHandlerRef *handler, PokemonEventFrame *frame,
    PokemonHandlerResult *handler_result
);
static int clear_major_status(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonConditionReason reason
);
static size_t major_status_removal_trace_count(
    const PokemonBattle *battle, size_t side, size_t slot
);
static int set_major_status(
    PokemonBattle *battle, PokemonStatus proposed, uint16_t move_id,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, PokemonSourceEffectRef source_effect,
    PokemonStatusSetPolicy policy, uint8_t emit_immunity, uint8_t *applied,
    PokemonEventCancellation *rejection
);
static int apply_direct_damage_inner(
    PokemonBattle *battle, const PokemonDirectDamageRequest *request,
    uint16_t *applied
);
static const PokemonEventSpec *event_spec(
    const PokemonBattle *battle, PokemonEventId event
);
static int queue_faint(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect
);

static int try_amount_heal(
    PokemonBattle *battle, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, size_t target_side,
    size_t target_slot, uint16_t requested,
    PokemonEffectResult *effect_result, uint16_t *actual
) {
    if (effect_result == NULL || actual == NULL || requested == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    const PokemonSet *target_set = &battle->sides[target_side].sets[target_slot];
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HEAL,
        .source = source,
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = source_effect,
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = requested},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *effect_result = POKEMON_EFFECT_FAILED;
    *actual = 0;
    uint32_t allowed = 0;
    if (frame.cancellation == POKEMON_EVENT_CANCEL_NONE) {
        if (frame.relay.kind == POKEMON_RELAY_U32) {
            allowed = frame.relay.value.u32;
        } else if (frame.relay.kind == POKEMON_RELAY_NUMBER &&
                   frame.relay.value.number >= 0.0 &&
                   frame.relay.value.number <= UINT32_MAX &&
                   frame.relay.value.number ==
                       (double)(uint32_t)frame.relay.value.number) {
            allowed = (uint32_t)frame.relay.value.number;
        } else {
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    if (allowed == 0 || target->hp == 0 ||
        battle->sides[target_side].active != target_slot ||
        target->hp >= target_set->stats[0]) return POKEMON_OK;
    uint16_t missing = (uint16_t)(target_set->stats[0] - target->hp);
    *actual = allowed < missing ? (uint16_t)allowed : missing;
    if (*actual == 0) return POKEMON_OK;
    target->hp = (uint16_t)(target->hp + *actual);
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_HEAL, .side = (uint8_t)target_side,
        .slot = (uint8_t)target_slot, .species_id = target_set->species_id,
        .amount = *actual, .hp = target->hp,
    });
    *effect_result = POKEMON_EFFECT_APPLIED;
    return POKEMON_OK;
}

static int try_fraction_heal(
    PokemonBattle *battle, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect, size_t target_side,
    size_t target_slot, uint8_t numerator, uint8_t denominator,
    PokemonEffectResult *effect_result, uint16_t *actual
) {
    if (numerator == 0 || denominator == 0 || numerator > denominator) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint16_t requested = battle->generation->fraction(
        battle->sides[target_side].sets[target_slot].stats[0],
        numerator, denominator);
    return try_amount_heal(
        battle, source, source_effect, target_side, target_slot, requested,
        effect_result, actual);
}

static int apply_fraction_heal(
    PokemonBattle *battle, const PokemonEffectOp *op, uint16_t move_id,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot
) {
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    const PokemonSet *target_set = &battle->sides[target_side].sets[target_slot];
    uint16_t before = target->hp;
    uint8_t numerator = op->fraction_numerator;
    uint8_t denominator = op->fraction_denominator;
    if (op->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION) {
        PokemonWeatherKind weather = effective_weather(battle);
        if (weather == POKEMON_WEATHER_SUN) {
            numerator = 2; denominator = 3;
        } else if (weather == POKEMON_WEATHER_RAIN ||
            weather == POKEMON_WEATHER_SANDSTORM ||
            weather == POKEMON_WEATHER_HAIL) {
            numerator = 1; denominator = 4;
        }
    }
    uint16_t requested = battle->generation->fraction(
        target_set->stats[0], numerator, denominator);
    uint16_t actual = 0;
    PokemonEffectResult effect_result = POKEMON_EFFECT_FAILED;

    /* runMoveEffects rejects full HP before Battle.heal/TryHeal. */
    if (before != 0 && before < target_set->stats[0] &&
        battle->sides[target_side].active == target_slot) {
        int status = try_amount_heal(
            battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)source_side, (uint8_t)source_slot},
            active_source_effect(battle, move_id), target_side, target_slot,
            requested, &effect_result, &actual);
        if (status != POKEMON_OK) return status;
        if (actual != 0) battle->events[battle->event_count - 1].move_id = move_id;
    }
    int status = trace_effect(
        battle, op, effect_result, move_id, source_side, source_slot,
        target_side, target_slot, before, target->hp);
    if (status != POKEMON_OK) return status;
    PokemonEffectTrace *trace = &battle->effect_traces[
        battle->effect_trace_count - 1];
    trace->requested = requested;
    trace->value = actual;
    trace->damage_basis = target_set->stats[0];
    trace->numerator = numerator;
    trace->denominator = denominator;
    return POKEMON_OK;
}

static int eat_held_berry(
    PokemonBattle *battle, uint8_t side, uint8_t slot, uint16_t expected_item
) {
    PokemonMutable *holder = &battle->sides[side].state[slot];
    if (holder->item_id != expected_item || holder->hp == 0 ||
        battle->sides[side].active != slot) return POKEMON_OK;
    PokemonEventFrame gate;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_EAT_ITEM,
        .source = {POKEMON_ENTITY_NONE, 0, 0},
        .target_side = side, .target_slot = slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_NONE, 0},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &gate);
    if (status != POKEMON_OK) return status;
    if (gate.cancellation != POKEMON_EVENT_CANCEL_NONE) return POKEMON_OK;
    PokemonEventFrame eat;
    status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_ITEM_EAT,
        .source = {POKEMON_ENTITY_POKEMON, side, slot},
        .target_side = side, .target_slot = slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_ITEM, expected_item},
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
    }, &eat);
    if (status != POKEMON_OK) return status;
    const PokemonItemData *consumed = find_item(battle, holder->item_id);
    if (consumed != NULL &&
        (consumed->flags & POKEMON_ITEM_FLAG_RESTORATIVE) != 0) {
        if (holder->pending_staleness == POKEMON_STALENESS_EXTERNAL) {
            holder->staleness = POKEMON_STALENESS_EXTERNAL;
        } else if (holder->pending_staleness == POKEMON_STALENESS_INTERNAL &&
            holder->staleness != POKEMON_STALENESS_EXTERNAL) {
            holder->staleness = POKEMON_STALENESS_INTERNAL;
        }
        holder->pending_staleness = POKEMON_STALENESS_NONE;
    }
    holder->last_item_id = holder->item_id;
    holder->item_id = 0;
    holder->item_generation++;
    holder->item_effect_order = 0;
    holder->used_item_this_turn = 1;
    holder->ate_berry = 1;
    return POKEMON_OK;
}

static int eat_threshold_berry(
    PokemonBattle *battle, uint8_t side, uint8_t slot, uint16_t expected_item
) {
    PokemonMutable *holder = &battle->sides[side].state[slot];
    const PokemonSet *set = &battle->sides[side].sets[slot];
    const PokemonItemData *item = find_item(battle, expected_item);
    if (item == NULL || item->berry_threshold_denominator == 0 ||
        (item->fixed_heal == 0 && item->boost_delta == 0 &&
         item->heal_denominator == 0 && item->add_volatile_kind == 0) ||
        holder->hp > set->stats[0] / item->berry_threshold_denominator ||
        holder->hp == set->stats[0]) return POKEMON_OK;
    return eat_held_berry(battle, side, slot, expected_item);
}

static int use_held_item(
    PokemonBattle *battle, uint8_t side, uint8_t slot, uint16_t expected_item,
    uint8_t *used
) {
    PokemonMutable *holder = &battle->sides[side].state[slot];
    *used = 0;
    if (holder->hp == 0 || battle->sides[side].active != slot ||
        holder->item_id != expected_item) return POKEMON_OK;
    holder->last_item_id = holder->item_id;
    holder->item_id = 0;
    holder->item_generation++;
    holder->item_effect_order = 0;
    holder->used_item_this_turn = 1;
    *used = 1;
    return POKEMON_OK;
}

static int apply_boost_effects(
    PokemonBattle *battle, const PokemonEffectOp *const *ops, size_t op_count,
    uint16_t move_id,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot
) {
    if (op_count > POKEMON_EFFECT_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    if (op_count == 0 || op_count > POKEMON_STAT_COUNT) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonBoostTable requested = {0};
    PokemonEffectOp trace_ops[POKEMON_STAT_COUNT] = {0};
    for (size_t i = 0; i < op_count; i++) {
        const PokemonEffectOp *op = ops[i];
        if (op == NULL || op->kind != POKEMON_EFFECT_BOOST ||
            op->argument >= POKEMON_STAT_COUNT ||
            requested.present[op->argument]) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        requested.present[op->argument] = 1;
        requested.delta[op->argument] = op->amount;
        trace_ops[op->argument] = *op;
    }

    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_CHANGE_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move_id),
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE,
            .value.boosts = requested},
    };
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;

    PokemonMutable *state = &battle->sides[target_side].state[target_slot];
    PokemonBoostTable capped = frame.relay.value.boosts;
    for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
        if (!capped.present[stat]) continue;
        int16_t before = state->boosts[stat];
        int16_t after = before + capped.delta[stat];
        if (after > battle->generation->stages->maximum) {
            after = battle->generation->stages->maximum;
        }
        if (after < battle->generation->stages->minimum) {
            after = battle->generation->stages->minimum;
        }
        capped.delta[stat] = (int8_t)(after - before);
    }

    input.event = POKEMON_HANDLER_EVENT_TRY_BOOST;
    input.relay.value.boosts = capped;
    status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;

    for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
        if (!frame.relay.value.boosts.present[stat]) continue;
        int16_t before = state->boosts[stat];
        int16_t after = before + frame.relay.value.boosts.delta[stat];
        /* TryBoost handlers may delete fields, but cannot evade the generation
         * cap established at the preceding ChangeBoost boundary. */
        if (after > battle->generation->stages->maximum ||
            after < battle->generation->stages->minimum) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        state->boosts[stat] = (int8_t)after;
        PokemonEffectOp trace_op = trace_ops[stat];
        if (!requested.present[stat]) {
            trace_op = *ops[0];
            trace_op.argument = (uint16_t)stat;
        }
        trace_op.amount = frame.relay.value.boosts.delta[stat];
        status = trace_effect(
            battle, &trace_op,
            after == before ? POKEMON_EFFECT_FAILED : POKEMON_EFFECT_APPLIED,
            move_id, source_side, source_slot, target_side, target_slot,
            before, after
        );
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static uint16_t secondary_chance(
    const PokemonBattle *battle, size_t source_side, size_t source_slot,
    uint8_t base_chance
) {
    const PokemonMutable *source =
        &battle->sides[source_side].state[source_slot];
    for (size_t i = 0; i < battle->data->secondary_chance_policy_count; i++) {
        const PokemonSecondaryChancePolicy *policy =
            &battle->data->secondary_chance_policies[i];
        if (policy->ability_id != source->ability_id) continue;
        assert(policy->numerator != 0 && policy->denominator != 0);
        return (uint16_t)((uint32_t)base_chance * policy->numerator /
            policy->denominator);
    }
    return base_chance;
}

static int apply_directed_boost(
    PokemonBattle *battle, uint8_t source_side, uint8_t source_slot,
    uint8_t target_side, uint8_t target_slot,
    PokemonSourceEffectRef source_effect,
    uint8_t stat, int8_t delta
) {
    if (stat >= POKEMON_STAT_COUNT || delta == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonBoostTable requested = {0};
    requested.present[stat] = 1;
    requested.delta[stat] = delta;
    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_CHANGE_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, source_side, source_slot},
        .target_side = target_side, .target_slot = target_slot,
        .source_effect = source_effect,
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = requested},
    };
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;
    PokemonMutable *holder = &battle->sides[target_side].state[target_slot];
    int16_t before = holder->boosts[stat];
    int16_t after = before + frame.relay.value.boosts.delta[stat];
    if (after > battle->generation->stages->maximum) {
        after = battle->generation->stages->maximum;
    }
    if (after < battle->generation->stages->minimum) {
        after = battle->generation->stages->minimum;
    }
    frame.relay.value.boosts.delta[stat] = (int8_t)(after - before);
    input.event = POKEMON_HANDLER_EVENT_TRY_BOOST;
    input.relay = frame.relay;
    status = run_event_inner(battle, &input, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.relay.value.boosts.present[stat]) {
        after = before + frame.relay.value.boosts.delta[stat];
        if (after > battle->generation->stages->maximum ||
            after < battle->generation->stages->minimum) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        holder->boosts[stat] = (int8_t)after;
    }
    return POKEMON_OK;
}

static int apply_owner_boost(
    PokemonBattle *battle, uint8_t side, uint8_t slot,
    PokemonSourceEffectRef source_effect,
    uint8_t stat, int8_t delta
) {
    return apply_directed_boost(
        battle, side, slot, side, slot, source_effect, stat, delta);
}

static int apply_item_boost(
    PokemonBattle *battle, uint8_t side, uint8_t slot, uint16_t item_id,
    uint8_t stat, int8_t delta
) {
    return apply_owner_boost(
        battle, side, slot,
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ITEM, item_id},
        stat, delta);
}

static int run_weather_change_each_event(PokemonBattle *battle);

static int set_weather_from_lifecycle(
    PokemonBattle *battle, PokemonWeatherKind requested,
    uint8_t source_side, uint8_t source_slot
) {
    if (requested == POKEMON_WEATHER_NONE) return POKEMON_INVALID_CONFIGURATION;
    /* In Gen 3 an ability refreshes finite weather to permanent weather, but
     * reapplying the same already-permanent weather fails without mutation. */
    if (battle->field.weather.kind == requested &&
        battle->field.weather.duration == 0) return POKEMON_OK;
    if (battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    const PokemonConditionRule *rule = condition_rule(
        battle, weather_rule_kind(requested));
    if (rule == NULL) return POKEMON_INVALID_CONFIGURATION;
    uint16_t generation =
        (uint16_t)(battle->field.weather.state_generation + 1u);
    if (generation == 0) generation = 1;
    battle->field.weather = (PokemonWeatherState){
        .kind = requested, .descriptor_id = rule->descriptor_id,
        .duration = 0, .source_side = source_side, .source_slot = source_slot,
        .state_generation = generation,
    };
    int status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_FIELD, POKEMON_CONDITION_ADD,
        POKEMON_CONDITION_REASON_HANDLER, POKEMON_CONDITION_VALUE_DURATION,
        source_side, source_slot, requested, 0, 0);
    return status == POKEMON_OK ? run_weather_change_each_event(battle) : status;
}

static int resolve_action_speed(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t *speed,
    uint8_t suppress_trace
);

static int dispatch_owner_lifecycle(
    PokemonBattle *battle, PokemonEventId event, PokemonOwnerRef owner
);

static int replace_pokemon_ability(
    PokemonBattle *battle, size_t holder_side, size_t holder_slot,
    size_t target_side, size_t target_slot, uint8_t runs_start
) {
    if (holder_side >= POKEMON_SIDES || target_side >= POKEMON_SIDES ||
        holder_slot >= battle->team_sizes[holder_side] ||
        target_slot >= battle->team_sizes[target_side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *holder = &battle->sides[holder_side].state[holder_slot];
    const PokemonMutable *target =
        &battle->sides[target_side].state[target_slot];
    if (holder->hp == 0 || holder->fainted || target->hp == 0 ||
        target->fainted || target->ability_id == 0 ||
        find_ability(battle, target->ability_id) == NULL) return POKEMON_OK;
    PokemonOwnerRef old_owner = {POKEMON_OWNER_ABILITY,
        (uint8_t)holder_side, (uint8_t)holder_slot,
        holder->ability_id, holder->ability_generation};
    int status = dispatch_owner_lifecycle(
        battle, POKEMON_HANDLER_EVENT_END, old_owner);
    if (status != POKEMON_OK) return status;
    holder->ability_id = target->ability_id;
    holder->ability_generation++;
    holder->ability_effect_order = ++battle->next_holder_effect_order;
    holder->ability_ending = 0;
    if (!runs_start) return POKEMON_OK;
    return dispatch_owner_lifecycle(
        battle, POKEMON_HANDLER_EVENT_START,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)holder_side,
            (uint8_t)holder_slot,
            holder->ability_id, holder->ability_generation});
}

static int admit_ability_installation(
    PokemonBattle *battle, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, uint16_t proposed,
    uint8_t *admitted
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_SET_ABILITY,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_ABILITY,
        .context.ability = {.proposed = proposed},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *admitted = frame.cancellation == POKEMON_EVENT_CANCEL_NONE &&
        frame.relay.value.boolean;
    return POKEMON_OK;
}

static int swap_pokemon_abilities(
    PokemonBattle *battle, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, uint8_t *applied
) {
    if (applied == NULL || source_side >= POKEMON_SIDES ||
        target_side >= POKEMON_SIDES ||
        source_slot >= battle->team_sizes[source_side] ||
        target_slot >= battle->team_sizes[target_side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *applied = 0;
    PokemonMutable *source = &battle->sides[source_side].state[source_slot];
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    const PokemonAbilityData *source_ability =
        find_ability(battle, source->ability_id);
    const PokemonAbilityData *target_ability =
        find_ability(battle, target->ability_id);
    if (source->hp == 0 || source->fainted || target->hp == 0 ||
        target->fainted || source_ability == NULL || target_ability == NULL ||
        source->ability_id == target->ability_id ||
        (source_ability->semantic_flags &
            POKEMON_ABILITY_SEMANTIC_FAIL_SKILL_SWAP) != 0 ||
        (target_ability->semantic_flags &
            POKEMON_ABILITY_SEMANTIC_FAIL_SKILL_SWAP) != 0) return POKEMON_OK;

    uint8_t admitted = 0;
    int status = admit_ability_installation(
        battle, source_side, source_slot, target_side, target_slot,
        source->ability_id, &admitted);
    if (status != POKEMON_OK || !admitted) return status;
    status = admit_ability_installation(
        battle, target_side, target_slot, source_side, source_slot,
        target->ability_id, &admitted);
    if (status != POKEMON_OK || !admitted) return status;

    uint16_t source_id = source->ability_id;
    uint16_t target_id = target->ability_id;
    status = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)source_side,
            (uint8_t)source_slot, source_id, source->ability_generation});
    if (status != POKEMON_OK) return status;
    status = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)target_side,
            (uint8_t)target_slot, target_id, target->ability_generation});
    if (status != POKEMON_OK) return status;

    source->ability_id = target_id;
    source->ability_generation++;
    source->ability_effect_order = ++battle->next_holder_effect_order;
    source->ability_ending = 0;
    target->ability_id = source_id;
    target->ability_generation++;
    target->ability_effect_order = ++battle->next_holder_effect_order;
    target->ability_ending = 0;
    source->volatile_staleness = POKEMON_STALENESS_NONE;
    if (source_side != target_side) {
        target->volatile_staleness = POKEMON_STALENESS_EXTERNAL;
    }
    *applied = 1;
    if (!battle->generation->replaced_ability_runs_start) return POKEMON_OK;
    status = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_START,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)target_side,
            (uint8_t)target_slot, source_id, target->ability_generation});
    if (status != POKEMON_OK) return status;
    return dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_START,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)source_side,
            (uint8_t)source_slot, target_id, source->ability_generation});
}

static int replace_holder_ability_from_target(
    PokemonBattle *battle, PokemonOwnerRef owner,
    PokemonHandlerTargetSelector selector
) {
    if (owner.kind != POKEMON_OWNER_ABILITY ||
        selector != POKEMON_HANDLER_TARGET_RANDOM_ACTIVE_FOE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    size_t foe_side = 1u - owner.side;
    size_t foe_slot = battle->sides[foe_side].active;
    const PokemonMutable *target = &battle->sides[foe_side].state[foe_slot];
    if (target->hp == 0 || target->fainted) return POKEMON_OK;

    /* Showdown's randomFoe delegates to sample, which advances the PRNG even
     * when singles supplies exactly one candidate. */
    uint32_t selected = 0;
    int status = draw_below(battle, POKEMON_DRAW_ABILITY_TARGET, 1, &selected);
    if (status != POKEMON_OK) return status;
    assert(selected == 0);
    return replace_pokemon_ability(
        battle, owner.side, owner.slot, foe_side, foe_slot,
        battle->generation->replaced_ability_runs_start);
}

/* Start/End are direct single-owner lifecycle events. They intentionally do
 * not use ordinary target/source/foe discovery or handler ordering. */
static int dispatch_owner_lifecycle(
    PokemonBattle *battle, PokemonEventId event, PokemonOwnerRef owner
) {
    if (event != POKEMON_HANDLER_EVENT_START &&
        event != POKEMON_HANDLER_EVENT_END) return POKEMON_INVALID_ARGUMENT;
    if (owner.kind != POKEMON_OWNER_ABILITY &&
        owner.kind != POKEMON_OWNER_ITEM &&
        owner.kind != POKEMON_OWNER_STATUS) return POKEMON_INVALID_CONFIGURATION;
    if (owner.side >= POKEMON_SIDES ||
        owner.slot >= battle->team_sizes[owner.side]) return POKEMON_INVALID_ARGUMENT;
    PokemonMutable *state = &battle->sides[owner.side].state[owner.slot];
    uint16_t installed_id = owner.kind == POKEMON_OWNER_ABILITY ?
        state->ability_id : owner.kind == POKEMON_OWNER_ITEM ?
            state->item_id : state->status.descriptor_id;
    uint16_t installed_generation = owner.kind == POKEMON_OWNER_ABILITY ?
        state->ability_generation : owner.kind == POKEMON_OWNER_ITEM ?
            state->item_generation : state->status.state_generation;
    if (installed_id != owner.effect_id ||
        installed_generation != owner.state_generation) return POKEMON_OK;

    const PokemonHandlerDescriptor *descriptor = NULL;
    uint16_t binding_index = 0;
    PokemonHandlerSourceKind source_kind = owner.kind == POKEMON_OWNER_ABILITY ?
        POKEMON_HANDLER_SOURCE_ABILITY : owner.kind == POKEMON_OWNER_ITEM ?
            POKEMON_HANDLER_SOURCE_ITEM : POKEMON_HANDLER_SOURCE_CONDITION;
    for (size_t i = 0; i < battle->data->handler_count; i++) {
        const PokemonHandlerDescriptor *candidate = &battle->data->handlers[i];
        if (candidate->event == event && candidate->source_kind == source_kind &&
            candidate->source_id == owner.effect_id) {
            if (descriptor != NULL) return POKEMON_INVALID_CONFIGURATION;
            descriptor = candidate;
            binding_index = (uint16_t)i;
        }
    }
    if (descriptor == NULL) {
        return owner.kind == POKEMON_OWNER_STATUS &&
                state->status.kind == POKEMON_STATUS_SLEEP ?
            POKEMON_INVALID_CONFIGURATION : POKEMON_OK;
    }
    if (descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
        descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
        descriptor->exceptional_handler_id != 0 ||
        (size_t)descriptor->program_offset + descriptor->program_count >
            battle->data->handler_program_count ||
        battle->handler_count == POKEMON_HANDLER_CAPACITY) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonHandlerRef ref = {
        .descriptor = *descriptor, .binding_index = binding_index,
        .owner = owner, .holder_side = owner.side, .holder_slot = owner.slot,
        .effect_order = owner.kind == POKEMON_OWNER_ABILITY ?
            state->ability_effect_order : owner.kind == POKEMON_OWNER_ITEM ?
                state->item_effect_order : state->status.effect_order,
    };
    int speed_status = resolve_action_speed(
        battle, owner.side, owner.slot, &ref.speed, 1);
    if (speed_status != POKEMON_OK) return speed_status;
    uint8_t lifecycle_special = 0;
    for (size_t i = 0; i < descriptor->program_count; i++) {
        PokemonHandlerOpcode opcode = battle->data->handler_programs[
            descriptor->program_offset + i].opcode;
        lifecycle_special |= opcode == POKEMON_HANDLER_OP_SET_OWNER_ENDING ||
            opcode == POKEMON_HANDLER_OP_SET_WEATHER ||
            opcode == POKEMON_HANDLER_OP_NEST_EVENT ||
            opcode == POKEMON_HANDLER_OP_EACH_EVENT;
    }
    if (lifecycle_special) {
        battle->handlers[battle->handler_count++] = (PokemonHandlerInvocation){
            .handler = ref, .semantic_sequence = next_semantic_sequence(battle),
            .invoked = 1, .result = POKEMON_HANDLER_CONTINUE,
        };
        for (size_t i = 0; i < descriptor->program_count; i++) {
            const PokemonHandlerOp *op = &battle->data->handler_programs[
                descriptor->program_offset + i];
            if (op->opcode == POKEMON_HANDLER_OP_SET_OWNER_ENDING) {
                if (owner.kind != POKEMON_OWNER_ABILITY || op->argument > 1) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                state->ability_ending = (uint8_t)op->argument;
            } else if (op->opcode == POKEMON_HANDLER_OP_SET_WEATHER) {
                if (event != POKEMON_HANDLER_EVENT_START ||
                    owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument < POKEMON_WEATHER_SANDSTORM ||
                    op->argument > POKEMON_WEATHER_SUN) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                int status = set_weather_from_lifecycle(
                    battle, (PokemonWeatherKind)op->argument,
                    owner.side, owner.slot);
                if (status != POKEMON_OK) return status;
            } else if (op->opcode == POKEMON_HANDLER_OP_NEST_EVENT) {
                const PokemonEventSpec *nested = event_spec(
                    battle, (PokemonEventId)op->argument);
                if (nested == NULL || !nested->supported ||
                    nested->algebra != POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonEventFrame ignored;
                int status = run_event_inner(battle, &(PokemonEventInput){
                    .event = (PokemonEventId)op->argument,
                    .source = {POKEMON_ENTITY_POKEMON, owner.side, owner.slot},
                    .target_side = owner.side, .target_slot = owner.slot,
                    .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                    .suppress_handler_trace = 1,
                }, &ignored);
                if (status != POKEMON_OK) return status;
            } else if (op->opcode == POKEMON_HANDLER_OP_EACH_EVENT) {
                if (op->argument != POKEMON_HANDLER_EVENT_WEATHER_CHANGE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                int status = run_weather_change_each_event(battle);
                if (status != POKEMON_OK) return status;
            } else {
                return POKEMON_INVALID_CONFIGURATION;
            }
        }
        return POKEMON_OK;
    }
    PokemonEventFrame ignored;
    return run_event_inner(battle, &(PokemonEventInput){
        .event = event,
        .source = {POKEMON_ENTITY_POKEMON, owner.side, owner.slot},
        .target_side = owner.side, .target_slot = owner.slot,
        .source_effect = {
            owner.kind == POKEMON_OWNER_ABILITY ? POKEMON_SOURCE_EFFECT_ABILITY :
            owner.kind == POKEMON_OWNER_ITEM ? POKEMON_SOURCE_EFFECT_ITEM :
                POKEMON_SOURCE_EFFECT_CONDITION,
            owner.effect_id,
        },
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .has_only_handler = 1,
        .only_handler = ref,
    }, &ignored);
}
#line 1517 "pokemon.c"
