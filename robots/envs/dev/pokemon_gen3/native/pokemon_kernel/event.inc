#line 4096 "pokemon.c"
static uint8_t type_multiplier(
    const PokemonBattle *battle, uint8_t attack_type,
    const PokemonMutable *defender
) {
    if (battle->data->has_non_interacting_type &&
        attack_type == battle->data->non_interacting_type) return 4;
    uint16_t result = 4;
    assert(defender->effective_type_count == 1 ||
        defender->effective_type_count == 2);
    for (size_t i = 0; i < defender->effective_type_count; i++) {
        uint8_t defense_type = defender->effective_types[i];
        assert(attack_type < battle->data->type_count);
        assert(defense_type < battle->data->type_count);
        uint8_t factor = battle->data->type_chart[
            (size_t)attack_type * battle->data->type_count + defense_type];
        /* Showdown tests raw immunity separately.  Its effectiveness product
         * treats an immune chart edge as neutral so an admitted hit (for
         * example through Foresight) retains every other type interaction. */
        if (factor == 0) factor = 4;
        result = (uint16_t)(result * factor / 4u);
    }
    return result > UINT8_MAX ? UINT8_MAX : (uint8_t)result;
}

static int type_is_immune(
    const PokemonBattle *battle, uint8_t attack_type,
    const PokemonMutable *defender
) {
    assert(defender->effective_type_count == 1 ||
        defender->effective_type_count == 2);
    for (size_t i = 0; i < defender->effective_type_count; i++) {
        uint8_t defense_type = defender->effective_types[i];
        assert(attack_type < battle->data->type_count);
        assert(defense_type < battle->data->type_count);
        if (battle->data->type_chart[
                (size_t)attack_type * battle->data->type_count +
                defense_type] == 0) return 1;
    }
    return 0;
}

static int has_type(const PokemonMutable *state, uint8_t type) {
    for (size_t i = 0; i < state->effective_type_count; i++) {
        if (state->effective_types[i] == type) return 1;
    }
    return 0;
}

static int restore_effective_types(
    PokemonBattle *battle, size_t side, size_t slot
) {
    const PokemonSpeciesData *species = find_species(
        battle, battle->sides[side].sets[slot].species_id);
    if (species == NULL || species->type_count == 0 ||
        species->type_count > 2) return POKEMON_INVALID_CONFIGURATION;
    PokemonMutable *state = &battle->sides[side].state[slot];
    state->species_id = species->id;
    state->effective_types[0] = species->types[0];
    state->effective_types[1] = species->type_count == 2 ? species->types[1] : 0;
    state->effective_type_count = species->type_count;
    return POKEMON_OK;
}

static int restore_base_battle_profile(
    PokemonBattle *battle, size_t side, size_t slot
) {
    if (side >= POKEMON_SIDES || slot >= battle->team_sizes[side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *state = &battle->sides[side].state[slot];
    const PokemonSet *set = &battle->sides[side].sets[slot];
    int status = restore_effective_types(battle, side, slot);
    if (status != POKEMON_OK) return status;
    memcpy(state->stored_stats, &set->stats[1], sizeof(state->stored_stats));
    state->cached_speed = set->stats[5];
    restore_base_move_slots(state);
    state->personal_move_profile = state->base_personal_move_profile;
    if (state->ability_id != set->ability_id) {
        state->ability_id = set->ability_id;
        state->ability_generation++;
        state->ability_effect_order = 0;
        state->ability_ending = 0;
    }
    return POKEMON_OK;
}

static int project_weather_form(
    PokemonBattle *battle, size_t side, size_t slot,
    const PokemonWeatherFormPolicy *policy
) {
    if (policy == NULL || side >= POKEMON_SIDES ||
        slot >= battle->team_sizes[side]) return POKEMON_INVALID_CONFIGURATION;
    PokemonMutable *state = &battle->sides[side].state[slot];
    const PokemonSet *set = &battle->sides[side].sets[slot];
    if (state->hp == 0 || battle->sides[side].active != slot ||
        set->species_id != policy->base_species_id || state->transformed) {
        return POKEMON_OK;
    }
    uint16_t species_id = policy->clear_species_id;
    PokemonWeatherKind weather = effective_weather(battle);
    if (weather == POKEMON_WEATHER_SUN) species_id = policy->sun_species_id;
    else if (weather == POKEMON_WEATHER_RAIN) species_id = policy->rain_species_id;
    else if (weather == POKEMON_WEATHER_HAIL) species_id = policy->hail_species_id;
    const PokemonSpeciesData *species = find_species(battle, species_id);
    if (species == NULL || species->type_count == 0 || species->type_count > 2) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (state->species_id == species_id) return POKEMON_OK;
    state->species_id = species_id;
    state->effective_types[0] = species->types[0];
    state->effective_types[1] = species->type_count == 2 ? species->types[1] : 0;
    state->effective_type_count = species->type_count;
    return POKEMON_OK;
}

static uint8_t target_is_grounded(
    const PokemonBattle *battle, size_t side, size_t slot, uint8_t ground_type
) {
    const PokemonMutable *state = &battle->sides[side].state[slot];
    const PokemonAbilityData *ability = find_ability(battle, state->ability_id);
    if (type_is_immune(battle, ground_type, state)) return 0;
    return ability == NULL || !ability->grants_ground_immunity ||
        ability->ground_immunity_type != ground_type;
}

int pokemon_compare_handler_refs(
    const PokemonHandlerRef *left, const PokemonHandlerRef *right
) {
    int left_order = left->descriptor.order == 0 ? INT_MAX : left->descriptor.order;
    int right_order = right->descriptor.order == 0 ? INT_MAX : right->descriptor.order;
    if (left_order != right_order) return left_order < right_order ? -1 : 1;
    if (left->descriptor.priority != right->descriptor.priority) {
        return left->descriptor.priority > right->descriptor.priority ? -1 : 1;
    }
    if (left->speed != right->speed) return left->speed > right->speed ? -1 : 1;
    if (left->descriptor.sub_order != right->descriptor.sub_order) {
        return left->descriptor.sub_order < right->descriptor.sub_order ? -1 : 1;
    }
    if (left->descriptor.event == POKEMON_HANDLER_EVENT_SWITCH_IN &&
        right->descriptor.event == POKEMON_HANDLER_EVENT_SWITCH_IN &&
        left->effect_order != right->effect_order) {
        return left->effect_order < right->effect_order ? -1 : 1;
    }
    return 0;
}

void pokemon_order_handler_refs(PokemonHandlerRef *handlers, size_t count) {
    for (size_t i = 1; i < count; i++) {
        PokemonHandlerRef value = handlers[i];
        size_t position = i;
        while (position != 0 &&
            pokemon_compare_handler_refs(&value, &handlers[position - 1]) < 0) {
            handlers[position] = handlers[position - 1];
            position--;
        }
        handlers[position] = value;
    }
}

static int append_choice_control_handler(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, uint16_t owner_id, uint16_t state_generation,
    size_t side, size_t slot, uint16_t holder_speed, uint16_t effect_order,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    if (scope != POKEMON_HANDLER_SCOPE_TARGET) return POKEMON_OK;
    const PokemonChoiceControlPolicy *policy = choice_control_policy(
        battle->generation->choice_control_policies,
        battle->generation->choice_control_policy_count, owner_id);
    if (policy == NULL) return POKEMON_OK;
    /* A resolved plugin may supply the source handler directly. The choice
     * policy remains the request-shape authority, but must not synthesize a
     * second copy of an already bound handler. */
    for (size_t binding = 0;
         binding < battle->data->owner_binding_index_count; binding++) {
        const PokemonOwnerBindingIndex *bound =
            &battle->data->owner_binding_index[binding];
        if (bound->owner_kind == POKEMON_OWNER_VOLATILE &&
            bound->owner_id == owner_id &&
            bound->event == event && bound->scope == scope) {
            return POKEMON_OK;
        }
    }
    uint16_t handler_id = 0;
    int8_t priority = 0;
    int16_t order = 0;
    int16_t sub_order = 2;
    const char *raw_hook = NULL;
    if (event == POKEMON_HANDLER_EVENT_START &&
        policy->start_op != POKEMON_CHOICE_START_NONE) {
        handler_id = policy->start_handler_id;
        sub_order = 0;
        raw_hook = "onStart";
    } else if (event == POKEMON_HANDLER_EVENT_DISABLE_MOVE &&
        policy->request_op != POKEMON_CHOICE_REQUEST_NONE &&
        policy->request_op != POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC) {
        handler_id = policy->request_handler_id;
        priority = policy->request_priority;
        raw_hook = "onDisableMove";
    } else if (event == POKEMON_HANDLER_EVENT_OVERRIDE_ACTION &&
        policy->action_op == POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE) {
        handler_id = policy->action_handler_id;
        priority = policy->action_priority;
        raw_hook = "onOverrideAction";
    } else if (event == POKEMON_HANDLER_EVENT_BEFORE_MOVE &&
        (policy->action_op == POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE ||
         policy->action_op == POKEMON_CHOICE_ACTION_REJECT_CATEGORY ||
         policy->action_op ==
            POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC)) {
        handler_id = policy->action_handler_id;
        priority = policy->action_priority;
        raw_hook = "onBeforeMove";
    } else if (event == POKEMON_HANDLER_EVENT_LOCK_MOVE &&
        policy->request_op ==
            POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC) {
        handler_id = policy->request_handler_id;
        raw_hook = "onLockMove";
    } else if (event == POKEMON_HANDLER_EVENT_RESIDUAL &&
        policy->residual_op != POKEMON_CHOICE_RESIDUAL_NONE) {
        const PokemonConditionRule *rule = condition_rule_by_descriptor(
            battle, owner_id);
        if (rule == NULL || !rule->has_residual) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        handler_id = policy->residual_handler_id;
        order = rule->has_order ? rule->residual_order : 0;
        sub_order = rule->residual_sub_order;
        raw_hook = "onResidual";
    }
    if (raw_hook == NULL) return POKEMON_OK;
    if (handler_id == 0) return POKEMON_INVALID_CONFIGURATION;
    if (*count == POKEMON_HANDLER_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
    handlers[(*count)++] = (PokemonHandlerRef){
        .descriptor = {
            .event = event, .id = handler_id,
            .source_kind = POKEMON_HANDLER_SOURCE_CONDITION,
            .source_id = owner_id, .order = order, .priority = priority,
            .sub_order = sub_order,
            .exceptional_handler_id = POKEMON_EXCEPTION_CHOICE_CONTROL,
            .scope = POKEMON_HANDLER_SCOPE_TARGET,
            .route = POKEMON_HANDLER_ROUTE_OWNER, .raw_hook = raw_hook,
        },
        .binding_index = UINT16_MAX,
        .owner = {POKEMON_OWNER_VOLATILE, (uint8_t)side, (uint8_t)slot,
            owner_id, state_generation},
        .holder_side = (uint8_t)side, .holder_slot = (uint8_t)slot,
        .speed = holder_speed, .effect_order = effect_order,
    };
    return POKEMON_OK;
}

static int append_owner_handlers(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, PokemonOwnerKind owner_kind, uint16_t owner_id,
    uint16_t state_generation, size_t side, size_t slot,
    uint16_t holder_speed, uint16_t effect_order,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    if (owner_id == 0) return POKEMON_OK;
    size_t binding_offset = 0, binding_count = 0;
    for (size_t i = 0; i < battle->data->owner_binding_index_count; i++) {
        const PokemonOwnerBindingIndex *entry = &battle->data->owner_binding_index[i];
        if (entry->owner_kind == owner_kind && entry->owner_id == owner_id &&
            entry->event == event &&
            entry->scope == scope &&
            entry->route == POKEMON_HANDLER_ROUTE_OWNER) {
            binding_offset = entry->binding_offset;
            binding_count = entry->binding_count;
            break;
        }
    }
    if (binding_offset + binding_count > battle->data->handler_count) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    for (size_t i = 0; i < binding_count; i++) {
        const PokemonHandlerDescriptor *descriptor =
            &battle->data->handlers[binding_offset + i];
        if (descriptor->event != event) continue;
        if (*count == POKEMON_HANDLER_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
        PokemonHandlerRef candidate = (PokemonHandlerRef){
            .descriptor = *descriptor,
            .binding_index = (uint16_t)(binding_offset + i),
            .owner = {owner_kind, (uint8_t)side, (uint8_t)slot,
                owner_id, state_generation},
            .holder_side = (uint8_t)side,
            .holder_slot = (uint8_t)slot,
            .speed = holder_speed, .effect_order = effect_order,
        };
        uint8_t duplicate = 0;
        for (size_t j = 0; j < *count; j++) duplicate |=
            handlers[j].binding_index == candidate.binding_index &&
            handlers[j].owner.kind == candidate.owner.kind &&
            handlers[j].owner.side == candidate.owner.side &&
            handlers[j].owner.slot == candidate.owner.slot &&
            handlers[j].owner.effect_id == candidate.owner.effect_id;
        if (!duplicate) handlers[(*count)++] = candidate;
    }
    if (owner_kind == POKEMON_OWNER_VOLATILE) {
        return append_choice_control_handler(
            battle, event, scope, owner_id, state_generation, side, slot,
            holder_speed, effect_order, handlers, count);
    }
    return POKEMON_OK;
}

static int discover_holder_scope(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, size_t side, size_t slot,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    const PokemonMutable *state = &battle->sides[side].state[slot];
    int status = append_owner_handlers(
        battle, event, scope, POKEMON_OWNER_STATUS, state->status.descriptor_id,
        state->status.state_generation, side, slot,
        state->cached_speed, state->status.effect_order,
        handlers, count);
    if (status != POKEMON_OK) return status;
    for (size_t i = 0; i < state->volatile_count; i++) {
        status = append_owner_handlers(
            battle, event, scope, POKEMON_OWNER_VOLATILE,
            state->volatiles[i].descriptor_id,
            state->volatiles[i].state_generation,
            side, slot, state->cached_speed,
            state->volatiles[i].effect_order, handlers, count);
        if (status != POKEMON_OK) return status;
    }
    if (find_ability(battle, state->ability_id) != NULL) {
        status = append_owner_handlers(
            battle, event, scope, POKEMON_OWNER_ABILITY, state->ability_id,
            state->ability_generation, side, slot,
            state->cached_speed, state->ability_effect_order,
            handlers, count);
        if (status != POKEMON_OK) return status;
    }
    if (find_item(battle, state->item_id) != NULL) {
        status = append_owner_handlers(
            battle, event, scope, POKEMON_OWNER_ITEM, state->item_id,
            state->item_generation, side, slot,
            state->cached_speed, state->item_effect_order,
            handlers, count);
    }
    return status;
}

static int discover_side_scope(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerScope scope, size_t side,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    for (size_t i = 0; i < battle->sides[side].condition_count; i++) {
        const PokemonSideConditionState *condition =
            &battle->sides[side].conditions[i];
        int status = append_owner_handlers(
            battle, event, scope, POKEMON_OWNER_SIDE,
            condition->descriptor_id, condition->state_generation,
            side, 0, 0, condition->effect_order, handlers, count);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int discover_field_scope(
    const PokemonBattle *battle, PokemonHandlerEvent event,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    const PokemonWeatherState *weather = &battle->field.weather;
    return append_owner_handlers(
        battle, event, POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_FIELD,
        weather->descriptor_id, weather->state_generation,
        0, 0, 0, weather->effect_order, handlers, count);
}

enum {
    POKEMON_SYNTHETIC_HANDLER_STATUS_IMMUNITY = UINT16_MAX,
};

static int append_status_admission_handlers(
    const PokemonBattle *battle, const PokemonEventInput *input,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    if (input->event != POKEMON_HANDLER_EVENT_SET_STATUS) return POKEMON_OK;
    if (input->context_kind != POKEMON_EVENT_CONTEXT_STATUS ||
        input->context.status.proposed <= POKEMON_STATUS_NONE ||
        input->context.status.proposed > POKEMON_STATUS_FREEZE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    for (size_t i = 0; i < battle->policy.status_clause_count; i++) {
        const PokemonStatusClausePolicy *clause =
            &battle->policy.status_clauses[i];
        const PokemonHandlerDescriptor *descriptor = NULL;
        size_t descriptor_index = 0;
        for (size_t candidate = 0; candidate < battle->data->handler_count;
             candidate++) {
            if (battle->data->handlers[candidate].id == clause->handler_id) {
                descriptor = &battle->data->handlers[candidate];
                descriptor_index = candidate;
                break;
            }
        }
        if (descriptor == NULL) return POKEMON_INVALID_CONFIGURATION;
        if (*count == POKEMON_HANDLER_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
        handlers[(*count)++] = (PokemonHandlerRef){
            .descriptor = *descriptor,
            .binding_index = (uint16_t)descriptor_index,
            .owner = {POKEMON_OWNER_FORMAT, input->target_side,
                input->target_slot, descriptor->source_id, 1},
            .holder_side = input->target_side,
            .holder_slot = input->target_slot,
        };
    }
    const PokemonMutable *target = &battle->sides[input->target_side].state[
        input->target_slot];
    uint8_t has_hook = 0;
    for (size_t i = 0; i < battle->data->status_immunity_count; i++) {
        const PokemonStatusImmunity *rule = &battle->data->status_immunities[i];
        has_hook |= rule->ability_id == target->ability_id &&
            rule->event == POKEMON_HANDLER_EVENT_SET_STATUS;
    }
    if (has_hook) {
        if (*count == POKEMON_HANDLER_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
        handlers[(*count)++] = (PokemonHandlerRef){
            .descriptor = {
                .event = POKEMON_HANDLER_EVENT_SET_STATUS,
                .id = POKEMON_SYNTHETIC_HANDLER_STATUS_IMMUNITY,
                .source_kind = POKEMON_HANDLER_SOURCE_ABILITY,
                .source_id = target->ability_id,
                .sub_order = 7,
                .exceptional_handler_id = POKEMON_EXCEPTION_STATUS_IMMUNITY,
                .scope = POKEMON_HANDLER_SCOPE_TARGET,
                .route = POKEMON_HANDLER_ROUTE_OWNER,
                .raw_hook = "ability.onSetStatus",
            },
            .binding_index = UINT16_MAX,
            .owner = {POKEMON_OWNER_ABILITY, input->target_side,
                input->target_slot, target->ability_id,
                target->ability_generation},
            .holder_side = input->target_side,
            .holder_slot = input->target_slot,
            .speed = target->cached_speed,
            .effect_order = target->ability_effect_order,
        };
    }
    return POKEMON_OK;
}

static int discover_handlers(
    const PokemonBattle *battle, const PokemonEventInput *input,
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY], size_t *count
) {
    *count = 0;
    size_t target_side = input->target_side, target_slot = input->target_slot;
    int status = discover_holder_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_TARGET, target_side, target_slot, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_holder_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_ANY, target_side, target_slot, handlers, count);
    if (status != POKEMON_OK) return status;
    size_t foe_side = 1u - target_side;
    size_t foe_slot = battle->sides[foe_side].active;
    status = discover_holder_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_FOE, foe_side, foe_slot, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_holder_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_ANY, foe_side, foe_slot, handlers, count);
    if (status != POKEMON_OK) return status;
    if (input->source.kind == POKEMON_ENTITY_POKEMON) {
        status = discover_holder_scope(battle, input->event,
            POKEMON_HANDLER_SCOPE_SOURCE, input->source.side,
            input->source.slot, handlers, count);
        if (status != POKEMON_OK) return status;
    }
    status = discover_side_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_TARGET, target_side, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_side_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_ANY, target_side, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_side_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_FOE, foe_side, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_side_scope(battle, input->event,
        POKEMON_HANDLER_SCOPE_ANY, foe_side, handlers, count);
    if (status != POKEMON_OK) return status;
    status = discover_field_scope(battle, input->event, handlers, count);
    if (status != POKEMON_OK) return status;
    return append_status_admission_handlers(battle, input, handlers, count);
}

static int unsupported_event_applicable(
    const PokemonBattle *battle, PokemonEventId event,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    uint8_t *applicable
) {
    PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
    size_t count = 0;
    int status = discover_handlers(battle, &(PokemonEventInput){
        .event = event,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
    }, handlers, &count);
    if (status != POKEMON_OK) return status;
    *applicable = count != 0;
    return POKEMON_OK;
}

typedef struct {
    uint64_t numerator;
    uint64_t denominator;
} PokemonAccuracyRatio;

static int valid_accuracy(PokemonAccuracy accuracy) {
    return (accuracy.kind == POKEMON_ACCURACY_ALWAYS && accuracy.percent == 0) ||
        (accuracy.kind == POKEMON_ACCURACY_PERCENT &&
         accuracy.percent >= 1 && accuracy.percent <= 100);
}

static int run_accuracy_events(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, PokemonRelay initial, uint8_t include_modify_accuracy,
    PokemonRelay *result
) {
    static const PokemonEventId events[] = {
        POKEMON_HANDLER_EVENT_MODIFY_ACCURACY,
        POKEMON_HANDLER_EVENT_ACCURACY,
    };
    PokemonRelay relay = initial;
    size_t first = include_modify_accuracy ? 0 : 1;
    for (size_t i = first; i < sizeof(events) / sizeof(events[0]); i++) {
        PokemonEventFrame frame;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = events[i],
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                (uint8_t)source_slot},
            .target_side = (uint8_t)target_side,
            .target_slot = (uint8_t)target_slot,
            .source_effect = active_source_effect(battle, move->id),
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move},
            .relay = relay,
        }, &frame);
        if (status != POKEMON_OK) return status;
        relay = frame.relay;
        if (relay.kind != POKEMON_RELAY_BOOLEAN &&
            relay.kind != POKEMON_RELAY_NUMBER) {
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    *result = relay;
    return POKEMON_OK;
}

static int run_modify_boost_table_event(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonBoostTable boosts, PokemonBoostTable *resolved
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_BOOST,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, (uint8_t)slot},
        .target_side = (uint8_t)side,
        .target_slot = (uint8_t)slot,
        .relay = {.kind = POKEMON_RELAY_BOOST_TABLE, .value.boosts = boosts},
        /* ModifyBoost's observable product is the mutable table plus handler
         * trace.  Do not let this helper overwrite the per-depth event-frame
         * scratch slot used by enclosing single-event assertions. */
        .suppress_trace = 1,
    }, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.relay.kind != POKEMON_RELAY_BOOST_TABLE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *resolved = frame.relay.value.boosts;
    return POKEMON_OK;
}

static int run_modify_boost_event(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonBoostTable *resolved
) {
    PokemonBoostTable boosts = {0};
    for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
        boosts.present[stat] = 1;
        boosts.delta[stat] = battle->sides[side].state[slot].boosts[stat];
    }
    return run_modify_boost_table_event(
        battle, side, slot, boosts, resolved);
}

static int resolve_move_accuracy(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    uint8_t *hit, PokemonImmunityCause *rule_immunity
) {
    int status;
    *rule_immunity = POKEMON_IMMUNITY_NONE;
    if (!valid_accuracy(move->accuracy)) return POKEMON_INVALID_CONFIGURATION;
    PokemonRelay staged;
    if (move->accuracy.kind == POKEMON_ACCURACY_ALWAYS) {
        status = run_accuracy_events(
            battle, move, source_side, source_slot, target_side, target_slot,
            (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                .value.boolean = 1}, 1, &staged);
        if (status != POKEMON_OK) return status;
        if (staged.kind == POKEMON_RELAY_BOOLEAN) {
            *hit = staged.value.boolean != 0;
            return POKEMON_OK;
        }
        goto draw_accuracy;
    }
    if (move->ohko.kind != POKEMON_OHKO_NONE) {
        /* Gen 3 dispatches both ModifyBoost events before OHKO replaces the
         * staged accuracy.  The resolved products are intentionally ignored. */
        PokemonBoostTable discarded;
        status = run_modify_boost_event(
            battle, source_side, source_slot, &discarded);
        if (status != POKEMON_OK) return status;
        status = run_modify_boost_event(
            battle, target_side, target_slot, &discarded);
        if (status != POKEMON_OK) return status;
        const PokemonSet *source = &battle->sides[source_side].sets[source_slot];
        const PokemonSet *target = &battle->sides[target_side].sets[target_slot];
        if (source->level < target->level ||
            (move->ohko.kind == POKEMON_OHKO_EXCLUDED_TYPE &&
             has_type(&battle->sides[target_side].state[target_slot],
                 move->ohko.excluded_type))) {
            *hit = 0;
            *rule_immunity = POKEMON_IMMUNITY_OHKO_RULE;
            return POKEMON_OK;
        }
        double accuracy = battle->generation->ohko.base_accuracy +
            (double)(source->level - target->level);
        status = run_accuracy_events(
            battle, move, source_side, source_slot, target_side, target_slot,
            (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
                .value.number = accuracy}, 0, &staged);
        if (status != POKEMON_OK) return status;
        if (staged.kind == POKEMON_RELAY_BOOLEAN) {
            *hit = staged.value.boolean != 0;
            return POKEMON_OK;
        }
        goto draw_accuracy;
    }
    const PokemonStagePolicy *policy = battle->generation->stages;
    int8_t accuracy_stage = 0;
    if (!move->ignore_accuracy) {
        PokemonBoostTable source_boosts;
        status = run_modify_boost_event(
            battle, source_side, source_slot, &source_boosts);
        if (status != POKEMON_OK ||
            !source_boosts.present[POKEMON_STAT_ACCURACY]) {
            return status != POKEMON_OK ? status : POKEMON_INVALID_CONFIGURATION;
        }
        accuracy_stage = source_boosts.delta[POKEMON_STAT_ACCURACY];
    }
    int8_t evasion_stage = 0;
    if (!move->ignore_evasion) {
        PokemonBoostTable target_boosts;
        status = run_modify_boost_event(
            battle, target_side, target_slot, &target_boosts);
        if (status != POKEMON_OK ||
            !target_boosts.present[POKEMON_STAT_EVASION]) {
            return status != POKEMON_OK ? status : POKEMON_INVALID_CONFIGURATION;
        }
        evasion_stage = target_boosts.delta[POKEMON_STAT_EVASION];
    }
    if (accuracy_stage < policy->minimum) accuracy_stage = policy->minimum;
    if (accuracy_stage > policy->maximum) accuracy_stage = policy->maximum;
    if (evasion_stage < policy->minimum) evasion_stage = policy->minimum;
    if (evasion_stage > policy->maximum) evasion_stage = policy->maximum;
    PokemonStageRatio accuracy = policy->accuracy[
        (size_t)(accuracy_stage - policy->minimum)];
    PokemonStageRatio evasion = policy->accuracy[
        (size_t)(evasion_stage - policy->minimum)];
    PokemonAccuracyRatio threshold = {
        .numerator = (uint64_t)move->accuracy.percent * accuracy.numerator *
            evasion.denominator,
        .denominator = (uint64_t)accuracy.denominator * evasion.numerator,
    };
    double staged_accuracy = (double)threshold.numerator /
        (double)threshold.denominator;
    status = run_accuracy_events(
        battle, move, source_side, source_slot, target_side, target_slot,
        (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
            .value.number = staged_accuracy}, 1, &staged);
    if (status != POKEMON_OK) return status;
    if (staged.kind == POKEMON_RELAY_BOOLEAN) {
        *hit = staged.value.boolean != 0;
        return POKEMON_OK;
    }
draw_accuracy:
    staged_accuracy = staged.value.number;
    uint32_t draw = 0;
    status = draw_below(battle, POKEMON_DRAW_ACCURACY, 100, &draw);
    if (status != POKEMON_OK) return status;
    *hit = (double)draw < staged_accuracy;
    return POKEMON_OK;
}

/* Showdown composes relay modifiers in Q12 and rounds only once when the
 * event finishes. These formulas mirror Battle#chainModify and Battle#modify. */
static uint32_t chain_modifier_q12(uint32_t previous, uint32_t next) {
    return (uint32_t)(((uint64_t)previous * next + 2048u) >> 12);
}

static uint32_t apply_modifier_q12(uint32_t value, uint32_t modifier) {
    return (uint32_t)(((uint64_t)value * modifier + 2047u) >> 12);
}

static const PokemonEventSpec *event_spec(
    const PokemonBattle *battle, PokemonEventId event
) {
    for (size_t i = 0; i < battle->data->event_spec_count; i++) {
        if (battle->data->event_specs[i].id == event) {
            return &battle->data->event_specs[i];
        }
    }
    return NULL;
}

typedef struct {
    PokemonEntityRef values[POKEMON_SIDES];
    uint8_t count;
} PokemonLivingActiveList;

static int collect_living_actives(
    const PokemonBattle *battle, PokemonLivingActiveList *actives
) {
    if (battle == NULL || actives == NULL ||
        battle->format.active_per_side != 1) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *actives = (PokemonLivingActiveList){0};
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        uint8_t slot = battle->sides[side].active;
        if (slot >= battle->team_sizes[side]) return POKEMON_INVALID_CONFIGURATION;
        const PokemonMutable *active = &battle->sides[side].state[slot];
        if (active->hp == 0 || active->fainted) continue;
        actives->values[actives->count++] = (PokemonEntityRef){
            POKEMON_ENTITY_POKEMON, (uint8_t)side, slot};
    }
    return POKEMON_OK;
}

static int run_event_inner(
    PokemonBattle *battle, const PokemonEventInput *input,
    PokemonEventFrame *result
) {
    if (battle == NULL || input == NULL || result == NULL ||
        input->target_side >= POKEMON_SIDES ||
        input->target_slot >= battle->team_sizes[input->target_side] ||
        (input->source.kind == POKEMON_ENTITY_POKEMON &&
         (input->source.side >= POKEMON_SIDES ||
          input->source.slot >= battle->team_sizes[input->source.side])) ||
        input->source.kind > POKEMON_ENTITY_POKEMON) {
        return POKEMON_INVALID_ARGUMENT;
    }
    const PokemonEventSpec *spec = event_spec(battle, input->event);
    if (spec == NULL || !spec->supported) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (battle->event_depth >= POKEMON_EVENT_FRAME_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    if ((spec->algebra == POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL &&
         input->relay.kind != POKEMON_RELAY_U32 &&
         input->relay.kind != POKEMON_RELAY_NUMBER &&
         !((input->event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ||
            input->event == POKEMON_HANDLER_EVENT_ACCURACY) &&
           input->relay.kind == POKEMON_RELAY_BOOLEAN)) ||
        (spec->algebra == POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL &&
         input->relay.kind != POKEMON_RELAY_BOOLEAN) ||
        (spec->algebra == POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NUMBER &&
         input->relay.kind != POKEMON_RELAY_BOOLEAN &&
         input->relay.kind != POKEMON_RELAY_NUMBER) ||
        (spec->algebra == POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE &&
         input->relay.kind != POKEMON_RELAY_BOOST_TABLE)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (((input->event == POKEMON_HANDLER_EVENT_TRY_HIT ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_ATK ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_DEF ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_SPA ||
          input->event == POKEMON_HANDLER_EVENT_MODIFY_SPD) &&
         (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
          input->context.move.move == NULL)) ||
        (input->event == POKEMON_HANDLER_EVENT_DAMAGE &&
         input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE) ||
        (input->event == POKEMON_HANDLER_EVENT_SET_STATUS &&
         input->context_kind != POKEMON_EVENT_CONTEXT_STATUS)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonHandlerRef discovered[POKEMON_HANDLER_CAPACITY];
    size_t count = 0;
    int status = POKEMON_OK;
    if (input->has_only_handler) {
        discovered[0] = input->only_handler;
        count = 1;
    } else {
        status = discover_handlers(battle, input, discovered, &count);
        if (status == POKEMON_OK && input->include_source_effect_move) {
            if (input->source_effect.kind != POKEMON_SOURCE_EFFECT_MOVE) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            for (size_t i = 0; i < battle->data->handler_count; i++) {
                const PokemonHandlerDescriptor *descriptor =
                    &battle->data->handlers[i];
                if (descriptor->event != input->event ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->source_id != input->source_effect.id ||
                    descriptor->route !=
                        POKEMON_HANDLER_ROUTE_SOURCE_EFFECT) continue;
                if (count == POKEMON_HANDLER_CAPACITY) {
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                discovered[count++] = (PokemonHandlerRef){
                    .descriptor = *descriptor, .binding_index = (uint16_t)i,
                    .owner = {POKEMON_OWNER_MOVE, input->target_side,
                        input->target_slot, input->source_effect.id, 1},
                    .holder_side = input->target_side,
                    .holder_slot = input->target_slot,
                    .speed = battle->sides[input->target_side].state[
                        input->target_slot].cached_speed,
                };
            }
        }
        if (status == POKEMON_OK && input->include_move_self) {
            if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                input->context.move.move == NULL ||
                input->source.kind != POKEMON_ENTITY_POKEMON) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            const PokemonMoveData *move = input->context.move.move;
            for (size_t i = 0; i < battle->data->handler_count; i++) {
                const PokemonHandlerDescriptor *descriptor =
                    &battle->data->handlers[i];
                if (descriptor->event != input->event ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->source_id != move->id ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) continue;
                if (count == POKEMON_HANDLER_CAPACITY) {
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                discovered[count++] = (PokemonHandlerRef){
                    .descriptor = *descriptor, .binding_index = (uint16_t)i,
                    .owner = {POKEMON_OWNER_MOVE, input->source.side,
                        input->source.slot, move->id, 1},
                    .holder_side = input->source.side,
                    .holder_slot = input->source.slot,
                    .speed = battle->sides[input->source.side].state[
                        input->source.slot].cached_speed,
                };
            }
        }
    }
    if (status != POKEMON_OK) return status;
    uint8_t uses_modifiers = input->event == POKEMON_HANDLER_EVENT_BASE_POWER ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_ATK ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_DEF ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_SPA ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_SPD ||
        input->event == POKEMON_HANDLER_EVENT_MODIFY_SPE ||
        input->event == POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE;
    size_t possible_events = 0;
    size_t possible_condition_traces = 0;
    size_t possible_effect_traces = 0;
    size_t possible_draws = 0;
    for (size_t i = 0; i < count; i++) {
        const PokemonHandlerDescriptor *descriptor = &discovered[i].descriptor;
        if ((size_t)descriptor->program_offset + descriptor->program_count >
                battle->data->handler_program_count) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (descriptor->exceptional_handler_id != 0) continue;
        for (size_t j = 0; j < descriptor->program_count; j++) {
            const PokemonHandlerOp *op = &battle->data->handler_programs[
                descriptor->program_offset + j];
            switch (op->opcode) {
            case POKEMON_HANDLER_OP_SET_OWNER_ENDING:
                if (discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument > 1) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_SET_WEATHER:
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument < POKEMON_WEATHER_SANDSTORM ||
                    op->argument > POKEMON_WEATHER_SUN) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_BOOST_OPPOSING_ACTIVES_EXCEPT_VOLATILE: {
                uint16_t excluded = (uint16_t)(op->argument >> 16);
                uint8_t stat = (uint8_t)(op->argument >> 8);
                int8_t delta = (int8_t)(op->argument & UINT32_C(0xff));
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    excluded == POKEMON_VOLATILE_NONE ||
                    excluded > POKEMON_VOLATILE_NIGHTMARE ||
                    stat >= POKEMON_STAT_COUNT || delta == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += POKEMON_SIDES - 1u;
                break;
            }
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_SLEEP_UNIFORM: {
                PokemonDrawLabel label = (PokemonDrawLabel)(op->argument >> 24);
                uint8_t minimum = (uint8_t)(op->argument >> 16);
                uint8_t maximum_exclusive = (uint8_t)(op->argument >> 8);
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    discovered[i].owner.kind != POKEMON_OWNER_STATUS ||
                    battle->sides[discovered[i].holder_side].state[
                        discovered[i].holder_slot].status.kind !=
                            POKEMON_STATUS_SLEEP ||
                    label == 0 || label > POKEMON_DRAW_ABILITY_TARGET ||
                    minimum == 0 || minimum >= maximum_exclusive ||
                    (op->argument & UINT32_C(0xff)) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REPLACE_HOLDER_ABILITY_FROM_TARGET:
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument != POKEMON_HANDLER_TARGET_RANDOM_ACTIVE_FOE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT:
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE:
                if (op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ACTIVE_TURNS:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_GUARD_ANY_LIVING_ACTIVE_ABILITY:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_SPA ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument == 0 || op->argument > UINT16_MAX ||
                    find_ability(battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_BOOST_HOLDER_STAT: {
                uint8_t stat = (uint8_t)(op->argument >> 8);
                int8_t delta = (int8_t)(op->argument & UINT32_C(0xff));
                int ability_owner =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_ABILITY &&
                    discovered[i].owner.kind == POKEMON_OWNER_ABILITY;
                int condition_owner =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
                    discovered[i].owner.kind == POKEMON_OWNER_VOLATILE;
                if (!((input->event == POKEMON_HANDLER_EVENT_RESIDUAL && ability_owner) ||
                      (input->event == POKEMON_HANDLER_EVENT_HIT && condition_owner)) ||
                    stat >= POKEMON_STAT_COUNT || delta == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_DAMAGE_HOLDER_BASE_MAX_HP_FRACTION:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    (op->argument >> 16) == 0 ||
                    (op->argument >> 16) > UINT8_MAX ||
                    (op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument & UINT32_C(0xffff)) > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += 2;
                break;
            case POKEMON_HANDLER_OP_TRANSFER_HOLDER_MAX_HP_FRACTION_TO_SOURCE_POSITION:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    battle->format.active_per_side != 1 ||
                    (op->argument >> 16) == 0 ||
                    (op->argument >> 16) > UINT8_MAX ||
                    (op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument & UINT32_C(0xffff)) > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += 4;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK:
            case POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_NOT_MASK:
            case POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK: {
                const uint32_t valid =
                    ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                    ~UINT32_C(1);
                if (op->argument == 0 || (op->argument & ~valid) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (op->opcode == POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK &&
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL &&
                    !(input->event == POKEMON_HANDLER_EVENT_START &&
                      spec->algebra == POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_TYPE:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_OHKO:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL || op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_MODIFIER_TAG:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL || op->argument >= 64) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_TAGGED_STATUS_MOVE_TARGET_ELIGIBLE: {
                uint16_t tag = (uint16_t)(op->argument >> 16);
                uint16_t excluded_type =
                    (uint16_t)(op->argument & UINT32_C(0xffff));
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    tag >= 64 || excluded_type >= battle->data->type_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_APPEND_ACTIVE_MOVE_VOLATILE_SECONDARY: {
                uint16_t kind = (uint16_t)(op->argument & UINT32_C(0xffff));
                uint16_t chance = (uint16_t)(op->argument >> 16);
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    battle->move_frame_depth == 0 || chance == 0 || chance > 100 ||
                    kind == POKEMON_VOLATILE_NONE ||
                    kind > POKEMON_VOLATILE_NIGHTMARE ||
                    battle->move_frames[battle->move_frame_depth - 1]
                            .appended_secondary_count ==
                        POKEMON_ACTIVE_SECONDARY_CAPACITY) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_HOLDER_FROM_MOVE_DAMAGE_FRACTION:
                if (input->event !=
                        POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    battle->move_frame_depth == 0 ||
                    (op->argument >> 16) == 0 ||
                    (op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument >> 16) >
                        (op->argument & UINT32_C(0xffff))) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_BASE_MOVE_TYPE:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    op->argument >= battle->data->type_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_DEFROST:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL || op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument == 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR:
                if ((op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument >> 16) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND:
                if ((input->event != POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE &&
                     input->event != POKEMON_HANDLER_EVENT_IMMUNITY) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_VOLATILE ||
                    op->argument == POKEMON_VOLATILE_NONE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND_MASK:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_VOLATILE ||
                    op->argument == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_EMIT_HANDLER_IMMUNITY:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ACTIVE:
                if (input->event != POKEMON_HANDLER_EVENT_TRAP_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ABILITY_ACTIVE:
                if (input->event !=
                        POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES:
                if (input->event != POKEMON_HANDLER_EVENT_TRAP_POKEMON ||
                    (descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION &&
                     descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY) ||
                    input->context_kind !=
                        POKEMON_EVENT_CONTEXT_SWITCH_RESTRICTIONS ||
                    input->context.switch_restrictions == NULL ||
                    op->argument > 1) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SOURCE_BOUND_MAX_HP_DAMAGE:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    (op->argument >> 16) == 0 ||
                    (op->argument >> 16) > UINT8_MAX ||
                    (op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument & UINT32_C(0xffff)) > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += 2;
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_TYPE:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument >= battle->data->type_count ||
                    battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_CATEGORY:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    (op->argument != POKEMON_CATEGORY_PHYSICAL &&
                     op->argument != POKEMON_CATEGORY_SPECIAL) ||
                    battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SNAPSHOT_ACTIVE_MOVE_PARTY_HITS:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0 || battle->move_frame_depth == 0 ||
                    input->source.kind != POKEMON_ENTITY_POKEMON) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_NEXT_PARTY_HIT_BASE_STAT:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_SPA ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != POKEMON_STAT_ATK ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_EVENT_TARGET_BASE_SPECIES_STAT:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_SPD ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_FOE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != POKEMON_STAT_DEF ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_NO_ACTIVE_PARTY_HITS:
                if (input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0 || battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_APPLY_ACTIVE_MOVE_PERSONAL_PROFILE:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 || op->argument > UINT16_MAX ||
                    battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    battle->move_frame_depth == 0 || op->argument == 0 ||
                    op->argument > UINT16_MAX ||
                    weighted_move_distribution(
                        battle, (uint16_t)op->argument) == NULL ||
                    battle->draw_count == POKEMON_DRAW_CAPACITY) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REQUIRE_TARGET_LAST_NONFALLBACK:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REQUIRE_TARGET_STATUS_NONE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_STATUS_FROM_OWNER_SOURCE:
                if (input->event != POKEMON_HANDLER_EVENT_END ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    op->argument <= POKEMON_STATUS_NONE ||
                    op->argument > POKEMON_STATUS_FREEZE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_OWNER_SIDE_COUNTER:
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_SIDE ||
                    op->argument == 0 || op->argument > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_INCREMENT_OWNER_SIDE_COUNTER_UP_TO:
                if (input->event != POKEMON_HANDLER_EVENT_RESTART ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_SIDE ||
                    op->argument == 0 || op->argument > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_TARGET_GROUNDED:
                if ((input->event != POKEMON_HANDLER_EVENT_ENTRY_HAZARD &&
                     input->event != POKEMON_HANDLER_EVENT_TRAP_POKEMON) ||
                    op->argument >= battle->data->type_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (input->event == POKEMON_HANDLER_EVENT_ENTRY_HAZARD &&
                    (descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                     discovered[i].owner.kind != POKEMON_OWNER_SIDE)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_ADJACENT_TO_TARGET:
                if (input->event != POKEMON_HANDLER_EVENT_TRAP_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE:
                if (!((input->event == POKEMON_HANDLER_EVENT_TRAP_POKEMON &&
                       descriptor->source_kind == POKEMON_HANDLER_SOURCE_ABILITY) ||
                      (input->event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY &&
                       descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF) ||
                      (input->event ==
                           POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_CONDITION &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER)) ||
                    op->argument >= battle->data->type_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DAMAGE_TARGET_MAX_HP_BY_OWNER_COUNTER_FRACTIONS:
                if (input->event != POKEMON_HANDLER_EVENT_ENTRY_HAZARD ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_SIDE ||
                    (op->argument >> 24) == 0 ||
                    ((op->argument >> 16) & UINT32_C(0xff)) == 0 ||
                    ((op->argument >> 8) & UINT32_C(0xff)) == 0 ||
                    (op->argument & UINT32_C(0xff)) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += 2;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument < POKEMON_CATEGORY_PHYSICAL ||
                    op->argument > POKEMON_CATEGORY_SPECIAL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
			case POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK:
				if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
					input->context.move.move == NULL || op->argument == 0 ||
					(op->argument & ~((UINT32_C(1) << POKEMON_CATEGORY_PHYSICAL) |
						(UINT32_C(1) << POKEMON_CATEGORY_SPECIAL) |
						(UINT32_C(1) << POKEMON_CATEGORY_STATUS))) != 0) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				break;
			case POKEMON_HANDLER_OP_REQUIRE_HOLDER_TYPE_EFFECTIVENESS_ABOVE:
				if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
					spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
					descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
					discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
					input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
					input->context.move.move == NULL || op->argument > UINT8_MAX) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_SIDE_CONTAINS_TARGET:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
                    discovered[i].owner.kind != POKEMON_OWNER_SIDE ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_HIT_NOT_CRITICAL:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION: {
                PokemonSideSelector selector =
                    (PokemonSideSelector)(op->argument >> 24);
                uint16_t condition_id =
                    (uint16_t)(op->argument & UINT32_C(0xffff));
                const PokemonConditionIdentity *condition =
                    pokemon_condition_identity(battle->data, condition_id);
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    (op->argument & UINT32_C(0x00ff0000)) != 0 ||
                    selector < POKEMON_SIDE_SELECTOR_SOURCE ||
                    selector > POKEMON_SIDE_SELECTOR_EVENT_TARGET ||
                    condition == NULL ||
                    condition->domain != POKEMON_CONDITION_DOMAIN_SIDE ||
                    condition->semantic_kind == 0 ||
                    condition->semantic_kind > POKEMON_SIDE_CONDITION_SPIKES) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_FLAG:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument >= 64) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_SELF_FAINT_TIMING:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    op->argument > POKEMON_SELF_FAINT_IF_HIT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE: {
                uint32_t label = op->argument >> 24;
                uint32_t numerator = (op->argument >> 16) & UINT32_C(0xff);
                uint32_t denominator = op->argument & UINT32_C(0xffff);
                if (label == 0 || label > POKEMON_DRAW_FOCUS_BAND ||
                    numerator > denominator || denominator == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER:
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGING_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument <= POKEMON_STATUS_NONE ||
                    op->argument > POKEMON_STATUS_FREEZE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER_UNIFORM_3: {
                uint32_t label = op->argument >> 24;
                uint32_t status0 = (op->argument >> 16) & UINT32_C(0xff);
                uint32_t status1 = (op->argument >> 8) & UINT32_C(0xff);
                uint32_t status2 = op->argument & UINT32_C(0xff);
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGING_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    label == 0 || label > POKEMON_DRAW_CONTACT_STATUS_SELECTION ||
                    status0 <= POKEMON_STATUS_NONE || status0 > POKEMON_STATUS_FREEZE ||
                    status1 <= POKEMON_STATUS_NONE || status1 > POKEMON_STATUS_FREEZE ||
                    status2 <= POKEMON_STATUS_NONE || status2 > POKEMON_STATUS_FREEZE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_TRY_ADD_EVENT_SOURCE_VOLATILE_FROM_HOLDER:
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGING_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument <= POKEMON_VOLATILE_NONE ||
                    op->argument >= POKEMON_VOLATILE_KIND_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
			case POKEMON_HANDLER_OP_TRY_ADD_EVENT_TARGET_VOLATILE_FROM_SOURCE:
				if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
					input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
					input->source.kind != POKEMON_ENTITY_POKEMON ||
					descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
					discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
					op->argument <= POKEMON_VOLATILE_NONE ||
					op->argument >= POKEMON_VOLATILE_KIND_COUNT) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				possible_condition_traces++;
				break;
            case POKEMON_HANDLER_OP_REQUIRE_SOURCE_OPPOSITE_GENDER_TO_HOLDER:
                if ((input->event != POKEMON_HANDLER_EVENT_START &&
                     input->event != POKEMON_HANDLER_EVENT_TRY_IMMUNITY) ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    !((descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
                       discovered[i].owner.kind == POKEMON_OWNER_VOLATILE) ||
                      (descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       discovered[i].owner.kind == POKEMON_OWNER_MOVE)) ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE_IF_SOURCE_INACTIVE:
                if (input->event != POKEMON_HANDLER_EVENT_UPDATE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_GUARD_EVENT_STATUS_MASK: {
                const uint32_t valid =
                    ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                    ~UINT32_C(1);
                if ((input->event != POKEMON_HANDLER_EVENT_SET_STATUS &&
                     input->event != POKEMON_HANDLER_EVENT_AFTER_SET_STATUS) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_STATUS ||
                    op->argument == 0 || (op->argument & ~valid) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REFLECT_EVENT_STATUS_TO_SOURCE: {
                uint32_t rewrite_from =
                    (op->argument >> 8) & UINT32_C(0xff);
                uint32_t rewrite_to = op->argument & UINT32_C(0xff);
                if (input->event != POKEMON_HANDLER_EVENT_AFTER_SET_STATUS ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_STATUS ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    (op->argument >> 16) != 0 ||
                    ((rewrite_from == 0) != (rewrite_to == 0)) ||
                    rewrite_from > POKEMON_STATUS_FREEZE ||
                    rewrite_to > POKEMON_STATUS_FREEZE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION: {
                uint32_t numerator = op->argument >> 16;
                uint32_t denominator = op->argument & UINT32_C(0xffff);
                uint8_t ability_damage =
                    input->event == POKEMON_HANDLER_EVENT_DAMAGING_HIT &&
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_ABILITY &&
                    discovered[i].owner.kind == POKEMON_OWNER_ABILITY;
                uint8_t move_payment =
                    input->event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK &&
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                    discovered[i].owner.kind == POKEMON_OWNER_MOVE &&
                    descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
                    descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF;
                if ((!ability_damage && !move_payment) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    numerator == 0 || denominator == 0 ||
                    numerator > denominator) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS:
                if (input->event != POKEMON_HANDLER_EVENT_INVULNERABILITY ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL || op->argument == 0 ||
                    (op->argument & (op->argument - 1u)) != 0 ||
                    op->argument > POKEMON_SEMI_INVULNERABLE_UNDERWATER) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE:
                if ((input->event != POKEMON_HANDLER_EVENT_BASE_POWER &&
                     input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE &&
                     input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL || op->argument == 0 ||
                    (op->argument & (op->argument - 1u)) != 0 ||
                    op->argument > POKEMON_SEMI_INVULNERABLE_UNDERWATER) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BOOST_STAGES_TO_SOURCE:
                if (op->argument != 0 ||
                    input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_BOOST_STAGES:
                if (op->argument != 0 ||
                    input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_FIELD ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_STATUS_MASK: {
                if (!valid_clear_living_active_status_op(descriptor, op) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->event != POKEMON_HANDLER_EVENT_TRY_HIT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces += POKEMON_SIDES;
                possible_effect_traces += POKEMON_SIDES;
                break;
            }
            case POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_FROM_MOVE:
                if (op->argument != 0 ||
                    input->event != POKEMON_HANDLER_EVENT_DAMAGING_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_LITERAL:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument >= battle->data->type_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SAMPLE_HOLDER_MOVE_SLOT_TYPE: {
                uint32_t label = op->argument >> 24;
                uint32_t excluded_catalog_id = op->argument & UINT32_C(0xffff);
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    (op->argument & UINT32_C(0x00ff0000)) != 0 ||
                    label == 0 || label >= POKEMON_DRAW_LABEL_COUNT ||
                    excluded_catalog_id == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_draws++;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND:
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND_ANY:
                if (input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE ||
                    op->argument < POKEMON_DAMAGE_RELATIVE_DRAIN ||
                    op->argument > POKEMON_DAMAGE_EVENT_ORDINARY_MOVE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_IS_EVENT_TARGET:
                if (op->argument != 0 ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    (input->event != POKEMON_HANDLER_EVENT_ACCURACY &&
                     input->event != POKEMON_HANDLER_EVENT_INVULNERABILITY)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET:
                break;
            case POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT:
                if ((op->argument >> 24) > POKEMON_SOURCE_EFFECT_ABILITY ||
                    (op->argument & UINT32_C(0xffff)) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_IMMUNITY_WEATHER_MASK:
                if (op->argument == 0 ||
                    (op->argument >> (POKEMON_WEATHER_SUN + 1u)) != 0 ||
                    input->event != POKEMON_HANDLER_EVENT_IMMUNITY ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_IMMUNITY) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HP_AT_MOST_FRACTION:
                if ((op->argument >> 16) == 0 ||
                    (op->argument & UINT32_C(0xffff)) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_STATUS_MASK: {
                const uint32_t valid =
                    ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                    ~UINT32_C(1);
                if (op->argument == 0 || (op->argument & ~valid) != 0 ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_MOVE_ACTIONS_ABOVE:
                if (op->argument == 0 ||
                    input->event != POKEMON_HANDLER_EVENT_TRY ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_HP_FULL:
                if (op->argument != 0 ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_ABILITY_BLOCKS_STATUS:
            case POKEMON_HANDLER_OP_REPLACE_HOLDER_MAJOR_STATUS:
                if (op->argument <= POKEMON_STATUS_NONE ||
                    op->argument > POKEMON_STATUS_FREEZE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (op->opcode == POKEMON_HANDLER_OP_REPLACE_HOLDER_MAJOR_STATUS &&
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_HOLDER_STATUS_COUNTER:
                if ((op->argument & UINT32_C(0xffff)) > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if ((op->argument >> 16) == POKEMON_STATUS_COUNTER_SLEEP_TIME) {
                    break;
                }
                if ((op->argument >> 16) != POKEMON_STATUS_COUNTER_TOXIC_STAGE ||
                    (op->argument & UINT32_C(0xffff)) != 0 ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_STATUS ||
                    battle->sides[discovered[i].holder_side].state[
                        discovered[i].holder_slot].status.kind !=
                            POKEMON_STATUS_TOXIC ||
                    (input->event != POKEMON_HANDLER_EVENT_START &&
                     input->event != POKEMON_HANDLER_EVENT_SWITCH_IN)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (input->event == POKEMON_HANDLER_EVENT_SWITCH_IN) {
                    possible_condition_traces++;
                }
                break;
            case POKEMON_HANDLER_OP_ADVANCE_OWNER_SLEEP:
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_STATUS ||
                    op->argument == 0 || op->argument > UINT16_MAX ||
                    find_ability(battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_RESTORE_OWNER_SLEEP_SKIPPED:
                if (op->argument != 0 ||
                    input->event != POKEMON_HANDLER_EVENT_SWITCH_IN ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_STATUS) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_NOT_BOUNCED:
            case POKEMON_HANDLER_OP_REFLECT_ACTIVE_MOVE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CALL_ACTIVE_MOVE_AS_OWNER:
                if (input->event != POKEMON_HANDLER_EVENT_PREPARE_HIT ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_ANY) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DEDUCT_OWNER_MOVE_PP_FROM_TARGET_EVENT:
                if (input->event != POKEMON_HANDLER_EVENT_PREPARE_HIT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_ANY) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE:
                if (descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    (descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET &&
                     descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE &&
                     descriptor->scope != POKEMON_HANDLER_SCOPE_ANY)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_TRY_HEAL_HOLDER_MAX_HP_FRACTION:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    (op->argument >> 16) == 0 ||
                    (op->argument & UINT32_C(0xffff)) == 0 ||
                    (op->argument >> 16) > UINT8_MAX ||
                    (op->argument & UINT32_C(0xffff)) > UINT8_MAX ||
                    (op->argument >> 16) >
                        (op->argument & UINT32_C(0xffff))) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE:
                if (!((input->event == POKEMON_HANDLER_EVENT_TRY_HIT &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_ABILITY &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET) ||
                      (input->event == POKEMON_HANDLER_EVENT_ITEM_EAT &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_ITEM &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET) ||
                      (input->event == POKEMON_HANDLER_EVENT_AFTER_MOVE &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_ITEM &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE)) ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > UINT16_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_SOURCE_VOLATILE:
                if ((input->event !=
                         POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK &&
                     input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > UINT16_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND:
                if (!valid_require_holder_without_volatile_op(
                        descriptor, op) ||
                    input->event != POKEMON_HANDLER_EVENT_TRY_IMMUNITY ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    op->argument >= POKEMON_VOLATILE_KIND_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND:
            case POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND:
                if (!((input->event == POKEMON_HANDLER_EVENT_UPDATE &&
                       (descriptor->source_kind == POKEMON_HANDLER_SOURCE_ITEM ||
                        descriptor->source_kind ==
                            POKEMON_HANDLER_SOURCE_ABILITY) &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER) ||
                      (op->opcode ==
                           POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND &&
                       input->event == POKEMON_HANDLER_EVENT_END &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_ABILITY &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER) ||
                      (op->opcode ==
                           POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND &&
                       (input->event == POKEMON_HANDLER_EVENT_AFTER_MOVE ||
                        input->event == POKEMON_HANDLER_EVENT_PREPARE_HIT ||
                        input->event ==
                            POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) &&
                       descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
                       descriptor->route ==
                           POKEMON_HANDLER_ROUTE_MOVE_SELF) ||
                      (op->opcode ==
                           POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND &&
                       (input->event == POKEMON_HANDLER_EVENT_TRY_HIT ||
                        input->event == POKEMON_HANDLER_EVENT_TRY) &&
                       descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
                       descriptor->route ==
                           POKEMON_HANDLER_ROUTE_MOVE_SELF)) ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > UINT16_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (op->opcode ==
                    POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND) {
                    possible_condition_traces++;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_COUNTER_AT_LEAST: {
                uint32_t kind = op->argument >> 16;
                uint32_t threshold = op->argument & UINT32_C(0xffff);
                if (kind == POKEMON_VOLATILE_NONE ||
                    kind >= POKEMON_VOLATILE_KIND_COUNT || threshold == 0 ||
                    threshold > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_USE_HANDLER_OWNED_HELD_ITEM:
                if ((input->event != POKEMON_HANDLER_EVENT_UPDATE &&
                     input->event != POKEMON_HANDLER_EVENT_START &&
                     input->event != POKEMON_HANDLER_EVENT_SWITCH_IN &&
                     input->event != POKEMON_HANDLER_EVENT_AFTER_MOVE &&
                     input->event != POKEMON_HANDLER_EVENT_RESIDUAL) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM ||
                    (descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET &&
                     descriptor->scope != POKEMON_HANDLER_SCOPE_ANY) ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_NEGATIVE_BOOST:
            case POKEMON_HANDLER_OP_CLEAR_HOLDER_NEGATIVE_BOOST_STAGES:
                if ((input->event != POKEMON_HANDLER_EVENT_START &&
                     input->event != POKEMON_HANDLER_EVENT_SWITCH_IN &&
                     input->event != POKEMON_HANDLER_EVENT_AFTER_MOVE &&
                     input->event != POKEMON_HANDLER_EVENT_RESIDUAL) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM ||
                    (descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET &&
                     descriptor->scope != POKEMON_HANDLER_SCOPE_ANY) ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CHAIN_Q12:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL ||
                    op->argument == 0) return POKEMON_INVALID_CONFIGURATION;
                uses_modifiers = 1;
                break;
            case POKEMON_HANDLER_OP_MODIFY_RELAY_Q12:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL ||
                    op->argument == 0) return POKEMON_INVALID_CONFIGURATION;
                uses_modifiers = 1;
                break;
            case POKEMON_HANDLER_OP_ADD_RELAY_U32:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL ||
                    op->argument == 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE:
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    !((descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_SOURCE_EFFECT) ||
                      (descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER) ||
					  (descriptor->source_kind == POKEMON_HANDLER_SOURCE_ITEM &&
					   descriptor->route == POKEMON_HANDLER_ROUTE_OWNER)) ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    (op->argument & UINT32_C(0xffff)) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uses_modifiers = 1;
                break;
            case POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER:
                if (op->argument < POKEMON_WEATHER_SANDSTORM ||
                    op->argument > POKEMON_WEATHER_SUN) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION:
                if (!((input->event == POKEMON_HANDLER_EVENT_RESIDUAL) ||
                      (input->event ==
                           POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
                       descriptor->route ==
                           POKEMON_HANDLER_ROUTE_MOVE_SELF)) ||
                    op->argument == 0 || op->argument > UINT16_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS:
                if (op->argument != 0 ||
                    !(((input->event == POKEMON_HANDLER_EVENT_SWITCH_OUT ||
                        input->event == POKEMON_HANDLER_EVENT_UPDATE ||
                        input->event == POKEMON_HANDLER_EVENT_RESIDUAL) &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_ABILITY &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER) ||
                      (input->event ==
                           POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK &&
                       descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
                       descriptor->route ==
                           POKEMON_HANDLER_ROUTE_MOVE_SELF) ||
                      ((input->event == POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                        input->event == POKEMON_HANDLER_EVENT_DAMAGING_HIT) &&
                       descriptor->source_kind ==
                           POKEMON_HANDLER_SOURCE_CONDITION &&
                       discovered[i].owner.kind == POKEMON_OWNER_STATUS &&
                       descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
                       descriptor->route == POKEMON_HANDLER_ROUTE_OWNER))) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                /* A successful cure caused by a move is part of that move's
                 * observable primary effect.  Ability-owned cures such as
                 * Natural Cure and Shed Skin remain condition-only events. */
                if (input->source_effect.kind ==
                    POKEMON_SOURCE_EFFECT_MOVE) {
                    possible_effect_traces++;
                }
                break;
            case POKEMON_HANDLER_OP_RANDOM_CURE_OR_REQUIRE_DEFROST: {
                uint32_t label = op->argument >> 24;
                uint32_t numerator = (op->argument >> 16) & UINT32_C(0xff);
                uint32_t denominator = (op->argument >> 8) & UINT32_C(0xff);
                uint32_t reserved = op->argument & UINT32_C(0xff);
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    input->source_effect.kind !=
                        POKEMON_SOURCE_EFFECT_MOVE ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_STATUS ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    label == 0 || label > POKEMON_DRAW_ITEM_RANDOM_STAT ||
                    numerator == 0 || denominator == 0 ||
                    numerator > denominator || reserved != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                possible_effect_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_ABILITY_TRANSFER_ALLOWED:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    (op->argument & UINT32_C(0xffff)) == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REPLACE_SOURCE_ABILITY_FROM_EVENT_TARGET:
                if (input->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SWAP_SOURCE_TARGET_ABILITIES:
                if (input->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS: {
                uint16_t excluded_ability =
                    (uint16_t)(op->argument & UINT32_C(0xffff));
                uint32_t flags = op->argument >> 16;
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    (flags & ~UINT32_C(3)) != 0 ||
                    (excluded_ability == 0 && (flags & UINT32_C(2)) != 0) ||
                    (excluded_ability != 0 &&
                     find_ability(battle, excluded_ability) == NULL)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                size_t team_side = discovered[i].holder_side;
                for (size_t ordinal = 0;
                     ordinal < battle->team_sizes[team_side]; ordinal++) {
                    size_t slot = battle->sides[team_side].active;
                    if (ordinal != 0) {
                        slot = ordinal - 1;
                        if (slot >= battle->sides[team_side].active) slot++;
                    }
                    const PokemonMutable *member =
                        &battle->sides[team_side].state[slot];
                    if (excluded_ability != 0 &&
                        member->ability_id == excluded_ability) {
                        possible_events += (flags & UINT32_C(2)) != 0 &&
                            slot == battle->sides[team_side].active;
                        continue;
                    }
                    size_t removals = major_status_removal_trace_count(
                        battle, team_side, slot);
                    possible_condition_traces += removals;
                    possible_effect_traces +=
                        removals != 0 && (flags & UINT32_C(1)) != 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_SOURCE_OPPOSES_HOLDER:
                if ((input->event != POKEMON_HANDLER_EVENT_DEDUCT_PP &&
                     input->event != POKEMON_HANDLER_EVENT_FAINT) ||
                    (input->event == POKEMON_HANDLER_EVENT_DEDUCT_PP &&
                     descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY) ||
                    (input->event == POKEMON_HANDLER_EVENT_FAINT &&
                     descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION) ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_FAINT_EVENT_SOURCE:
                if (input->event != POKEMON_HANDLER_EVENT_FAINT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_ZERO_LIVING_EVENT_SOURCE_LAST_MOVE_PP:
                if (input->event != POKEMON_HANDLER_EVENT_FAINT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_EAT_FIXED_HEAL_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_HEAL_FIXED_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_TRY_HEAL_BERRY_GATE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_EAT_ITEM ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_BOOST_PINCH_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_BOOST_RANDOM_ELIGIBLE_HOLDER_STAT:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_EAT_STATUS_CURE_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_UPDATE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_CURE_STATUS_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_EAT_VOLATILE_CURE_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_UPDATE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_CURE_VOLATILE_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_EAT_HELD_BERRY:
                if ((input->event != POKEMON_HANDLER_EVENT_AFTER_SET_STATUS &&
                     input->event != POKEMON_HANDLER_EVENT_UPDATE) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_ZERO_MOVE_PP:
                if (input->event != POKEMON_HANDLER_EVENT_UPDATE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_RESTORE_FIRST_HOLDER_MOVE_PP:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument == 0 || op->argument > UINT8_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DEDUCT_TARGET_LAST_MOVE_PP_UNIFORM: {
                uint32_t label = (op->argument >> 24) & UINT32_C(0xff);
                uint32_t minimum = (op->argument >> 16) & UINT32_C(0xff);
                uint32_t maximum = (op->argument >> 8) & UINT32_C(0xff);
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    label == 0 || label >= POKEMON_DRAW_LABEL_COUNT ||
                    minimum >= maximum ||
                    (op->argument & UINT32_C(0xff)) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_draws++;
                break;
            }
            case POKEMON_HANDLER_OP_EAT_CONDITION_CURE_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_UPDATE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_HEAL_FRACTION_BERRY:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_CONFUSE_DISLIKED_FLAVOR:
                if (input->event != POKEMON_HANDLER_EVENT_ITEM_EAT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ITEM) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                possible_condition_traces++;
                break;
            case POKEMON_HANDLER_OP_RETURN_UNDEFINED:
            case POKEMON_HANDLER_OP_RETURN_NULL:
                break;
            case POKEMON_HANDLER_OP_SUPPRESS_ACTIVE_MOVE_PROTOCOL_TARGET:
                if (input->event != POKEMON_HANDLER_EVENT_TRY ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0 || battle->move_frame_depth == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DROP_BOOST_STAT:
            case POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT:
            case POKEMON_HANDLER_OP_ZERO_POSITIVE_BOOST_STAT:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE ||
                    op->argument >= POKEMON_STAT_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DROP_ALL_NEGATIVE_BOOSTS:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_MUTABLE_BOOST_TABLE ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_NEST_EVENT: {
                const PokemonEventSpec *nested = event_spec(
                    battle, (PokemonEventId)op->argument);
                if (nested == NULL || !nested->supported ||
                    (nested->algebra != POKEMON_EVENT_ALGEBRA_VOID_NOTIFICATION &&
                     nested->algebra != POKEMON_EVENT_ALGEBRA_STATE_NOTIFICATION)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_EACH_EVENT:
                if (input->event != POKEMON_HANDLER_EVENT_END ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != POKEMON_HANDLER_EVENT_WEATHER_CHANGE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_PROJECT_HOLDER_WEATHER_FORM:
                if (input->event != POKEMON_HANDLER_EVENT_WEATHER_CHANGE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    weather_form_policy(battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_TRUE:
            case POKEMON_HANDLER_OP_RETURN_FALSE:
            case POKEMON_HANDLER_OP_RETURN_NOT_FAIL:
                if (spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL &&
                    !(spec->algebra ==
                          POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NUMBER &&
                      (op->opcode == POKEMON_HANDLER_OP_RETURN_TRUE ||
                       op->opcode == POKEMON_HANDLER_OP_RETURN_FALSE)) &&
                    !((input->event == POKEMON_HANDLER_EVENT_ACCURACY ||
                        input->event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY) &&
                       op->opcode == POKEMON_HANDLER_OP_RETURN_TRUE)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_NUMBER_ZERO:
                if (op->argument != 0 ||
                    (spec->algebra !=
                         POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NUMBER &&
                     spec->algebra !=
                         POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_DAMAGE_EVENT_TARGET_BY_RELAY_IMMEDIATE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HEAL ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += 2;
                break;
            case POKEMON_HANDLER_OP_RETURN_SOURCE_HP_BELOW_TARGET:
                if (input->event != POKEMON_HANDLER_EVENT_TRY ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_RETALIATION:
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS:
            case POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2:
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    (op->opcode ==
                         POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS &&
                     (op->argument == 0 ||
                      (op->argument &
                       ~(POKEMON_RETALIATION_PHYSICAL |
                         POKEMON_RETALIATION_SPECIAL)) != 0)) ||
                    (op->opcode ==
                         POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2 &&
                     op->argument != 0)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_REQUIRE_OWNER_RETALIATION_CAPTURE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 ||
                    condition_rule_by_descriptor(
                        battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_STORED_DAMAGE:
                if (input->event != POKEMON_HANDLER_EVENT_START ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE:
                if ((input->event != POKEMON_HANDLER_EVENT_DAMAGE &&
                     input->event != POKEMON_HANDLER_EVENT_FAINT) ||
                    (input->event == POKEMON_HANDLER_EVENT_DAMAGE &&
                     input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_ACCUMULATE_OWNER_STORED_DAMAGE:
                if (input->event != POKEMON_HANDLER_EVENT_DAMAGE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_DAMAGE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT:
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    find_constructed_hit_template(
                        battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR:
                if (input->event != POKEMON_HANDLER_EVENT_LOCK_MOVE ||
                    spec->algebra !=
                        POKEMON_EVENT_ALGEBRA_SELECTOR_REPLACEMENT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CLAIM_QUEUED_SELECTED_MOVE:
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL: {
                const PokemonMoveCallPool *pool = find_move_call_pool(
                    battle, (uint16_t)op->argument);
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    pool == NULL || pool->caller_move_id != descriptor->source_id ||
                    input->context.move.move->id != pool->caller_move_id) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_FIXED_MOVE:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    find_move(battle, (uint16_t)op->argument) == NULL ||
                    input->context.move.move->id != descriptor->source_id) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_USER_SLOTS:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 ||
                    (op->argument & (op->argument - 1u)) != 0 ||
                    (op->argument &
                        ~POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_PARTY_SLOTS:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != POKEMON_MOVE_CALL_ELIGIBLE_ASSIST) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT: {
                uint32_t eligibility = op->argument & UINT32_C(0xff);
                uint32_t known = UINT32_C(0xff) |
                    POKEMON_MOVE_COPY_PERSIST_BASE | UINT32_C(0xff0000);
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->target_side >= POKEMON_SIDES ||
                    input->target_slot >=
                        battle->team_sizes[input->target_side] ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->context.move.move->id != descriptor->source_id ||
                    eligibility == 0 ||
                    (eligibility & (eligibility - 1u)) != 0 ||
                    (eligibility & ~(POKEMON_MOVE_COPY_ELIGIBLE_MIMIC |
                        POKEMON_MOVE_COPY_ELIGIBLE_SKETCH)) != 0 ||
                    (op->argument & ~known) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BATTLE_PROFILE:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->target_side >= POKEMON_SIDES ||
                    input->target_slot >= battle->team_sizes[input->target_side] ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->context.move.move->id != descriptor->source_id ||
                    transform_policy(battle->data, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_TARGET_STATUS_MASK: {
                const uint32_t valid =
                    ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                    ~UINT32_C(1);
                if ((input->event != POKEMON_HANDLER_EVENT_BASE_POWER &&
                     input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK) ||
                    (input->event == POKEMON_HANDLER_EVENT_BASE_POWER &&
                     spec->algebra != POKEMON_EVENT_ALGEBRA_NUMERIC_OR_CANCEL) ||
                    (input->event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK &&
                     spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 || (op->argument & ~valid) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_TARGET_MAJOR_STATUS:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                possible_effect_traces++;
                break;
            case POKEMON_HANDLER_OP_PAY_MAX_HP_FRACTION_AND_MAXIMIZE_HOLDER_STAT: {
                uint8_t stat = (uint8_t)(op->argument >> 16);
                uint8_t numerator = (uint8_t)(op->argument >> 8);
                uint8_t denominator = (uint8_t)op->argument;
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    stat >= POKEMON_STAT_COUNT || numerator == 0 ||
                    denominator == 0 || numerator >= denominator) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                possible_effect_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_FAINT_HOLDER:
                if (input->event != POKEMON_HANDLER_EVENT_END ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0 ||
                    owner_volatile(battle, &discovered[i]) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_APPLY_VOLATILE_TO_ADMITTED_ACTIVES: {
                uint16_t descriptor_id = battle->generation->condition_descriptor(
                    POKEMON_OWNER_VOLATILE, (uint16_t)op->argument);
                const PokemonConditionRule *rule = condition_rule_by_descriptor(
                    battle, descriptor_id);
                if (input->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_FIELD ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > POKEMON_VOLATILE_COUNTDOWN_FAINT ||
                    descriptor_id == 0 || rule == NULL ||
                    rule->lifecycle_duration.kind ==
                        POKEMON_CONDITION_DURATION_NONE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events += POKEMON_SIDES;
                possible_condition_traces += POKEMON_SIDES;
                break;
            }
            case POKEMON_HANDLER_OP_ENSURE_HOLDER_VOLATILE: {
                uint16_t condition_descriptor =
                    battle->generation->condition_descriptor(
                        POKEMON_OWNER_VOLATILE, (uint16_t)op->argument);
                if (input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > UINT16_MAX || condition_descriptor == 0 ||
                    condition_rule_by_descriptor(
                        battle, condition_descriptor) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_condition_traces++;
                break;
            }
            case POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER:
                if ((input->event != POKEMON_HANDLER_EVENT_START &&
                     input->event != POKEMON_HANDLER_EVENT_HIT) ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument == 0 || op->argument > UINT8_MAX ||
                    owner_volatile(battle, &discovered[i]) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_ADVANCE_OWNER_VOLATILE_COUNTER: {
                uint32_t multiplier = op->argument >> 16;
                uint32_t cap = op->argument & UINT32_C(0xffff);
                const PokemonVolatileState *owner =
                    owner_volatile(battle, &discovered[i]);
                const PokemonConditionRule *owner_rule = owner == NULL ? NULL :
                    condition_rule_by_descriptor(battle, owner->descriptor_id);
                if (input->event != POKEMON_HANDLER_EVENT_RESTART ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    multiplier < 2 || multiplier > UINT8_MAX || cap == 0 ||
                    cap > UINT8_MAX || owner == NULL || owner->counter == 0 ||
                    owner_rule == NULL || owner_rule->lifecycle_duration.kind !=
                        POKEMON_CONDITION_DURATION_FIXED) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_INCREMENT_OWNER_VOLATILE_COUNTER_UP_TO: {
                const PokemonVolatileState *owner =
                    owner_volatile(battle, &discovered[i]);
                if (input->event != POKEMON_HANDLER_EVENT_RESTART ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument == 0 || op->argument > UINT8_MAX ||
                    owner == NULL || owner->counter == 0 ||
                    owner->counter > op->argument) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_MULTIPLY_RELAY_BY_HOLDER_VOLATILE_COUNTER:
                if (input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == POKEMON_VOLATILE_NONE ||
                    op->argument > UINT16_MAX) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32:
                if (!valid_direct_u32_relay_multiplier(descriptor, op) ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN: {
                const PokemonActiveMoveFrame *active =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (!valid_attacked_by_target_guard(descriptor, op) ||
                    input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    active == NULL ||
                    input->context.move.move->id != descriptor->source_id ||
                    active->invocation.move_id != descriptor->source_id ||
                    active->invocation.user.kind != POKEMON_ENTITY_POKEMON ||
                    active->invocation.user.side != discovered[i].holder_side ||
                    active->invocation.user.slot != discovered[i].holder_slot ||
                    active->resolved_target.kind != POKEMON_ENTITY_POKEMON) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_COUNTER_AT_LEAST:
            case POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE: {
                uint32_t kind = op->argument >> 16;
                uint32_t threshold = op->argument & UINT32_C(0xffff);
                if (input->event != POKEMON_HANDLER_EVENT_TRY ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    kind == POKEMON_VOLATILE_NONE ||
                    kind >= POKEMON_VOLATILE_KIND_COUNT ||
                    (op->opcode ==
                         POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_COUNTER_AT_LEAST &&
                     (threshold == 0 || threshold > UINT8_MAX)) ||
                    (op->opcode ==
                         POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE &&
                     threshold != 0)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_MASK:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 || (op->argument & UINT32_C(1)) != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_HOLDER_VOLATILE_COUNTER_TIMES: {
                uint32_t kind = op->argument >> 16;
                uint32_t scale = op->argument & UINT32_C(0xffff);
                if (input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
                    input->relay.kind != POKEMON_RELAY_U32 ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    kind == POKEMON_VOLATILE_NONE ||
                    kind >= POKEMON_VOLATILE_KIND_COUNT || scale == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_HOLDER_BY_COUNTER_POLICY:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 || op->argument > UINT16_MAX ||
                    counter_heal_policy(battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                possible_events++;
                break;
            case POKEMON_HANDLER_OP_SAMPLE_SOURCE_TYPE_RESPONSE:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->target_side >= POKEMON_SIDES ||
                    input->target_slot >= battle->team_sizes[input->target_side] ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 || op->argument > UINT16_MAX ||
                    type_response_policy(battle, (uint16_t)op->argument) == NULL) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
			case POKEMON_HANDLER_OP_INSTALL_LOCKED_RAMP_IF_TARGET_AWAKE: {
				const PokemonLockedRampPolicy *policy =
					locked_ramp_policy(battle, (uint16_t)op->argument);
				if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
					input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
					input->context.move.move == NULL || policy == NULL ||
					input->context.move.move->id != policy->move_id ||
					input->source.kind != POKEMON_ENTITY_POKEMON ||
					input->target_side >= POKEMON_SIDES ||
					input->target_slot >= battle->team_sizes[input->target_side] ||
					battle->sides[input->target_side].state[
						input->target_slot].hp == 0 ||
					descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
					descriptor->source_id != policy->move_id ||
					discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
					descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
					descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				possible_condition_traces++;
				break;
			}
			case POKEMON_HANDLER_OP_APPLY_LOCKED_RAMP_BASE_POWER: {
				const PokemonLockedRampPolicy *policy =
					locked_ramp_policy(battle, (uint16_t)op->argument);
				if (input->event != POKEMON_HANDLER_EVENT_BASE_POWER ||
					input->relay.kind != POKEMON_RELAY_U32 ||
					policy == NULL || input->context_kind !=
						POKEMON_EVENT_CONTEXT_MOVE ||
					input->context.move.move == NULL ||
					input->context.move.move->id != policy->move_id ||
					descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
					descriptor->source_id != policy->move_id ||
					discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
					descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
					descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				possible_condition_traces++;
				break;
			}
			case POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK:
				if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
					descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
					discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
					descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
					descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
					op->argument != 0 || owner_volatile(
						battle, &discovered[i]) == NULL) {
					return POKEMON_INVALID_CONFIGURATION;
				}
				break;
            case POKEMON_HANDLER_OP_REQUIRE_ACTIVE_FOE_SHARES_HOLDER_MOVE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_APPEND_HOLDER_MOVES_TO_EVENT_RESTRICTIONS: {
                if (input->event != POKEMON_HANDLER_EVENT_DISABLE_MOVE ||
                    input->context_kind !=
                        POKEMON_EVENT_CONTEXT_MOVE_RESTRICTIONS ||
                    input->context.move_restrictions == NULL ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_FOE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                size_t additions = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    uint16_t move_id = current_move_id(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, slot);
                    additions += move_id != 0 &&
                        move_id != battle->generation->fallback_move_id;
                }
                PokemonMoveRestrictionBuffer *restrictions =
                    input->context.move_restrictions;
                if (additions > restrictions->capacity - restrictions->count) {
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REJECT_EVENT_MOVE_SHARED_WITH_HOLDER:
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    input->relay.kind != POKEMON_RELAY_BOOLEAN ||
                    descriptor->source_kind !=
                        POKEMON_HANDLER_SOURCE_CONDITION ||
                    discovered[i].owner.kind != POKEMON_OWNER_VOLATILE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_FOE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument != 0) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_SELECT_ACTIVE_MOVE_PROFILE_BY_USER_TYPE: {
                const PokemonMoveProfileSelection *selection =
                    find_move_profile_selection(battle->data,
                        (uint16_t)op->argument);
                const PokemonMoveInvocationProfile *matching = selection == NULL ?
                    NULL : find_move_invocation_profile(
                        battle->data, selection->matching_profile_id);
                const PokemonMoveInvocationProfile *nonmatching =
                    selection == NULL ? NULL : find_move_invocation_profile(
                        battle->data, selection->nonmatching_profile_id);
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    battle->move_frame_depth == 0 || selection == NULL ||
                    matching == NULL || nonmatching == NULL ||
                    matching->owner_move_id != descriptor->source_id ||
                    nonmatching->owner_move_id != descriptor->source_id) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_PROFILE_TAG:
                if ((input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE &&
                     input->event != POKEMON_HANDLER_EVENT_TRY_HIT) ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    battle->move_frame_depth == 0 || op->argument == 0 ||
                    op->argument > UINT16_MAX) return POKEMON_INVALID_CONFIGURATION;
                break;
            case POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_EFFECTS_IF_TARGET_VOLATILE:
                if (input->event != POKEMON_HANDLER_EVENT_MODIFY_MOVE ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    battle->move_frame_depth == 0 ||
                    input->target_side >= POKEMON_SIDES ||
                    input->target_slot >=
                        battle->team_sizes[input->target_side] ||
                    op->argument <= POKEMON_VOLATILE_NONE ||
                    op->argument >= POKEMON_VOLATILE_KIND_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_EVENT_TARGET_VOLATILE:
                if (input->event != POKEMON_HANDLER_EVENT_TRY_HIT ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->target_side >= POKEMON_SIDES ||
                    input->target_slot >=
                        battle->team_sizes[input->target_side] ||
                    op->argument <= POKEMON_VOLATILE_NONE ||
                    op->argument >= POKEMON_VOLATILE_KIND_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_HOLDER_BOOLEAN_FROM_BATTLE_STARTED:
                if (input->event != POKEMON_HANDLER_EVENT_SWITCH_IN ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument <= POKEMON_BOOLEAN_STATE_NONE ||
                    op->argument >= POKEMON_BOOLEAN_STATE_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_BOOLEAN:
                if (input->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument <= POKEMON_BOOLEAN_STATE_NONE ||
                    op->argument >= POKEMON_BOOLEAN_STATE_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_TOGGLE_HOLDER_BOOLEAN:
                if (input->event != POKEMON_HANDLER_EVENT_RESIDUAL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_ABILITY ||
                    discovered[i].owner.kind != POKEMON_OWNER_ABILITY ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
                    op->argument <= POKEMON_BOOLEAN_STATE_NONE ||
                    op->argument >= POKEMON_BOOLEAN_STATE_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            case POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE:
                if (input->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    spec->algebra != POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL ||
                    descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    discovered[i].owner.kind != POKEMON_OWNER_MOVE ||
                    descriptor->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->source.side >= POKEMON_SIDES ||
                    input->source.slot >=
                        battle->team_sizes[input->source.side] ||
                    (input->source.side == input->target_side &&
                     input->source.slot == input->target_slot) ||
                    battle->sides[input->source.side].state[
                        input->source.slot].hp == 0 ||
                    battle->sides[input->target_side].state[
                        input->target_slot].hp == 0 ||
                    op->argument != 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            default:
                return POKEMON_INVALID_CONFIGURATION;
            }
        }
    }
    if ((size_t)battle->event_count + possible_events > POKEMON_EVENT_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    if ((size_t)battle->condition_trace_count + possible_condition_traces >
        POKEMON_CONDITION_TRACE_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
    if ((size_t)battle->effect_trace_count + possible_effect_traces >
        POKEMON_EFFECT_TRACE_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
    uint8_t traces_modifiers = uses_modifiers && count != 0 &&
        input->relay.kind != POKEMON_RELAY_BOOLEAN;
    size_t modifier_trace_count = 0;
    size_t handler_trace_count = 0;
    for (size_t i = 0; i < count; i++) {
        if (traces_modifiers &&
            discovered[i].descriptor.exceptional_handler_id == 0) {
            modifier_trace_count++;
        } else {
            handler_trace_count++;
        }
    }
    if ((size_t)battle->modifier_count + modifier_trace_count >
            POKEMON_MODIFIER_CAPACITY ||
        (modifier_trace_count != 0 &&
         battle->relay_result_count == POKEMON_RELAY_RESULT_CAPACITY)) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    if (!input->suppress_handler_trace &&
        (size_t)battle->handler_count + handler_trace_count >
            POKEMON_HANDLER_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    size_t order_draws = spec->ordering == POKEMON_EVENT_ORDER_ORDINARY ?
        event_handler_order_draw_count(discovered, count) : 0;
    if ((size_t)battle->draw_count + order_draws + possible_draws >
        POKEMON_DRAW_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
    if (spec->ordering == POKEMON_EVENT_ORDER_ORDINARY) {
        status = order_event_handlers(battle, input->event, discovered, count);
        if (status != POKEMON_OK) return status;
        if (input->event == POKEMON_HANDLER_EVENT_SET_STATUS) {
            for (size_t i = battle->draw_count - order_draws;
                 i < battle->draw_count; i++) {
                battle->draws[i].semantic_sequence =
                    next_semantic_sequence(battle);
            }
        }
    } else if (spec->ordering == POKEMON_EVENT_ORDER_LEFT_TO_RIGHT) {
        order_left_to_right_handlers(discovered, count);
    }
    PokemonEventFrame frame = {
        .event = input->event, .algebra = spec->algebra,
        .depth = battle->event_depth, .relay = input->relay,
        .modifier_q12 = 4096,
        .source = input->source,
        .target = {POKEMON_ENTITY_POKEMON, input->target_side,
            input->target_slot},
        .source_effect = input->source_effect,
        .cancellation_emits_immunity = 1,
    };
    if (!input->suppress_trace) {
        battle->event_frames[battle->event_depth] = frame;
    }
    battle->event_depth++;
    size_t modifier_start = battle->modifier_count;
    size_t handler_start = battle->handler_count;
    double event_relay_input = input->relay.kind == POKEMON_RELAY_U32 ?
        input->relay.value.u32 : input->relay.kind == POKEMON_RELAY_NUMBER ?
            input->relay.value.number : 0;
    uint8_t direct_relay_mutated = 0;
    size_t handler_trace_index[POKEMON_HANDLER_CAPACITY];
    for (size_t i = 0; i < count; i++) {
        handler_trace_index[i] = SIZE_MAX;
        if (!input->suppress_handler_trace &&
            (!traces_modifiers ||
             discovered[i].descriptor.exceptional_handler_id != 0)) {
            handler_trace_index[i] = battle->handler_count;
            battle->handlers[battle->handler_count++] = (PokemonHandlerInvocation){
                .handler = discovered[i],
                .semantic_sequence = next_semantic_sequence(battle),
                .result = POKEMON_HANDLER_CONTINUE,
            };
        }
    }
    const PokemonMutable *holder =
        &battle->sides[input->target_side].state[input->target_slot];
    for (size_t i = 0; i < count && frame.cancellation == POKEMON_EVENT_CANCEL_NONE; i++) {
        const PokemonHandlerDescriptor *descriptor = &discovered[i].descriptor;
        uint32_t handler_modifier = 4096;
        double handler_input = frame.relay.kind == POKEMON_RELAY_U32 ?
            frame.relay.value.u32 : frame.relay.kind == POKEMON_RELAY_NUMBER ?
                frame.relay.value.number : frame.relay.kind == POKEMON_RELAY_BOOLEAN ?
                    frame.relay.value.boolean : 0;
        uint8_t suppressed = discovered[i].owner.kind == POKEMON_OWNER_FIELD &&
            battle->field.weather.kind != POKEMON_WEATHER_NONE &&
            descriptor->source_id == battle->field.weather.descriptor_id &&
            effective_weather(battle) == POKEMON_WEATHER_NONE;
        uint8_t applicable = !suppressed;
        uint8_t guarded_negative_boost_mask = 0;
        uint8_t removed_owner_volatile_present = 0;
        PokemonVolatileState removed_owner_volatile = {0};
        PokemonHandlerResult legacy_result = POKEMON_HANDLER_CONTINUE;
        if (descriptor->exceptional_handler_id != 0) {
            status = run_exceptional_handler(
                battle, input, &discovered[i], &frame, &legacy_result);
            if (status != POKEMON_OK) {
                battle->event_depth--;
                return status;
            }
            if (handler_trace_index[i] != SIZE_MAX) {
                battle->handlers[handler_trace_index[i]].invoked = 1;
                battle->handlers[handler_trace_index[i]].result = legacy_result;
            }
            continue;
        }
        for (size_t op_index = 0; op_index < descriptor->program_count; op_index++) {
            const PokemonHandlerOp *op = &battle->data->handler_programs[
                descriptor->program_offset + op_index];
            if (!applicable) break;
            switch (op->opcode) {
            case POKEMON_HANDLER_OP_SET_OWNER_ENDING:
                battle->sides[discovered[i].holder_side].state[
                    discovered[i].holder_slot].ability_ending =
                        (uint8_t)op->argument;
                break;
            case POKEMON_HANDLER_OP_SET_WEATHER:
                status = set_weather_from_lifecycle(
                    battle, (PokemonWeatherKind)op->argument,
                    discovered[i].holder_side, discovered[i].holder_slot);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            case POKEMON_HANDLER_OP_BOOST_OPPOSING_ACTIVES_EXCEPT_VOLATILE: {
                uint16_t excluded = (uint16_t)(op->argument >> 16);
                uint8_t stat = (uint8_t)(op->argument >> 8);
                int8_t delta = (int8_t)(op->argument & UINT32_C(0xff));
                for (size_t target_side = 0; target_side < POKEMON_SIDES;
                     target_side++) {
                    if (target_side == discovered[i].holder_side) continue;
                    size_t target_slot = battle->sides[target_side].active;
                    PokemonMutable *target = &battle->sides[target_side].state[
                        target_slot];
                    if (target->hp == 0 || volatile_index(
                            target, (PokemonVolatileKind)excluded) >= 0) continue;
                    status = apply_directed_boost(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot,
                        (uint8_t)target_side, (uint8_t)target_slot,
                        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                            descriptor->source_id}, stat, delta);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_SLEEP_UNIFORM: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonDrawLabel label = (PokemonDrawLabel)(op->argument >> 24);
                uint8_t minimum = (uint8_t)(op->argument >> 16);
                uint8_t maximum_exclusive = (uint8_t)(op->argument >> 8);
                uint32_t sampled = 0;
                status = draw_below(
                    battle, label, (uint32_t)(maximum_exclusive - minimum),
                    &sampled);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                mutable_holder->status.state.sleep.time =
                    (uint8_t)(minimum + sampled);
                mutable_holder->status.state.sleep.skipped_time = 0;
                break;
            }
            case POKEMON_HANDLER_OP_REPLACE_HOLDER_ABILITY_FROM_TARGET:
                status = replace_holder_ability_from_target(
                    battle, discovered[i].owner,
                    (PokemonHandlerTargetSelector)op->argument);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_STATUS_PRESENT:
                applicable = holder->status.kind != POKEMON_STATUS_NONE;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ALIVE:
                applicable = holder->hp != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ACTIVE_TURNS:
                applicable = holder->active_turns != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_ANY_LIVING_ACTIVE_ABILITY:
                applicable = 0;
                for (size_t active_side = 0; active_side < POKEMON_SIDES;
                     active_side++) {
                    size_t active_slot = battle->sides[active_side].active;
                    const PokemonMutable *active = &battle->sides[active_side]
                        .state[active_slot];
                    if (active->hp != 0 && !active->fainted &&
                        !active->ability_ending &&
                        active->ability_id == (uint16_t)op->argument) {
                        applicable = 1;
                        break;
                    }
                }
                break;
            case POKEMON_HANDLER_OP_BOOST_HOLDER_STAT: {
                uint8_t stat = (uint8_t)(op->argument >> 8);
                int8_t delta = (int8_t)(op->argument & UINT32_C(0xff));
                PokemonSourceEffectKind effect_kind =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_CONDITION ?
                        POKEMON_SOURCE_EFFECT_CONDITION :
                        POKEMON_SOURCE_EFFECT_ABILITY;
                status = apply_owner_boost(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot,
                    (PokemonSourceEffectRef){effect_kind, descriptor->source_id},
                    stat, delta);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_DAMAGE_HOLDER_BASE_MAX_HP_FRACTION: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t numerator = (uint8_t)(op->argument >> 16);
                uint8_t denominator =
                    (uint8_t)(op->argument & UINT32_C(0xffff));
                uint16_t amount = battle->generation->fraction(
                    battle->sides[discovered[i].holder_side].sets[
                        discovered[i].holder_slot].stats[0],
                    numerator, denominator);
                if (amount == 0) amount = 1;
                status = residual_damage(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, amount,
                    POKEMON_CONDITION_SCOPE_VOLATILE,
                    condition->kind);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_TRANSFER_HOLDER_MAX_HP_FRACTION_TO_SOURCE_POSITION: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL ||
                    condition->source.kind != POKEMON_ENTITY_POKEMON ||
                    condition->source.side >= POKEMON_SIDES) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                /* source.slot is immutable roster identity. The current
                 * singles position is side + position zero, whose occupant
                 * is resolved here at execution time. */
                size_t recipient_side = condition->source.side;
                size_t recipient_slot = battle->sides[recipient_side].active;
                PokemonMutable *recipient = &battle->sides[recipient_side].state[
                    recipient_slot];
                if (recipient->hp == 0 || recipient->fainted) break;
                uint8_t numerator = (uint8_t)(op->argument >> 16);
                uint8_t denominator =
                    (uint8_t)(op->argument & UINT32_C(0xffff));
                uint16_t requested = battle->generation->fraction(
                    battle->sides[discovered[i].holder_side].sets[
                        discovered[i].holder_slot].stats[0],
                    numerator, denominator);
                if (requested == 0) requested = 1;
                uint16_t actual_damage = 0;
                status = residual_damage_deferred(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, requested,
                    POKEMON_CONDITION_SCOPE_VOLATILE, condition->kind,
                    &actual_damage);
                if (status == POKEMON_OK && actual_damage != 0) {
                    PokemonEffectResult heal_result;
                    uint16_t actual_heal = 0;
                    status = try_amount_heal(
                        battle,
                        (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                            discovered[i].holder_side,
                            discovered[i].holder_slot},
                        (PokemonSourceEffectRef){
                            POKEMON_SOURCE_EFFECT_CONDITION,
                            condition->descriptor_id},
                        recipient_side, recipient_slot, actual_damage,
                        &heal_result, &actual_heal);
                }
                if (status == POKEMON_OK) status = drain_faints(battle);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_MASK: {
                PokemonStatus holder_status = battle->sides[
                    discovered[i].holder_side].state[
                        discovered[i].holder_slot].status.kind;
                applicable = holder_status != POKEMON_STATUS_NONE &&
                    holder_status < 32 &&
                    (op->argument & (UINT32_C(1) << holder_status)) != 0;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_STATUS_NOT_MASK: {
                PokemonStatus holder_status = battle->sides[
                    discovered[i].holder_side].state[
                        discovered[i].holder_slot].status.kind;
                applicable = holder_status == POKEMON_STATUS_NONE ||
                    holder_status >= 32 ||
                    (op->argument & (UINT32_C(1) << holder_status)) == 0;
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_HOLDER_STATUS_MASK: {
                PokemonStatus holder_status = battle->sides[
                    discovered[i].holder_side].state[
                        discovered[i].holder_slot].status.kind;
                if (holder_status == POKEMON_STATUS_NONE ||
                    holder_status >= 32 ||
                    (op->argument & (UINT32_C(1) << holder_status)) == 0) {
                    if (spec->algebra ==
                            POKEMON_EVENT_ALGEBRA_BOOLEAN_OR_NULL) {
                        frame.relay = (PokemonRelay){
                            .kind = POKEMON_RELAY_BOOLEAN,
                            .value.boolean = 0};
                    }
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_TYPE:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move->type == op->argument;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_OHKO:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move != NULL &&
                    input->context.move.move->ohko.kind != POKEMON_OHKO_NONE;
                break;
            case POKEMON_HANDLER_OP_GUARD_BASE_MOVE_TYPE: {
                const PokemonMoveData *base_move = find_move(
                    battle, input->context.move.move->id);
                if (base_move == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                applicable = base_move->type == op->argument;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_DEFROST:
                applicable = input->context.move.move->defrost != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_TYPE_MASK:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move->type < 32 &&
                    (op->argument & (UINT32_C(1) <<
                        input->context.move.move->type)) != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_SPECIES_PAIR: {
                uint16_t species_id = battle->sides[discovered[i].holder_side].sets[
                    discovered[i].holder_slot].species_id;
                applicable = species_id == (uint16_t)(op->argument & UINT32_C(0xffff)) ||
                    species_id == (uint16_t)(op->argument >> 16);
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_VOLATILE &&
                    input->context.volatile_condition.kind == op->argument;
                break;
            case POKEMON_HANDLER_OP_GUARD_VOLATILE_KIND_MASK:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_VOLATILE &&
                    input->context.volatile_condition.kind < 32 &&
                    (op->argument & (UINT32_C(1) <<
                        input->context.volatile_condition.kind)) != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_MODIFIER_TAG:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move != NULL &&
                    (input->context.move.move->modifier_tags &
                        (UINT64_C(1) << op->argument)) != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_TAGGED_STATUS_MOVE_TARGET_ELIGIBLE: {
                const PokemonMoveData *move = input->context.move.move;
                uint16_t tag = (uint16_t)(op->argument >> 16);
                if ((move->modifier_tags & (UINT64_C(1) << tag)) == 0) break;
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint8_t excluded_type =
                    (uint8_t)(op->argument & UINT32_C(0xffff));
                applicable = holder->status.kind == POKEMON_STATUS_NONE &&
                    !has_type(holder, excluded_type) &&
                    volatile_index(holder, POKEMON_VOLATILE_SUBSTITUTE) < 0;
                break;
            }
            case POKEMON_HANDLER_OP_APPEND_ACTIVE_MOVE_VOLATILE_SECONDARY: {
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (active->appended_secondary_count ==
                    POKEMON_ACTIVE_SECONDARY_CAPACITY) {
                    battle->event_depth--;
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                active->appended_secondaries[active->appended_secondary_count++] =
                    (PokemonEffectOp){
                        .kind = POKEMON_EFFECT_ADD_VOLATILE,
                        .phase = POKEMON_EFFECT_PHASE_AFTER_HIT,
                        .target = POKEMON_EFFECT_TARGET_MOVE_TARGET,
                        .chance = (uint8_t)(op->argument >> 16),
                        .argument = (uint16_t)(op->argument & UINT32_C(0xffff)),
                    };
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_HOLDER_FROM_MOVE_DAMAGE_FRACTION: {
                const PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                uint8_t numerator = (uint8_t)(op->argument >> 16);
                uint8_t denominator =
                    (uint8_t)(op->argument & UINT32_C(0xffff));
                if (active->actual_damage == 0) break;
                uint32_t scaled = (uint32_t)active->actual_damage * numerator;
                uint16_t requested = (uint16_t)(scaled / denominator);
                if (requested == 0) requested = 1;
                PokemonEffectResult heal_result;
                uint16_t amount = 0;
                PokemonSourceEffectKind effect_kind =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_ITEM ?
                        POKEMON_SOURCE_EFFECT_ITEM :
                        POKEMON_SOURCE_EFFECT_ABILITY;
                status = try_amount_heal(
                    battle, input->source,
                    (PokemonSourceEffectRef){effect_kind,
                        descriptor->source_id},
                    discovered[i].holder_side, discovered[i].holder_slot,
                    requested, &heal_result, &amount);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ACTIVE: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                applicable = condition != NULL &&
                    entity_is_living_active(battle, condition->source);
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_ABILITY_ACTIVE: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                applicable = condition != NULL &&
                    condition->source_effect.kind ==
                        POKEMON_SOURCE_EFFECT_ABILITY &&
                    condition->source_effect.id == holder->ability_id;
                break;
            }
            case POKEMON_HANDLER_OP_DISALLOW_TARGET_SWITCHES:
                if (input->context_kind !=
                        POKEMON_EVENT_CONTEXT_SWITCH_RESTRICTIONS ||
                    input->context.switch_restrictions == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                status = pokemon_append_switch_restriction(
                    input->context.switch_restrictions,
                    (PokemonSwitchRestriction){
                        .kind = POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL,
                        .hidden = (uint8_t)op->argument,
                    });
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            case POKEMON_HANDLER_OP_SOURCE_BOUND_MAX_HP_DAMAGE: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (!entity_is_living_active(battle, condition->source)) {
                    uint8_t before = condition->duration;
                    PokemonVolatileKind condition_kind = condition->kind;
                    size_t condition_index = (size_t)(condition -
                        mutable_holder->volatiles);
                    remove_volatile_at(mutable_holder, condition_index);
                    status = trace_condition(
                        battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                        POKEMON_CONDITION_REMOVE,
                        POKEMON_CONDITION_REASON_HANDLER,
                        POKEMON_CONDITION_VALUE_DURATION,
                        discovered[i].holder_side,
                        discovered[i].holder_slot, condition_kind, before, 0);
                } else {
                    uint8_t numerator = (uint8_t)(op->argument >> 16);
                    uint16_t denominator =
                        (uint16_t)(op->argument & UINT32_C(0xffff));
                    uint16_t amount = battle->generation->fraction(
                        battle->sides[discovered[i].holder_side].sets[
                            discovered[i].holder_slot].stats[0],
                        numerator, (uint8_t)denominator);
                    if (amount == 0) amount = 1;
                    status = residual_damage(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, amount,
                        POKEMON_CONDITION_SCOPE_VOLATILE, condition->kind);
                }
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                applicable = 0;
                break;
            }
            case POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_TYPE:
                battle->move_frames[battle->move_frame_depth - 1].type =
                    (uint8_t)op->argument;
                break;
            case POKEMON_HANDLER_OP_SET_ACTIVE_MOVE_CATEGORY:
                battle->move_frames[battle->move_frame_depth - 1].category =
                    (PokemonCategory)op->argument;
                break;
            case POKEMON_HANDLER_OP_SNAPSHOT_ACTIVE_MOVE_PARTY_HITS: {
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                uint8_t side = active->invocation.user.side;
                active->party_hit_count = 0;
                active->party_hit_cursor = 0;
                active->party_hit_plan_active = 1;
                for (size_t position = 0; position < battle->team_sizes[side];
                     position++) {
                    uint8_t slot = battle->sides[side].party_order[position];
                    const PokemonMutable *candidate =
                        &battle->sides[side].state[slot];
                    if (candidate->hp != 0 &&
                        candidate->status.kind == POKEMON_STATUS_NONE) {
                        active->party_hit_slots[active->party_hit_count++] = slot;
                    }
                }
                active->multihit_min = active->party_hit_count;
                active->multihit_max = active->party_hit_count;
                break;
            }
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_NEXT_PARTY_HIT_BASE_STAT: {
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (active->party_hit_cursor >= active->party_hit_count) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t side = active->invocation.user.side;
                uint8_t slot = active->party_hit_slots[active->party_hit_cursor++];
                const PokemonSpeciesIdentity *species =
                    species_identity_by_executable_id(
                        battle->data, battle->sides[side].sets[slot].species_id);
                if (species == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 = species->base_stats[1];
                frame.modifier_q12 = 4096;
                /* This models a callback return value, not chainModify().
                 * Showdown's relay-result input is therefore the returned
                 * base stat, while the handler trace retains the old relay. */
                break;
            }
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_EVENT_TARGET_BASE_SPECIES_STAT: {
                const PokemonSpeciesIdentity *species =
                    species_identity_by_executable_id(battle->data,
                        battle->sides[input->target_side].sets[
                            input->target_slot].species_id);
                if (species == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 = species->base_stats[2];
                frame.modifier_q12 = 4096;
                /* As above, the descriptor replaces the relay by returning
                 * a value; it does not modify the event multiplier. */
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_NO_ACTIVE_PARTY_HITS:
                if (battle->move_frames[battle->move_frame_depth - 1]
                        .party_hit_count == 0) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NULL};
                    frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            case POKEMON_HANDLER_OP_APPLY_ACTIVE_MOVE_PERSONAL_PROFILE: {
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                PokemonEntityRef user = active->invocation.user;
                if (user.kind != POKEMON_ENTITY_POKEMON ||
                    user.side >= POKEMON_SIDES ||
                    user.slot >= battle->team_sizes[user.side]) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonPersonalMoveProfile *profile =
                    &battle->sides[user.side].state[user.slot]
                        .personal_move_profile;
                if (profile->kind != (uint16_t)op->argument ||
                    profile->type >= battle->data->type_count ||
                    profile->category < POKEMON_CATEGORY_PHYSICAL ||
                    profile->category > POKEMON_CATEGORY_SPECIAL ||
                    profile->power == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                active->type = profile->type;
                active->category = profile->category;
                break;
            }
            case POKEMON_HANDLER_OP_SAMPLE_ACTIVE_MOVE_OUTCOME_WEIGHTED: {
                const PokemonWeightedMoveOutcomeDistribution *distribution =
                    weighted_move_distribution(
                        battle, (uint16_t)op->argument);
                if (distribution == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint32_t total = 0;
                for (size_t outcome = 0;
                     outcome < distribution->outcome_count; outcome++) {
                    total += battle->data->weighted_move_outcomes[
                        distribution->outcome_offset + outcome].weight;
                }
                uint32_t sampled = 0;
                status = draw_below(battle,
                    (PokemonDrawLabel)distribution->draw_label, total, &sampled);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                uint32_t cumulative = 0;
                const PokemonWeightedMoveOutcome *selected = NULL;
                for (size_t outcome = 0;
                     outcome < distribution->outcome_count; outcome++) {
                    const PokemonWeightedMoveOutcome *candidate =
                        &battle->data->weighted_move_outcomes[
                            distribution->outcome_offset + outcome];
                    cumulative += candidate->weight;
                    if (sampled < cumulative) { selected = candidate; break; }
                }
                if (selected == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                active->weighted_outcome_kind = (uint8_t)selected->kind;
                if (selected->kind == POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE) {
                    active->base_power = selected->value.damage.power;
                    active->message_value =
                        selected->value.damage.message_value;
                    active->has_message_value =
                        selected->value.damage.message_value != 0;
                    active->heal_numerator = 0;
                    active->heal_denominator = 0;
                } else if (selected->kind ==
                        POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL) {
                    active->base_power = 0;
                    active->message_value = 0;
                    active->has_message_value = 0;
                    active->heal_numerator = selected->value.heal.numerator;
                    active->heal_denominator = selected->value.heal.denominator;
                } else {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_TARGET_LAST_NONFALLBACK: {
                uint16_t last_move = battle->sides[input->target_side].state[
                    input->target_slot].last_move_id;
                if (last_move == 0 ||
                    last_move == battle->generation->fallback_move_id) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_TARGET_STATUS_NONE:
                if (battle->sides[input->target_side].state[
                        input->target_slot].status.kind != POKEMON_STATUS_NONE) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            case POKEMON_HANDLER_OP_SET_STATUS_FROM_OWNER_SOURCE: {
                uint8_t applied = 0;
                int set_status = pokemon_set_status(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        input->target_side, input->target_slot},
                    (PokemonStatus)op->argument, input->source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_CONDITION,
                        descriptor->source_id},
                    0, &applied);
                if (set_status != POKEMON_OK) {
                    battle->event_depth--;
                    return set_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_OWNER_SIDE_COUNTER: {
                PokemonSideConditionState *condition = owner_side_condition(
                    battle, &discovered[i]);
                if (condition == NULL || condition->counter != 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                condition->counter = (uint8_t)op->argument;
                break;
            }
            case POKEMON_HANDLER_OP_INCREMENT_OWNER_SIDE_COUNTER_UP_TO: {
                PokemonSideConditionState *condition = owner_side_condition(
                    battle, &discovered[i]);
                if (condition == NULL || condition->counter == 0 ||
                    condition->counter > op->argument) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (condition->counter < op->argument) condition->counter++;
                else applicable = 0;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_TARGET_GROUNDED:
                applicable = target_is_grounded(
                    battle, input->target_side, input->target_slot,
                    (uint8_t)op->argument);
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_ADJACENT_TO_TARGET:
                applicable = discovered[i].holder_side != input->target_side &&
                    battle->sides[discovered[i].holder_side].active ==
                        discovered[i].holder_slot;
                break;
            case POKEMON_HANDLER_OP_GUARD_TARGET_CURRENT_TYPE: {
                const PokemonMutable *target = &battle->sides[
                    input->target_side].state[input->target_slot];
                applicable = has_type(target, (uint8_t)op->argument);
                break;
            }
            case POKEMON_HANDLER_OP_DAMAGE_TARGET_MAX_HP_BY_OWNER_COUNTER_FRACTIONS: {
                PokemonSideConditionState *condition = owner_side_condition(
                    battle, &discovered[i]);
                if (condition == NULL || condition->counter == 0 ||
                    condition->counter > 3) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t shift = (uint8_t)((3u - condition->counter) * 8u);
                uint8_t numerator = (uint8_t)(op->argument >> shift);
                uint8_t denominator = (uint8_t)(op->argument >> 24);
                uint16_t max_hp = battle->sides[input->target_side].sets[
                    input->target_slot].stats[0];
                uint16_t amount = battle->generation->fraction(
                    max_hp, numerator, denominator);
                if (amount == 0) amount = 1;
                status = residual_damage(
                    battle, input->target_side, input->target_slot, amount,
                    POKEMON_CONDITION_SCOPE_SIDE, condition->kind);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                applicable = 0;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move->category == op->argument;
                break;
			case POKEMON_HANDLER_OP_GUARD_MOVE_CATEGORY_MASK:
				applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
					input->context.move.move->category < 32 &&
					(op->argument & (UINT32_C(1) <<
						input->context.move.move->category)) != 0;
				break;
			case POKEMON_HANDLER_OP_REQUIRE_HOLDER_TYPE_EFFECTIVENESS_ABOVE: {
				const PokemonMutable *holder = &battle->sides[
					discovered[i].holder_side].state[discovered[i].holder_slot];
				uint8_t effectiveness = type_multiplier(
					battle, input->context.move.move->type, holder);
				if (effectiveness <= op->argument) {
					frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NULL};
					frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
					frame.cancelling_owner = discovered[i].owner;
					frame.cancelling_handler_id = descriptor->id;
				}
				break;
			}
            case POKEMON_HANDLER_OP_GUARD_HOLDER_SIDE_CONTAINS_TARGET:
                applicable = discovered[i].holder_side == input->target_side;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_HIT_NOT_CRITICAL:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    !input->context.move.critical;
                break;
            case POKEMON_HANDLER_OP_REMOVE_SIDE_CONDITION: {
                PokemonSideSelector selector =
                    (PokemonSideSelector)(op->argument >> 24);
                size_t selected_side = input->target_side;
                if (selector == POKEMON_SIDE_SELECTOR_SOURCE ||
                    selector == POKEMON_SIDE_SELECTOR_SOURCE_OPPOSING) {
                    if (input->source.kind != POKEMON_ENTITY_POKEMON) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    selected_side = input->source.side;
                    if (selector == POKEMON_SIDE_SELECTOR_SOURCE_OPPOSING) {
                        selected_side = 1u - selected_side;
                    }
                }
                status = remove_side_condition_by_descriptor(
                    battle, selected_side,
                    (uint16_t)(op->argument & UINT32_C(0xffff)),
                    input->source, input->source_effect,
                    POKEMON_CONDITION_REASON_MOVE);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_EMIT_HANDLER_IMMUNITY:
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE,
                    .side = input->target_side,
                    .target_side = input->source.side,
                    .species_id = battle->sides[input->target_side].sets[
                        input->target_slot].species_id,
                    .move_id = input->source_effect.kind ==
                            POKEMON_SOURCE_EFFECT_MOVE ?
                        input->source_effect.id : 0,
                    .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                });
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_FLAG:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    op->argument < 64 &&
                    (input->context.move.move->flags &
                        (UINT64_C(1) << op->argument)) != 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_SELF_FAINT_TIMING:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                    input->context.move.move->self_faint_timing == op->argument;
                break;
            case POKEMON_HANDLER_OP_GUARD_RANDOM_CHANCE: {
                uint32_t roll = 0;
                uint32_t numerator = (op->argument >> 16) & UINT32_C(0xff);
                uint32_t denominator = op->argument & UINT32_C(0xffff);
                status = draw_below(
                    battle, (PokemonDrawLabel)(op->argument >> 24),
                    denominator, &roll);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                applicable = roll < numerator;
                break;
            }
            case POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER: {
                uint8_t applied = 0;
                status = set_major_status(
                    battle, (PokemonStatus)op->argument, 0,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    input->source.side, input->source.slot,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                        descriptor->source_id},
                    POKEMON_STATUS_SET_EMPTY_ONLY, 0, &applied, NULL);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_EVENT_SOURCE_STATUS_FROM_HOLDER_UNIFORM_3: {
                uint32_t selected = 0;
                status = draw_below(
                    battle, (PokemonDrawLabel)(op->argument >> 24), 3,
                    &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                unsigned shift = (unsigned)(2u - selected) * 8u;
                PokemonStatus proposed = (PokemonStatus)(
                    (op->argument >> shift) & UINT32_C(0xff));
                uint8_t applied = 0;
                status = set_major_status(
                    battle, proposed, 0,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    input->source.side, input->source.slot,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                        descriptor->source_id},
                    POKEMON_STATUS_SET_EMPTY_ONLY, 0, &applied, NULL);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_TRY_ADD_EVENT_SOURCE_VOLATILE_FROM_HOLDER: {
                uint8_t installed = CONDITION_INSTALL_FAILED;
                status = install_condition_volatile(
                    battle, input->source,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                        descriptor->source_id},
                    (PokemonVolatileKind)op->argument,
                    POKEMON_CONDITION_REASON_HANDLER, &installed);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
			case POKEMON_HANDLER_OP_TRY_ADD_EVENT_TARGET_VOLATILE_FROM_SOURCE: {
				uint8_t installed = CONDITION_INSTALL_FAILED;
				status = install_condition_volatile(
					battle,
					(PokemonEntityRef){POKEMON_ENTITY_POKEMON,
						input->target_side, input->target_slot},
					input->source,
					(PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
						descriptor->source_id},
					(PokemonVolatileKind)op->argument,
					POKEMON_CONDITION_REASON_HANDLER, &installed);
				if (status != POKEMON_OK) {
					battle->event_depth--;
					return status;
				}
				frame.relay.kind = POKEMON_RELAY_BOOLEAN;
				frame.relay.value.boolean =
					installed == CONDITION_INSTALL_APPLIED;
				break;
			}
            case POKEMON_HANDLER_OP_REQUIRE_SOURCE_OPPOSITE_GENDER_TO_HOLDER: {
                PokemonGender source_gender = battle->sides[input->source.side]
                    .sets[input->source.slot].gender;
                PokemonGender holder_gender = battle->sides[
                    discovered[i].holder_side].sets[discovered[i].holder_slot]
                    .gender;
                uint8_t opposite =
                    (source_gender == POKEMON_GENDER_MALE &&
                     holder_gender == POKEMON_GENDER_FEMALE) ||
                    (source_gender == POKEMON_GENDER_FEMALE &&
                     holder_gender == POKEMON_GENDER_MALE);
                if (!opposite) {
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE_IF_SOURCE_INACTIVE: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (!entity_is_active(battle, condition->source)) {
                    PokemonVolatileState removed = *condition;
                    size_t condition_index = (size_t)(condition -
                        mutable_holder->volatiles);
                    remove_volatile_at(mutable_holder, condition_index);
                    status = trace_condition(
                        battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                        POKEMON_CONDITION_REMOVE,
                        POKEMON_CONDITION_REASON_HANDLER,
                        removed.duration == 0 ? POKEMON_CONDITION_VALUE_NONE :
                            POKEMON_CONDITION_VALUE_DURATION,
                        discovered[i].holder_side,
                        discovered[i].holder_slot, removed.kind,
                        removed.duration, 0);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_EVENT_STATUS_MASK:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_STATUS &&
                    input->context.status.proposed < 32 &&
                    (op->argument & (UINT32_C(1) <<
                        input->context.status.proposed)) != 0;
                break;
            case POKEMON_HANDLER_OP_REFLECT_EVENT_STATUS_TO_SOURCE: {
                PokemonStatus proposed =
                    (PokemonStatus)input->context.status.proposed;
                PokemonStatus rewrite_from =
                    (PokemonStatus)((op->argument >> 8) & UINT32_C(0xff));
                if (rewrite_from != POKEMON_STATUS_NONE &&
                    proposed == rewrite_from) {
                    proposed = (PokemonStatus)(
                        op->argument & UINT32_C(0xff));
                }
                uint8_t applied = 0;
                status = set_major_status(
                    battle, proposed, 0,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    input->source.side, input->source.slot,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                        descriptor->source_id},
                    POKEMON_STATUS_SET_EMPTY_ONLY, 1, &applied, NULL);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_DAMAGE_EVENT_SOURCE_BASE_MAX_HP_FRACTION: {
                uint32_t numerator = op->argument >> 16;
                uint32_t denominator = op->argument & UINT32_C(0xffff);
                const PokemonSet *source_set = &battle->sides[
                    input->source.side].sets[input->source.slot];
                uint32_t quotient =
                    ((uint32_t)source_set->stats[0] * numerator) / denominator;
                uint16_t amount = quotient == 0 ? 1 : (uint16_t)quotient;
                uint16_t applied = 0;
                PokemonSourceEffectKind effect_kind =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE ?
                        POKEMON_SOURCE_EFFECT_MOVE :
                        POKEMON_SOURCE_EFFECT_ABILITY;
                status = apply_direct_damage_inner(
                    battle, &(PokemonDirectDamageRequest){
                        .source = {POKEMON_ENTITY_POKEMON,
                            discovered[i].holder_side,
                            discovered[i].holder_slot},
                        .target = input->source,
                        .source_effect = {effect_kind,
                            descriptor->source_id},
                        .amount = amount,
                    }, &applied);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_MOVE_LACKS_SEMI_INVULNERABLE_BYPASS:
                applicable = (input->context.move.move->semi_invulnerable_hit_mask &
                    op->argument) == 0;
                break;
            case POKEMON_HANDLER_OP_GUARD_MOVE_HAS_SEMI_INVULNERABLE_DOUBLE:
                applicable = (input->context.move.move->semi_invulnerable_double_mask &
                    op->argument) != 0;
                break;
            case POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BOOST_STAGES_TO_SOURCE: {
                PokemonMutable *copy_destination = &battle->sides[
                    input->source.side].state[input->source.slot];
                const PokemonMutable *target = &battle->sides[
                    input->target_side].state[input->target_slot];
                memcpy(copy_destination->boosts, target->boosts,
                    sizeof(copy_destination->boosts));
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_BOOST_STAGES: {
                PokemonLivingActiveList actives;
                int collect_status = collect_living_actives(battle, &actives);
                if (collect_status != POKEMON_OK) {
                    battle->event_depth--;
                    return collect_status;
                }
                for (size_t active_index = 0; active_index < actives.count;
                     active_index++) {
                    PokemonEntityRef ref = actives.values[active_index];
                    memset(battle->sides[ref.side].state[ref.slot].boosts, 0,
                        sizeof(battle->sides[ref.side].state[ref.slot].boosts));
                }
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_STATUS_MASK: {
                PokemonLivingActiveList actives;
                int collect_status = collect_living_actives(battle, &actives);
                if (collect_status != POKEMON_OK) {
                    battle->event_depth--;
                    return collect_status;
                }
                for (size_t active_index = 0; active_index < actives.count;
                     active_index++) {
                    PokemonEntityRef ref = actives.values[active_index];
                    PokemonStatus current = battle->sides[ref.side]
                        .state[ref.slot].status.kind;
                    if (current < 32 &&
                        (op->argument & (UINT32_C(1) << current)) != 0) {
                        int clear_status = clear_major_status(
                            battle, ref.side, ref.slot,
                            POKEMON_CONDITION_REASON_HANDLER);
                        if (clear_status != POKEMON_OK) {
                            battle->event_depth--;
                            return clear_status;
                        }
                        const PokemonEffectOp cure = {
                            .kind = POKEMON_EFFECT_CURE_STATUS,
                            .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                            .target = POKEMON_EFFECT_TARGET_MOVE_TARGET,
                            .chance = 100,
                            .argument = current,
                        };
                        clear_status = trace_effect(
                            battle, &cure, POKEMON_EFFECT_APPLIED,
                            descriptor->source_id,
                            input->source.side, input->source.slot,
                            ref.side, ref.slot,
                            current, POKEMON_STATUS_NONE);
                        if (clear_status != POKEMON_OK) {
                            battle->event_depth--;
                            return clear_status;
                        }
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_DAMAGE &&
                    input->context.damage.kind == op->argument &&
                    input->context.damage.preventable;
                break;
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_KIND_ANY:
                applicable = input->context_kind == POKEMON_EVENT_CONTEXT_DAMAGE &&
                    input->context.damage.kind == op->argument;
                break;
            case POKEMON_HANDLER_OP_GUARD_OWNER_SOURCE_IS_EVENT_TARGET: {
                PokemonVolatileState *owner = owner_volatile(
                    battle, &discovered[i]);
                applicable = owner != NULL &&
                    owner->source.kind == POKEMON_ENTITY_POKEMON &&
                    owner->source.side == input->target_side &&
                    owner->source.slot == input->target_slot;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_SOURCE_NOT_TARGET:
                applicable = input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->source.side != input->target_side ||
                    input->source.slot != input->target_slot;
                break;
            case POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT:
                applicable = input->source_effect.kind !=
                        (PokemonSourceEffectKind)(op->argument >> 24) ||
                    input->source_effect.id !=
                        (uint16_t)(op->argument & UINT32_C(0xffff));
                break;
            case POKEMON_HANDLER_OP_GUARD_IMMUNITY_WEATHER_MASK: {
                const PokemonWeatherPolicy *source_weather =
                    weather_policy_by_descriptor(battle,
                        input->context.immunity.condition_descriptor_id);
                applicable = source_weather != NULL &&
                    (op->argument & (UINT32_C(1) << source_weather->kind)) != 0;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HP_AT_MOST_FRACTION: {
                uint32_t numerator = op->argument >> 16;
                uint32_t denominator = op->argument & UINT32_C(0xffff);
                const PokemonMutable *guard_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint16_t max_hp = battle->sides[discovered[i].holder_side].sets[
                    discovered[i].holder_slot].stats[0];
                applicable = (uint64_t)guard_holder->hp * denominator <=
                    (uint64_t)max_hp * numerator;
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_STATUS_MASK: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if ((op->argument & (UINT32_C(1) << holder->status.kind)) != 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_MOVE_ACTIONS_ABOVE: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (holder->active_move_actions > op->argument) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_HP_FULL: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint16_t max_hp = battle->sides[discovered[i].holder_side].sets[
                    discovered[i].holder_slot].stats[0];
                if (holder->hp != 0 && holder->hp == max_hp) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_UNDEFINED};
                    frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_NULL_IF_HOLDER_ABILITY_BLOCKS_STATUS: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint8_t blocked = 0;
                for (size_t immunity_index = 0;
                     immunity_index < battle->data->status_immunity_count;
                     immunity_index++) {
                    const PokemonStatusImmunity *rule =
                        &battle->data->status_immunities[immunity_index];
                    if (rule->ability_id == holder->ability_id &&
                        rule->blocked_status == (PokemonStatus)op->argument) {
                        blocked = 1;
                        break;
                    }
                }
                if (blocked) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_UNDEFINED};
                    frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_NOT_BOUNCED:
                applicable = battle->move_frame_depth != 0 &&
                    !battle->move_frames[battle->move_frame_depth - 1].invocation.has_bounced;
                break;
            case POKEMON_HANDLER_OP_REMOVE_OWNER_VOLATILE: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                /* Match Pokemon.removeVolatile: explicit callback-owned
                 * removal is a no-op once the holder has zero HP. Faint and
                 * switch cleanup use their separate silent-clear paths. */
                if (mutable_holder->hp == 0) {
                    applicable = 0;
                    break;
                }
                int volatile_position = -1;
                for (size_t volatile_index_value = 0;
                     volatile_index_value < mutable_holder->volatile_count;
                     volatile_index_value++) {
                    if (mutable_holder->volatiles[volatile_index_value].descriptor_id ==
                        descriptor->source_id) {
                        volatile_position = (int)volatile_index_value;
                        break;
                    }
                }
                if (volatile_position < 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonVolatileState removed =
                    mutable_holder->volatiles[volatile_position];
                removed_owner_volatile = removed;
                removed_owner_volatile_present = 1;
                int remove_status = end_and_remove_volatile_exact(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, removed.descriptor_id,
                    removed.state_generation, removed.effect_order,
                    POKEMON_CONDITION_REASON_MOVE);
                if (remove_status != POKEMON_OK) {
                    battle->event_depth--;
                    return remove_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_DEDUCT_OWNER_MOVE_PP_FROM_TARGET_EVENT: {
                if (!removed_owner_volatile_present ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    removed_owner_volatile.source_effect.kind !=
                        POKEMON_SOURCE_EFFECT_MOVE) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonEventFrame deduction;
                int deduct_status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_DEDUCT_PP,
                    .source = {POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    .target_side = input->source.side,
                    .target_slot = input->source.slot,
                    .source_effect = removed_owner_volatile.source_effect,
                    .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 0},
                    .context_kind = input->context_kind,
                    .context = input->context,
                }, &deduction);
                if (deduct_status != POKEMON_OK) {
                    battle->event_depth--;
                    return deduct_status;
                }
                if (deduction.relay.value.u32 != 0) {
                    PokemonMutable *snatcher = &battle->sides[
                        discovered[i].holder_side].state[discovered[i].holder_slot];
                    int selected = -1;
                    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                        if (snatcher->move_ids[slot] ==
                            removed_owner_volatile.source_effect.id) {
                            selected = (int)slot;
                            break;
                        }
                    }
                    if (selected < 0) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    uint32_t amount = deduction.relay.value.u32;
                    set_current_pp(battle, discovered[i].holder_side,
                        discovered[i].holder_slot, (size_t)selected,
                        amount >= snatcher->pp[selected] ? 0 :
                            (uint8_t)(snatcher->pp[selected] - amount));
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_ACTIVE_MOVE_AS_OWNER: {
                if (battle->move_frame_depth == 0 ||
                    !removed_owner_volatile_present) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = active->invocation.move_id,
                    .user = {POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    .target_request = {POKEMON_TARGET_REQUEST_RESOLVE, {0}},
                    .source_effect = {POKEMON_SOURCE_EFFECT_CONDITION,
                        descriptor->source_id},
                    .has_bounced = 0,
                    .inherited_priority = active->priority,
                    .selected_slot = UINT8_MAX,
                };
                int child_status = invoke_move_inner(battle, child);
                if (child_status != POKEMON_OK) {
                    battle->event_depth--;
                    return child_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REFLECT_ACTIVE_MOVE: {
                if (battle->move_frame_depth == 0 ||
                    input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = active->invocation.move_id,
                    .user = {POKEMON_ENTITY_POKEMON, input->target_side,
                        input->target_slot},
                    .target_request = {POKEMON_TARGET_REQUEST_EXPLICIT,
                        input->source},
                    .source_effect = {POKEMON_SOURCE_EFFECT_CONDITION,
                        descriptor->source_id},
                    .has_bounced = 1,
                    .inherited_priority = active->priority,
                    .selected_slot = UINT8_MAX,
                };
                int child_status = invoke_move_inner(battle, child);
                if (child_status != POKEMON_OK) {
                    battle->event_depth--;
                    return child_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_TRY_HEAL_HOLDER_MAX_HP_FRACTION: {
                PokemonEffectResult heal_result;
                uint16_t amount = 0;
                status = try_fraction_heal(
                    battle, input->source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ABILITY,
                        descriptor->source_id},
                    discovered[i].holder_side, discovered[i].holder_slot,
                    (uint8_t)(op->argument >> 16),
                    (uint8_t)(op->argument & UINT32_C(0xffff)),
                    &heal_result, &amount);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                frame.cancellation_emits_immunity =
                    heal_result == POKEMON_EFFECT_FAILED;
                break;
            }
            case POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_HOLDER_VOLATILE: {
                PokemonEffectResult volatile_result;
                PokemonSourceEffectKind source_effect_kind =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_ITEM ?
                        POKEMON_SOURCE_EFFECT_ITEM :
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE ?
                        POKEMON_SOURCE_EFFECT_MOVE :
                        POKEMON_SOURCE_EFFECT_ABILITY;
                status = pokemon_try_add_or_restart_volatile(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    input->source,
                    (PokemonSourceEffectRef){source_effect_kind,
                        descriptor->source_id},
                    (PokemonVolatileKind)op->argument,
                    POKEMON_CONDITION_REASON_HANDLER, &volatile_result);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                frame.cancellation_emits_immunity =
                    descriptor->source_kind == POKEMON_HANDLER_SOURCE_ABILITY &&
                    volatile_result == POKEMON_EFFECT_FAILED;
                break;
            }
            case POKEMON_HANDLER_OP_TRY_ADD_OR_RESTART_SOURCE_VOLATILE: {
                PokemonEffectResult volatile_result;
                status = pokemon_try_add_or_restart_volatile(
                    battle, input->source, input->source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    (PokemonVolatileKind)op->argument,
                    POKEMON_CONDITION_REASON_HANDLER, &volatile_result);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_KIND: {
                const PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                applicable = volatile_index(mutable_holder,
                    (PokemonVolatileKind)op->argument) >= 0;
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND: {
                const PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (volatile_index(mutable_holder,
                        (PokemonVolatileKind)op->argument) >= 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_VOLATILE_COUNTER_AT_LEAST: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileKind kind =
                    (PokemonVolatileKind)(op->argument >> 16);
                uint8_t threshold = (uint8_t)op->argument;
                int index = volatile_index(holder, kind);
                applicable = index >= 0 &&
                    holder->volatiles[index].counter >= threshold;
                break;
            }
            case POKEMON_HANDLER_OP_USE_HANDLER_OWNED_HELD_ITEM: {
                uint8_t used = 0;
                status = use_held_item(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, descriptor->source_id, &used);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                applicable = used;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_NEGATIVE_BOOST: {
                const PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                applicable = 0;
                guarded_negative_boost_mask = 0;
                for (uint8_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
                    if (mutable_holder->boosts[stat] < 0) {
                        applicable = 1;
                        guarded_negative_boost_mask |= (uint8_t)(1u << stat);
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_HOLDER_NEGATIVE_BOOST_STAGES: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                for (uint8_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
                    if ((guarded_negative_boost_mask & (uint8_t)(1u << stat)) != 0) {
                        mutable_holder->boosts[stat] = 0;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_REMOVE_HOLDER_VOLATILE_KIND: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                int position = volatile_index(mutable_holder,
                    (PokemonVolatileKind)op->argument);
                if (position < 0) break;
                PokemonVolatileState old = mutable_holder->volatiles[position];
                status = end_and_remove_volatile_exact(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, old.descriptor_id,
                    old.state_generation, (uint16_t)old.effect_order,
                    POKEMON_CONDITION_REASON_HANDLER);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CHAIN_Q12:
                if (frame.relay.kind == POKEMON_RELAY_BOOLEAN) applicable = 0;
                else handler_modifier = chain_modifier_q12(
                    handler_modifier, op->argument);
                break;
            case POKEMON_HANDLER_OP_MODIFY_RELAY_Q12:
                if (frame.relay.kind != POKEMON_RELAY_U32) {
                    applicable = 0;
                } else {
                    frame.relay.value.u32 = apply_modifier_q12(
                        frame.relay.value.u32, op->argument);
                }
                break;
            case POKEMON_HANDLER_OP_ADD_RELAY_U32:
                if (frame.relay.kind != POKEMON_RELAY_U32 ||
                    UINT32_MAX - frame.relay.value.u32 < op->argument) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 += op->argument;
                break;
            case POKEMON_HANDLER_OP_CAP_DAMAGE_TO_HOLDER_HP_MINUS_ONE: {
                if (frame.relay.kind != POKEMON_RELAY_U32) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonMutable *damage_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (damage_holder->hp == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (frame.relay.value.u32 >= damage_holder->hp) {
                    frame.relay.value.u32 = damage_holder->hp - 1u;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CHAIN_Q12_IF_MOVE_TYPE:
                if (input->context.move.move->type == (uint8_t)(op->argument >> 24)) {
                    handler_modifier = chain_modifier_q12(
                        handler_modifier, op->argument & UINT32_C(0xffff));
                }
                break;
            case POKEMON_HANDLER_OP_GUARD_EFFECTIVE_WEATHER:
                applicable = effective_weather(battle) ==
                    (PokemonWeatherKind)op->argument;
                break;
            case POKEMON_HANDLER_OP_HEAL_MAX_HP_FRACTION: {
                PokemonMutable *mutable_holder = &battle->sides[
                    input->target_side].state[input->target_slot];
                uint16_t max_hp = battle->sides[input->target_side].sets[
                    input->target_slot].stats[0];
                uint16_t amount = (uint16_t)(max_hp / op->argument);
                if (amount == 0) amount = 1;
                uint16_t missing = (uint16_t)(max_hp - mutable_holder->hp);
                if (amount > missing) amount = missing;
                if (amount != 0 && mutable_holder->hp != 0) {
                    mutable_holder->hp = (uint16_t)(mutable_holder->hp + amount);
                    append_event(battle, (PokemonEvent){
                        .kind = POKEMON_EVENT_HEAL,
                        .side = input->target_side, .slot = input->target_slot,
                        .species_id = battle->sides[input->target_side].sets[
                            input->target_slot].species_id,
                        .amount = amount, .hp = mutable_holder->hp,
                    });
                }
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_MAJOR_STATUS: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonStatus before = holder->status.kind;
                int clear_status = clear_major_status(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, POKEMON_CONDITION_REASON_HANDLER);
                if (clear_status != POKEMON_OK) {
                    battle->event_depth--;
                    return clear_status;
                }
                if (input->source_effect.kind ==
                        POKEMON_SOURCE_EFFECT_MOVE &&
                    before != POKEMON_STATUS_NONE &&
                    holder->status.kind == POKEMON_STATUS_NONE) {
                    const PokemonEffectOp cure = {
                        .kind = POKEMON_EFFECT_CURE_STATUS,
                        .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                        .target = POKEMON_EFFECT_TARGET_MOVE_TARGET,
                        .chance = 100,
                        .argument = before,
                    };
                    clear_status = trace_effect(
                        battle, &cure, POKEMON_EFFECT_APPLIED,
                        input->source_effect.id,
                        input->source.side, input->source.slot,
                        discovered[i].holder_side,
                        discovered[i].holder_slot,
                        before, POKEMON_STATUS_NONE);
                    if (clear_status != POKEMON_OK) {
                        battle->event_depth--;
                        return clear_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_RANDOM_CURE_OR_REQUIRE_DEFROST: {
                uint32_t roll = 0;
                uint32_t numerator =
                    (op->argument >> 16) & UINT32_C(0xff);
                uint32_t denominator =
                    (op->argument >> 8) & UINT32_C(0xff);
                status = draw_below(
                    battle, (PokemonDrawLabel)(op->argument >> 24),
                    denominator, &roll);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                if (roll < numerator) {
                    PokemonStatus before = battle->sides[
                        discovered[i].holder_side].state[
                            discovered[i].holder_slot].status.kind;
                    status = clear_major_status(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot,
                        POKEMON_CONDITION_REASON_HANDLER);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                    const PokemonEffectOp cure = {
                        .kind = POKEMON_EFFECT_CURE_STATUS,
                        .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                        .target = POKEMON_EFFECT_TARGET_USER,
                        .chance = 100,
                        .argument = before,
                    };
                    status = trace_effect(
                        battle, &cure, POKEMON_EFFECT_APPLIED,
                        input->context.move.move->id,
                        discovered[i].holder_side,
                        discovered[i].holder_slot,
                        discovered[i].holder_side,
                        discovered[i].holder_slot,
                        before, POKEMON_STATUS_NONE);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                } else if (!input->context.move.move->defrost) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_ABILITY_TRANSFER_ALLOWED: {
                const PokemonMutable *source_state = &battle->sides[
                    frame.source.side].state[frame.source.slot];
                const PokemonMutable *target_state = &battle->sides[
                    frame.target.side].state[frame.target.slot];
                const PokemonAbilityData *source_ability = find_ability(
                    battle, source_state->ability_id);
                const PokemonAbilityData *target_ability = find_ability(
                    battle, target_state->ability_id);
                uint32_t target_forbidden =
                    op->argument & UINT32_C(0xffff);
                uint32_t source_forbidden = op->argument >> 16;
                if (source_ability == NULL || target_ability == NULL ||
                    source_state->ability_id == target_state->ability_id ||
                    (target_ability->semantic_flags & target_forbidden) != 0 ||
                    (source_ability->semantic_flags & source_forbidden) != 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_REPLACE_SOURCE_ABILITY_FROM_EVENT_TARGET:
                status = replace_pokemon_ability(
                    battle, frame.source.side, frame.source.slot,
                    frame.target.side, frame.target.slot,
                    battle->generation->replaced_ability_runs_start);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            case POKEMON_HANDLER_OP_SWAP_SOURCE_TARGET_ABILITIES: {
                uint8_t applied = 0;
                status = swap_pokemon_abilities(
                    battle, frame.source.side, frame.source.slot,
                    frame.target.side, frame.target.slot, &applied);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                if (!applied) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS: {
                uint16_t excluded_ability =
                    (uint16_t)(op->argument & UINT32_C(0xffff));
                uint32_t flags = op->argument >> 16;
                size_t team_side = discovered[i].holder_side;
                for (size_t ordinal = 0;
                     ordinal < battle->team_sizes[team_side]; ordinal++) {
                    size_t slot = battle->sides[team_side].active;
                    if (ordinal != 0) {
                        slot = ordinal - 1;
                        if (slot >= battle->sides[team_side].active) slot++;
                    }
                    PokemonMutable *member =
                        &battle->sides[team_side].state[slot];
                    if (excluded_ability != 0 &&
                        member->ability_id == excluded_ability) {
                        if ((flags & UINT32_C(2)) != 0 &&
                            slot == battle->sides[team_side].active) {
                            append_event(battle, (PokemonEvent){
                                .kind = POKEMON_EVENT_IMMUNE,
                                .side = (uint8_t)team_side,
                                .slot = (uint8_t)slot,
                                .species_id = battle->sides[team_side].sets[
                                    slot].species_id,
                                .move_id = descriptor->source_id,
                                .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                                .handler_id = descriptor->id,
                            });
                        }
                        continue;
                    }
                    if (member->hp == 0 ||
                        member->status.kind == POKEMON_STATUS_NONE) continue;
                    PokemonStatus before = member->status.kind;
                    status = clear_major_status(
                        battle, team_side, slot,
                        POKEMON_CONDITION_REASON_HANDLER);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                    if ((flags & UINT32_C(1)) != 0) {
                        const PokemonEffectOp cure = {
                            .kind = POKEMON_EFFECT_CURE_STATUS,
                            .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                            .target = POKEMON_EFFECT_TARGET_USER,
                            .chance = 100,
                            .argument = before,
                        };
                        status = trace_effect(
                            battle, &cure, POKEMON_EFFECT_APPLIED,
                            descriptor->source_id, input->source.side,
                            input->source.slot, team_side, slot,
                            before, POKEMON_STATUS_NONE);
                        if (status != POKEMON_OK) {
                            battle->event_depth--;
                            return status;
                        }
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_REPLACE_HOLDER_MAJOR_STATUS: {
                uint8_t applied = 0;
                PokemonEventCancellation rejection = POKEMON_EVENT_CANCEL_NONE;
                status = set_major_status(
                    battle, (PokemonStatus)op->argument,
                    descriptor->source_id,
                    input->source.side, input->source.slot,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    POKEMON_STATUS_SET_REPLACE_DIFFERENT, 0, &applied,
                    &rejection);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                if (!applied) {
                    frame.relay = rejection == POKEMON_EVENT_CANCEL_NULL ?
                        (PokemonRelay){.kind = POKEMON_RELAY_NULL} :
                        (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                            .value.boolean = 0};
                    frame.cancellation = rejection == POKEMON_EVENT_CANCEL_NONE ?
                        POKEMON_EVENT_CANCEL_FALSE : rejection;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_HOLDER_STATUS_COUNTER: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                switch ((PokemonStatusCounterSelector)(op->argument >> 16)) {
                case POKEMON_STATUS_COUNTER_SLEEP_TIME:
                    if (holder->status.kind != POKEMON_STATUS_SLEEP) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    holder->status.state.sleep.time =
                        (uint8_t)(op->argument & UINT32_C(0xffff));
                    holder->status.state.sleep.skipped_time = 0;
                    break;
                case POKEMON_STATUS_COUNTER_TOXIC_STAGE: {
                    if (holder->status.kind != POKEMON_STATUS_TOXIC) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    uint8_t before = holder->status.state.toxic.stage;
                    holder->status.state.toxic.stage =
                        (uint8_t)(op->argument & UINT32_C(0xffff));
                    if (input->event == POKEMON_HANDLER_EVENT_SWITCH_IN &&
                        before != holder->status.state.toxic.stage) {
                        status = trace_condition(
                            battle, POKEMON_CONDITION_SCOPE_STATUS,
                            POKEMON_CONDITION_UPDATE,
                            POKEMON_CONDITION_REASON_SWITCH,
                            POKEMON_CONDITION_VALUE_STAGE,
                            discovered[i].holder_side,
                            discovered[i].holder_slot,
                            holder->status.kind, before,
                            holder->status.state.toxic.stage);
                        if (status != POKEMON_OK) {
                            battle->event_depth--;
                            return status;
                        }
                    }
                    break;
                }
                default:
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                break;
            }
            case POKEMON_HANDLER_OP_ADVANCE_OWNER_SLEEP: {
                PokemonMutable *sleep_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (sleep_holder->status.kind != POKEMON_STATUS_SLEEP ||
                    sleep_holder->status.state.sleep.time == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t before_time = sleep_holder->status.state.sleep.time;
                uint8_t before_skipped =
                    sleep_holder->status.state.sleep.skipped_time;
                uint8_t decrements = sleep_holder->ability_id ==
                    (uint16_t)op->argument ? 2 : 1;
                sleep_holder->status.state.sleep.time = before_time > decrements ?
                    (uint8_t)(before_time - decrements) : 0;
                if (sleep_holder->status.state.sleep.time == 0) {
                    uint8_t removed_skipped =
                        sleep_holder->status.state.sleep.skipped_time;
                    int clear_status = clear_major_status(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot,
                        POKEMON_CONDITION_REASON_HANDLER);
                    if (clear_status != POKEMON_OK) {
                        battle->event_depth--;
                        return clear_status;
                    }
                    if (input->context_kind == POKEMON_EVENT_CONTEXT_MOVE &&
                        input->context.move.move != NULL) {
                        clear_status = trace_effect(
                            battle, &(PokemonEffectOp){
                                .kind = POKEMON_EFFECT_CURE_STATUS,
                                .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                                .target = POKEMON_EFFECT_TARGET_USER,
                                .argument = POKEMON_STATUS_SLEEP,
                            }, POKEMON_EFFECT_APPLIED,
                            input->context.move.move->id,
                            discovered[i].holder_side,
                            discovered[i].holder_slot,
                            discovered[i].holder_side,
                            discovered[i].holder_slot,
                            POKEMON_STATUS_SLEEP, POKEMON_STATUS_NONE);
                        if (clear_status != POKEMON_OK) {
                            battle->event_depth--;
                            return clear_status;
                        }
                    }
                    PokemonConditionTrace *trace = &battle->condition_traces[
                        battle->condition_trace_count - 1];
                    trace->has_duration_before = 1;
                    trace->duration_before = 0;
                    trace->has_counter_before = 1;
                    trace->counter_before = removed_skipped;
                    break;
                }
                if (input->context.move.move->sleep_usable) {
                    if (sleep_holder->status.state.sleep.skipped_time ==
                        UINT8_MAX) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    sleep_holder->status.state.sleep.skipped_time++;
                } else {
                    sleep_holder->status.state.sleep.skipped_time = 0;
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                int trace_status = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_STATUS,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_HANDLER,
                    POKEMON_CONDITION_VALUE_DURATION,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    POKEMON_STATUS_SLEEP, before_time,
                    sleep_holder->status.state.sleep.time);
                if (trace_status != POKEMON_OK) {
                    battle->event_depth--;
                    return trace_status;
                }
                PokemonConditionTrace *trace = &battle->condition_traces[
                    battle->condition_trace_count - 1];
                trace->has_counter_before = 1;
                trace->counter_before = before_skipped;
                trace->has_counter_after = 1;
                trace->counter_after =
                    sleep_holder->status.state.sleep.skipped_time;
                break;
            }
            case POKEMON_HANDLER_OP_RESTORE_OWNER_SLEEP_SKIPPED: {
                PokemonMutable *sleep_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (sleep_holder->status.kind != POKEMON_STATUS_SLEEP ||
                    sleep_holder->status.state.sleep.time == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t before_time = sleep_holder->status.state.sleep.time;
                uint8_t before_skipped =
                    sleep_holder->status.state.sleep.skipped_time;
                if (UINT8_MAX - before_time < before_skipped) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                sleep_holder->status.state.sleep.time =
                    (uint8_t)(before_time + before_skipped);
                sleep_holder->status.state.sleep.skipped_time = 0;
                if (before_skipped != 0) {
                    int trace_status = trace_condition(
                        battle, POKEMON_CONDITION_SCOPE_STATUS,
                        POKEMON_CONDITION_UPDATE,
                        POKEMON_CONDITION_REASON_SWITCH,
                        POKEMON_CONDITION_VALUE_DURATION,
                        discovered[i].holder_side, discovered[i].holder_slot,
                        POKEMON_STATUS_SLEEP, before_time,
                        sleep_holder->status.state.sleep.time);
                    if (trace_status != POKEMON_OK) {
                        battle->event_depth--;
                        return trace_status;
                    }
                    PokemonConditionTrace *trace = &battle->condition_traces[
                        battle->condition_trace_count - 1];
                    trace->has_counter_before = 1;
                    trace->counter_before = before_skipped;
                    trace->has_counter_after = 1;
                    trace->counter_after = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_SOURCE_OPPOSES_HOLDER:
                applicable = input->source.kind == POKEMON_ENTITY_POKEMON &&
                    input->source.side != discovered[i].holder_side;
                break;
            case POKEMON_HANDLER_OP_FAINT_EVENT_SOURCE:
                if (input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (battle->sides[input->source.side].state[
                        input->source.slot].hp == 0) break;
                if (battle->faint_count == POKEMON_FAINT_QUEUE_CAPACITY) {
                    battle->event_depth--;
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                battle->sides[input->source.side].state[
                    input->source.slot].hp = 0;
                status = queue_faint(
                    battle, input->source,
                    (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_NONE, 0});
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            case POKEMON_HANDLER_OP_ZERO_LIVING_EVENT_SOURCE_LAST_MOVE_PP: {
                if (input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMutable *source_state = &battle->sides[
                    input->source.side].state[input->source.slot];
                if (source_state->hp == 0 || source_state->fainted ||
                    source_state->last_move_id == 0) {
                    applicable = 0;
                    break;
                }
                uint8_t matched = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (source_state->move_ids[slot] !=
                        source_state->last_move_id) continue;
                    set_current_pp(battle, input->source.side,
                        input->source.slot, slot, 0);
                    matched = 1;
                }
                applicable = matched;
                break;
            }
            case POKEMON_HANDLER_OP_EAT_FIXED_HEAL_BERRY: {
                int eat_status = eat_threshold_berry(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, descriptor->source_id);
                if (eat_status != POKEMON_OK) {
                    battle->event_depth--;
                    return eat_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_EAT_PINCH_BOOST_BERRY: {
                int eat_status = eat_threshold_berry(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, descriptor->source_id);
                if (eat_status != POKEMON_OK) {
                    battle->event_depth--;
                    return eat_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_BOOST_PINCH_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->boost_delta == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                int boost_status = apply_item_boost(
                    battle, discovered[i].holder_side, discovered[i].holder_slot,
                    descriptor->source_id, item->boost_stat, item->boost_delta);
                if (boost_status != POKEMON_OK) {
                    battle->event_depth--;
                    return boost_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_BOOST_RANDOM_ELIGIBLE_HOLDER_STAT: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(
                    battle, descriptor->source_id);
                if (item == NULL || item->boost_delta == 0 ||
                    item->eligible_boost_mask == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t candidates[POKEMON_STAT_COUNT];
                uint8_t candidate_count = 0;
                for (uint8_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
                    if ((item->eligible_boost_mask &
                            (uint8_t)(UINT8_C(1) << stat)) != 0 &&
                        mutable_holder->boosts[stat] <
                            battle->generation->stages->maximum) {
                        candidates[candidate_count++] = stat;
                    }
                }
                if (candidate_count != 0) {
                    uint32_t selected = 0;
                    int boost_status = draw_below(
                        battle, POKEMON_DRAW_ITEM_RANDOM_STAT,
                        candidate_count, &selected);
                    if (boost_status == POKEMON_OK) {
                        boost_status = apply_item_boost(
                            battle, discovered[i].holder_side,
                            discovered[i].holder_slot, descriptor->source_id,
                            candidates[selected], item->boost_delta);
                    }
                    if (boost_status != POKEMON_OK) {
                        battle->event_depth--;
                        return boost_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_EAT_STATUS_CURE_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->cure_status_mask == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t status_bit = mutable_holder->status.kind == POKEMON_STATUS_NONE ?
                    0 : (uint16_t)(UINT16_C(1) << mutable_holder->status.kind);
                if ((item->cure_status_mask & status_bit) != 0) {
                    int eat_status = eat_held_berry(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, descriptor->source_id);
                    if (eat_status != POKEMON_OK) {
                        battle->event_depth--;
                        return eat_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_CURE_STATUS_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->cure_status_mask == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t status_bit = mutable_holder->status.kind == POKEMON_STATUS_NONE ?
                    0 : (uint16_t)(UINT16_C(1) << mutable_holder->status.kind);
                if ((item->cure_status_mask & status_bit) != 0) {
                    PokemonStatus before_status = mutable_holder->status.kind;
                    int cure_status = clear_major_status(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, POKEMON_CONDITION_REASON_HANDLER);
                    if (cure_status != POKEMON_OK) {
                        battle->event_depth--;
                        return cure_status;
                    }
                    if (battle->move_frame_depth != 0) {
                        const PokemonMoveInvocation *active = &battle->move_frames[
                            battle->move_frame_depth - 1].invocation;
                        cure_status = trace_effect(battle, &(PokemonEffectOp){
                            .kind = POKEMON_EFFECT_CURE_STATUS,
                            .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                            .target = POKEMON_EFFECT_TARGET_MOVE_TARGET,
                            .argument = before_status,
                        }, POKEMON_EFFECT_APPLIED, active->move_id,
                            active->user.side, active->user.slot,
                            discovered[i].holder_side, discovered[i].holder_slot,
                            before_status, mutable_holder->status.kind);
                        if (cure_status != POKEMON_OK) {
                            battle->event_depth--;
                            return cure_status;
                        }
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_EAT_VOLATILE_CURE_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->cure_volatile_kind == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (volatile_index(mutable_holder,
                        (PokemonVolatileKind)item->cure_volatile_kind) >= 0) {
                    int eat_status = eat_held_berry(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, descriptor->source_id);
                    if (eat_status != POKEMON_OK) {
                        battle->event_depth--;
                        return eat_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_CURE_VOLATILE_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->cure_volatile_kind == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                int position = volatile_index(mutable_holder,
                    (PokemonVolatileKind)item->cure_volatile_kind);
                if (position >= 0) {
                    PokemonVolatileState old = mutable_holder->volatiles[position];
                    PokemonEventFrame end;
                    int cure_status = run_event_inner(battle, &(PokemonEventInput){
                        .event = POKEMON_HANDLER_EVENT_END,
                        .source = old.source,
                        .target_side = discovered[i].holder_side,
                        .target_slot = discovered[i].holder_slot,
                        .source_effect = old.source_effect,
                        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                        .context.volatile_condition = {
                            .kind = (PokemonVolatileKind)item->cure_volatile_kind,
                        },
                    }, &end);
                    if (cure_status == POKEMON_OK) cure_status = trace_condition(
                        battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                        POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_HANDLER,
                        POKEMON_CONDITION_VALUE_DURATION,
                        discovered[i].holder_side, discovered[i].holder_slot,
                        item->cure_volatile_kind,
                        old.kind == POKEMON_VOLATILE_CONFUSION ?
                            old.payload.confusion.time : 0, 0);
                    if (cure_status == POKEMON_OK) {
                        remove_volatile_at(mutable_holder, (size_t)position);
                    } else {
                        battle->event_depth--;
                        return cure_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_EAT_HELD_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                int eat_status = eat_held_berry(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, descriptor->source_id);
                if (eat_status != POKEMON_OK) {
                    battle->event_depth--;
                    return eat_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_HOLDER_HAS_ZERO_MOVE_PP: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                applicable = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (holder->move_ids[slot] != 0 && holder->pp[slot] == 0) {
                        applicable = 1;
                        break;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_RESTORE_FIRST_HOLDER_MOVE_PP: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                int selected = -1;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (holder->move_ids[slot] != 0 && holder->pp[slot] == 0) {
                        selected = (int)slot;
                        break;
                    }
                }
                if (selected < 0) {
                    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                        if (holder->move_ids[slot] != 0 &&
                            holder->pp[slot] < holder->max_pp[slot]) {
                            selected = (int)slot;
                            break;
                        }
                    }
                }
                if (selected >= 0) {
                    if (find_move(battle,
                            holder->move_ids[(size_t)selected]) == NULL) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    uint32_t restored = holder->pp[(size_t)selected] + op->argument;
                    set_current_pp(battle, discovered[i].holder_side,
                        discovered[i].holder_slot, (size_t)selected,
                        (uint8_t)(restored > holder->max_pp[(size_t)selected] ?
                            holder->max_pp[(size_t)selected] : restored));
                }
                break;
            }
            case POKEMON_HANDLER_OP_DEDUCT_TARGET_LAST_MOVE_PP_UNIFORM: {
                PokemonDrawLabel label = (PokemonDrawLabel)
                    ((op->argument >> 24) & UINT32_C(0xff));
                uint32_t minimum =
                    (op->argument >> 16) & UINT32_C(0xff);
                uint32_t maximum =
                    (op->argument >> 8) & UINT32_C(0xff);
                uint32_t requested = 0;
                int draw_status = draw_range(
                    battle, label, minimum, maximum, &requested);
                if (draw_status != POKEMON_OK) {
                    battle->event_depth--;
                    return draw_status;
                }
                PokemonMutable *target = &battle->sides[
                    input->target_side].state[input->target_slot];
                int selected = -1;
                if (target->last_move_id != 0) {
                    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                        if (target->move_ids[slot] == target->last_move_id) {
                            selected = (int)slot;
                            break;
                        }
                    }
                }
                if (selected < 0 || target->pp[(size_t)selected] == 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint8_t remaining = requested >= target->pp[(size_t)selected] ?
                    0 : (uint8_t)(target->pp[(size_t)selected] - requested);
                set_current_pp(battle, input->target_side, input->target_slot,
                    (size_t)selected, remaining);
                break;
            }
            case POKEMON_HANDLER_OP_EAT_CONDITION_CURE_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || mutable_holder->item_id != descriptor->source_id ||
                    (item->cure_status_mask == 0 && item->cure_volatile_kind == 0)) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t status_bit = mutable_holder->status.kind == POKEMON_STATUS_NONE ?
                    0 : (uint16_t)(UINT16_C(1) << mutable_holder->status.kind);
                int volatile_position = item->cure_volatile_kind == 0 ? -1 :
                    volatile_index(mutable_holder,
                        (PokemonVolatileKind)item->cure_volatile_kind);
                if ((item->cure_status_mask & status_bit) != 0 ||
                    volatile_position >= 0) {
                    int eat_status = eat_held_berry(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, descriptor->source_id);
                    if (eat_status != POKEMON_OK) {
                        battle->event_depth--;
                        return eat_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_FRACTION_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonSet *holder_set = &battle->sides[
                    discovered[i].holder_side].sets[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->heal_denominator == 0 ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t requested = (uint16_t)(holder_set->stats[0] /
                    item->heal_denominator);
                if (requested == 0) requested = 1;
                PokemonEventFrame heal_gate;
                int heal_status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_TRY_HEAL,
                    .source = {POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    .target_side = discovered[i].holder_side,
                    .target_slot = discovered[i].holder_slot,
                    .source_effect = {POKEMON_SOURCE_EFFECT_ITEM,
                        descriptor->source_id},
                    .relay = {.kind = POKEMON_RELAY_U32,
                        .value.u32 = requested},
                }, &heal_gate);
                if (heal_status != POKEMON_OK) {
                    battle->event_depth--;
                    return heal_status;
                }
                if (heal_gate.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                    heal_gate.relay.value.u32 == 0) break;
                uint16_t missing = (uint16_t)(holder_set->stats[0] -
                    mutable_holder->hp);
                uint16_t amount = heal_gate.relay.value.u32 < missing ?
                    (uint16_t)heal_gate.relay.value.u32 : missing;
                if (amount != 0 && mutable_holder->hp != 0) {
                    mutable_holder->hp = (uint16_t)(mutable_holder->hp + amount);
                    append_event(battle, (PokemonEvent){
                        .kind = POKEMON_EVENT_HEAL,
                        .side = discovered[i].holder_side,
                        .slot = discovered[i].holder_slot,
                        .species_id = holder_set->species_id,
                        .amount = amount, .hp = mutable_holder->hp,
                    });
                }
                break;
            }
            case POKEMON_HANDLER_OP_CONFUSE_DISLIKED_FLAVOR: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonSet *holder_set = &battle->sides[
                    discovered[i].holder_side].sets[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || item->disliked_flavor == POKEMON_FLAVOR_NONE ||
                    mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (holder_set->disliked_flavor == item->disliked_flavor) {
                    uint8_t installed = 0;
                    int confuse_status = install_condition_volatile(
                        battle,
                        (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                            discovered[i].holder_side,
                            discovered[i].holder_slot},
                        (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                            discovered[i].holder_side,
                            discovered[i].holder_slot},
                        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_ITEM,
                            descriptor->source_id},
                        POKEMON_VOLATILE_CONFUSION,
                        POKEMON_CONDITION_REASON_HANDLER, &installed);
                    if (confuse_status != POKEMON_OK) {
                        battle->event_depth--;
                        return confuse_status;
                    }
                }
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_FIXED_BERRY: {
                PokemonMutable *mutable_holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonSet *holder_set = &battle->sides[
                    discovered[i].holder_side].sets[discovered[i].holder_slot];
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                if (item == NULL || mutable_holder->item_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonEventFrame heal_gate;
                int heal_status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_TRY_HEAL,
                    .source = {POKEMON_ENTITY_POKEMON, discovered[i].holder_side,
                        discovered[i].holder_slot},
                    .target_side = discovered[i].holder_side,
                    .target_slot = discovered[i].holder_slot,
                    .source_effect = {POKEMON_SOURCE_EFFECT_ITEM, descriptor->source_id},
                    .relay = {.kind = POKEMON_RELAY_U32,
                        .value.u32 = item->fixed_heal},
                }, &heal_gate);
                if (heal_status != POKEMON_OK) {
                    battle->event_depth--;
                    return heal_status;
                }
                if (heal_gate.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                    heal_gate.relay.value.u32 == 0) break;
                uint16_t missing = (uint16_t)(holder_set->stats[0] - mutable_holder->hp);
                uint16_t amount = item->fixed_heal < missing ? item->fixed_heal : missing;
                if (amount != 0 && mutable_holder->hp != 0) {
                    mutable_holder->hp = (uint16_t)(mutable_holder->hp + amount);
                    append_event(battle, (PokemonEvent){
                        .kind = POKEMON_EVENT_HEAL,
                        .side = discovered[i].holder_side,
                        .slot = discovered[i].holder_slot,
                        .species_id = holder_set->species_id,
                        .amount = amount, .hp = mutable_holder->hp,
                    });
                }
                break;
            }
            case POKEMON_HANDLER_OP_TRY_HEAL_BERRY_GATE: {
                const PokemonItemData *item = find_item(battle, descriptor->source_id);
                const PokemonSet *holder_set = &battle->sides[
                    discovered[i].holder_side].sets[discovered[i].holder_slot];
                if (item == NULL || (item->try_heal_fixed == 0 &&
                    item->try_heal_denominator == 0)) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t requested = item->try_heal_fixed != 0 ? item->try_heal_fixed :
                    (uint16_t)(holder_set->stats[0] / item->try_heal_denominator);
                PokemonEventFrame heal_gate;
                int heal_status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_TRY_HEAL,
                    .source = {POKEMON_ENTITY_NONE, 0, 0},
                    .target_side = discovered[i].holder_side,
                    .target_slot = discovered[i].holder_slot,
                    .source_effect = {POKEMON_SOURCE_EFFECT_ITEM, descriptor->source_id},
                    .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = requested},
                }, &heal_gate);
                if (heal_status != POKEMON_OK) {
                    battle->event_depth--;
                    return heal_status;
                }
                if (heal_gate.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                    heal_gate.relay.value.u32 == 0) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_UNDEFINED:
                break;
            case POKEMON_HANDLER_OP_RETURN_TRUE:
                frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                    .value.boolean = 1};
                break;
            case POKEMON_HANDLER_OP_RETURN_NUMBER_ZERO:
                frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NUMBER,
                    .value.number = 0.0};
                break;
            case POKEMON_HANDLER_OP_DAMAGE_EVENT_TARGET_BY_RELAY_IMMEDIATE: {
                uint16_t amount = frame.relay.value.u32 > UINT16_MAX ?
                    UINT16_MAX : (uint16_t)frame.relay.value.u32;
                uint16_t applied = 0;
                status = apply_direct_damage_inner(
                    battle, &(PokemonDirectDamageRequest){
                        .source = {POKEMON_ENTITY_NONE, 0, 0},
                        .target = {POKEMON_ENTITY_POKEMON,
                            input->target_side, input->target_slot},
                        .source_effect = {POKEMON_SOURCE_EFFECT_NONE, 0},
                        .amount = amount,
                    }, &applied);
                if (status == POKEMON_OK) status = drain_faints(battle);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_SOURCE_HP_BELOW_TARGET: {
                const PokemonMutable *source_state = &battle->sides[
                    frame.source.side].state[frame.source.slot];
                const PokemonMutable *target_state = &battle->sides[
                    frame.target.side].state[frame.target.slot];
                if (source_state->hp < target_state->hp) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 1};
                } else {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NULL};
                    frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE:
                frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                    .value.boolean = 0};
                frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                frame.cancelling_owner = discovered[i].owner;
                frame.cancelling_handler_id = descriptor->id;
                break;
            case POKEMON_HANDLER_OP_RETURN_NULL:
                frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NULL};
                frame.cancellation = POKEMON_EVENT_CANCEL_NULL;
                frame.cancelling_owner = discovered[i].owner;
                frame.cancelling_handler_id = descriptor->id;
                break;
            case POKEMON_HANDLER_OP_SUPPRESS_ACTIVE_MOVE_PROTOCOL_TARGET:
                if (battle->move_frame_depth == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                battle->move_frames[
                    battle->move_frame_depth - 1u].suppress_protocol_target = 1;
                break;
            case POKEMON_HANDLER_OP_RETURN_NOT_FAIL:
                /* Pinned Showdown Battle.NOT_FAIL is the empty string. Its
                 * TryHit normalizer preserves only that exact sentinel while
                 * null/false/undefined become ordinary failure. */
                frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_NOT_FAIL};
                frame.cancellation = POKEMON_EVENT_CANCEL_NOT_FAIL;
                frame.cancelling_owner = discovered[i].owner;
                frame.cancelling_handler_id = descriptor->id;
                break;
            case POKEMON_HANDLER_OP_DROP_BOOST_STAT:
                frame.relay.value.boosts.present[op->argument] = 0;
                frame.relay.value.boosts.delta[op->argument] = 0;
                break;
            case POKEMON_HANDLER_OP_DROP_NEGATIVE_BOOST_STAT:
                if (frame.relay.value.boosts.present[op->argument] &&
                    frame.relay.value.boosts.delta[op->argument] < 0) {
                    frame.relay.value.boosts.present[op->argument] = 0;
                    frame.relay.value.boosts.delta[op->argument] = 0;
                }
                break;
            case POKEMON_HANDLER_OP_DROP_ALL_NEGATIVE_BOOSTS:
                for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
                    if (frame.relay.value.boosts.present[stat] &&
                        frame.relay.value.boosts.delta[stat] < 0) {
                        frame.relay.value.boosts.present[stat] = 0;
                        frame.relay.value.boosts.delta[stat] = 0;
                    }
                }
                break;
            case POKEMON_HANDLER_OP_ZERO_POSITIVE_BOOST_STAT:
                if (frame.relay.value.boosts.present[op->argument] &&
                    frame.relay.value.boosts.delta[op->argument] > 0) {
                    frame.relay.value.boosts.delta[op->argument] = 0;
                }
                break;
            case POKEMON_HANDLER_OP_NEST_EVENT: {
                PokemonRelay nested_relay = {.kind = POKEMON_RELAY_UNDEFINED};
                PokemonEventFrame nested_frame;
                int nested_status = run_event_inner(battle, &(PokemonEventInput){
                    .event = (PokemonEventId)op->argument,
                    .source = input->source,
                    .target_side = input->target_side,
                    .target_slot = input->target_slot,
                    .source_effect = input->source_effect,
                    .relay = nested_relay,
                    .context_kind = input->context_kind,
                    .context = input->context,
                    .suppress_handler_trace = 1,
                }, &nested_frame);
                if (nested_status != POKEMON_OK) {
                    battle->event_depth--;
                    return nested_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_EACH_EVENT: {
                int nested_status = run_weather_change_each_event(battle);
                if (nested_status != POKEMON_OK) {
                    battle->event_depth--;
                    return nested_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_PROJECT_HOLDER_WEATHER_FORM: {
                const PokemonWeatherFormPolicy *policy = weather_form_policy(
                    battle, (uint16_t)op->argument);
                status = project_weather_form(
                    battle, discovered[i].holder_side,
                    discovered[i].holder_slot, policy);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_FROM_MOVE: {
                if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                    input->context.move.move == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                const PokemonMoveData *move = input->context.move.move;
                if (holder->hp == 0 ||
                    move->category == POKEMON_CATEGORY_STATUS ||
                    (battle->data->has_non_interacting_type &&
                     move->type == battle->data->non_interacting_type) ||
                    has_type(holder, move->type)) {
                    applicable = 0;
                    break;
                }
                if (move->type >= battle->data->type_count) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                holder->effective_types[0] = move->type;
                holder->effective_types[1] = 0;
                holder->effective_type_count = 1;
                break;
            }
            case POKEMON_HANDLER_OP_SET_HOLDER_EFFECTIVE_TYPE_LITERAL: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint8_t type = (uint8_t)op->argument;
                if (has_type(holder, type)) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                holder->effective_types[0] = type;
                holder->effective_types[1] = 0;
                holder->effective_type_count = 1;
                break;
            }
            case POKEMON_HANDLER_OP_SAMPLE_HOLDER_MOVE_SLOT_TYPE: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint16_t excluded_catalog_id =
                    (uint16_t)(op->argument & UINT32_C(0xffff));
                uint8_t candidates[POKEMON_MOVE_CAPACITY];
                uint8_t candidate_count = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    uint16_t move_id = current_move_id(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, slot);
                    if (move_id == 0) continue;
                    const PokemonMoveData *candidate = find_move(battle, move_id);
                    if (candidate == NULL) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    if (candidate->catalog_id == excluded_catalog_id ||
                        has_type(holder, candidate->type)) continue;
                    candidates[candidate_count++] = candidate->type;
                }
                if (candidate_count == 0) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint32_t selected = 0;
                status = draw_below(battle,
                    (PokemonDrawLabel)(op->argument >> 24),
                    candidate_count, &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                holder->effective_types[0] = candidates[selected];
                holder->effective_types[1] = 0;
                holder->effective_type_count = 1;
                break;
            }
            case POKEMON_HANDLER_OP_SAMPLE_SOURCE_TYPE_RESPONSE: {
                const PokemonTypeResponsePolicy *policy =
                    type_response_policy(battle, (uint16_t)op->argument);
                const PokemonMutable *target = &battle->sides[
                    input->target_side].state[input->target_slot];
                PokemonMutable *source = &battle->sides[input->source.side].state[
                    input->source.slot];
                if (policy == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (!target->last_move_used.present) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    break;
                }
                const PokemonMoveData *last_used_move = find_move(
                    battle, target->last_move_used.move_id);
                if (last_used_move == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t attack_type = last_used_move->catalog_id ==
                        policy->move_type_override_catalog_id ?
                    policy->move_type_override :
                    target->last_move_used.resolved_type;
                if (attack_type >= battle->data->type_count) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t candidates[POKEMON_TYPE_CAPACITY];
                uint8_t candidate_count = 0;
                for (uint8_t candidate_index = 0;
                     candidate_index < policy->candidate_count;
                     candidate_index++) {
                    uint8_t candidate = policy->candidate_types[candidate_index];
                    uint8_t multiplier = battle->data->type_chart[
                        (size_t)attack_type * battle->data->type_count + candidate];
                    if (multiplier != policy->resistant_multiplier_q2 &&
                        multiplier != policy->immune_multiplier_q2) continue;
                    if (policy->exclude_source_current_types &&
                        has_type(source, candidate)) continue;
                    candidates[candidate_count++] = candidate;
                }
                if (candidate_count == 0) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    break;
                }
                uint32_t selected = 0;
                status = draw_below(battle, POKEMON_DRAW_TYPE_RESPONSE_SELECTION,
                    candidate_count, &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                source->effective_types[0] = candidates[selected];
                source->effective_types[1] = 0;
                source->effective_type_count = 1;
                break;
            }
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_RETALIATION: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL ||
                    condition->kind != POKEMON_VOLATILE_PREPARED_RETALIATION) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                memset(&condition->payload.retaliation, 0,
                    sizeof(condition->payload.retaliation));
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_RETALIATION_CLASS: {
                applicable =
                    input->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE &&
                    input->source.kind == POKEMON_ENTITY_POKEMON &&
                    input->source.side != discovered[i].holder_side &&
                    (input->context.damage.retaliation_class_mask &
                        op->argument) != 0;
                break;
            }
            case POKEMON_HANDLER_OP_CAPTURE_OWNER_RETALIATION_X2: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL || frame.relay.kind != POKEMON_RELAY_U32 ||
                    input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint32_t damage = frame.relay.value.u32;
                condition->payload.retaliation.damage =
                    damage > UINT32_MAX / 2u ? UINT32_MAX : damage * 2u;
                condition->payload.retaliation.source_side = input->source.side;
                condition->payload.retaliation.source_position = 0;
                condition->payload.retaliation.captured = 1;
                break;
            }
            case POKEMON_HANDLER_OP_REQUIRE_OWNER_RETALIATION_CAPTURE: {
                const PokemonMutable *source_state = &battle->sides[
                    input->source.side].state[input->source.slot];
                const PokemonVolatileState *condition = NULL;
                for (size_t state_index = 0;
                     state_index < source_state->volatile_count; state_index++) {
                    if (source_state->volatiles[state_index].descriptor_id ==
                            (uint16_t)op->argument) {
                        condition = &source_state->volatiles[state_index];
                        break;
                    }
                }
                if (condition == NULL ||
                    condition->kind != POKEMON_VOLATILE_PREPARED_RETALIATION ||
                    !condition->payload.retaliation.captured) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_INITIALIZE_OWNER_STORED_DAMAGE: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL ||
                    condition->kind != POKEMON_VOLATILE_STORED_DAMAGE) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                memset(&condition->payload.stored_damage, 0,
                    sizeof(condition->payload.stored_damage));
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_DAMAGE_FROM_MOVE_SOURCE:
                applicable =
                    input->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE &&
                    input->source.kind == POKEMON_ENTITY_POKEMON;
                break;
            case POKEMON_HANDLER_OP_ACCUMULATE_OWNER_STORED_DAMAGE: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL ||
                    condition->kind != POKEMON_VOLATILE_STORED_DAMAGE ||
                    frame.relay.kind != POKEMON_RELAY_U32 ||
                    input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint32_t value = frame.relay.value.u32;
                condition->payload.stored_damage.value =
                    UINT32_MAX - condition->payload.stored_damage.value < value ?
                        UINT32_MAX :
                        condition->payload.stored_damage.value + value;
                condition->payload.stored_damage.last_source = input->source;
                condition->payload.stored_damage.captured = 1;
                break;
            }
            case POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                const PokemonConstructedHitTemplate *template =
                    find_constructed_hit_template(
                        battle, (uint16_t)op->argument);
                if (condition == NULL || template == NULL ||
                    condition->kind != POKEMON_VOLATILE_STORED_DAMAGE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (condition->duration != 1) {
                    applicable = 0;
                    break;
                }
                if (!condition->payload.stored_damage.captured ||
                    condition->payload.stored_damage.last_source.kind !=
                        POKEMON_ENTITY_POKEMON) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                PokemonEntityRef target =
                    condition->payload.stored_damage.last_source;
                if (target.side >= POKEMON_SIDES ||
                    target.slot >= battle->team_sizes[target.side] ||
                    target.slot != battle->sides[target.side].active ||
                    battle->sides[target.side].state[target.slot].hp == 0) {
                    if (template->target_policy !=
                            POKEMON_CONSTRUCTED_TARGET_LAST_SOURCE_OR_CURRENT_FOE) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    uint8_t target_side =
                        (uint8_t)(1u - discovered[i].holder_side);
                    target = (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        target_side, battle->sides[target_side].active};
                }
                PokemonVolatileState snapshot = *condition;
                status = execute_stored_damage_constructed_hit(
                    battle, template,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side,
                        discovered[i].holder_slot},
                    target, &snapshot);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                condition = owner_volatile(battle, &discovered[i]);
                if (condition != NULL) {
                    status = end_and_remove_volatile_exact(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, snapshot.descriptor_id,
                        snapshot.state_generation, snapshot.effect_order,
                        POKEMON_CONDITION_REASON_HANDLER);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                }
                frame.relay = (PokemonRelay){
                    .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                frame.cancelling_owner = discovered[i].owner;
                frame.cancelling_handler_id = descriptor->id;
                applicable = 0;
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_OWNER_SOURCE_MOVE_SELECTOR: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL ||
                    condition->source_effect.kind != POKEMON_SOURCE_EFFECT_MOVE ||
                    condition->source_effect.id == 0 ||
                    frame.relay.kind != POKEMON_RELAY_SELECTOR) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.selector = condition->source_effect.id;
                break;
            }
            case POKEMON_HANDLER_OP_CLAIM_QUEUED_SELECTED_MOVE: {
                PokemonVolatileState *installed = owner_volatile(
                    battle, &discovered[i]);
                if (installed == NULL ||
                    installed->source.kind != POKEMON_ENTITY_POKEMON ||
                    installed->source_effect.kind != POKEMON_SOURCE_EFFECT_MOVE ||
                    input->source.kind != POKEMON_ENTITY_POKEMON ||
                    input->source.side != discovered[i].holder_side ||
                    input->source.slot != discovered[i].holder_slot) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonEntityRef move_user = installed->source;
                uint16_t move_id = installed->source_effect.id;
                if (move_user.side >= POKEMON_SIDES ||
                    move_user.slot != battle->sides[move_user.side].active ||
                    battle->sides[move_user.side].state[move_user.slot].hp == 0) {
                    applicable = 0;
                    break;
                }
                size_t queued_index = battle->queue.count;
                for (size_t queued = 0; queued < battle->queue.count; queued++) {
                    const PokemonAction *candidate = &battle->queue.values[queued];
                    if (candidate->kind != POKEMON_ACTION_MOVE ||
                        candidate->side != move_user.side ||
                        candidate->selected_move_id != move_id) continue;
                    if (queued_index != battle->queue.count) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    queued_index = queued;
                }
                if (queued_index == battle->queue.count) {
                    applicable = 0;
                    break;
                }
                PokemonAction claimed = battle->queue.values[queued_index];
                const PokemonMoveData *claimed_move = find_move(battle, move_id);
                PokemonMutable *user_state = &battle->sides[
                    move_user.side].state[move_user.slot];
                if (claimed_move == NULL ||
                    user_state->active_move_actions == UINT32_MAX) {
                    battle->event_depth--;
                    return claimed_move == NULL ? POKEMON_INVALID_CONFIGURATION :
                        POKEMON_CAPACITY_EXCEEDED;
                }
                size_t volatile_position = (size_t)(installed -
                    battle->sides[discovered[i].holder_side].state[
                        discovered[i].holder_slot].volatiles);
                PokemonVolatileState removed = *installed;
                remove_volatile_at(&battle->sides[discovered[i].holder_side].state[
                    discovered[i].holder_slot], volatile_position);
                int claim_status = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                    POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_MOVE,
                    POKEMON_CONDITION_VALUE_DURATION,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    removed.kind, removed.duration, 0);
                if (claim_status != POKEMON_OK) {
                    battle->event_depth--;
                    return claim_status;
                }
                for (size_t queued = queued_index + 1;
                     queued < battle->queue.count; queued++) {
                    battle->queue.values[queued - 1] = battle->queue.values[queued];
                }
                battle->queue.count--;
                user_state->active_move_actions++;
                claim_status = execute_selected_move_after_before_move(
                    battle, &claimed, claimed_move, input->source, 1);
                if (claim_status != POKEMON_OK) {
                    battle->event_depth--;
                    return claim_status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL: {
                const PokemonMoveCallPool *pool = find_move_call_pool(
                    battle, (uint16_t)op->argument);
                if (pool == NULL || pool->candidate_count == 0) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint32_t selected = 0;
                status = draw_below(
                    battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION,
                    pool->candidate_count, &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                uint16_t catalog_id = battle->data->move_call_pool_candidates[
                    pool->candidate_offset + selected];
                const PokemonMoveIdentity *identity = pokemon_move_identity(
                    battle->data, catalog_id);
                if (identity == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (identity->executable_id == 0) {
                    battle->event_depth--;
                    return POKEMON_UNSUPPORTED_CAPABILITY;
                }
                const PokemonActiveMoveFrame *parent =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (parent == NULL ||
                    parent->invocation.move_id != pool->caller_move_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = identity->executable_id,
                    .user = parent->invocation.user,
                    .target_request = {POKEMON_TARGET_REQUEST_RESOLVE, {0}},
                    .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                        pool->caller_move_id},
                    .inherited_priority = parent->priority,
                    .selected_slot = UINT8_MAX,
                };
                status = invoke_move_inner(battle, child);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_FIXED_MOVE: {
                const PokemonMoveData *called = find_move(
                    battle, (uint16_t)op->argument);
                const PokemonActiveMoveFrame *parent =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (called == NULL || parent == NULL ||
                    parent->invocation.move_id != descriptor->source_id) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = called->id,
                    .user = parent->invocation.user,
                    .target_request = {POKEMON_TARGET_REQUEST_RESOLVE, {0}},
                    .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    .inherited_priority = parent->priority,
                    .selected_slot = UINT8_MAX,
                };
                status = invoke_move_inner(battle, child);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_USER_SLOTS: {
                const PokemonActiveMoveFrame *parent =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (parent == NULL ||
                    parent->invocation.move_id != descriptor->source_id ||
                    parent->invocation.user.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonSide *user_side = &battle->sides[
                    parent->invocation.user.side];
                const PokemonMutable *user = &user_side->state[
                    parent->invocation.user.slot];
                uint8_t candidates[POKEMON_MOVE_CAPACITY];
                size_t candidate_count = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    const PokemonMoveData *candidate =
                        find_move(battle, user->move_ids[slot]);
                    if (candidate != NULL &&
                        (candidate->call_eligibility & op->argument) != 0) {
                        candidates[candidate_count++] = (uint8_t)slot;
                    }
                }
                if (candidate_count == 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint32_t selected = 0;
                status = draw_below(
                    battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION,
                    (uint32_t)candidate_count, &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                uint8_t selected_slot = candidates[selected];
                if (user->pp[selected_slot] == 0) break;
                const PokemonMoveData *called = find_move(
                    battle, user->move_ids[selected_slot]);
                if (called == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = called->id,
                    .user = parent->invocation.user,
                    .target_request = {POKEMON_TARGET_REQUEST_RESOLVE, {0}},
                    .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    .inherited_priority = parent->priority,
                    .selected_slot = UINT8_MAX,
                };
                status = invoke_move_inner(battle, child);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_CALL_MOVE_FROM_PARTY_SLOTS: {
                const PokemonActiveMoveFrame *parent =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (parent == NULL ||
                    parent->invocation.move_id != descriptor->source_id ||
                    parent->invocation.user.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                const PokemonSide *user_side = &battle->sides[
                    parent->invocation.user.side];
                uint16_t candidates[
                    (POKEMON_TEAM_CAPACITY - 1) * POKEMON_MOVE_CAPACITY];
                size_t candidate_count = 0;
                for (size_t position = 0;
                     position < battle->team_sizes[parent->invocation.user.side];
                     position++) {
                    uint8_t member_slot = user_side->party_order[position];
                    if (member_slot == parent->invocation.user.slot) continue;
                    const PokemonMutable *member = &user_side->state[member_slot];
                    for (size_t move_slot = 0;
                         move_slot < POKEMON_MOVE_CAPACITY; move_slot++) {
                        const PokemonMoveData *candidate = find_move(
                            battle, member->move_ids[move_slot]);
                        if (candidate != NULL &&
                            (candidate->call_eligibility & op->argument) != 0) {
                            candidates[candidate_count++] = candidate->id;
                        }
                    }
                }
                if (candidate_count == 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint32_t selected = 0;
                status = draw_below(
                    battle, POKEMON_DRAW_MOVE_DELEGATION_SELECTION,
                    (uint32_t)candidate_count, &selected);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                const PokemonMoveData *called = find_move(
                    battle, candidates[selected]);
                if (called == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMoveInvocation child = {
                    .entry = POKEMON_MOVE_ENTRY_CALLED,
                    .move_id = called->id,
                    .user = parent->invocation.user,
                    .target_request = {POKEMON_TARGET_REQUEST_RESOLVE, {0}},
                    .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    .inherited_priority = parent->priority,
                    .selected_slot = UINT8_MAX,
                };
                status = invoke_move_inner(battle, child);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT: {
                const PokemonActiveMoveFrame *parent =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (parent == NULL ||
                    parent->invocation.move_id != descriptor->source_id ||
                    parent->invocation.user.kind != POKEMON_ENTITY_POKEMON ||
                    parent->resolved_target.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonEntityRef source_ref = parent->invocation.user;
                PokemonEntityRef target_ref = parent->resolved_target;
                PokemonMutable *source = &battle->sides[source_ref.side]
                    .state[source_ref.slot];
                const PokemonMutable *target = &battle->sides[target_ref.side]
                    .state[target_ref.slot];
                uint8_t source_slot = POKEMON_MOVE_CAPACITY;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (source->move_ids[slot] == descriptor->source_id) {
                        source_slot = (uint8_t)slot;
                        break;
                    }
                }
                uint16_t copied_id = target->last_move_id;
                const PokemonMoveData *copied = find_move(battle, copied_id);
                uint32_t eligibility = op->argument & UINT32_C(0xff);
                uint8_t rejected = source->transformed ||
                    source_slot == POKEMON_MOVE_CAPACITY || copied == NULL ||
                    volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE) >= 0 ||
                    (copied->copy_eligibility & eligibility) == 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    rejected |= source->move_ids[slot] == copied_id;
                }
                if (rejected) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint8_t initial_pp = copied->raw_pp;
                uint8_t cap = (uint8_t)(op->argument >> 16);
                if (cap != 0 && initial_pp > cap) initial_pp = cap;
                uint16_t calculated_max = (uint16_t)copied->raw_pp *
                    (uint16_t)(5u + source->pp_ups[source_slot]) / 5u;
                if (calculated_max == 0 || calculated_max > UINT8_MAX ||
                    initial_pp > calculated_max) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                source->move_ids[source_slot] = copied_id;
                source->pp[source_slot] = initial_pp;
                source->max_pp[source_slot] = (uint8_t)calculated_max;
                if ((op->argument & POKEMON_MOVE_COPY_PERSIST_BASE) != 0) {
                    source->base_move_ids[source_slot] = copied_id;
                    source->base_pp[source_slot] = initial_pp;
                    source->base_max_pp[source_slot] = (uint8_t)calculated_max;
                    source->temporary_move_slots &=
                        (uint8_t)~(1u << source_slot);
                } else {
                    source->temporary_move_slots |=
                        (uint8_t)(1u << source_slot);
                }
                break;
            }
            case POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BATTLE_PROFILE: {
                const PokemonTransformPolicy *policy = transform_policy(
                    battle->data, (uint16_t)op->argument);
                PokemonMutable *source = &battle->sides[frame.source.side]
                    .state[frame.source.slot];
                const PokemonMutable *target = &battle->sides[frame.target.side]
                    .state[frame.target.slot];
                uint8_t rejected = policy == NULL || source->hp == 0 ||
                    source->fainted || target->hp == 0 || target->fainted ||
                    (policy->reject_source_transformed && source->transformed) ||
                    (policy->reject_target_transformed && target->transformed) ||
                    (policy->reject_target_substitute &&
                     volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE) >= 0);
                if (rejected) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                const PokemonSpeciesData *species = find_species(
                    battle, target->species_id);
                const PokemonSet *source_set = &battle->sides[frame.source.side]
                    .sets[frame.source.slot];
                const PokemonSpeciesIdentity *source_species =
                    species_identity_by_executable_id(
                        battle->data, source_set->species_id);
                const PokemonSpeciesIdentity *target_species =
                    species_identity_by_executable_id(
                        battle->data, target->species_id);
                const PokemonAbilityData *ability = find_ability(
                    battle, target->ability_id);
                PokemonPersonalMoveProfile profile = {0};
                if (species == NULL || species->type_count == 0 ||
                    species->type_count > 2 || source_species == NULL ||
                    target_species == NULL || ability == NULL ||
                    policy->copied_move_pp_cap == 0 ||
                    policy->personal_move_profile_kind == 0 ||
                    battle->generation->resolve_personal_move_profile(
                        policy->personal_move_profile_kind,
                        battle->sides[frame.target.side].sets[
                            frame.target.slot].ivs, &profile) != POKEMON_OK ||
                    profile.kind != policy->personal_move_profile_kind) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t transformed_speed = 0;
                if (battle->generation->recalculate_species_stat == NULL ||
                    battle->generation->recalculate_species_stat(
                        source_set->stats[5], source_species->base_stats[5],
                        target_species->base_stats[5], source_set->ivs[5],
                        source_set->level, (uint8_t)source_set->nature,
                        &transformed_speed) != POKEMON_OK) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t copied_pp[POKEMON_MOVE_CAPACITY] = {0};
                uint8_t copied_max_pp[POKEMON_MOVE_CAPACITY] = {0};
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (target->move_ids[slot] == 0) continue;
                    const PokemonMoveData *move = find_move(
                        battle, target->move_ids[slot]);
                    if (move == NULL || move->raw_pp == 0) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    copied_pp[slot] = move->raw_pp < policy->copied_move_pp_cap ?
                        move->raw_pp : policy->copied_move_pp_cap;
                    uint8_t pp_ups = move->no_pp_boosts ? 0 : source->pp_ups[slot];
                    uint16_t maximum = (uint16_t)move->raw_pp *
                        (uint16_t)(5u + pp_ups) / 5u;
                    if (maximum == 0 || maximum > UINT8_MAX ||
                        copied_pp[slot] > maximum) {
                        battle->event_depth--;
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    copied_max_pp[slot] = (uint8_t)maximum;
                }
                source->species_id = target->species_id;
                memcpy(source->effective_types, target->effective_types,
                    sizeof(source->effective_types));
                source->effective_type_count = target->effective_type_count;
                memcpy(source->stored_stats, target->stored_stats,
                    sizeof(source->stored_stats));
                /* The current turn's action queue is already fixed, but
                 * subsequent eachEvent ordering observes the new profile. */
                source->cached_speed = transformed_speed;
                memcpy(source->boosts, target->boosts, sizeof(source->boosts));
                memcpy(source->move_ids, target->move_ids, sizeof(source->move_ids));
                memcpy(source->pp, copied_pp, sizeof(source->pp));
                memcpy(source->max_pp, copied_max_pp, sizeof(source->max_pp));
                source->temporary_move_slots = 0;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    if (source->move_ids[slot] != 0) {
                        source->temporary_move_slots |= (uint8_t)(1u << slot);
                    }
                }
                source->personal_move_profile = profile;
                source->transformed = 1;
                status = replace_pokemon_ability(
                    battle, frame.source.side, frame.source.slot,
                    frame.target.side, frame.target.slot,
                    policy->copied_ability_runs_start);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_TARGET_STATUS_MASK: {
                const PokemonActiveMoveFrame *active =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (active == NULL ||
                    active->invocation.move_id != descriptor->source_id ||
                    active->resolved_target.kind != POKEMON_ENTITY_POKEMON ||
                    active->resolved_target.side >= POKEMON_SIDES ||
                    active->resolved_target.slot >= battle->team_sizes[
                        active->resolved_target.side]) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonStatus target_status = battle->sides[
                    active->resolved_target.side].state[
                        active->resolved_target.slot].status.kind;
                applicable = target_status != POKEMON_STATUS_NONE &&
                    target_status < 32 &&
                    (op->argument & (UINT32_C(1) << target_status)) != 0;
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_TARGET_MAJOR_STATUS: {
                const PokemonActiveMoveFrame *active =
                    battle->move_frame_depth == 0 ? NULL :
                    &battle->move_frames[battle->move_frame_depth - 1];
                if (active == NULL ||
                    active->invocation.move_id != descriptor->source_id ||
                    active->resolved_target.kind != POKEMON_ENTITY_POKEMON) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonStatus before = battle->sides[
                    active->resolved_target.side].state[
                        active->resolved_target.slot].status.kind;
                status = clear_major_status(
                    battle, active->resolved_target.side,
                    active->resolved_target.slot,
                    POKEMON_CONDITION_REASON_HANDLER);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                const PokemonEffectOp cure = {
                    .kind = POKEMON_EFFECT_CURE_STATUS,
                    .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                    .target = POKEMON_EFFECT_TARGET_MOVE_TARGET,
                    .chance = 100,
                    .argument = before,
                };
                status = trace_effect(
                    battle, &cure, POKEMON_EFFECT_APPLIED,
                    descriptor->source_id,
                    input->source.side, input->source.slot,
                    active->resolved_target.side,
                    active->resolved_target.slot,
                    before, POKEMON_STATUS_NONE);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_PAY_MAX_HP_FRACTION_AND_MAXIMIZE_HOLDER_STAT: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint16_t max_hp = battle->sides[discovered[i].holder_side].sets[
                    discovered[i].holder_slot].stats[0];
                uint8_t stat = (uint8_t)(op->argument >> 16);
                uint8_t numerator = (uint8_t)(op->argument >> 8);
                uint8_t denominator = (uint8_t)op->argument;
                uint16_t cost = battle->generation->fraction(
                    max_hp, numerator, denominator);
                if (max_hp == 1 || cost == 0 || holder->hp <= cost ||
                    holder->boosts[stat] >=
                        battle->generation->stages->maximum) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                    break;
                }
                uint16_t applied = 0;
                PokemonEntityRef holder_ref = {
                    POKEMON_ENTITY_POKEMON, discovered[i].holder_side,
                    discovered[i].holder_slot};
                status = apply_direct_damage_inner(
                    battle, &(PokemonDirectDamageRequest){
                        .source = holder_ref, .target = holder_ref,
                        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE,
                            descriptor->source_id},
                        .amount = cost,
                    }, &applied);
                if (status != POKEMON_OK || applied != cost) {
                    battle->event_depth--;
                    return status == POKEMON_OK ?
                        POKEMON_INVALID_CONFIGURATION : status;
                }
                const PokemonEffectOp boost = {
                    .kind = POKEMON_EFFECT_BOOST,
                    .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                    .target = POKEMON_EFFECT_TARGET_USER,
                    .chance = 100,
                    .argument = stat,
                    .amount = (int8_t)(
                        battle->generation->stages->maximum -
                        holder->boosts[stat]),
                };
                const PokemonEffectOp *boosts[] = {&boost};
                status = apply_boost_effects(
                    battle, boosts, 1, descriptor->source_id,
                    discovered[i].holder_side, discovered[i].holder_slot,
                    discovered[i].holder_side, discovered[i].holder_slot);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_FAINT_HOLDER: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                PokemonMutable *fainting = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (fainting->hp == 0 || fainting->fainted) break;
                PokemonEntityRef condition_source = condition->source;
                uint16_t condition_descriptor = condition->descriptor_id;
                fainting->hp = 0;
                status = queue_faint(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side,
                        discovered[i].holder_slot},
                    condition_source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_CONDITION,
                        condition_descriptor});
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
            case POKEMON_HANDLER_OP_APPLY_VOLATILE_TO_ADMITTED_ACTIVES: {
                const PokemonMoveData *field_move = input->context.move.move;
                uint8_t any_result = 0;
                for (size_t target_side = 0; target_side < POKEMON_SIDES;
                     target_side++) {
                    size_t target_slot = battle->sides[target_side].active;
                    PokemonMutable *target_state = &battle->sides[target_side]
                        .state[target_slot];
                    if (target_state->hp == 0 || target_state->fainted) continue;
                    uint8_t invulnerability_admitted = 0;
                    status = resolve_invulnerability(
                        battle, field_move, input->source.side,
                        input->source.slot, target_side, target_slot,
                        &invulnerability_admitted);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                    if (!invulnerability_admitted) {
                        append_event(battle, (PokemonEvent){
                            .kind = POKEMON_EVENT_MISS,
                            .side = input->source.side,
                            .target_side = (uint8_t)target_side,
                            .species_id = battle->sides[input->source.side]
                                .sets[input->source.slot].species_id,
                            .move_id = field_move->id,
                        });
                        any_result = 1;
                        continue;
                    }
                    PokemonImmunityCause cause = POKEMON_IMMUNITY_NONE;
                    uint16_t effect_id = 0;
                    PokemonHandlerId handler_id = 0;
                    uint8_t emit_immunity = 1;
                    PokemonEventCancellation cancellation =
                        POKEMON_EVENT_CANCEL_NONE;
                    status = run_try_hit_handlers(
                        battle, input->source.side, input->source.slot,
                        target_side, target_slot, field_move, &cause,
                        &effect_id, &handler_id, &emit_immunity, &cancellation);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                    if (cancellation == POKEMON_EVENT_CANCEL_NULL) {
                        if (emit_immunity) append_event(battle, (PokemonEvent){
                            .kind = POKEMON_EVENT_IMMUNE,
                            .side = (uint8_t)target_side,
                            .target_side = input->source.side,
                            .species_id = battle->sides[target_side]
                                .sets[target_slot].species_id,
                            .move_id = field_move->id,
                            .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                            .handler_id = handler_id,
                        });
                        any_result = 1;
                        continue;
                    }
                    if (volatile_index(target_state,
                            (PokemonVolatileKind)op->argument) >= 0) continue;
                    uint8_t installed = CONDITION_INSTALL_FAILED;
                    status = install_condition_volatile(
                        battle,
                        (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                            (uint8_t)target_side, (uint8_t)target_slot},
                        input->source,
                        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                            field_move->id},
                        (PokemonVolatileKind)op->argument,
                        POKEMON_CONDITION_REASON_MOVE, &installed);
                    if (status != POKEMON_OK) {
                        battle->event_depth--;
                        return status;
                    }
                    any_result |= installed == CONDITION_INSTALL_APPLIED;
                }
                if (!any_result) {
                    frame.relay = (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_ENSURE_HOLDER_VOLATILE: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileKind kind = (PokemonVolatileKind)op->argument;
                if (volatile_index(holder, kind) >= 0) break;
                uint8_t installed = CONDITION_INSTALL_FAILED;
                status = install_condition_volatile(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        discovered[i].holder_side, discovered[i].holder_slot},
                    input->source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    kind, POKEMON_CONDITION_REASON_HANDLER, &installed);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                if (installed != CONDITION_INSTALL_APPLIED) applicable = 0;
                break;
            }
            case POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                condition->counter = (uint8_t)op->argument;
                break;
            }
            case POKEMON_HANDLER_OP_ADVANCE_OWNER_VOLATILE_COUNTER: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                const PokemonConditionRule *owner_rule = condition == NULL ?
                    NULL : condition_rule_by_descriptor(
                        battle, condition->descriptor_id);
                if (condition == NULL || owner_rule == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint32_t multiplier = op->argument >> 16;
                uint32_t cap = op->argument & UINT32_C(0xffff);
                uint32_t next = (uint32_t)condition->counter * multiplier;
                condition->counter = (uint8_t)(next < cap ? next : cap);
                condition->duration = owner_rule->lifecycle_duration.minimum;
                break;
            }
            case POKEMON_HANDLER_OP_INCREMENT_OWNER_VOLATILE_COUNTER_UP_TO: {
                PokemonVolatileState *condition = owner_volatile(
                    battle, &discovered[i]);
                if (condition == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (condition->counter < op->argument) condition->counter++;
                break;
            }
            case POKEMON_HANDLER_OP_MULTIPLY_RELAY_BY_HOLDER_VOLATILE_COUNTER: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                int condition_index = volatile_index(
                    holder, (PokemonVolatileKind)op->argument);
                if (condition_index < 0 ||
                    holder->volatiles[condition_index].counter == 0 ||
                    frame.relay.value.u32 > UINT32_MAX /
                        holder->volatiles[condition_index].counter) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 *=
                    holder->volatiles[condition_index].counter;
                direct_relay_mutated = 1;
                break;
            }
            case POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32:
                if (frame.relay.value.u32 > UINT32_MAX / op->argument) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 *= op->argument;
                direct_relay_mutated = 1;
                break;
            case POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN: {
                const PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                const PokemonAttackRecord *record = &battle->sides[
                    discovered[i].holder_side].state[
                        discovered[i].holder_slot].last_attacked_by;
                PokemonEntityRef target = active->resolved_target;
                applicable = record->present && record->this_turn &&
                    record->damage > 0 &&
                    record->damage_was_number &&
                    record->source.kind == POKEMON_ENTITY_POKEMON &&
                    target.kind == POKEMON_ENTITY_POKEMON &&
                    record->source.side == target.side &&
                    record->source.slot == target.slot;
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_COUNTER_AT_LEAST:
            case POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileKind kind =
                    (PokemonVolatileKind)(op->argument >> 16);
                int index = volatile_index(holder, kind);
                uint8_t reject = op->opcode ==
                    POKEMON_HANDLER_OP_RETURN_FALSE_UNLESS_HOLDER_VOLATILE ?
                    index < 0 : index >= 0 && holder->volatiles[index].counter >=
                        (uint8_t)(op->argument & UINT32_C(0xffff));
                if (reject) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_VOLATILE_MASK: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint8_t reject = 0;
                for (size_t condition = 0;
                     condition < holder->volatile_count; condition++) {
                    PokemonVolatileKind kind = holder->volatiles[condition].kind;
                    reject |= kind < 32u &&
                        (op->argument & (UINT32_C(1) << kind)) != 0;
                }
                if (reject) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                    applicable = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_RELAY_FROM_HOLDER_VOLATILE_COUNTER_TIMES: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                PokemonVolatileKind kind =
                    (PokemonVolatileKind)(op->argument >> 16);
                uint32_t scale = op->argument & UINT32_C(0xffff);
                int index = volatile_index(holder, kind);
                if (index < 0 || holder->volatiles[index].counter == 0 ||
                    holder->volatiles[index].counter > UINT32_MAX / scale) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                frame.relay.value.u32 =
                    holder->volatiles[index].counter * scale;
                direct_relay_mutated = 1;
                break;
            }
            case POKEMON_HANDLER_OP_HEAL_HOLDER_BY_COUNTER_POLICY: {
                const PokemonCounterHealPolicy *policy =
                    counter_heal_policy(battle, (uint16_t)op->argument);
                if (policy == NULL) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                int index = volatile_index(
                    holder, (PokemonVolatileKind)policy->volatile_kind);
                uint8_t counter = index < 0 ? policy->default_counter :
                    holder->volatiles[index].counter;
                if (counter == 0 || counter > policy->maximum_counter) {
                    battle->event_depth--;
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint16_t max_hp = battle->sides[discovered[i].holder_side]
                    .sets[discovered[i].holder_slot].stats[0];
                uint32_t requested = apply_modifier_q12(
                    max_hp, policy->modifiers_q12[counter - 1]);
                if (requested == 0) requested = 1;
                PokemonEffectResult heal_result;
                uint16_t actual = 0;
                status = try_amount_heal(
                    battle, input->source,
                    (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
                        descriptor->source_id},
                    discovered[i].holder_side, discovered[i].holder_slot,
                    (uint16_t)requested, &heal_result, &actual);
                if (status != POKEMON_OK) {
                    battle->event_depth--;
                    return status;
                }
                break;
            }
			case POKEMON_HANDLER_OP_INSTALL_LOCKED_RAMP_IF_TARGET_AWAKE: {
				const PokemonLockedRampPolicy *policy =
					locked_ramp_policy(battle, (uint16_t)op->argument);
				PokemonMutable *holder = &battle->sides[
					discovered[i].holder_side].state[discovered[i].holder_slot];
				if (policy == NULL) {
					battle->event_depth--;
					return POKEMON_INVALID_CONFIGURATION;
				}
				if (holder->status.kind == POKEMON_STATUS_SLEEP ||
					volatile_index(holder, policy->volatile_kind) >= 0) break;
				uint8_t installed = CONDITION_INSTALL_FAILED;
				status = install_descriptor_volatile(
					battle,
					(PokemonEntityRef){POKEMON_ENTITY_POKEMON,
						discovered[i].holder_side, discovered[i].holder_slot},
					input->source,
					(PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE,
						descriptor->source_id},
					policy->volatile_kind, policy->condition_descriptor_id,
					POKEMON_CONDITION_REASON_HANDLER, &installed);
				if (status != POKEMON_OK) {
					battle->event_depth--;
					return status;
				}
				if (installed != CONDITION_INSTALL_APPLIED) applicable = 0;
				break;
			}
			case POKEMON_HANDLER_OP_APPLY_LOCKED_RAMP_BASE_POWER: {
				const PokemonLockedRampPolicy *policy =
					locked_ramp_policy(battle, (uint16_t)op->argument);
				PokemonMutable *holder = &battle->sides[
					discovered[i].holder_side].state[discovered[i].holder_slot];
				if (policy == NULL) {
					battle->event_depth--;
					return POKEMON_INVALID_CONFIGURATION;
				}
				int ramp_index = volatile_index(holder, policy->volatile_kind);
				if (ramp_index < 0) {
					battle->event_depth--;
					return POKEMON_INVALID_CONFIGURATION;
				}
				PokemonVolatileState *condition = &holder->volatiles[ramp_index];
				uint8_t duration_before = condition->duration;
				uint8_t counter_before = condition->counter;
				uint32_t factor = 1;
				for (uint8_t hit = 0; hit < condition->counter; hit++) {
					if (factor > UINT32_MAX / policy->power_multiplier) {
						battle->event_depth--;
						return POKEMON_INVALID_CONFIGURATION;
					}
					factor *= policy->power_multiplier;
				}
				if (volatile_index(holder, policy->marker_kind) >= 0) {
					if (factor > UINT32_MAX / policy->power_multiplier) {
						battle->event_depth--;
						return POKEMON_INVALID_CONFIGURATION;
					}
					factor *= policy->power_multiplier;
				}
				if (frame.relay.value.u32 > UINT32_MAX / factor) {
					battle->event_depth--;
					return POKEMON_INVALID_CONFIGURATION;
				}
				frame.relay.value.u32 *= factor;
				if (condition->counter < policy->maximum_hits) condition->counter++;
				if (condition->counter < policy->maximum_hits) {
					condition->duration = policy->refresh_duration;
				}
				status = trace_condition(
					battle, POKEMON_CONDITION_SCOPE_VOLATILE,
					POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_HANDLER,
					POKEMON_CONDITION_VALUE_DURATION,
					discovered[i].holder_side, discovered[i].holder_slot,
					condition->kind, duration_before, condition->duration);
				if (status != POKEMON_OK) {
					battle->event_depth--;
					return status;
				}
				PokemonConditionTrace *update_trace = &battle->condition_traces[
					battle->condition_trace_count - 1u];
				update_trace->descriptor_id = condition->descriptor_id;
				update_trace->has_counter_before = 1;
				update_trace->has_counter_after = 1;
				update_trace->counter_before = counter_before;
				update_trace->counter_after = condition->counter;
				direct_relay_mutated = 1;
				break;
			}
			case POKEMON_HANDLER_OP_REMOVE_OWNER_IF_LAST_MOVE_FALLBACK: {
				PokemonVolatileState *condition = owner_volatile(
					battle, &discovered[i]);
				PokemonMutable *holder = &battle->sides[
					discovered[i].holder_side].state[discovered[i].holder_slot];
				if (condition != NULL && holder->last_move_id ==
						battle->generation->fallback_move_id) {
					PokemonVolatileState old = *condition;
					status = trace_condition(
						battle, POKEMON_CONDITION_SCOPE_VOLATILE,
						POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_HANDLER,
						POKEMON_CONDITION_VALUE_DURATION,
						discovered[i].holder_side, discovered[i].holder_slot,
						old.kind, old.duration, 0);
					if (status != POKEMON_OK) {
						battle->event_depth--;
						return status;
					}
					remove_volatile_at(holder, (size_t)volatile_index(
						holder, old.kind));
				}
				break;
			}
            case POKEMON_HANDLER_OP_REQUIRE_ACTIVE_FOE_SHARES_HOLDER_MOVE:
                if (!active_foes_share_current_move(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot)) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            case POKEMON_HANDLER_OP_APPEND_HOLDER_MOVES_TO_EVENT_RESTRICTIONS: {
                PokemonMoveRestrictionBuffer *restrictions =
                    input->context.move_restrictions;
                for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                    uint16_t move_id = current_move_id(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot, slot);
                    if (move_id == 0 ||
                        move_id == battle->generation->fallback_move_id) continue;
                    restrictions->values[restrictions->count++] =
                        (PokemonMoveRestriction){
                            .kind = POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL,
                            .move_id = move_id,
                        };
                }
                break;
            }
            case POKEMON_HANDLER_OP_REJECT_EVENT_MOVE_SHARED_WITH_HOLDER:
                if (input->context.move.move->id !=
                        battle->generation->fallback_move_id &&
                    pokemon_knows_current_move(
                        battle, discovered[i].holder_side,
                        discovered[i].holder_slot,
                        input->context.move.move->id)) {
                    frame.relay.value.boolean = 0;
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            case POKEMON_HANDLER_OP_SELECT_ACTIVE_MOVE_PROFILE_BY_USER_TYPE: {
                const PokemonMoveProfileSelection *selection =
                    find_move_profile_selection(battle->data,
                        (uint16_t)op->argument);
                PokemonMutable *user = &battle->sides[input->source.side]
                    .state[input->source.slot];
                uint8_t matches = 0;
                for (size_t type_index = 0;
                     type_index < user->effective_type_count; type_index++) {
                    uint8_t type = user->effective_types[type_index];
                    matches |= type < 32 &&
                        (selection->current_user_type_mask &
                            (UINT32_C(1) << type)) != 0;
                }
                uint16_t profile_id = matches ?
                    selection->matching_profile_id :
                    selection->nonmatching_profile_id;
                const PokemonMoveInvocationProfile *profile =
                    find_move_invocation_profile(battle->data, profile_id);
                PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                active->target_mode = profile->target;
                active->effect_offset = profile->effect_offset;
                active->effect_count = profile->effect_count;
                active->profile_tag = profile->tag;
                break;
            }
            case POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_PROFILE_TAG: {
                const PokemonActiveMoveFrame *active =
                    &battle->move_frames[battle->move_frame_depth - 1];
                applicable = active->profile_tag == (uint16_t)op->argument;
                break;
            }
            case POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_EFFECTS_IF_TARGET_VOLATILE: {
                PokemonMutable *target = &battle->sides[input->target_side]
                    .state[input->target_slot];
                if (applicable &&
                    volatile_index(target,
                        (PokemonVolatileKind)op->argument) >= 0) {
                    PokemonActiveMoveFrame *active =
                        &battle->move_frames[battle->move_frame_depth - 1];
                    active->effect_count = 0;
                }
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_EVENT_TARGET_VOLATILE: {
                PokemonMutable *target = &battle->sides[input->target_side]
                    .state[input->target_slot];
                if (applicable &&
                    volatile_index(target,
                        (PokemonVolatileKind)op->argument) >= 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_SET_HOLDER_BOOLEAN_FROM_BATTLE_STARTED: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                uint32_t mask = UINT32_C(1) << op->argument;
                if (battle->initial_setup_complete) holder->boolean_states |= mask;
                else holder->boolean_states &= ~mask;
                break;
            }
            case POKEMON_HANDLER_OP_RETURN_FALSE_IF_HOLDER_BOOLEAN: {
                const PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                if ((holder->boolean_states &
                     (UINT32_C(1) << op->argument)) != 0) {
                    frame.relay = (PokemonRelay){
                        .kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 0};
                    frame.cancellation = POKEMON_EVENT_CANCEL_FALSE;
                    frame.cancelling_owner = discovered[i].owner;
                    frame.cancelling_handler_id = descriptor->id;
                }
                break;
            }
            case POKEMON_HANDLER_OP_TOGGLE_HOLDER_BOOLEAN: {
                PokemonMutable *holder = &battle->sides[
                    discovered[i].holder_side].state[discovered[i].holder_slot];
                holder->boolean_states ^= UINT32_C(1) << op->argument;
                break;
            }
            case POKEMON_HANDLER_OP_SET_SOURCE_TARGET_HP_TO_FLOOR_AVERAGE: {
                PokemonMutable *source = &battle->sides[input->source.side]
                    .state[input->source.slot];
                PokemonMutable *target = &battle->sides[input->target_side]
                    .state[input->target_slot];
                uint32_t requested =
                    ((uint32_t)source->hp + (uint32_t)target->hp) / 2u;
                if (requested == 0) requested = 1;
                uint16_t source_max = battle->sides[input->source.side]
                    .sets[input->source.slot].stats[0];
                uint16_t target_max = battle->sides[input->target_side]
                    .sets[input->target_slot].stats[0];
                source->hp = (uint16_t)(requested > source_max ?
                    source_max : requested);
                target->hp = (uint16_t)(requested > target_max ?
                    target_max : requested);
                break;
            }
            default:
                assert(0 && "handler program was validated before execution");
                break;
            }
        }
        uint32_t before = frame.modifier_q12;
        if (uses_modifiers) {
            frame.modifier_q12 = chain_modifier_q12(
                frame.modifier_q12, applicable ? handler_modifier : 4096);
        }
        if (traces_modifiers && descriptor->exceptional_handler_id == 0 &&
            frame.relay.kind == POKEMON_RELAY_NULL) {
            /* A modifier callback that returns null is still an executed
             * handler, but it has no numeric modifier/result pair. */
            if (!input->suppress_handler_trace) {
                if (battle->handler_count == POKEMON_HANDLER_CAPACITY) {
                    battle->event_depth--;
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                battle->handlers[battle->handler_count++] =
                    (PokemonHandlerInvocation){
                        .handler = discovered[i],
                        .semantic_sequence = next_semantic_sequence(battle),
                        .invoked = !suppressed,
                        .result = legacy_result,
                    };
            }
        } else if (traces_modifiers &&
            descriptor->exceptional_handler_id == 0) {
            if (!input->suppress_trace) {
                battle->modifiers[battle->modifier_count++] =
                    (PokemonModifierInvocation){
                    .handler = discovered[i],
                    .semantic_sequence = next_semantic_sequence(battle),
                    .input = handler_input,
                    .modifier_before_q12 = before,
                    .modifier_q12 = applicable ? handler_modifier : 4096,
                    .modifier_after_q12 = frame.modifier_q12,
                    .invoked = !suppressed,
                };
            }
        } else if (handler_trace_index[i] != SIZE_MAX) {
            battle->handlers[handler_trace_index[i]].invoked = 1;
            battle->handlers[handler_trace_index[i]].result = legacy_result;
        }
        frame.executed_count += !suppressed;
        /* Showdown's relay contract stops after any falsy numeric result.
         * Zero is a successful numeric result, not false/null cancellation. */
        if ((frame.relay.kind == POKEMON_RELAY_U32 &&
             frame.relay.value.u32 == 0) ||
            (frame.relay.kind == POKEMON_RELAY_NUMBER &&
             frame.relay.value.number == 0.0)) break;
    }
    frame.skipped_count = (uint8_t)(count - frame.executed_count);
    if (uses_modifiers && (frame.relay.kind == POKEMON_RELAY_U32 ||
            frame.relay.kind == POKEMON_RELAY_NUMBER)) {
        double relay_input = frame.relay.kind == POKEMON_RELAY_U32 ?
            frame.relay.value.u32 : frame.relay.value.number;
        double relay_before_modifier = direct_relay_mutated ?
            event_relay_input : relay_input;
        double output = relay_input;
        if (relay_input >= 0 && relay_input <= UINT32_MAX &&
            relay_input == (double)(uint32_t)relay_input) {
            output = apply_modifier_q12((uint32_t)relay_input, frame.modifier_q12);
        }
        if (frame.relay.kind == POKEMON_RELAY_U32) {
            frame.relay.value.u32 = (uint32_t)output;
        } else {
            frame.relay.value.number = output;
        }
        if (!input->suppress_trace) {
            for (size_t i = modifier_start; i < battle->modifier_count; i++) {
                battle->modifiers[i].output = output;
            }
        }
        if (!input->suppress_trace &&
            ((input->event != POKEMON_HANDLER_EVENT_BASE_POWER &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_DEF &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_SPD &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_SPE &&
              input->event != POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE &&
              input->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) ||
             count != 0)) {
            battle->relay_results[battle->relay_result_count++] = (PokemonRelayResult){
                .event = input->event,
                .semantic_sequence = next_semantic_sequence(battle),
                .holder_side = input->target_side,
                .holder_slot = input->target_slot,
                .input = relay_before_modifier,
                .modifier_q12 = frame.modifier_q12,
                .output = output,
            };
        }
    }
    if (!uses_modifiers && !input->suppress_handler_trace &&
        frame.cancellation != POKEMON_EVENT_CANCEL_NONE &&
        frame.cancelling_handler_id != 0) {
        for (size_t i = handler_start; i < battle->handler_count; i++) {
            if (battle->handlers[i].handler.descriptor.id ==
                    frame.cancelling_handler_id &&
                battle->handlers[i].invoked) {
                battle->handlers[i].result = POKEMON_HANDLER_PREVENT;
                break;
            }
        }
    }
    if (!input->suppress_trace) battle->event_frames[frame.depth] = frame;
    battle->event_depth--;
    *result = frame;
    return POKEMON_OK;
}

int pokemon_run_event(
    PokemonBattle *battle, const PokemonEventInput *input,
    PokemonEventFrame *result
) {
    if (battle == NULL || result == NULL) return POKEMON_INVALID_ARGUMENT;
    PokemonBattle next = *battle;
    PokemonEventFrame next_result;
    int status = run_event_inner(&next, input, &next_result);
    if (status != POKEMON_OK) return status;
    *battle = next;
    *result = next_result;
    return POKEMON_OK;
}

static int run_modify_attack_handlers(
    PokemonBattle *battle, size_t attacker_side, size_t attacker_slot,
    PokemonEventId event, const PokemonMoveData *move,
    uint32_t input, uint32_t *output,
    uint8_t *guts_active
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = event,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)attacker_side,
            (uint8_t)attacker_slot},
        .target_side = (uint8_t)attacker_side,
        .target_slot = (uint8_t)attacker_slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = input},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *output = frame.relay.value.u32;
    const PokemonAbilityData *ability = find_ability(
        battle, battle->sides[attacker_side].state[attacker_slot].ability_id);
    *guts_active = ability != NULL && ability->ignores_burn_attack_penalty &&
        battle->sides[attacker_side].state[attacker_slot].status.kind !=
            POKEMON_STATUS_NONE;
    return POKEMON_OK;
}

static int run_modify_defense_handlers(
    PokemonBattle *battle, PokemonEntityRef attacker,
    PokemonEntityRef defender, PokemonEventId event,
    const PokemonMoveData *move,
    uint32_t input, uint32_t *output
) {
    const PokemonEventSpec *spec = event_spec(
        battle, event);
    if (spec == NULL || !spec->supported) {
        *output = input;
        return POKEMON_OK;
    }
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = event,
        .source = attacker,
        .target_side = defender.side,
        .target_slot = defender.slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = input},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *output = frame.relay.value.u32;
    return POKEMON_OK;
}

static int run_try_hit_handlers(
    PokemonBattle *battle, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot,
    const PokemonMoveData *move, PokemonImmunityCause *cause,
    uint16_t *effect_id, PokemonHandlerId *handler_id,
    uint8_t *emit_immunity, PokemonEventCancellation *cancellation
) {
    size_t trace_start = battle->handler_count;
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side, .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *cancellation = frame.cancellation;
    if (frame.cancellation != POKEMON_EVENT_CANCEL_NONE) {
        *cause = POKEMON_IMMUNITY_HANDLER;
        *effect_id = frame.cancelling_owner.effect_id;
        *handler_id = frame.cancelling_handler_id;
        *emit_immunity = frame.cancellation_emits_immunity;
        for (size_t i = trace_start; i < battle->handler_count; i++) {
            if (battle->handlers[i].handler.descriptor.id == *handler_id &&
                battle->handlers[i].invoked) {
                battle->handlers[i].result = POKEMON_HANDLER_IMMUNE;
                break;
            }
        }
    }
    return POKEMON_OK;
}

static int run_damage_handlers(
    PokemonBattle *battle, size_t target_side, size_t target_slot,
    PokemonDamageRelativeKind cause, uint16_t source_move_id,
    uint8_t preventable, uint8_t *prevented
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
            (uint8_t)target_slot},
        .target_side = (uint8_t)target_side, .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, source_move_id),
        .context_kind = POKEMON_EVENT_CONTEXT_DAMAGE,
        .context.damage = {.kind = cause, .source_move_id = source_move_id,
            .preventable = preventable},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 0},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *prevented = frame.cancellation != POKEMON_EVENT_CANCEL_NONE;
    if (*prevented) {
        for (size_t i = 0; i < battle->handler_count; i++) {
            if (battle->handlers[i].handler.descriptor.id ==
                    frame.cancelling_handler_id && battle->handlers[i].invoked) {
                battle->handlers[i].result = POKEMON_HANDLER_PREVENT;
            }
        }
    }
    return POKEMON_OK;
}

/* Showdown's ordinary Damage relay is a commit boundary: hit admission,
 * critical staging, the damage roll, and Substitute have already resolved,
 * but real target HP has not changed.  Keep the requested value visible to
 * handlers and clamp only the relay result which will actually be applied. */
static int run_ordinary_move_damage_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot,
    uint16_t requested, uint16_t *applied
) {
    PokemonSourceEffectRef source_effect = active_source_effect(
        battle, move->id);
    PokemonRetaliationClassMask retaliation_class =
        move->retaliation_class_policy == POKEMON_RETALIATION_FIXED_CLASS ?
            move->retaliation_class_mask :
        move->category == POKEMON_CATEGORY_PHYSICAL ?
            POKEMON_RETALIATION_PHYSICAL :
        move->category == POKEMON_CATEGORY_SPECIAL ?
            POKEMON_RETALIATION_SPECIAL : 0;
    uint8_t applicable = 0;
    int status = unsupported_event_applicable(
        battle, POKEMON_HANDLER_EVENT_DAMAGE,
        source_side, source_slot, target_side, target_slot, &applicable);
    if (status != POKEMON_OK) return status;
    if (!applicable && source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE) {
        for (size_t i = 0; i < battle->data->handler_count; i++) {
            const PokemonHandlerDescriptor *descriptor =
                &battle->data->handlers[i];
            if (descriptor->event == POKEMON_HANDLER_EVENT_DAMAGE &&
                descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
                descriptor->source_id == source_effect.id &&
                descriptor->route == POKEMON_HANDLER_ROUTE_SOURCE_EFFECT) {
                applicable = 1;
                break;
            }
        }
    }
    uint16_t hp = battle->sides[target_side].state[target_slot].hp;
    if (!applicable) {
        *applied = requested < hp ? requested : hp;
        return POKEMON_OK;
    }
    PokemonEventFrame frame;
    status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = source_effect,
        .context_kind = POKEMON_EVENT_CONTEXT_DAMAGE,
        .context.damage = {.kind = POKEMON_DAMAGE_EVENT_ORDINARY_MOVE,
            .source_move_id = move->id, .preventable = 0,
            .retaliation_class_mask = retaliation_class},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = requested},
        .include_source_effect_move = 1,
    }, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        frame.relay.kind != POKEMON_RELAY_U32) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *applied = frame.relay.value.u32 < hp ?
        (uint16_t)frame.relay.value.u32 : hp;
    return POKEMON_OK;
}

static int run_modify_damage_phase1_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    PokemonEntityRef source, PokemonEntityRef target, uint8_t critical,
    uint32_t *damage
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1,
        .source = source,
        .target_side = target.side, .target_slot = target.slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move, .critical = critical},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = *damage},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *damage = frame.relay.value.u32;
    return POKEMON_OK;
}

/* Showdown's final ModifyDamage event uses reversed target/source topology:
 * the attacker is the event target and the defender is the event source.
 * This is what makes a defender-owned `onSourceModifyDamage` marker visible
 * without teaching the kernel any marker or move identities. */
static int run_modify_damage_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    PokemonEntityRef attacker, PokemonEntityRef defender, uint32_t *damage
) {
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_DAMAGE,
        .source = defender,
        .target_side = attacker.side, .target_slot = attacker.slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = *damage},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *damage = frame.relay.value.u32;
    return POKEMON_OK;
}
#line 4096 "pokemon.c"
