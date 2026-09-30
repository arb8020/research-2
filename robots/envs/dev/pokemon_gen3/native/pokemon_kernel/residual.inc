#line 17551 "pokemon.c"
static int residual_damage(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t amount,
    PokemonConditionScope condition_scope, uint16_t condition_id
) {
    uint16_t applied = 0;
    int result = residual_damage_deferred(
        battle, side, slot, amount, condition_scope, condition_id, &applied);
    return result == POKEMON_OK ? drain_faints(battle) : result;
}

static int build_residual_queue(PokemonBattle *battle) {
    battle->residual_count = 0;
    /* Field handlers are discovered before side/Pokemon-owned handlers in
     * Showdown. This initial order matters because speedSort is a selection
     * sort: selecting a field handler can otherwise perturb a later tie. */
    if (battle->field.weather.kind != POKEMON_WEATHER_NONE) {
        const PokemonConditionRule *rule = condition_rule_by_descriptor(
            battle, battle->field.weather.descriptor_id);
        assert(rule != NULL && rule->has_residual);
        battle->residuals[battle->residual_count++] = (PokemonResidualWork){
            .kind = POKEMON_RESIDUAL_WEATHER,
            .order = rule->residual_order, .has_order = rule->has_order,
            .sub_order = rule->residual_sub_order,
            .condition_id = battle->field.weather.kind,
            .duration_before = battle->field.weather.duration,
        };
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t i = 0; i < battle->sides[side].condition_count; i++) {
            PokemonSideConditionState *condition =
                &battle->sides[side].conditions[i];
            const PokemonConditionRule *rule =
                condition_rule_by_descriptor(battle, condition->descriptor_id);
            assert(rule != NULL);
            if (!rule->has_residual) continue;
            if (battle->residual_count == POKEMON_RESIDUAL_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            battle->residuals[battle->residual_count++] = (PokemonResidualWork){
                .kind = POKEMON_RESIDUAL_SIDE_CONDITION,
                .order = rule->residual_order, .has_order = rule->has_order,
                .sub_order = rule->residual_sub_order, .side = (uint8_t)side,
                .condition_id = condition->kind,
                .duration_before = condition->duration,
            };
        }
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        size_t slot = battle->sides[side].active;
        PokemonMutable *state = &battle->sides[side].state[slot];
        /* Showdown discovers each active's Residual handlers in owner order:
         * status, volatile insertion order, ability, item, species, then slot
         * conditions. Preserve that pre-sort sequence: its selection sort can
         * perturb a later tie before the owning PRNG shuffle. */
        const PokemonStatusState *status_state = &state->status;
        const PokemonStatusResidualPolicy *status_policy =
            status_residual_policy(battle->data, status_state->descriptor_id);
        if (status_policy != NULL) {
            if (battle->residual_count == POKEMON_RESIDUAL_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            const PokemonConditionRule *rule = condition_rule_by_descriptor(
                battle, status_policy->descriptor_id);
            assert(rule != NULL && rule->has_residual);
            battle->residuals[battle->residual_count++] = (PokemonResidualWork){
                .kind = POKEMON_RESIDUAL_STATUS,
                .order = rule->residual_order, .has_order = rule->has_order,
                .sub_order = rule->residual_sub_order,
                .side = (uint8_t)side, .slot = (uint8_t)slot,
                .condition_id = status_state->kind,
                .descriptor_id = status_state->descriptor_id,
                .state_generation = status_state->state_generation,
                .effect_order = status_state->effect_order,
                .speed = rule->speed_tied ?
                    state->cached_speed : 0,
                .counter_before = status_policy->state_policy ==
                        POKEMON_STATUS_RESIDUAL_ESCALATE ?
                    status_state->state.toxic.stage : 0,
            };
        }
        for (size_t i = 0; i < state->volatile_count; i++) {
            const PokemonConditionRule *rule = condition_rule_by_descriptor(
                battle, state->volatiles[i].descriptor_id);
            uint8_t marker_residual =
                rule == NULL &&
                state->volatiles[i].kind == POKEMON_VOLATILE_TWO_TURN_MARKER;
            /* Persistent payload volatiles without callbacks do not enter the
             * residual queue. Durationless descriptor-owned conditions may. */
            if (state->volatiles[i].duration == 0 &&
                (rule == NULL || !rule->has_residual)) continue;
            if (battle->residual_count == POKEMON_RESIDUAL_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            if (rule == NULL && !marker_residual) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (rule != NULL && !rule->has_residual) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            battle->residuals[battle->residual_count++] = (PokemonResidualWork){
                .kind = POKEMON_RESIDUAL_VOLATILE, .side = (uint8_t)side,
                .slot = (uint8_t)slot, .condition_id = state->volatiles[i].kind,
                .descriptor_id = state->volatiles[i].descriptor_id,
                .state_generation = state->volatiles[i].state_generation,
                .effect_order = state->volatiles[i].effect_order,
                .order = marker_residual ? 0 : rule->residual_order,
                .has_order = marker_residual ? 0 : rule->has_order,
                .speed = (marker_residual || rule->speed_tied) ?
                    state->cached_speed : 0,
                .sub_order = marker_residual ? 2 : rule->residual_sub_order,
                .duration_before = state->volatiles[i].duration,
                .counter_before = state->volatiles[i].counter,
            };
        }
        PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
        size_t count = 0;
        int status = discover_holder_scope(
            battle, POKEMON_HANDLER_EVENT_RESIDUAL,
            POKEMON_HANDLER_SCOPE_TARGET, side, slot, handlers, &count);
        if (status != POKEMON_OK) return status;
        for (size_t handler_index = 0; handler_index < count; handler_index++) {
            const PokemonHandlerRef *handler = &handlers[handler_index];
            if (handler->owner.kind == POKEMON_OWNER_VOLATILE) continue;
            const PokemonHandlerDescriptor *descriptor = &handler->descriptor;
            if (descriptor->order < 0 || descriptor->order > UINT8_MAX ||
                battle->residual_count == POKEMON_RESIDUAL_CAPACITY) {
                return descriptor->order < 0 || descriptor->order > UINT8_MAX ?
                    POKEMON_INVALID_CONFIGURATION : POKEMON_CAPACITY_EXCEEDED;
            }
            battle->residuals[battle->residual_count++] = (PokemonResidualWork){
                .kind = POKEMON_RESIDUAL_OWNER_EVENT,
                .order = (uint8_t)descriptor->order, .has_order = 1,
                .priority = descriptor->priority,
                .sub_order = (uint8_t)descriptor->sub_order,
                .side = (uint8_t)side, .slot = (uint8_t)slot,
                .condition_id = descriptor->id, .speed = handler->speed,
                .effect_order = handler->owner.kind == POKEMON_OWNER_ITEM ?
                    state->item_effect_order :
                    handler->owner.kind == POKEMON_OWNER_ABILITY ?
                        state->ability_effect_order : 0,
                .handler = *handler,
            };
        }
        for (uint8_t position = 0;
             position < battle->format.active_per_side; position++) {
            if (position >= POKEMON_ACTIVE_POSITION_CAPACITY) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            for (size_t i = 0;
                 i < battle->sides[side].slot_condition_count[position]; i++) {
                const PokemonSlotConditionState *condition =
                    &battle->sides[side].slot_conditions[position][i];
                const PokemonSlotConditionPolicy *policy =
                    slot_condition_policy(battle->data,
                        condition->descriptor_id);
                if (policy == NULL || policy->semantic_kind !=
                        condition->semantic_kind ||
                    battle->residual_count == POKEMON_RESIDUAL_CAPACITY) {
                    return policy == NULL || policy->semantic_kind !=
                        condition->semantic_kind ?
                        POKEMON_INVALID_CONFIGURATION :
                        POKEMON_CAPACITY_EXCEEDED;
                }
                battle->residuals[battle->residual_count++] =
                    (PokemonResidualWork){
                        .kind = POKEMON_RESIDUAL_SLOT_CONDITION,
                        .order = policy->residual_order, .has_order = 1,
                        .sub_order = policy->residual_sub_order,
                        .side = (uint8_t)side, .slot = position,
                        .condition_id = condition->semantic_kind,
                        .descriptor_id = condition->descriptor_id,
                        .state_generation = condition->state_generation,
                        .effect_order = condition->effect_order,
                        .duration_before = condition->duration,
                    };
            }
        }
    }
    return POKEMON_OK;
}

static int residual_precedes(
    const PokemonResidualWork *left, const PokemonResidualWork *right
) {
    uint16_t left_order = left->has_order ? left->order : UINT8_MAX + 1u;
    uint16_t right_order = right->has_order ? right->order : UINT8_MAX + 1u;
    if (left_order != right_order) return left_order < right_order;
    if (left->priority != right->priority) return left->priority > right->priority;
    if (left->speed != right->speed) return left->speed > right->speed;
    return left->sub_order < right->sub_order;
}

static int residual_tied(
    const PokemonResidualWork *left, const PokemonResidualWork *right
) {
    return !residual_precedes(left, right) && !residual_precedes(right, left);
}

static int remove_active_volatile_kind(
    PokemonBattle *battle, size_t side, size_t slot, PokemonVolatileKind kind
) {
    int index = volatile_index(&battle->sides[side].state[slot], kind);
    if (index < 0) return POKEMON_OK;
    PokemonVolatileState condition =
        battle->sides[side].state[slot].volatiles[index];
    return end_and_remove_volatile_exact(
        battle, side, slot, condition.descriptor_id,
        condition.state_generation, condition.effect_order,
        POKEMON_CONDITION_REASON_HANDLER);
}

static int execute_stored_damage_constructed_hit(
    PokemonBattle *battle, const PokemonConstructedHitTemplate *template,
    PokemonEntityRef source, PokemonEntityRef target,
    const PokemonVolatileState *condition
) {
    if (template == NULL || condition == NULL ||
        source.kind != POKEMON_ENTITY_POKEMON ||
        target.kind != POKEMON_ENTITY_POKEMON ||
        source.side >= POKEMON_SIDES || target.side >= POKEMON_SIDES ||
        source.slot >= battle->team_sizes[source.side] ||
        target.slot >= battle->team_sizes[target.side] ||
        source.slot != battle->sides[source.side].active ||
        target.slot != battle->sides[target.side].active ||
        battle->sides[source.side].state[source.slot].hp == 0 ||
        battle->sides[target.side].state[target.slot].hp == 0 ||
        condition->kind != POKEMON_VOLATILE_STORED_DAMAGE ||
        !condition->payload.stored_damage.captured ||
        template->owner_condition_descriptor != condition->descriptor_id ||
        battle->move_frame_depth == POKEMON_MOVE_FRAME_CAPACITY) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMoveData move = template->move;
    move.damage_parameter = condition->descriptor_id;
    PokemonMoveInvocation invocation = {
        .entry = POKEMON_MOVE_ENTRY_CALLED,
        .move_id = move.id,
        .user = source,
        .target_request = {POKEMON_TARGET_REQUEST_EXPLICIT, target},
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move.id},
        .selected_slot = UINT8_MAX,
    };
    battle->move_frames[battle->move_frame_depth++] =
        (PokemonActiveMoveFrame){
            .invocation = invocation,
            .resolved_target = target,
            .target_mode = move.target,
            .flags = move.flags,
            .type = move.type,
            .category = move.category,
            .base_power = 0,
            .accuracy = move.accuracy,
        };
    const PokemonSet *attacker = &battle->sides[source.side].sets[source.slot];
    const PokemonSet *defender = &battle->sides[target.side].sets[target.slot];
    PokemonMutable *target_state =
        &battle->sides[target.side].state[target.slot];
    PokemonEventFrame prepare_hit;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_PREPARE_HIT,
        .source = source,
        .target_side = target.side,
        .target_slot = target.slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move.id},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = &move},
    }, &prepare_hit);
    if (status != POKEMON_OK ||
        prepare_hit.cancellation != POKEMON_EVENT_CANCEL_NONE) goto done;
    HitResult hit;
    uint8_t requested_hits = 1;
    status = resolve_hit(
        battle, attacker, defender, target_state, &move,
        source.side, source.slot, target.side, target.slot,
        0, &requested_hits, &hit);
    if (status != POKEMON_OK) goto done;
    if (hit.kind == HIT_MISSED) {
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_MISS,
            .side = source.side, .target_side = target.side,
            .species_id = attacker->species_id, .move_id = move.id,
        });
        goto done;
    }
    if (hit.kind == HIT_IMMUNE) {
        if (hit.value.immune.emit_event) append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_IMMUNE,
            .side = target.side, .target_side = source.side,
            .species_id = defender->species_id, .move_id = move.id,
            .immunity_cause = hit.value.immune.cause,
            .handler_id = hit.value.immune.handler_id,
        });
        goto done;
    }
    if (hit.kind == HIT_BLOCKED) {
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_BLOCK,
            .side = target.side, .target_side = source.side,
            .species_id = defender->species_id, .move_id = move.id,
        });
        goto done;
    }
    if (hit.kind == HIT_SUBSTITUTE) {
        status = consume_substitute_hit(
            battle, &move, source.side, source.slot,
            target.side, target.slot, 1, 1, &hit.value.substitute);
        if (status == POKEMON_OK) status = run_move_hit_event(
            battle, &move, source.side, source.slot,
            target.side, target.slot, NULL, NULL);
        if (status == POKEMON_OK) status = apply_after_hit_effects(
            battle, &move, source.side, source.slot,
            target.side, target.slot, 1);
        if (status == POKEMON_OK) status = run_update_each_event(battle);
        if (status == POKEMON_OK) record_attack(
            battle, target.side, target.slot, source.side, source.slot,
            move.id, 0, 1);
        goto done;
    }
    assert(hit.kind == HIT_CONNECTED);
    {
        uint16_t calculated_damage = hit.value.connected.damage;
        uint16_t damage = calculated_damage;
        uint16_t hp_before = target_state->hp;
        status = run_ordinary_move_damage_event(
            battle, &move, source.side, source.slot,
            target.side, target.slot, damage, &damage);
        if (status != POKEMON_OK) goto done;
        target_state->hp = (uint16_t)(target_state->hp - damage);
        battle->move_frames[battle->move_frame_depth - 1].actual_damage = damage;
        battle->move_frames[battle->move_frame_depth - 1].move_succeeded = 1;
        if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
            status = POKEMON_CAPACITY_EXCEEDED;
            goto done;
        }
        battle->hit_traces[battle->hit_trace_count++] = (PokemonHitTrace){
            .semantic_sequence = next_semantic_sequence(battle),
            .kind = POKEMON_HIT_CONNECTED, .move_id = move.id,
            .source_side = source.side, .source_slot = source.slot,
            .target_side = target.side, .target_slot = target.slot,
            .hit_index = 1, .requested_hits = 1,
            .dynamic_plan = 1,
            .critical = 0, .damage_roll = 0,
            .damage = damage, .calculated_damage = calculated_damage,
            .hp_before = hp_before, .hp_after = target_state->hp,
            .source_hp_after =
                battle->sides[source.side].state[source.slot].hp,
        };
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_DAMAGE,
            .side = target.side, .target_side = source.side,
            .species_id = defender->species_id, .move_id = move.id,
            .amount = damage, .hp = target_state->hp,
        });
        status = apply_damage_relative_effects(
            battle, &move, POKEMON_EFFECT_PHASE_AFTER_DAMAGE,
            source.side, source.slot, target.side, target.slot, damage);
        if (status == POKEMON_OK) status = run_move_hit_event(
            battle, &move, source.side, source.slot,
            target.side, target.slot, NULL, NULL);
        if (status == POKEMON_OK) status = apply_after_hit_effects(
            battle, &move, source.side, source.slot,
            target.side, target.slot, 0);
        if (status == POKEMON_OK) status = run_damaging_hit_event(
            battle, &move, damage, source.side, source.slot,
            target.side, target.slot);
        if (status == POKEMON_OK) status = run_update_each_event(battle);
        if (status == POKEMON_OK) status = resolve_move_faint(
            battle, target.side, target.slot, source,
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move.id});
        if (status == POKEMON_OK) status = resolve_move_faint(
            battle, source.side, source.slot,
            (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_NONE, 0});
        if (status == POKEMON_OK) record_attack(
            battle, target.side, target.slot, source.side, source.slot,
            move.id, damage, 1);
    }
done:
    battle->move_frame_depth--;
    return status;
}

static int execute_delayed_fixed_damage(
    PokemonBattle *battle, const PokemonSlotConditionState *condition,
    size_t target_side, size_t target_slot
) {
    if (condition->source.kind != POKEMON_ENTITY_POKEMON ||
        condition->source.side >= POKEMON_SIDES ||
        condition->source.slot >= battle->team_sizes[condition->source.side] ||
        condition->payload.delayed_move.fixed_damage == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *target_state = &battle->sides[target_side].state[target_slot];
    if (target_state->hp == 0 || target_state->fainted ||
        (condition->source.side == target_side &&
         condition->source.slot == target_slot)) {
        return POKEMON_OK;
    }
    const PokemonMoveData *base = find_move(
        battle, condition->payload.delayed_move.move_id);
    if (base == NULL || battle->move_frame_depth == POKEMON_MOVE_FRAME_CAPACITY) {
        return base == NULL ? POKEMON_INVALID_CONFIGURATION :
            POKEMON_CAPACITY_EXCEEDED;
    }
    int status = remove_active_volatile_kind(
        battle, target_side, target_slot, POKEMON_VOLATILE_PROTECT);
    if (status == POKEMON_OK) status = remove_active_volatile_kind(
        battle, target_side, target_slot, POKEMON_VOLATILE_ENDURE);
    if (status != POKEMON_OK) return status;

    PokemonMoveData move = *base;
    move.type = battle->data->non_interacting_type;
    move.power = 0;
    move.damage_formula = POKEMON_DAMAGE_FIXED_LITERAL;
    move.damage_parameter = condition->payload.delayed_move.fixed_damage;
    move.effect_count = 0;
    move.multihit_min = 0;
    move.multihit_max = 0;
    move.critical_stage = 0;
    move.slot_condition_descriptor = 0;
    PokemonMoveInvocation invocation = {
        .entry = POKEMON_MOVE_ENTRY_CALLED,
        .move_id = move.id,
        .user = condition->source,
        .target_request = {POKEMON_TARGET_REQUEST_EXPLICIT,
            {POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
                (uint8_t)target_slot}},
        /* The slot condition schedules this work, but Showdown constructs a
         * Move effect for the delayed hit. The slot trace retains scheduling
         * provenance independently from Damage-event ownership. */
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move.id},
        .selected_slot = UINT8_MAX,
    };
    battle->move_frames[battle->move_frame_depth++] = (PokemonActiveMoveFrame){
        .invocation = invocation,
        .resolved_target = {POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
            (uint8_t)target_slot},
        .target_mode = move.target, .flags = move.flags,
        .type = move.type, .category = move.category,
        .base_power = 0, .accuracy = move.accuracy,
    };
    const PokemonSet *attacker = &battle->sides[condition->source.side].sets[
        condition->source.slot];
    const PokemonSet *defender = &battle->sides[target_side].sets[target_slot];
    HitResult hit;
    uint8_t requested_hits = 1;
    status = resolve_hit(
        battle, attacker, defender, target_state, &move,
        condition->source.side, condition->source.slot,
        target_side, target_slot, 0, &requested_hits, &hit);
    if (status != POKEMON_OK) goto done;
    if (hit.kind == HIT_MISSED) {
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_MISS, .side = condition->source.side,
            .target_side = (uint8_t)target_side,
            .species_id = attacker->species_id, .move_id = move.id,
        });
        goto done;
    }
    if (hit.kind == HIT_BLOCKED || hit.kind == HIT_IMMUNE) {
        status = POKEMON_INVALID_CONFIGURATION;
        goto done;
    }
    if (hit.kind == HIT_SUBSTITUTE) {
        status = consume_substitute_hit(
            battle, &move, condition->source.side, condition->source.slot,
            target_side, target_slot, 1, 1, &hit.value.substitute);
        if (status == POKEMON_OK) status = run_move_hit_event(
            battle, &move, condition->source.side, condition->source.slot,
            target_side, target_slot, NULL, NULL);
        if (status == POKEMON_OK) status = run_update_each_event(battle);
        goto done;
    }
    {
        uint16_t damage = hit.value.connected.damage;
        status = run_ordinary_move_damage_event(
            battle, &move, condition->source.side, condition->source.slot,
            target_side, target_slot, damage, &damage);
        if (status != POKEMON_OK) goto done;
        uint16_t hp_before = target_state->hp;
        target_state->hp = (uint16_t)(target_state->hp - damage);
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_DAMAGE, .side = (uint8_t)target_side,
            .target_side = condition->source.side,
            .species_id = defender->species_id, .move_id = move.id,
            .amount = damage, .hp = target_state->hp,
        });
        if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
            status = POKEMON_CAPACITY_EXCEEDED;
            goto done;
        }
        battle->hit_traces[battle->hit_trace_count++] = (PokemonHitTrace){
            .semantic_sequence = next_semantic_sequence(battle),
            .kind = POKEMON_HIT_CONNECTED, .move_id = move.id,
            .source_side = condition->source.side,
            .source_slot = condition->source.slot,
            .target_side = (uint8_t)target_side,
            .target_slot = (uint8_t)target_slot,
            .hit_index = 1, .requested_hits = 1,
            .damage = damage, .calculated_damage =
                condition->payload.delayed_move.fixed_damage,
            .hp_before = hp_before, .hp_after = target_state->hp,
            .source_hp_after = battle->sides[condition->source.side].state[
                condition->source.slot].hp,
        };
        status = run_move_hit_event(
            battle, &move, condition->source.side, condition->source.slot,
            target_side, target_slot, NULL, NULL);
        if (status == POKEMON_OK) status = run_damaging_hit_event(
            battle, &move, damage, condition->source.side,
            condition->source.slot, target_side, target_slot);
        if (status == POKEMON_OK) status = run_update_each_event(battle);
        if (status == POKEMON_OK) status = resolve_move_faint(
            battle, target_side, target_slot, condition->source,
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move.id});
        /* Delayed slot damage is its own damage owner, outside the ordinary
         * move-action drain point. Complete its faint transaction here so a
         * lethal expiry can project forced replacement or terminal state
         * before the turn advances. The slot-condition caller still removes
         * the expired work item after this returns. */
        if (status == POKEMON_OK) status = drain_faints(battle);
        /* trySpreadMoveHit drains faint messages between its per-hit Update
         * and its post-spread Update. This ordering matters because the
         * latter discovers only still-active owners. Keep that phase shape
         * here instead of treating the two Update passes as interchangeable. */
        if (status == POKEMON_OK) status = run_update_each_event(battle);
        if (status == POKEMON_OK) set_attack_record(
            battle, target_side, target_slot, condition->source.side,
            condition->source.slot, move.id, damage, 1);
    }
done:
    battle->move_frame_depth--;
    return status;
}

static int run_residual(PokemonBattle *battle) {
    int result = POKEMON_OK;
    if (!battle->residual_pending) {
        /* Showdown's residual action refreshes the cached active speeds before
         * discovering and dispatching residual handlers. eachEvent itself
         * only sorts by that cache; it does not recompute it. */
        result = refresh_active_speeds(battle);
        if (result != POKEMON_OK) return result;
        result = build_residual_queue(battle);
        if (result != POKEMON_OK) return result;
        /* Match Showdown's selection sort exactly. Sorting first and then
         * shuffling equal runs changes later tie groups when selecting an
         * earlier ordered handler swaps with the first unsorted entry. */
        for (size_t sorted = 0; sorted + 1 < battle->residual_count;) {
            size_t next_indexes[POKEMON_RESIDUAL_CAPACITY];
            size_t next_count = 1;
            next_indexes[0] = sorted;
            for (size_t i = sorted + 1; i < battle->residual_count; i++) {
                PokemonResidualWork *best =
                    &battle->residuals[next_indexes[0]];
                PokemonResidualWork *candidate = &battle->residuals[i];
                if (residual_precedes(best, candidate)) continue;
                if (residual_precedes(candidate, best)) {
                    next_count = 1;
                    next_indexes[0] = i;
                } else if (residual_tied(best, candidate)) {
                    next_indexes[next_count++] = i;
                }
            }
            for (size_t i = 0; i < next_count; i++) {
                size_t index = next_indexes[i];
                if (index == sorted + i) continue;
                PokemonResidualWork temporary = battle->residuals[sorted + i];
                battle->residuals[sorted + i] = battle->residuals[index];
                battle->residuals[index] = temporary;
            }
            for (size_t i = sorted; i + 1 < sorted + next_count; i++) {
                uint32_t handler_order = 0;
                result = draw_range(
                    battle, POKEMON_DRAW_RESIDUAL_HANDLER_ORDER,
                    (uint32_t)i, (uint32_t)(sorted + next_count),
                    &handler_order);
                if (result != POKEMON_OK) return result;
                if (handler_order != i) {
                    PokemonResidualWork temporary = battle->residuals[i];
                    battle->residuals[i] = battle->residuals[handler_order];
                    battle->residuals[handler_order] = temporary;
                }
            }
            sorted += next_count;
        }
        /* Record discovered handlers in the already-sorted residual queue
         * order. Volatile callbacks and ability/item callbacks are peers in
         * Showdown's one residual event list; grouping them by owner kind
         * would falsify cross-owner sub-ordering. */
        for (size_t i = 0; i < battle->residual_count; i++) {
            PokemonResidualWork *work = &battle->residuals[i];
            if (work->kind == POKEMON_RESIDUAL_OWNER_EVENT) {
                if (battle->handler_count == POKEMON_HANDLER_CAPACITY) {
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                battle->handlers[battle->handler_count++] =
                    (PokemonHandlerInvocation){
                        .handler = work->handler,
                        .semantic_sequence = next_semantic_sequence(battle),
                        .invoked = 1,
                        .result = POKEMON_HANDLER_CONTINUE,
                    };
                continue;
            }
            if (work->kind != POKEMON_RESIDUAL_VOLATILE) continue;
            PokemonMutable *state = &battle->sides[work->side].state[work->slot];
            int index = volatile_index_by_identity(
                state, work->descriptor_id, work->state_generation,
                work->effect_order);
            if (index < 0) return POKEMON_INVALID_CONFIGURATION;
            PokemonVolatileState *condition = &state->volatiles[index];
            PokemonHandlerRef handlers[POKEMON_HANDLER_CAPACITY];
            size_t count = 0;
            result = append_owner_handlers(
                battle, POKEMON_HANDLER_EVENT_RESIDUAL,
                POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_VOLATILE,
                condition->descriptor_id, condition->state_generation,
                work->side, work->slot, state->cached_speed,
                condition->effect_order, handlers, &count);
            if (result != POKEMON_OK) return result;
            if ((size_t)battle->handler_count + count >
                POKEMON_HANDLER_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
            for (size_t j = 0; j < count; j++) {
                battle->handlers[battle->handler_count++] =
                    (PokemonHandlerInvocation){
                        .handler = handlers[j],
                        .semantic_sequence = next_semantic_sequence(battle),
                        .invoked = 1,
                        .result = POKEMON_HANDLER_CONTINUE,
                    };
            }
        }
        battle->residual_index = 0;
        battle->residual_pending = 1;
    }
    battle->phase = POKEMON_PHASE_RESIDUAL;
    /* A forced replacement is deferred until the already-discovered list is
     * drained; a terminal winner ends the list immediately. */
    while (battle->residual_index < battle->residual_count && !battle->terminal) {
        PokemonResidualWork *work = &battle->residuals[battle->residual_index++];
        /* A residual work item owns execution, not discovery.  Allocate its
         * semantic sequence when it runs so traces produced by an earlier
         * item cannot sort behind a later item merely because the complete
         * queue was discovered up front. */
        work->semantic_sequence = next_semantic_sequence(battle);
        if (work->kind == POKEMON_RESIDUAL_STATUS ||
            work->kind == POKEMON_RESIDUAL_VOLATILE ||
            work->kind == POKEMON_RESIDUAL_OWNER_EVENT) {
            const PokemonMutable *holder =
                &battle->sides[work->side].state[work->slot];
            if (holder->hp == 0 || holder->fainted) continue;
        }
        if (work->kind == POKEMON_RESIDUAL_WEATHER) {
            uint8_t before = battle->field.weather.duration;
            if (before != 0) battle->field.weather.duration--;
            if (before != 0 && battle->field.weather.duration == 0) {
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_FIELD,
                    POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_EXPIRY,
                    POKEMON_CONDITION_VALUE_DURATION,
                    battle->field.weather.source_side,
                    battle->field.weather.source_slot,
                    work->condition_id, before, 0
                );
                if (result != POKEMON_OK) return result;
                memset(&battle->field.weather, 0, sizeof(battle->field.weather));
                result = run_weather_change_each_event(battle);
                if (result != POKEMON_OK) return result;
                continue;
            }
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_FIELD,
                POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_RESIDUAL,
                POKEMON_CONDITION_VALUE_DURATION,
                battle->field.weather.source_side,
                battle->field.weather.source_slot,
                work->condition_id, before,
                battle->field.weather.duration
            );
            if (result != POKEMON_OK) return result;
            uint8_t weather_order[POKEMON_SIDES];
            result = resolve_each_event_active_order(
                battle, POKEMON_DRAW_EACH_EVENT_WEATHER_ACTIVE_ORDER,
                weather_order);
            if (result != POKEMON_OK) return result;
            memcpy(work->weather_order, weather_order, sizeof(weather_order));
            if (effective_weather(battle) != work->condition_id) continue;
            work->weather_event_dispatched = 1;
            const PokemonWeatherPolicy *policy = weather_policy(
                battle, (PokemonWeatherKind)work->condition_id);
            if (policy == NULL) return POKEMON_INVALID_CONFIGURATION;
            if (policy->residual_damage_formula ==
                POKEMON_RESIDUAL_FORMULA_NONE) continue;
            for (size_t index = 0;
                 index < POKEMON_SIDES && !battle->terminal; index++) {
                size_t side = weather_order[index];
                size_t slot = battle->sides[side].active;
                const PokemonMutable *state = &battle->sides[side].state[slot];
                uint32_t type_mask = 0;
                for (uint8_t type = 0; type < battle->data->type_count; type++) {
                    if (has_type(state, type)) type_mask |= UINT32_C(1) << type;
                }
                if (type_mask & policy->residual_immune_type_mask) continue;
                PokemonEventFrame immunity;
                result = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_IMMUNITY,
                    .source = {POKEMON_ENTITY_NONE, 0, 0},
                    .target_side = (uint8_t)side,
                    .target_slot = (uint8_t)slot,
                    .source_effect = {POKEMON_SOURCE_EFFECT_NONE, 0},
                    .relay = {.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 1},
                    .context_kind = POKEMON_EVENT_CONTEXT_IMMUNITY,
                    .context.immunity = {
                        .condition_descriptor_id = policy->descriptor_id},
                }, &immunity);
                if (result != POKEMON_OK) return result;
                if (immunity.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                    !immunity.relay.value.boolean) continue;
                uint16_t amount = battle->generation->residual_damage(
                    policy->residual_damage_formula,
                    battle->sides[side].sets[slot].stats[0], 0
                );
                uint16_t applied = 0;
                result = residual_damage_deferred(
                    battle, side, slot, amount,
                    POKEMON_CONDITION_SCOPE_FIELD, work->condition_id,
                    &applied);
                if (result != POKEMON_OK) return result;
            }
            /* Weather is one field event over every active. Damage from all
             * participants is observable before its queued faint batch. */
            result = drain_faints(battle);
            if (result != POKEMON_OK) return result;
        } else if (work->kind == POKEMON_RESIDUAL_STATUS) {
            PokemonMutable *state = &battle->sides[work->side].state[work->slot];
            if (state->status.kind != work->condition_id ||
                state->status.descriptor_id != work->descriptor_id ||
                state->status.state_generation != work->state_generation ||
                state->status.effect_order != work->effect_order) continue;
            const PokemonStatusResidualPolicy *policy =
                status_residual_policy(battle->data, work->descriptor_id);
            if (policy == NULL || policy->status != state->status.kind) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint8_t stage = 0;
            if (policy->state_policy == POKEMON_STATUS_RESIDUAL_TICK) {
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_STATUS,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_RESIDUAL,
                    POKEMON_CONDITION_VALUE_NONE,
                    work->side, work->slot, state->status.kind, 0, 0);
                if (result != POKEMON_OK) return result;
            } else if (policy->state_policy ==
                    POKEMON_STATUS_RESIDUAL_ESCALATE) {
                uint8_t before = state->status.state.toxic.stage;
                if (before < battle->generation->toxic_stage_cap) {
                    state->status.state.toxic.stage++;
                }
                stage = state->status.state.toxic.stage;
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_STATUS,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_RESIDUAL,
                    POKEMON_CONDITION_VALUE_STAGE,
                    work->side, work->slot, state->status.kind, before, stage
                );
                if (result != POKEMON_OK) return result;
            } else if (policy->state_policy !=
                    POKEMON_STATUS_RESIDUAL_STATELESS) {
                return POKEMON_INVALID_CONFIGURATION;
            } else {
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_STATUS,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_RESIDUAL,
                    POKEMON_CONDITION_VALUE_NONE,
                    work->side, work->slot, state->status.kind, 0, 0);
                if (result != POKEMON_OK) return result;
            }
            uint16_t amount = battle->generation->residual_damage(
                policy->formula,
                battle->sides[work->side].sets[work->slot].stats[0],
                stage
            );
            result = residual_damage(
                battle, work->side, work->slot, amount,
                POKEMON_CONDITION_SCOPE_STATUS, state->status.kind
            );
            if (result != POKEMON_OK) return result;
        } else if (work->kind == POKEMON_RESIDUAL_VOLATILE) {
            PokemonMutable *state = &battle->sides[work->side].state[work->slot];
            int index = volatile_index_by_identity(
                state, work->descriptor_id, work->state_generation,
                work->effect_order);
            if (index < 0) {
                /* Showdown's residual handler list owns the captured effect
                 * state. A prior handler may remove the live volatile, but
                 * the already-discovered duration callback still executes on
                 * that captured state. Preserve the observable no-op tick. */
                if (work->duration_before != 0 && state->hp != 0 &&
                    !state->fainted) {
                    result = trace_condition(
                        battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                        POKEMON_CONDITION_UPDATE,
                        POKEMON_CONDITION_REASON_RESIDUAL,
                        POKEMON_CONDITION_VALUE_DURATION,
                        work->side, work->slot, work->condition_id,
                        work->duration_before,
                        (uint8_t)(work->duration_before - 1u));
                    if (result != POKEMON_OK) return result;
                    battle->condition_traces[
                        battle->condition_trace_count - 1u].descriptor_id =
                        work->descriptor_id;
                }
                continue;
            }
            PokemonVolatileState *volatile_state = &state->volatiles[index];
            uint8_t before = volatile_state->duration;
            uint8_t persistent = before == 0;
            if (!persistent) volatile_state->duration--;
            work->duration_after = volatile_state->duration;
            work->counter_after = volatile_state->counter;
            if (!persistent && volatile_state->duration == 0) {
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_EXPIRY,
                    POKEMON_CONDITION_VALUE_DURATION,
                    work->side, work->slot, work->condition_id, before, 0);
                if (result != POKEMON_OK) return result;
                battle->condition_traces[
                    battle->condition_trace_count - 1u].descriptor_id =
                    work->descriptor_id;
                if (work->condition_id == POKEMON_VOLATILE_STALL ||
					locked_ramp_policy_for_condition(battle, volatile_state) != NULL) {
                    PokemonConditionTrace *trace = &battle->condition_traces[
                        battle->condition_trace_count - 1];
                    trace->has_counter_before = 1;
                    trace->has_counter_after = 1;
                    trace->counter_before = volatile_state->counter;
                    trace->counter_after = volatile_state->counter;
                }
                PokemonHandlerRef condition_handlers[POKEMON_HANDLER_CAPACITY];
                size_t condition_handler_count = 0;
                result = append_owner_handlers(
                    battle, POKEMON_HANDLER_EVENT_END,
                    POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_VOLATILE,
                    volatile_state->descriptor_id,
                    volatile_state->state_generation,
                    work->side, work->slot, state->cached_speed,
                    volatile_state->effect_order, condition_handlers,
                    &condition_handler_count);
                if (result != POKEMON_OK) return result;
                for (size_t handler_index = 0;
                     handler_index < condition_handler_count; handler_index++) {
                    PokemonEventFrame end;
                    result = run_event_inner(battle, &(PokemonEventInput){
                        .event = POKEMON_HANDLER_EVENT_END,
                        .source = volatile_state->source,
                        .target_side = work->side, .target_slot = work->slot,
                        .source_effect = volatile_state->source_effect,
                        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                        .context.volatile_condition = {
                            .kind = (PokemonVolatileKind)work->condition_id},
                        .has_only_handler = 1,
                        .only_handler = condition_handlers[handler_index],
                    }, &end);
                    if (result != POKEMON_OK) return result;
                }
                /* End may install another volatile and reallocate the inline
                 * array, so reacquire the expiring condition by identity. */
                index = volatile_index_by_identity(
                    state, work->descriptor_id, work->state_generation,
                    work->effect_order);
                if (index < 0) return POKEMON_INVALID_CONFIGURATION;
                volatile_state = &state->volatiles[index];
            } else {
                PokemonHandlerRef condition_handlers[POKEMON_HANDLER_CAPACITY];
                size_t condition_handler_count = 0;
                result = append_owner_handlers(
                    battle, POKEMON_HANDLER_EVENT_RESIDUAL,
                    POKEMON_HANDLER_SCOPE_TARGET, POKEMON_OWNER_VOLATILE,
                    volatile_state->descriptor_id,
                    volatile_state->state_generation,
                    work->side, work->slot, state->cached_speed,
                    volatile_state->effect_order, condition_handlers,
                    &condition_handler_count);
                if (result != POKEMON_OK) return result;
                for (size_t handler_index = 0;
                     handler_index < condition_handler_count; handler_index++) {
                    PokemonEventFrame residual;
                    result = run_event_inner(battle, &(PokemonEventInput){
                        .event = POKEMON_HANDLER_EVENT_RESIDUAL,
                        .source = volatile_state->source,
                        .target_side = work->side, .target_slot = work->slot,
                        .source_effect = volatile_state->source_effect,
                        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                        .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                        .context.volatile_condition = {
                            .kind = (PokemonVolatileKind)work->condition_id},
                        .suppress_handler_trace = 1,
                        .has_only_handler = 1,
                        .only_handler = condition_handlers[handler_index],
                    }, &residual);
                    if (result != POKEMON_OK) return result;
                    index = volatile_index_by_identity(
                        state, work->descriptor_id, work->state_generation,
                        work->effect_order);
                    if (index < 0) break;
                    volatile_state = &state->volatiles[index];
                }
                if (index < 0) continue;
            }
            if (persistent) continue;
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                volatile_state->duration == 0 ? POKEMON_CONDITION_REMOVE :
                    POKEMON_CONDITION_UPDATE,
                volatile_state->duration == 0 ? POKEMON_CONDITION_REASON_HANDLER :
                    POKEMON_CONDITION_REASON_RESIDUAL,
                POKEMON_CONDITION_VALUE_DURATION,
                work->side, work->slot, work->condition_id,
                volatile_state->duration == 0 ? 0 : before,
                volatile_state->duration
            );
            if (result == POKEMON_OK && (volatile_state->counter != 0 ||
					locked_ramp_policy_for_condition(battle, volatile_state) != NULL)) {
                PokemonConditionTrace *trace = &battle->condition_traces[
                    battle->condition_trace_count - 1];
                trace->has_counter_before = 1;
                trace->has_counter_after = volatile_state->duration != 0;
                trace->counter_before = volatile_state->counter;
                trace->counter_after = volatile_state->counter;
            }
            if (result != POKEMON_OK) return result;
            battle->condition_traces[battle->condition_trace_count - 1u].descriptor_id =
                work->descriptor_id;
            if (volatile_state->duration == 0) {
                remove_volatile_at(state, (size_t)index);
            }
        } else if (work->kind == POKEMON_RESIDUAL_SLOT_CONDITION) {
            if (work->slot >= POKEMON_ACTIVE_POSITION_CAPACITY) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            PokemonSide *side = &battle->sides[work->side];
            int index = slot_condition_index(
                side, work->slot, work->descriptor_id);
            if (index < 0) continue;
            PokemonSlotConditionState *condition =
                &side->slot_conditions[work->slot][index];
            if (condition->state_generation != work->state_generation ||
                condition->effect_order != work->effect_order) continue;
            const PokemonSlotConditionPolicy *policy = slot_condition_policy(
                battle->data, condition->descriptor_id);
            if (policy == NULL || condition->duration == 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            PokemonSlotConditionState snapshot = *condition;
            uint8_t before = condition->duration--;
            work->duration_after = condition->duration;
            if (condition->duration != 0) {
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_SLOT,
                    POKEMON_CONDITION_UPDATE,
                    POKEMON_CONDITION_REASON_RESIDUAL,
                    POKEMON_CONDITION_VALUE_DURATION,
                    work->side, work->slot, condition->semantic_kind,
                    before, condition->duration);
                if (result != POKEMON_OK) return result;
                battle->condition_traces[
                    battle->condition_trace_count - 1].descriptor_id =
                    condition->descriptor_id;
                continue;
            }
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_SLOT,
                POKEMON_CONDITION_UPDATE,
                POKEMON_CONDITION_REASON_RESIDUAL,
                POKEMON_CONDITION_VALUE_DURATION,
                work->side, work->slot, snapshot.semantic_kind, before, 0);
            if (result != POKEMON_OK) return result;
            battle->condition_traces[
                battle->condition_trace_count - 1].descriptor_id =
                snapshot.descriptor_id;
            size_t active_slot = side->active;
            if (policy->effect_kind ==
                    POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE) {
                result = execute_delayed_fixed_damage(
                    battle, &snapshot, work->side, active_slot);
            } else if (policy->effect_kind ==
                    POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION) {
                PokemonEffectResult heal_result;
                uint16_t actual = 0;
                result = try_fraction_heal(
                    battle, snapshot.source, snapshot.source_effect,
                    work->side, active_slot, policy->numerator,
                    policy->denominator, &heal_result, &actual);
            } else {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (result != POKEMON_OK) return result;
            index = slot_condition_index(
                side, work->slot, work->descriptor_id);
            if (index < 0 ||
                side->slot_conditions[work->slot][index].state_generation !=
                    work->state_generation ||
                side->slot_conditions[work->slot][index].effect_order !=
                    work->effect_order) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_SLOT,
                POKEMON_CONDITION_REMOVE,
                POKEMON_CONDITION_REASON_HANDLER,
                POKEMON_CONDITION_VALUE_DURATION,
                work->side, work->slot, snapshot.semantic_kind, 0, 0);
            if (result != POKEMON_OK) return result;
            battle->condition_traces[
                battle->condition_trace_count - 1].descriptor_id =
                snapshot.descriptor_id;
            memmove(&side->slot_conditions[work->slot][index],
                &side->slot_conditions[work->slot][index + 1],
                (side->slot_condition_count[work->slot] - (size_t)index - 1) *
                    sizeof(side->slot_conditions[work->slot][0]));
            side->slot_condition_count[work->slot]--;
        } else if (work->kind == POKEMON_RESIDUAL_OWNER_EVENT) {
            const PokemonMutable *holder = &battle->sides[work->side].state[work->slot];
            if ((work->handler.owner.kind == POKEMON_OWNER_ITEM &&
                 (holder->item_id != work->handler.owner.effect_id ||
                  holder->item_generation != work->handler.owner.state_generation)) ||
                (work->handler.owner.kind == POKEMON_OWNER_ABILITY &&
                 (holder->ability_id != work->handler.owner.effect_id ||
                  holder->ability_generation != work->handler.owner.state_generation))) {
                continue;
            }
            PokemonEventFrame frame;
            result = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_RESIDUAL,
                .source = {POKEMON_ENTITY_POKEMON, work->side, work->slot},
                .target_side = work->side, .target_slot = work->slot,
                .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                .has_only_handler = 1, .only_handler = work->handler,
                .suppress_handler_trace = 1,
            }, &frame);
            if (result != POKEMON_OK) return result;
        } else if (work->kind == POKEMON_RESIDUAL_SIDE_CONDITION) {
            int index = side_condition_index(
                &battle->sides[work->side],
                (PokemonSideConditionKind)work->condition_id
            );
            if (index < 0) return POKEMON_INVALID_CONFIGURATION;
            PokemonSideConditionState *condition =
                &battle->sides[work->side].conditions[index];
            uint8_t before = condition->duration;
            condition->duration--;
            work->duration_after = condition->duration;
            if (condition->duration == 0) {
                uint16_t descriptor_id = condition->descriptor_id;
                uint16_t state_generation = condition->state_generation;
                uint8_t ran = 0;
                result = dispatch_side_condition_handler(
                    battle, POKEMON_HANDLER_EVENT_END, work->side, condition,
                    (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
                    (PokemonSourceEffectRef){
                        POKEMON_SOURCE_EFFECT_CONDITION, descriptor_id},
                    &ran);
                if (result != POKEMON_OK) return result;
                index = side_condition_index(
                    &battle->sides[work->side],
                    (PokemonSideConditionKind)work->condition_id);
                if (index < 0 ||
                    battle->sides[work->side].conditions[index].descriptor_id !=
                        descriptor_id ||
                    battle->sides[work->side].conditions[index].state_generation !=
                        state_generation) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                condition = &battle->sides[work->side].conditions[index];
            }
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_SIDE,
                condition->duration == 0 ? POKEMON_CONDITION_REMOVE :
                    POKEMON_CONDITION_UPDATE,
                condition->duration == 0 ? POKEMON_CONDITION_REASON_EXPIRY :
                    POKEMON_CONDITION_REASON_RESIDUAL,
                POKEMON_CONDITION_VALUE_DURATION,
                work->side, 0, work->condition_id, before, condition->duration
            );
            if (result != POKEMON_OK) return result;
            if (condition->duration == 0) {
                for (size_t i = (size_t)index + 1;
                    i < battle->sides[work->side].condition_count; i++) {
                    battle->sides[work->side].conditions[i - 1] =
                        battle->sides[work->side].conditions[i];
                }
                battle->sides[work->side].condition_count--;
            }
        }
    }
    /* Showdown queues faint work produced by duration-expiry End handlers
     * while the already-discovered residual list continues. Drain that batch
     * only after every residual owner has run. In Gen 3 this permits both
     * sides of a simultaneous Perish Song expiry to faint before terminal
     * resolution, yielding the generation's tie behavior. */
    result = drain_faints(battle);
    if (result != POKEMON_OK) return result;
    battle->residual_pending = 0;
    battle->residual_index = 0;
    if (battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
        battle->request.kind[1] == POKEMON_REQUEST_SWITCH) {
        battle->turn_suspended = POKEMON_TURN_SUSPENDED_AFTER_RESIDUAL;
    }
    return POKEMON_OK;
}
#line 17551 "pokemon.c"
