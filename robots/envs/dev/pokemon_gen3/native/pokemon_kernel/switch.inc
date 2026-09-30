#line 17294 "pokemon.c"
static int execute_switch(PokemonBattle *battle, const PokemonAction *action) {
    PokemonSide *side = &battle->sides[action->side];
    uint8_t outgoing_slot = side->active;
    PokemonMutable *outgoing = &side->state[outgoing_slot];
    int result = POKEMON_OK;
    uint8_t interception_fainted = 0;
    int8_t transferred_boosts[POKEMON_STAT_COUNT] = {0};
    PokemonVolatileState transferred_volatiles[POKEMON_VOLATILE_CAPACITY];
    uint8_t transferred_count = 0;
    if (action->switch_transfer >
            POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (outgoing->hp != 0 &&
        (action->switch_cause == POKEMON_SWITCH_CAUSE_VOLUNTARY ||
         (action->switch_cause == POKEMON_SWITCH_CAUSE_MOVE_DRIVEN &&
          !action->skip_before_switch_out))) {
        const PokemonEventSpec *before_switch_out = event_spec(
            battle, POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT);
        if (before_switch_out != NULL && before_switch_out->supported) {
            PokemonEventFrame frame;
            result = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT,
                .source = {POKEMON_ENTITY_POKEMON, action->side, outgoing_slot},
                .target_side = action->side, .target_slot = outgoing_slot,
                .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            }, &frame);
            if (result != POKEMON_OK) return result;
            if (outgoing->hp == 0) {
                result = drain_faints(battle);
                if (result != POKEMON_OK) return result;
                if (!battle->generation
                        ->continue_preselected_switch_after_interception_faint) {
                    return POKEMON_OK;
                }
                interception_fainted = 1;
            }
        }
    }
    if (outgoing->hp != 0) {
        PokemonEventFrame switch_out;
        result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_SWITCH_OUT,
            .source = {POKEMON_ENTITY_POKEMON, action->side, outgoing_slot},
            .target_side = action->side, .target_slot = outgoing_slot,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        }, &switch_out);
		if (result != POKEMON_OK) return result;
    }
    /* Showdown constructs the transfer product after SwitchOut plus the
     * outgoing ability/item End lifecycle, but before clearVolatile.  Taking
     * this snapshot earlier would preserve state that those handlers removed
     * or miss state they created. */
    if (action->switch_transfer ==
            POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES) {
        memcpy(transferred_boosts, outgoing->boosts,
            sizeof(transferred_boosts));
        for (size_t i = 0; i < outgoing->volatile_count; i++) {
            const PokemonConditionRule *rule = condition_rule_by_descriptor(
                battle, outgoing->volatiles[i].descriptor_id);
            if (rule == NULL) return POKEMON_INVALID_CONFIGURATION;
            if (!rule->no_copy) {
                transferred_volatiles[transferred_count++] =
                    outgoing->volatiles[i];
            }
        }
    }
    if (!interception_fainted) {
        result = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
            (PokemonOwnerRef){POKEMON_OWNER_ABILITY, action->side, outgoing_slot,
                outgoing->ability_id, outgoing->ability_generation});
        if (result != POKEMON_OK) return result;
        result = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
            (PokemonOwnerRef){POKEMON_OWNER_ITEM, action->side, outgoing_slot,
                outgoing->item_id, outgoing->item_generation});
        if (result != POKEMON_OK) return result;
		result = remove_source_linked_volatiles(
			battle,
			(PokemonEntityRef){POKEMON_ENTITY_POKEMON, action->side, outgoing_slot},
			POKEMON_CONDITION_REASON_SWITCH);
        if (result != POKEMON_OK) return result;
    }
    outgoing->last_move_id = 0;
    outgoing->volatile_staleness = POKEMON_STALENESS_NONE;
    outgoing->last_move_used = (PokemonLastUsedMove){0};
    /* A forced replacement of a fainted delayed-move target preserves the
     * completed attack record in Showdown's canonical state. Ordinary live
     * switches still clear the relation. */
    if (!outgoing->fainted) {
        memset(&outgoing->last_attacked_by, 0,
            sizeof(outgoing->last_attacked_by));
    }
    memset(outgoing->boosts, 0, sizeof(outgoing->boosts));
    result = restore_base_battle_profile(battle, action->side, outgoing_slot);
    if (result != POKEMON_OK) return result;
    while (outgoing->volatile_count != 0) {
        /* Showdown clears Object.keys(volatiles) in insertion order. Keep the
         * lifecycle trace in the same order while compacting fixed storage. */
        PokemonVolatileState volatile_state = outgoing->volatiles[0];
        uint8_t trace_value = volatile_state.kind == POKEMON_VOLATILE_CONFUSION ?
            volatile_state.payload.confusion.time : volatile_state.duration;
        result = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE,
            POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_SWITCH,
            trace_value == 0 ? POKEMON_CONDITION_VALUE_NONE :
                POKEMON_CONDITION_VALUE_DURATION,
            action->side, side->active, volatile_state.kind,
            trace_value, 0
        );
        if (result != POKEMON_OK) return result;
        if (volatile_state.counter != 0) {
            PokemonConditionTrace *trace = &battle->condition_traces[
                battle->condition_trace_count - 1];
            trace->has_counter_before = 1;
            trace->counter_before = volatile_state.counter;
        }
        remove_volatile_at(outgoing, 0);
    }
    PokemonMutable *incoming = &side->state[action->slot];
    if (action->switch_transfer != POKEMON_SWITCH_TRANSFER_NONE) {
        memset(incoming->boosts, 0, sizeof(incoming->boosts));
        incoming->volatile_count = 0;
    }
    incoming->last_item_id = outgoing->last_item_id;
    outgoing->last_item_id = 0;
    outgoing->used_item_this_turn = 0;
    /* Showdown silently drops a fainted outgoing Pokemon's major status while
     * swapping party positions; this is state cleanup, not cureStatus. */
    if (outgoing->fainted) memset(&outgoing->status, 0, sizeof(outgoing->status));
    size_t incoming_position = 0;
    while (incoming_position < battle->team_sizes[action->side] &&
        side->party_order[incoming_position] != action->slot) {
        incoming_position++;
    }
    if (incoming_position == battle->team_sizes[action->side] ||
        side->party_order[0] != outgoing_slot) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    side->party_order[incoming_position] = outgoing_slot;
    side->party_order[0] = action->slot;
    side->active = action->slot;
    if (interception_fainted) {
        /* drain_faints projected a replacement request for the outgoing
         * Pokemon, but this action already owns the exact replacement chosen
         * before interception.  Consuming that choice must not expose a
         * second, arbitrary replacement request. */
        memset(&battle->request, 0, sizeof(battle->request));
        battle->turn_suspended = POKEMON_TURN_NOT_SUSPENDED;
    }
    incoming = &side->state[side->active];
    if (action->switch_transfer ==
            POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES) {
        memcpy(incoming->boosts, transferred_boosts,
            sizeof(incoming->boosts));
        memcpy(incoming->volatiles, transferred_volatiles,
            (size_t)transferred_count * sizeof(transferred_volatiles[0]));
        incoming->volatile_count = transferred_count;
    }
    incoming->active_turns = 0;
    incoming->active_move_actions = 0;
    incoming->ability_generation++;
    incoming->ability_effect_order = incoming->ability_id ?
        ++battle->next_holder_effect_order : 0;
    incoming->ability_ending = 0;
    incoming->item_generation++;
    incoming->item_effect_order = incoming->item_id ?
        ++battle->next_holder_effect_order : 0;
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_SWITCH,
        .side = action->side,
        .slot = action->slot,
        .species_id = side->sets[action->slot].species_id,
        .hp = side->state[action->slot].hp,
        .switch_cause = action->switch_cause,
    });
    return POKEMON_OK;
}

static int execute_one_run_switch(
    PokemonBattle *battle, const PokemonAction *action
) {
    PokemonSide *side = &battle->sides[action->side];
    if (side->active != action->slot) return POKEMON_INVALID_CONFIGURATION;
    PokemonMutable *incoming = &side->state[action->slot];
    PokemonEventFrame entry_hazard;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_ENTRY_HAZARD,
        .source = {POKEMON_ENTITY_POKEMON, action->side, action->slot},
        .target_side = action->side, .target_slot = action->slot,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &entry_hazard);
    if (result != POKEMON_OK) return result;
    PokemonEventFrame switch_in;
    result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_SWITCH_IN,
        .source = {POKEMON_ENTITY_POKEMON, action->side, action->slot},
        .target_side = action->side, .target_slot = action->slot,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
    }, &switch_in);
    if (result != POKEMON_OK) return result;
    if (incoming->hp != 0) {
        result = dispatch_owner_lifecycle(
            battle, POKEMON_HANDLER_EVENT_START,
            (PokemonOwnerRef){POKEMON_OWNER_ABILITY, action->side,
                action->slot, incoming->ability_id,
                incoming->ability_generation});
        if (result == POKEMON_OK) result = dispatch_owner_lifecycle(
            battle, POKEMON_HANDLER_EVENT_START,
            (PokemonOwnerRef){POKEMON_OWNER_ITEM, action->side,
                action->slot, incoming->item_id,
                incoming->item_generation});
    }
    return result;
}

/* Gen 3 inherits Gen 4's runSwitch override, which handles one Pokemon per
 * action. The generic coalescing implementation belongs to later generations.
 * Showdown's outer action loop therefore runs Update after each queued entry. */
static int execute_run_switch(
    PokemonBattle *battle, const PokemonAction *action
) {
    return execute_one_run_switch(battle, action);
}

static int residual_damage_deferred(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t amount,
    PokemonConditionScope condition_scope, uint16_t condition_id,
    uint16_t *applied
) {
    if (applied == NULL) return POKEMON_INVALID_ARGUMENT;
    *applied = 0;
    /* Showdown's damage transaction is a no-op at zero: it does not emit a
     * damage event or enqueue faint work.  Suppressed weather and guarded
     * residual handlers can legitimately reduce their owned amount to zero. */
    if (amount == 0) return POKEMON_OK;
    PokemonMutable *state = &battle->sides[side].state[slot];
    const PokemonSet *set = &battle->sides[side].sets[slot];
    if (amount > state->hp) amount = state->hp;
    state->hp = (uint16_t)(state->hp - amount);
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_DAMAGE, .side = (uint8_t)side,
        .slot = (uint8_t)slot, .species_id = set->species_id,
        .amount = amount, .hp = state->hp,
        .condition_scope = (uint8_t)condition_scope,
        .condition_id = condition_id,
    });
    *applied = amount;
    if (state->hp != 0) return POKEMON_OK;
    return queue_faint(battle,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
            (uint8_t)slot},
        (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_CONDITION, condition_id});
}
#line 17294 "pokemon.c"
