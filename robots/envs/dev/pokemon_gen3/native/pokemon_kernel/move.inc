#line 11641 "pokemon.c"
static int finish_battle(PokemonBattle *battle, size_t winner) {
    battle->terminal = 1;
    battle->winner = (int8_t)winner;
    battle->queue.count = 0;
    battle->phase = POKEMON_PHASE_TERMINAL;
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_WIN,
        .side = (uint8_t)winner,
    });
    return project_request(battle);
}

static int finish_draw(PokemonBattle *battle) {
    battle->terminal = 1;
    battle->winner = -1;
    battle->queue.count = 0;
    battle->phase = POKEMON_PHASE_TERMINAL;
    append_event(battle, (PokemonEvent){.kind = POKEMON_EVENT_TIE});
    return project_request(battle);
}

static int begin_next_turn(PokemonBattle *battle) {
    battle->turn++;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        PokemonMutable *active = &battle->sides[side].state[
            battle->sides[side].active];
        if (active->hp != 0 && active->active_turns != UINT32_MAX) {
            active->active_turns++;
        }
        for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
            battle->sides[side].state[slot].used_item_this_turn = 0;
            PokemonAttackRecord *record =
                &battle->sides[side].state[slot].last_attacked_by;
            if (!record->present) continue;
            if (battle->sides[side].state[slot].fainted) continue;
            if (record->source.kind != POKEMON_ENTITY_POKEMON ||
                record->source.side >= POKEMON_SIDES ||
                battle->sides[record->source.side].active != record->source.slot ||
                battle->sides[record->source.side].state[
                    record->source.slot].hp == 0) {
                memset(record, 0, sizeof(*record));
            } else {
                record->this_turn = 0;
            }
        }
    }
    return POKEMON_OK;
}

static int sample_next_turn_speed(PokemonBattle *battle) {
    const PokemonSharedTurnSpeedPolicy *speed_policy =
        &battle->generation->shared_turn_speed;
    battle->shared_turn_speed_active = 0;
    if (speed_policy->numerator != 0) {
        uint32_t sampled = 0;
        int status = draw_below(
            battle, POKEMON_DRAW_END_TURN, speed_policy->denominator, &sampled);
        if (status != POKEMON_OK) return status;
        battle->shared_turn_speed_active = sampled < speed_policy->numerator;
    }
    return POKEMON_OK;
}

static PokemonStaleness effective_staleness(const PokemonMutable *state) {
    return state->volatile_staleness != POKEMON_STALENESS_NONE ?
        state->volatile_staleness : state->staleness;
}

static uint8_t move_cycles_restorative_item(
    const PokemonBattle *battle, uint16_t move_id
) {
    const PokemonMoveData *move = find_move(battle, move_id);
    if (move == NULL) return 0;
    for (size_t i = 0; i < move->effect_count; i++) {
        const PokemonEffectOp *effect = move_effect(battle, move, i);
        if (effect != NULL && effect->kind == POKEMON_EFFECT_RECYCLE_ITEM) {
            return 1;
        }
    }
    return 0;
}

static uint8_t side_started_with_restorative_cycle(
    const PokemonBattle *battle, size_t side
) {
    uint8_t berry = 0;
    uint8_t cycle = 0;
    for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
        const PokemonSet *set = &battle->sides[side].sets[slot];
        const PokemonItemData *item = find_item(battle, set->item_id);
        const PokemonAbilityData *ability = find_ability(
            battle, set->ability_id);
        /* Preserve pinned Showdown's per-member assignment: cycle is
         * cumulative, while berry is overwritten until the pair is found. */
        berry = item != NULL &&
            (item->flags & POKEMON_ITEM_FLAG_RESTORATIVE) != 0;
        cycle |= ability != NULL &&
            (ability->semantic_flags &
                POKEMON_ABILITY_SEMANTIC_CYCLES_RESTORATIVE_ITEM) != 0;
        for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++) {
            cycle |= move_cycles_restorative_item(
                battle, set->move_ids[move]);
        }
        if (berry && cycle) break;
    }
    return berry && cycle;
}

/* Runs after next-turn request projection has resolved trapping, but before
 * generation-owned next-turn PRNG. It consumes no randomness. */
static int apply_terminal_policy(PokemonBattle *battle) {
    const PokemonTerminalPolicy *policy = &battle->policy.terminal;
    if (policy->turn_limit != 0 && battle->turn > policy->turn_limit) {
        return finish_draw(battle);
    }
    if (!policy->endless_battle_clause ||
        battle->turn <= policy->endless_minimum_turn) return POKEMON_OK;

    PokemonStaleness side_staleness[POKEMON_SIDES] = {0};
    uint8_t all_stale = 1;
    uint8_t any_external = 0;
    uint8_t can_escape[POKEMON_SIDES] = {0};
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        const PokemonSide *owner = &battle->sides[side];
        side_staleness[side] = effective_staleness(
            &owner->state[owner->active]);
        all_stale &= side_staleness[side] != POKEMON_STALENESS_NONE;
        any_external |= side_staleness[side] == POKEMON_STALENESS_EXTERNAL;
        uint8_t legal = battle->request.legal_switches[side];
        for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
            if ((legal & (UINT8_C(1) << slot)) == 0) continue;
            const PokemonMutable *candidate = &owner->state[slot];
            if (!candidate->fainted && candidate->hp != 0 &&
                effective_staleness(candidate) == POKEMON_STALENESS_NONE) {
                can_escape[side] = 1;
                break;
            }
        }
    }
    if (!all_stale || !any_external ||
        (can_escape[0] && can_escape[1])) return POKEMON_OK;

    uint8_t loser[POKEMON_SIDES] = {0};
    size_t loser_count = 0;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        loser[side] = side_started_with_restorative_cycle(battle, side);
        loser_count += loser[side];
    }
    if (loser_count == 1) return finish_battle(battle, loser[0] ? 1 : 0);
    return finish_draw(battle);
}

/* One owner for the stable next-turn boundary. Request projection discovers
 * trapping and legal replacements; terminal policy consumes that projection;
 * generation PRNG runs only for a surviving turn. */
static int project_and_stage_next_turn(PokemonBattle *battle) {
    int status = project_request(battle);
    if (status != POKEMON_OK) return status;
    status = apply_terminal_policy(battle);
    if (status != POKEMON_OK || battle->terminal) return status;
    return sample_next_turn_speed(battle);
}

typedef enum {
    HIT_IMMUNE,
    HIT_MISSED,
    HIT_BLOCKED,
    HIT_SUBSTITUTE,
    HIT_HEALED,
    HIT_CONNECTED,
} HitResultKind;

typedef struct {
    uint8_t critical;
    uint8_t damage_roll;
    uint16_t damage;
} ConnectedHit;

typedef struct {
    PokemonImmunityCause cause;
    uint16_t effect_id;
    PokemonHandlerId handler_id;
    uint8_t emit_event;
} ImmuneHit;

typedef struct {
    uint8_t critical;
    uint8_t damage_roll;
    uint16_t calculated_damage;
    uint16_t absorbed_damage;
    uint8_t broke;
} SubstituteHit;

typedef struct {
    uint16_t amount;
    uint8_t succeeded;
} HealedHit;

typedef struct {
    HitResultKind kind;
    union {
        ConnectedHit connected;
        ImmuneHit immune;
        SubstituteHit substitute;
        HealedHit healed;
    } value;
} HitResult;

static void remove_volatile_at(PokemonMutable *state, size_t index) {
    assert(index < state->volatile_count);
    for (size_t i = index + 1; i < state->volatile_count; i++) {
        state->volatiles[i - 1] = state->volatiles[i];
    }
    state->volatile_count--;
}

static int discover_try_primary_hit(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, uint8_t *intercepted
) {
    PokemonEventInput input = {
        .event = POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    };
    PokemonHandlerRef discovered[POKEMON_HANDLER_CAPACITY];
    size_t count = 0;
    int status = discover_handlers(battle, &input, discovered, &count);
    if (status != POKEMON_OK) return status;
    if ((size_t)battle->handler_count + count > POKEMON_HANDLER_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    status = order_event_handlers(
        battle, POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT, discovered, count);
    if (status != POKEMON_OK) return status;
    *intercepted = 0;
    for (size_t i = 0; i < count; i++) {
        const PokemonHandlerDescriptor *descriptor = &discovered[i].descriptor;
        if (descriptor->exceptional_handler_id !=
                POKEMON_EXCEPTION_SUBSTITUTE_TRY_PRIMARY_HIT ||
            descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint8_t applies = source_side != target_side || source_slot != target_slot;
        applies &= !move->bypass_substitute;
        battle->handlers[battle->handler_count++] = (PokemonHandlerInvocation){
            .handler = discovered[i],
            .semantic_sequence = next_semantic_sequence(battle),
            .invoked = 1,
            .result = applies ? POKEMON_HANDLER_HIT_SUBSTITUTE :
                POKEMON_HANDLER_CONTINUE,
        };
        *intercepted |= applies;
    }
    return POKEMON_OK;
}

/* TryPrimaryHit's Substitute handler.  Damage has already been calculated,
 * including its critical and damage-roll draws, but real HP has not changed. */
static int intercept_substitute(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t target_side, size_t target_slot, uint8_t intercepted, uint8_t critical,
    uint8_t damage_roll, uint16_t calculated_damage, HitResult *hit
) {
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    if (!intercepted) return POKEMON_OK;
    int index = volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE);
    if (index < 0) return POKEMON_INVALID_CONFIGURATION;
    PokemonVolatileState *sub = &target->volatiles[index];
    uint16_t absorbed = calculated_damage < sub->payload.substitute.hp ?
        calculated_damage : sub->payload.substitute.hp;
    sub->payload.substitute.hp = (uint16_t)(sub->payload.substitute.hp - absorbed);
    uint8_t broke = sub->payload.substitute.hp == 0;
    if (broke) {
        remove_volatile_at(target, (size_t)index);
        int marker = volatile_index(target, POKEMON_VOLATILE_SUBSTITUTE_BROKEN);
        if (marker < 0) {
            if (target->volatile_count == POKEMON_VOLATILE_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            target->volatiles[target->volatile_count++] = (PokemonVolatileState){
                .kind = POKEMON_VOLATILE_SUBSTITUTE_BROKEN,
                .descriptor_id = battle->generation->condition_descriptor(
                    POKEMON_OWNER_VOLATILE, POKEMON_VOLATILE_SUBSTITUTE_BROKEN),
                .state_generation = 1,
                .effect_order = ++battle->next_holder_effect_order,
                .payload.substitute_broken.breaking_move_id = move->id,
            };
        } else {
            target->volatiles[marker].payload.substitute_broken.breaking_move_id = move->id;
        }
    }
    *hit = (HitResult){
        .kind = HIT_SUBSTITUTE,
        .value.substitute = {critical, damage_roll, calculated_damage, absorbed, broke},
    };
    return POKEMON_OK;
}

static int apply_weather_damage_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, uint32_t *damage
) {
    PokemonEventFrame frame;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = *damage},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
    }, &frame);
    if (result == POKEMON_OK) *damage = frame.relay.value.u32;
    return result;
}

/* The calculation boundary owns only damage arithmetic and its draw.  Hit
 * admission (accuracy, immunity and Substitute) and HP mutation remain with
 * their respective transactions.  This makes source==target a valid product
 * state instead of encoding the source as `1 - target_side`. */
static int calculate_damage_inner(
    PokemonBattle *battle, const PokemonDamageRequest *request,
    PokemonCalculatedDamage *calculated
) {
    if (battle == NULL || request == NULL || calculated == NULL ||
        request->move == NULL ||
        request->source.kind != POKEMON_ENTITY_POKEMON ||
        request->target.kind != POKEMON_ENTITY_POKEMON ||
        request->source.side >= POKEMON_SIDES ||
        request->target.side >= POKEMON_SIDES ||
        request->source.slot >= battle->team_sizes[request->source.side] ||
        request->target.slot >= battle->team_sizes[request->target.side] ||
        (request->mode != POKEMON_DAMAGE_MODE_ORDINARY_MOVE &&
         request->mode != POKEMON_DAMAGE_MODE_SYNTHETIC_SELF_HIT)) {
        return POKEMON_INVALID_ARGUMENT;
    }
    const PokemonSet *source = &battle->sides[request->source.side].sets[
        request->source.slot];
    const PokemonSet *target = &battle->sides[request->target.side].sets[
        request->target.slot];
    const PokemonMutable *source_state = &battle->sides[request->source.side].state[
        request->source.slot];
    const PokemonMutable *target_state = &battle->sides[request->target.side].state[
        request->target.slot];
    const PokemonMoveData *move = request->move;
    uint8_t ordinary = request->mode == POKEMON_DAMAGE_MODE_ORDINARY_MOVE;
    uint8_t critical = ordinary && request->critical;
    uint32_t attack = move->category == POKEMON_CATEGORY_PHYSICAL ?
        source_state->stored_stats[0] : source_state->stored_stats[2];
    uint32_t defense = move->category == POKEMON_CATEGORY_PHYSICAL ?
        target_state->stored_stats[1] : target_state->stored_stats[3];
    PokemonStat attack_stat = move->category == POKEMON_CATEGORY_PHYSICAL ?
        POKEMON_STAT_ATK : POKEMON_STAT_SPA;
    PokemonStat defense_stat = move->category == POKEMON_CATEGORY_PHYSICAL ?
        POKEMON_STAT_DEF : POKEMON_STAT_SPD;
    int8_t attack_stage = source_state->boosts[attack_stat];
    int8_t defense_stage = target_state->boosts[defense_stat];
    if (critical && attack_stage < 0) attack_stage = 0;
    if (critical && defense_stage > 0) defense_stage = 0;
    /* Confusion self-hit uses calculated stats and their explicit stages, but
     * bypasses ordinary ModifyBoost/Atk/Def handlers and damage modifiers. */
    if (ordinary) {
        PokemonBoostTable source_input = {0};
        PokemonBoostTable target_input = {0};
        source_input.present[attack_stat] = 1;
        source_input.delta[attack_stat] = attack_stage;
        target_input.present[defense_stat] = 1;
        target_input.delta[defense_stat] = defense_stage;
        PokemonBoostTable source_boosts;
        PokemonBoostTable target_boosts;
        int boost_status = run_modify_boost_table_event(
            battle, request->source.side, request->source.slot,
            source_input, &source_boosts);
        if (boost_status != POKEMON_OK) return boost_status;
        boost_status = run_modify_boost_table_event(
            battle, request->target.side, request->target.slot,
            target_input, &target_boosts);
        if (boost_status != POKEMON_OK) return boost_status;
        if (!source_boosts.present[attack_stat] ||
            !target_boosts.present[defense_stat]) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        attack_stage = source_boosts.delta[attack_stat];
        defense_stage = target_boosts.delta[defense_stat];
    }
    attack = pokemon_apply_stage_ratio(
        battle->generation->stages, attack, attack_stage, 0);
    defense = pokemon_apply_stage_ratio(
        battle->generation->stages, defense, defense_stage, 0);
    uint8_t guts_active = 0;
    int result = POKEMON_OK;
    if (ordinary) {
        result = run_modify_attack_handlers(
            battle, request->source.side, request->source.slot,
            move->category == POKEMON_CATEGORY_PHYSICAL ?
                POKEMON_HANDLER_EVENT_MODIFY_ATK : POKEMON_HANDLER_EVENT_MODIFY_SPA,
            move, attack, &attack, &guts_active);
        if (result != POKEMON_OK) return result;
        result = run_modify_defense_handlers(
            battle, request->source, request->target,
            move->category == POKEMON_CATEGORY_PHYSICAL ?
                POKEMON_HANDLER_EVENT_MODIFY_DEF : POKEMON_HANDLER_EVENT_MODIFY_SPD,
            move, defense, &defense);
        if (result != POKEMON_OK) return result;
    }
    if (ordinary &&
        move->defense_policy == POKEMON_DEFENSE_POLICY_SELF_DESTRUCT) {
        defense /= battle->generation->self_destruct_defense_divisor;
        if (defense == 0) defense = 1;
    }
    PokemonDamageInput input = {
        .attacker = source, .defender = target, .move = move,
        .critical = critical, .attack = attack, .defense = defense,
    };
    uint32_t damage = battle->generation->base_damage(&input);
    if (ordinary) {
        if (battle->damage_stage_count == POKEMON_DAMAGE_STAGE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        uint32_t before_burn = damage;
        PokemonBurnReason burn_reason = POKEMON_BURN_NOT_BURNED;
        if (source_state->status.kind == POKEMON_STATUS_BURN) {
            if (damage == 0) burn_reason = POKEMON_BURN_ZERO_DAMAGE;
            else if (move->category != POKEMON_CATEGORY_PHYSICAL) {
                burn_reason = POKEMON_BURN_NOT_PHYSICAL;
            } else if (guts_active) burn_reason = POKEMON_BURN_GUTS;
            else {
                damage = apply_modifier_q12(damage, 2048);
                burn_reason = POKEMON_BURN_APPLIED;
            }
        }
        battle->damage_stages[battle->damage_stage_count++] =
            (PokemonDamageStageTrace){
                .kind = POKEMON_DAMAGE_STAGE_BURN,
                .mode = request->mode,
                .semantic_sequence = next_semantic_sequence(battle),
                .input = before_burn, .modifier_q12 = 2048, .output = damage,
                .source_side = request->source.side,
                .target_side = request->target.side, .move_id = move->id,
                .applied = burn_reason == POKEMON_BURN_APPLIED,
                .reason = burn_reason,
        };
        result = run_modify_damage_phase1_event(
            battle, move, request->source, request->target, critical, &damage);
        if (result != POKEMON_OK) return result;
        if (battle->generation->weather_damage_stage ==
                POKEMON_WEATHER_DAMAGE_BEFORE_FINAL_BASE_OFFSET) {
            result = apply_weather_damage_event(
                battle, move, request->source.side, request->source.slot,
                request->target.side, request->target.slot, &damage);
            if (result != POKEMON_OK) return result;
        }
    }
    if (move->category == POKEMON_CATEGORY_PHYSICAL && damage == 0) damage = 1;
    damage += 2u;
    if (ordinary && battle->generation->weather_damage_stage ==
            POKEMON_WEATHER_DAMAGE_AFTER_FINAL_BASE_OFFSET) {
        result = apply_weather_damage_event(
            battle, move, request->source.side, request->source.slot,
            request->target.side, request->target.slot, &damage);
        if (result != POKEMON_OK) return result;
    }
    if (critical) damage = apply_modifier_q12(
        damage, (uint32_t)battle->generation->critical_multiplier * 4096u);
    if (ordinary && has_type(source_state, move->type)) {
        damage = apply_modifier_q12(damage, 6144);
    }
    if (ordinary) damage = damage * type_multiplier(
        battle, move->type, target_state) / 4u;
    if (ordinary) {
        result = run_modify_damage_event(
            battle, move, request->source, request->target, &damage);
        if (result != POKEMON_OK) return result;
    }
    uint32_t roll = 0;
    result = draw_below(battle, POKEMON_DRAW_DAMAGE_ROLL, 16, &roll);
    if (result != POKEMON_OK) return result;
    damage = damage * (100u - roll) / 100u;
    if (damage == 0) damage = 1;
    *calculated = (PokemonCalculatedDamage){
        .critical = critical, .damage_roll = (uint8_t)roll,
        .damage = (uint16_t)(damage > UINT16_MAX ? UINT16_MAX : damage),
    };
    return POKEMON_OK;
}

int pokemon_calculate_damage(
    PokemonBattle *battle, const PokemonDamageRequest *request,
    PokemonCalculatedDamage *calculated
) {
    if (battle == NULL || calculated == NULL) return POKEMON_INVALID_ARGUMENT;
    PokemonBattle next = *battle;
    PokemonCalculatedDamage next_calculated;
    int result = calculate_damage_inner(&next, request, &next_calculated);
    if (result != POKEMON_OK) return result;
    *battle = next;
    *calculated = next_calculated;
    return POKEMON_OK;
}

static int resolve_invulnerability(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, uint8_t *admitted
) {
    *admitted = 1;
    const PokemonEventSpec *spec = event_spec(
        battle, POKEMON_HANDLER_EVENT_INVULNERABILITY);
    if (spec == NULL || !spec->supported) return POKEMON_OK;
    PokemonEventFrame frame;
    int status = run_event_inner(
        battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_INVULNERABILITY,
            .source = {POKEMON_ENTITY_POKEMON,
                (uint8_t)source_side, (uint8_t)source_slot},
            .target_side = (uint8_t)target_side,
            .target_slot = (uint8_t)target_slot,
            .source_effect = active_source_effect(battle, move->id),
            .relay = {.kind = POKEMON_RELAY_BOOLEAN,
                .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move},
        }, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        (frame.relay.kind == POKEMON_RELAY_BOOLEAN &&
         !frame.relay.value.boolean)) {
        *admitted = 0;
        return POKEMON_OK;
    }
    if (frame.relay.kind != POKEMON_RELAY_BOOLEAN &&
        !(frame.relay.kind == POKEMON_RELAY_NUMBER &&
          frame.relay.value.number == 0.0)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    return POKEMON_OK;
}

static int resolve_negate_immunity(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, uint8_t *negated
) {
    uint8_t applicable = 0;
    int status = unsupported_event_applicable(
        battle, POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY,
        source_side, source_slot, target_side, target_slot, &applicable);
    if (status != POKEMON_OK) return status;
    if (!applicable) {
        *negated = 0;
        return POKEMON_OK;
    }
    PokemonEventFrame frame;
    status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY,
        .source = {POKEMON_ENTITY_POKEMON,
            (uint8_t)source_side, (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .suppress_trace = 1,
    }, &frame);
    if (status != POKEMON_OK) return status;
    if (frame.relay.kind == POKEMON_RELAY_NULL) {
        *negated = 0;
        return POKEMON_OK;
    }
    if (frame.relay.kind != POKEMON_RELAY_BOOLEAN) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *negated = !frame.relay.value.boolean;
    return POKEMON_OK;
}

static int resolve_move_immunity(
    PokemonBattle *battle, const PokemonMoveData *move,
    const PokemonSet *defender, const PokemonMutable *defender_state,
    size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot,
    PokemonImmunityCause *cause, uint16_t *effect_id
) {
    uint8_t natural_immune = 0;
    uint8_t immunity_negated = 0;
    int status = resolve_negate_immunity(
        battle, move, source_side, source_slot, target_side, target_slot,
        &immunity_negated);
    if (status != POKEMON_OK) return status;
    *cause = POKEMON_IMMUNITY_NONE;
    *effect_id = 0;
    /* Showdown's ??? type returns from runImmunity before consulting either
     * the type chart or ability immunities.  The resolved plugin names that
     * non-interacting type; the generic kernel does not name a generation. */
    if (battle->data->has_non_interacting_type &&
        move->type == battle->data->non_interacting_type) return POKEMON_OK;
    natural_immune = type_is_immune(battle, move->type, defender_state) &&
        !immunity_negated;
    if (natural_immune) {
        *cause = POKEMON_IMMUNITY_NATURAL_TYPE;
        return POKEMON_OK;
    }
    const PokemonAbilityData *ability = find_ability(
        battle, defender->ability_id);
    if (ability != NULL && ability->grants_ground_immunity &&
        move->type == ability->ground_immunity_type) {
        *cause = POKEMON_IMMUNITY_LEVITATE;
        *effect_id = ability->id;
    }
    return POKEMON_OK;
}

/* Evaluate an already-admitted ordinary move without mutating either HP.
 * This is shared by connected hits and generated failure callbacks such as
 * Gen 3's crash-damage family, so critical and damage-roll draws remain
 * owned by the semantic calculation that consumes them. */
static int calculate_admitted_move_damage(
    PokemonBattle *battle, const PokemonMoveData *event_move,
    PokemonMoveData *resolved_move, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, PokemonCalculatedDamage *calculated
) {
    PokemonEventFrame crit_ratio;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)source_side,
        .target_slot = (uint8_t)source_slot,
        .source_effect = active_source_effect(battle, event_move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = event_move},
        .relay = {.kind = POKEMON_RELAY_U32,
            .value.u32 = event_move->critical_stage},
    }, &crit_ratio);
    if (result != POKEMON_OK) return result;
    uint8_t numerator = 0;
    uint8_t denominator = 0;
    battle->generation->critical_chance(
        crit_ratio.cancellation == POKEMON_EVENT_CANCEL_NONE ?
            crit_ratio.relay.value.u32 : 0,
        &numerator, &denominator);
    uint8_t critical = 0;
    if (numerator != 0) {
        if (denominator == 0 || numerator > denominator) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint32_t roll = 0;
        result = draw_below(battle, POKEMON_DRAW_CRITICAL, denominator, &roll);
        if (result != POKEMON_OK) return result;
        critical = roll < numerator;
    }
    if (critical) {
        PokemonEventFrame critical_hit;
        result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_CRITICAL_HIT,
            .source = {POKEMON_ENTITY_NONE, 0, 0},
            .target_side = (uint8_t)target_side,
            .target_slot = (uint8_t)target_slot,
            .source_effect = active_source_effect(battle, event_move->id),
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = event_move},
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        }, &critical_hit);
        if (result != POKEMON_OK) return result;
        critical = critical_hit.cancellation == POKEMON_EVENT_CANCEL_NONE &&
            critical_hit.relay.value.boolean;
    }
    if (resolved_move->target_status_power_mask != 0) {
        const uint8_t target_status =
            battle->sides[target_side].state[target_slot].status.kind;
        if (target_status != POKEMON_STATUS_NONE &&
            (resolved_move->target_status_power_mask &
                (UINT16_C(1) << target_status)) != 0) {
            const uint32_t adjusted_power =
                (uint32_t)resolved_move->power *
                resolved_move->target_status_power_multiplier;
            if (adjusted_power == 0 || adjusted_power > UINT16_MAX) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            resolved_move->power = (uint16_t)adjusted_power;
        }
    }
    PokemonEventFrame base_power;
    result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_BASE_POWER,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)source_side,
        .target_slot = (uint8_t)source_slot,
        .source_effect = active_source_effect(battle, event_move->id),
        .relay = {.kind = POKEMON_RELAY_U32,
            .value.u32 = resolved_move->power},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = event_move},
        .include_move_self = 1,
    }, &base_power);
    if (result != POKEMON_OK) return result;
    if (base_power.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        base_power.relay.value.u32 == 0 ||
        base_power.relay.value.u32 > UINT16_MAX) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    resolved_move->power = (uint16_t)base_power.relay.value.u32;
    return calculate_damage_inner(battle, &(PokemonDamageRequest){
        .mode = POKEMON_DAMAGE_MODE_ORDINARY_MOVE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target = {POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
            (uint8_t)target_slot},
        .move = resolved_move,
        .critical = critical,
    }, calculated);
}

static int resolve_hit(
    PokemonBattle *battle, const PokemonSet *attacker,
    const PokemonSet *defender,
    PokemonMutable *defender_state, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    uint8_t hit_index, uint8_t *requested_hits, HitResult *hit
) {
    int result = POKEMON_OK;
    hit->kind = HIT_CONNECTED;
    if (hit_index == 0) {
        uint8_t admitted = 0;
        int status = resolve_invulnerability(
            battle, move, source_side, source_slot, target_side, target_slot,
            &admitted);
        if (status != POKEMON_OK) return status;
        if (!admitted) {
            hit->kind = HIT_MISSED;
            return POKEMON_OK;
        }
    }

    PokemonImmunityCause cause = POKEMON_IMMUNITY_NONE;
    uint16_t effect_id = 0;
    PokemonHandlerId handler_id = 0;
    result = resolve_move_immunity(
        battle, move, defender, defender_state,
        source_side, source_slot, target_side, target_slot,
        &cause, &effect_id);
    if (result != POKEMON_OK) return result;
    result = POKEMON_OK;
    /* Showdown runs immunity inside every moveHit. Repeat-accuracy moves
     * perform their later accuracy check before entering that hit. */
    uint8_t records_immunity = !battle->data->has_non_interacting_type ||
        move->type != battle->data->non_interacting_type;
    if (records_immunity &&
        (hit_index == 0 || move->multihit_accuracy ==
            POKEMON_MULTIHIT_ACCURACY_EACH_HIT)) {
        if (battle->immunity_count == POKEMON_IMMUNITY_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        battle->immunities[battle->immunity_count++] =
            (PokemonImmunityDecision){
                .move_type = move->type,
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .cause = cause,
                .effect_id = effect_id,
            };
    }
    if (hit_index > 0 &&
        move->multihit_accuracy == POKEMON_MULTIHIT_ACCURACY_EACH_HIT) {
        uint8_t accuracy_hit = 0;
        PokemonImmunityCause accuracy_immunity = POKEMON_IMMUNITY_NONE;
        result = resolve_move_accuracy(
            battle, move, source_side, source_slot, target_side, target_slot,
            &accuracy_hit, &accuracy_immunity);
        if (result != POKEMON_OK) return result;
        if (accuracy_immunity != POKEMON_IMMUNITY_NONE) {
            *hit = (HitResult){
                .kind = HIT_IMMUNE,
                .value.immune = {accuracy_immunity, 0, 0, 1},
            };
            return POKEMON_OK;
        }
        if (!accuracy_hit) {
            hit->kind = HIT_MISSED;
            return POKEMON_OK;
        }
    }
    if (hit_index > 0 && cause != POKEMON_IMMUNITY_NONE) {
        *hit = (HitResult){
            .kind = HIT_IMMUNE,
            .value.immune = {cause, effect_id, 0, 1},
        };
        return POKEMON_OK;
    }
    if (hit_index == 0) {
        if (battle->generation->hit_staging !=
                POKEMON_HIT_STAGING_DEFER_IMMUNITY_AFTER_ACCURACY_AND_TRY_HIT) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        /* The Gen 3 override discovers natural and move-owned immunity before
         * accuracy, but deliberately defers that result.  Accuracy is still
         * consumed; target TryHit (Protect, absorbers, etc.) can mask it. */
        PokemonImmunityCause pending_cause = cause;
        uint16_t pending_effect_id = effect_id;
        PokemonHandlerId pending_handler_id = 0;
        if (pending_cause == POKEMON_IMMUNITY_NONE) {
            PokemonEventFrame try_immunity;
            uint8_t ran_try_immunity = 0;
            result = run_move_self_event(
                battle, POKEMON_HANDLER_EVENT_TRY_IMMUNITY, move,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)source_side, (uint8_t)source_slot},
                target_side, target_slot, active_source_effect(battle, move->id),
                (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                    .value.boolean = 1},
                &try_immunity, &ran_try_immunity);
            if (result != POKEMON_OK) return result;
            if (ran_try_immunity &&
                (try_immunity.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                 !try_immunity.relay.value.boolean)) {
                pending_cause = POKEMON_IMMUNITY_HANDLER;
                pending_handler_id = try_immunity.cancelling_handler_id;
            }
        }
        uint8_t accuracy_hit = 0;
        PokemonImmunityCause accuracy_immunity = POKEMON_IMMUNITY_NONE;
        result = resolve_move_accuracy(
            battle, move, source_side, source_slot, target_side, target_slot,
            &accuracy_hit, &accuracy_immunity);
        if (result != POKEMON_OK) return result;
        if (accuracy_immunity != POKEMON_IMMUNITY_NONE) {
            *hit = (HitResult){
                .kind = HIT_IMMUNE,
                .value.immune = {accuracy_immunity, 0, 0, 1},
            };
            return POKEMON_OK;
        }
        if (!accuracy_hit) {
            if (pending_cause != POKEMON_IMMUNITY_NONE) {
                *hit = (HitResult){.kind = HIT_IMMUNE,
                    .value.immune = {pending_cause, pending_effect_id,
                        pending_handler_id, 1}};
            } else {
                hit->kind = HIT_MISSED;
            }
            return POKEMON_OK;
        }
        PokemonEventCancellation cancellation = POKEMON_EVENT_CANCEL_NONE;
        uint8_t emit_immunity = 1;
        cause = POKEMON_IMMUNITY_NONE;
        effect_id = 0;
        result = run_try_hit_handlers(
            battle, source_side, source_slot, target_side, target_slot, move,
            &cause, &effect_id, &handler_id, &emit_immunity, &cancellation);
        if (result != POKEMON_OK) return result;
        if (cancellation == POKEMON_EVENT_CANCEL_NOT_FAIL) {
            hit->kind = HIT_BLOCKED;
            return POKEMON_OK;
        }
        if (cause != POKEMON_IMMUNITY_NONE) {
            *hit = (HitResult){.kind = HIT_IMMUNE,
                .value.immune = {cause, effect_id, handler_id, emit_immunity}};
            return POKEMON_OK;
        }
        if (pending_cause != POKEMON_IMMUNITY_NONE) {
            *hit = (HitResult){.kind = HIT_IMMUNE,
                .value.immune = {pending_cause, pending_effect_id,
                    pending_handler_id, 1}};
            return POKEMON_OK;
        }
        PokemonEventFrame move_try_hit;
        uint8_t ran_move_try_hit = 0;
        result = run_move_self_event(
            battle, POKEMON_HANDLER_EVENT_TRY_HIT, move,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)source_side, (uint8_t)source_slot},
            target_side, target_slot, active_source_effect(battle, move->id),
            (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                .value.boolean = 1},
            &move_try_hit, &ran_move_try_hit);
        if (result != POKEMON_OK) return result;
        if (ran_move_try_hit &&
            (move_try_hit.cancellation != POKEMON_EVENT_CANCEL_NONE ||
             !move_try_hit.relay.value.boolean)) {
            hit->kind = HIT_BLOCKED;
            return POKEMON_OK;
        }
        if (move->multihit_min != 0) {
            if (move->multihit_min == move->multihit_max) {
                *requested_hits = move->multihit_min;
            } else {
                const PokemonMultiHitPolicy *policy =
                    &battle->generation->multihit;
                uint32_t sample = 0;
                result = draw_below(
                    battle, POKEMON_DRAW_MULTIHIT_COUNT,
                    policy->outcome_count, &sample
                );
                if (result != POKEMON_OK) return result;
                *requested_hits = policy->outcomes[sample];
            }
            if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            battle->hit_traces[battle->hit_trace_count++] = (PokemonHitTrace){
                .semantic_sequence = next_semantic_sequence(battle),
                .kind = POKEMON_HIT_PLAN, .move_id = move->id,
                .source_side = (uint8_t)source_side,
                .source_slot = (uint8_t)source_slot,
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .requested_hits = *requested_hits,
                .dynamic_plan = battle->move_frame_depth != 0 &&
                    battle->move_frames[battle->move_frame_depth - 1].party_hit_plan_active,
            };
        }
    }

    if (battle->move_frame_depth != 0) {
        const PokemonActiveMoveFrame *active =
            &battle->move_frames[battle->move_frame_depth - 1];
        if (active->party_hit_plan_active && active->party_hit_count == 0) {
            PokemonEventFrame base_power;
            result = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_BASE_POWER,
                .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                    (uint8_t)source_slot},
                .target_side = (uint8_t)source_side,
                .target_slot = (uint8_t)source_slot,
                .source_effect = active_source_effect(battle, move->id),
                .relay = {.kind = POKEMON_RELAY_U32,
                    .value.u32 = move->power},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = move},
                .include_move_self = 1,
            }, &base_power);
            if (result != POKEMON_OK) return result;
            if (base_power.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                base_power.relay.kind == POKEMON_RELAY_NULL) {
                hit->kind = HIT_BLOCKED;
                return POKEMON_OK;
            }
            return POKEMON_INVALID_CONFIGURATION;
        }
    }

    const PokemonMutable *attacker_state =
        &battle->sides[source_side].state[source_slot];
    uint8_t substitute_intercepted = 0;
    result = discover_try_primary_hit(
        battle, move, source_side, source_slot, target_side, target_slot,
        &substitute_intercepted);
    if (result != POKEMON_OK) return result;
    PokemonImmunityCause damage_cause = POKEMON_IMMUNITY_NONE;
    uint16_t damage_effect_id = 0;
    result = resolve_move_immunity(
        battle, move, defender, defender_state,
        source_side, source_slot, target_side, target_slot,
        &damage_cause, &damage_effect_id);
    if (result != POKEMON_OK) return result;
    if (damage_cause != POKEMON_IMMUNITY_NONE) {
        *hit = (HitResult){
            .kind = HIT_IMMUNE,
            .value.immune = {damage_cause, damage_effect_id, 0, 1},
        };
        return POKEMON_OK;
    }
    if (battle->move_frame_depth != 0) {
        PokemonActiveMoveFrame *active =
            &battle->move_frames[battle->move_frame_depth - 1];
        if (active->weighted_outcome_kind ==
                POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL) {
            PokemonEffectResult effect_result = POKEMON_EFFECT_FAILED;
            uint16_t actual = 0;
            if (!substitute_intercepted && defender_state->hp != 0 &&
                defender_state->hp < defender->stats[0] &&
                battle->sides[target_side].active == target_slot) {
                result = try_fraction_heal(
                    battle, (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        (uint8_t)source_side, (uint8_t)source_slot},
                    active_source_effect(battle, move->id), target_side,
                    target_slot, active->heal_numerator,
                    active->heal_denominator, &effect_result, &actual);
                if (result != POKEMON_OK) return result;
                if (actual != 0) {
                    battle->events[battle->event_count - 1].move_id = move->id;
                }
            }
            *hit = (HitResult){
                .kind = HIT_HEALED,
                .value.healed = {
                    .amount = actual,
                    .succeeded = effect_result == POKEMON_EFFECT_APPLIED,
                },
            };
            return POKEMON_OK;
        }
    }
    PokemonMoveData resolved_move = *move;
    if (move->damage_formula == POKEMON_DAMAGE_OWNER_CONDITION_VALUE) {
        const PokemonVolatileState *condition = NULL;
        for (size_t i = 0; i < attacker_state->volatile_count; i++) {
            if (attacker_state->volatiles[i].descriptor_id ==
                    move->damage_parameter) {
                condition = &attacker_state->volatiles[i];
                break;
            }
        }
        if (condition == NULL ||
            (condition->kind != POKEMON_VOLATILE_PREPARED_RETALIATION &&
             condition->kind != POKEMON_VOLATILE_STORED_DAMAGE)) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint32_t stored = 0;
        if (condition->kind == POKEMON_VOLATILE_PREPARED_RETALIATION) {
            if (!condition->payload.retaliation.captured) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            stored = condition->payload.retaliation.damage;
        } else {
            if (!condition->payload.stored_damage.captured) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            stored = condition->payload.stored_damage.value;
        }
        uint8_t multiplier = move->owner_condition_damage_multiplier == 0 ?
            1 : move->owner_condition_damage_multiplier;
        stored = stored > UINT32_MAX / multiplier ? UINT32_MAX :
            stored * multiplier;
        uint16_t damage = stored == 0 ? 1 :
            stored > UINT16_MAX ? UINT16_MAX : (uint16_t)stored;
        if (battle->damage_formula_trace_count ==
            POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        battle->damage_formula_traces[battle->damage_formula_trace_count++] =
            (PokemonDamageFormulaTrace){
                .semantic_sequence = next_semantic_sequence(battle),
                .formula = move->damage_formula, .move_id = move->id,
                .source_side = (uint8_t)source_side,
                .source_slot = (uint8_t)source_slot,
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .resolved_value = damage,
            };
        result = intercept_substitute(
            battle, move, target_side, target_slot, substitute_intercepted,
            0, 0, damage, hit);
        if (result != POKEMON_OK || hit->kind == HIT_SUBSTITUTE) return result;
        if (damage > defender_state->hp) damage = defender_state->hp;
        *hit = (HitResult){
            .kind = HIT_CONNECTED,
            .value.connected = {.critical = 0, .damage_roll = 0,
                .damage = damage},
        };
        return POKEMON_OK;
    }
    if (move->damage_formula == POKEMON_DAMAGE_FIXED_LEVEL ||
        move->damage_formula == POKEMON_DAMAGE_FIXED_LITERAL ||
        move->damage_formula == POKEMON_DAMAGE_TARGET_HP_FRACTION ||
        move->damage_formula == POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE ||
        move->damage_formula == POKEMON_DAMAGE_TARGET_CURRENT_HP ||
        move->damage_formula == POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT) {
        uint16_t random_value = 0;
        if (move->damage_formula == POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT) {
            const PokemonDamageFormulaRandomPolicy *random_policy = NULL;
            for (size_t i = 0;
                 i < battle->generation->random_damage_formula_count; i++) {
                const PokemonDamageFormulaRandomPolicy *candidate =
                    &battle->generation->random_damage_formulas[i];
                if (candidate->formula == move->damage_formula) {
                    random_policy = candidate;
                    break;
                }
            }
            if (random_policy == NULL) return POKEMON_INVALID_CONFIGURATION;
            uint32_t sample = 0;
            result = draw_below(
                battle, POKEMON_DRAW_DAMAGE_FORMULA,
                (uint32_t)(random_policy->maximum_exclusive -
                    random_policy->minimum), &sample);
            if (result != POKEMON_OK) return result;
            random_value = (uint16_t)(random_policy->minimum + sample);
        }
        PokemonDamageFormulaOutput formula;
        battle->generation->resolve_damage_formula(
            &(PokemonDamageFormulaInput){
                .formula = move->damage_formula,
                .parameter = move->damage_parameter,
                .level = attacker->level,
                .hp = attacker_state->hp, .max_hp = attacker->stats[0],
                .target_hp = defender_state->hp,
                .random_value = random_value,
            },
            &formula
        );
        if (battle->damage_formula_trace_count ==
            POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        battle->damage_formula_traces[battle->damage_formula_trace_count++] =
            (PokemonDamageFormulaTrace){
                .semantic_sequence = next_semantic_sequence(battle),
                .formula = move->damage_formula, .move_id = move->id,
                .source_side = (uint8_t)source_side,
                .source_slot = (uint8_t)source_slot,
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .resolved_value = formula.fixed_damage,
            };
        uint16_t damage = formula.fixed_damage;
        result = intercept_substitute(
            battle, move, target_side, target_slot, substitute_intercepted,
            0, 0, damage, hit);
        if (result != POKEMON_OK || hit->kind == HIT_SUBSTITUTE) return result;
        if (damage > defender_state->hp) damage = defender_state->hp;
        *hit = (HitResult){
            .kind = HIT_CONNECTED,
            .value.connected = {.critical = 0, .damage_roll = 0, .damage = damage},
        };
        return POKEMON_OK;
    }
    if (move->damage_formula == POKEMON_DAMAGE_HP_BRACKET) {
        PokemonDamageFormulaOutput formula;
        battle->generation->resolve_damage_formula(
            &(PokemonDamageFormulaInput){
                .formula = move->damage_formula, .level = attacker->level,
                .hp = attacker_state->hp, .max_hp = attacker->stats[0],
            },
            &formula
        );
        if (battle->damage_formula_trace_count ==
            POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        battle->damage_formula_traces[battle->damage_formula_trace_count++] =
            (PokemonDamageFormulaTrace){
                .semantic_sequence = next_semantic_sequence(battle),
                .formula = POKEMON_DAMAGE_HP_BRACKET, .move_id = move->id,
                .source_side = (uint8_t)source_side,
                .source_slot = (uint8_t)source_slot,
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .hp = attacker_state->hp, .max_hp = attacker->stats[0],
                .ratio = formula.ratio, .bracket = formula.bracket,
                .resolved_value = formula.resolved_power,
            };
        resolved_move.power = (uint8_t)formula.resolved_power;
    }
    if (move->base_power_policy == POKEMON_BASE_POWER_SOURCE_HP_RATIO) {
        uint32_t scaled = (uint32_t)move->power * attacker_state->hp /
            attacker->stats[0];
        resolved_move.power = (uint8_t)(scaled == 0 ? 1 : scaled);
    } else if (move->base_power_policy ==
            POKEMON_BASE_POWER_SOURCE_HAPPINESS ||
            move->base_power_policy ==
            POKEMON_BASE_POWER_SOURCE_UNHAPPINESS) {
        uint32_t happiness = attacker->happiness_specified ?
            attacker->happiness : 255u;
        if (move->base_power_policy ==
            POKEMON_BASE_POWER_SOURCE_UNHAPPINESS) {
            happiness = 255u - happiness;
        }
        uint32_t scaled = happiness * 10u / 25u;
        resolved_move.power = (uint8_t)(scaled == 0 ? 1 : scaled);
    } else if (move->base_power_policy ==
            POKEMON_BASE_POWER_PERSONAL_MOVE_PROFILE) {
        const PokemonPersonalMoveProfile *profile =
            &attacker_state->personal_move_profile;
        if (move->personal_move_profile_kind == 0 ||
            profile->kind != move->personal_move_profile_kind ||
            profile->power == 0) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        resolved_move.power = profile->power;
    } else if (move->base_power_policy == POKEMON_BASE_POWER_HIT_INDEX) {
        uint16_t indexed_power = (uint16_t)move->power * (hit_index + 1u);
        if (indexed_power == 0 || indexed_power > UINT8_MAX) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        resolved_move.power = (uint8_t)indexed_power;
    } else if (move->base_power_policy == POKEMON_BASE_POWER_TARGET_WEIGHT) {
        const PokemonSpeciesData *species = find_species(
            battle, defender_state->species_id);
        const PokemonWeightPowerPolicy *policy = weight_power_policy(
            battle->data, move->weight_power_policy_id);
        if (species == NULL || species->weight_hg == 0 || policy == NULL ||
            policy->bracket_count == 0) return POKEMON_INVALID_CONFIGURATION;
        size_t bracket = 0;
        while (bracket + 1u < policy->bracket_count &&
            species->weight_hg >= policy->upper_bounds_hg[bracket]) {
            bracket++;
        }
        resolved_move.power = policy->powers[bracket];
    }

    PokemonCalculatedDamage calculated;
    result = calculate_admitted_move_damage(
        battle, move, &resolved_move, source_side, source_slot,
        target_side, target_slot, &calculated);
    if (result != POKEMON_OK) return result;
    result = intercept_substitute(
        battle, move, target_side, target_slot, substitute_intercepted,
        calculated.critical, calculated.damage_roll, calculated.damage, hit);
    if (result != POKEMON_OK || hit->kind == HIT_SUBSTITUTE) return result;
    *hit = (HitResult){
        .kind = HIT_CONNECTED,
        .value.connected = {
            .critical = calculated.critical,
            .damage_roll = calculated.damage_roll,
            .damage = calculated.damage,
        },
    };
    return POKEMON_OK;
}

static int apply_move_failure_policy(
    PokemonBattle *battle, const PokemonMoveData *move,
    PokemonEntityRef user, PokemonEntityRef target
) {
    const PokemonMoveFailurePolicy *policy = &move->failure_policy;
    if (policy->kind == POKEMON_MOVE_FAILURE_NONE) return POKEMON_OK;
    if (policy->kind !=
            POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE ||
        user.kind != POKEMON_ENTITY_POKEMON ||
        target.kind != POKEMON_ENTITY_POKEMON) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (battle->effect_trace_count == POKEMON_EFFECT_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    const PokemonSet *target_set = &battle->sides[target.side].sets[target.slot];
    const PokemonMutable *target_state =
        &battle->sides[target.side].state[target.slot];
    if (policy->require_target_type_admission) {
        PokemonImmunityCause cause = POKEMON_IMMUNITY_NONE;
        uint16_t effect_id = 0;
        int status = resolve_move_immunity(
            battle, move, target_set, target_state,
            user.side, user.slot, target.side, target.slot,
            &cause, &effect_id);
        if (status != POKEMON_OK || cause != POKEMON_IMMUNITY_NONE) {
            return status;
        }
    }
    /* getDamage performs its own admission after the callback's explicit
     * runImmunity guard. Preserve both event boundaries. */
    PokemonImmunityCause cause = POKEMON_IMMUNITY_NONE;
    uint16_t effect_id = 0;
    int status = resolve_move_immunity(
        battle, move, target_set, target_state,
        user.side, user.slot, target.side, target.slot,
        &cause, &effect_id);
    if (status != POKEMON_OK || cause != POKEMON_IMMUNITY_NONE) return status;
    PokemonMoveData resolved = *move;
    PokemonCalculatedDamage hypothetical;
    status = calculate_admitted_move_damage(
        battle, move, &resolved, user.side, user.slot,
        target.side, target.slot, &hypothetical);
    if (status != POKEMON_OK) return status;
    uint32_t requested = (uint32_t)hypothetical.damage * policy->numerator /
        policy->denominator;
    if (requested < policy->minimum) requested = policy->minimum;
    uint32_t target_max = battle->sides[target.side].sets[target.slot].stats[0];
    uint32_t cap = target_max * policy->target_max_hp_cap_numerator /
        policy->target_max_hp_cap_denominator;
    if (requested > cap) requested = cap;
    uint16_t applied = (uint16_t)(requested > UINT16_MAX ? UINT16_MAX : requested);
    status = run_ordinary_move_damage_event(
        battle, move, user.side, user.slot, user.side, user.slot,
        applied, &applied);
    if (status != POKEMON_OK) return status;
    PokemonMutable *source = &battle->sides[user.side].state[user.slot];
    uint16_t before = source->hp;
    source->hp = (uint16_t)(source->hp - applied);
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_DAMAGE, .side = user.side,
        .target_side = user.side, .slot = user.slot,
        .species_id = battle->sides[user.side].sets[user.slot].species_id,
        .move_id = move->id, .amount = applied, .hp = source->hp,
    });
    battle->effect_traces[battle->effect_trace_count++] = (PokemonEffectTrace){
        .semantic_sequence = next_semantic_sequence(battle),
        .kind = POKEMON_EFFECT_CRASH_DAMAGE,
        .phase = POKEMON_EFFECT_PHASE_MOVE_FAIL,
        .target = POKEMON_EFFECT_TARGET_USER,
        .result = POKEMON_EFFECT_APPLIED,
        .source_side = user.side, .source_slot = user.slot,
        .target_side = target.side, .target_slot = target.slot,
        .move_id = move->id,
        .value = applied,
        .damage_basis = hypothetical.damage,
        .requested = (uint16_t)(requested > UINT16_MAX ? UINT16_MAX : requested),
        .numerator = policy->numerator,
        .denominator = policy->denominator,
        .damage_target_side = user.side,
        .damage_target_slot = user.slot,
        .critical = hypothetical.critical,
        .damage_roll = hypothetical.damage_roll,
        .minimum = policy->minimum,
        .cap_numerator = policy->target_max_hp_cap_numerator,
        .cap_denominator = policy->target_max_hp_cap_denominator,
        .cap_value = (uint16_t)(cap > UINT16_MAX ? UINT16_MAX : cap),
        .before = (int16_t)before,
        .after = (int16_t)source->hp,
    };
    return queue_faint(
        battle, user, user,
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id});
}

/* The sole major-status mutation boundary.  Callers describe the proposed
 * condition and provenance; this transaction owns rejection, clauses,
 * generated identity installation, status payload initialization and trace.
 * Keeping the complete previous value makes a cancelling Start handler
 * rollback byte-for-byte once such handlers are admitted. */
static int set_major_status(
    PokemonBattle *battle, PokemonStatus proposed, uint16_t move_id,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, PokemonSourceEffectRef source_effect,
    PokemonStatusSetPolicy policy, uint8_t emit_immunity, uint8_t *applied,
    PokemonEventCancellation *rejection
) {
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    if (applied == NULL || proposed <= POKEMON_STATUS_NONE ||
        proposed > POKEMON_STATUS_FREEZE ||
        policy > POKEMON_STATUS_SET_REPLACE_DIFFERENT) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *applied = 0;
    if (rejection != NULL) *rejection = POKEMON_EVENT_CANCEL_NONE;
    if (target->hp == 0 || target->status.kind == proposed ||
        (target->status.kind != POKEMON_STATUS_NONE &&
         policy == POKEMON_STATUS_SET_EMPTY_ONLY)) {
        return POKEMON_OK;
    }
    uint8_t immune = 0;
    uint8_t ability_immune = 0;
    if (proposed == POKEMON_STATUS_BURN) {
        immune = has_type(target, battle->data->fire_type);
    } else if (proposed == POKEMON_STATUS_POISON ||
               proposed == POKEMON_STATUS_TOXIC) {
        immune = has_type(target, battle->data->poison_type) ||
            has_type(target, battle->data->steel_type);
    } else if (proposed == POKEMON_STATUS_FREEZE) {
        immune = has_type(target, battle->data->ice_type);
    }
    const PokemonWeatherPolicy *active_weather = weather_policy(
        battle, effective_weather(battle));
    if (active_weather != NULL &&
        (active_weather->blocked_status_mask & (UINT32_C(1) << proposed))) {
        immune = 1;
    }
    for (size_t i = 0; i < battle->data->status_immunity_count; i++) {
        const PokemonStatusImmunity *rule = &battle->data->status_immunities[i];
        if (rule->ability_id != target->ability_id ||
            rule->blocked_status != proposed) continue;
        if (rule->event == POKEMON_HANDLER_EVENT_IMMUNITY) {
            immune = 1;
            ability_immune = 1;
        }
        else if (rule->event != POKEMON_HANDLER_EVENT_SET_STATUS) {
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    if (immune) {
        if (emit_immunity) append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_IMMUNE, .side = (uint8_t)target_side,
            .target_side = (uint8_t)source_side,
            .species_id = battle->sides[target_side].sets[target_slot].species_id,
            .move_id = move_id,
            .immunity_cause = ability_immune ? POKEMON_IMMUNITY_HANDLER :
                POKEMON_IMMUNITY_NATURAL_TYPE,
        });
        return POKEMON_OK;
    }
    /* A successful transaction necessarily emits one event and one condition
     * trace. Reject exhaustion before provisional mutation or status PRNG. */
    size_t required_condition_traces =
        target->status.kind == POKEMON_STATUS_NONE ? 1u : 2u;
    for (size_t i = 0; i < target->volatile_count; i++) {
        const PokemonConditionRule *linked = condition_rule_by_descriptor(
            battle, target->volatiles[i].descriptor_id);
        required_condition_traces += linked != NULL &&
            linked->remove_with_status == target->status.kind;
    }
    if (battle->event_count == POKEMON_EVENT_CAPACITY ||
        (size_t)battle->condition_trace_count + required_condition_traces >
            POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    /* Major-status admission is an event boundary just like volatile
     * admission.  Side conditions and future generated owners participate
     * here before status payload mutation or sleep-duration PRNG. */
    PokemonEventFrame admission;
    int admission_status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_SET_STATUS,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = source_effect,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_STATUS,
        .context.status = {
            .proposed = proposed, .emit_immunity = emit_immunity,
        },
    }, &admission);
    if (admission_status != POKEMON_OK) return admission_status;
    if (admission.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        !admission.relay.value.boolean) {
        if (rejection != NULL) *rejection = admission.cancellation;
        if (emit_immunity &&
            admission.cancelling_owner.kind == POKEMON_OWNER_ABILITY) {
            append_event(battle, (PokemonEvent){
                .kind = POKEMON_EVENT_IMMUNE, .side = (uint8_t)target_side,
                .target_side = (uint8_t)source_side,
                .species_id = battle->sides[target_side].sets[target_slot].species_id,
                .move_id = move_id,
                .immunity_cause = POKEMON_IMMUNITY_HANDLER,
            });
        }
        return POKEMON_OK;
    }
    PokemonStatusState previous = target->status;
    uint16_t previous_effect_order = battle->next_holder_effect_order;
    memset(&target->status, 0, sizeof(target->status));
    target->status.kind = proposed;
    target->status.descriptor_id = battle->generation->condition_descriptor(
        POKEMON_OWNER_STATUS, proposed);
    if (target->status.descriptor_id == 0) {
        target->status = previous;
        return POKEMON_INVALID_CONFIGURATION;
    }
    target->status.state_generation = (uint16_t)(previous.state_generation + 1u);
    target->status.effect_order = ++battle->next_holder_effect_order;
    target->status.source = (PokemonEntityRef){
        POKEMON_ENTITY_POKEMON, (uint8_t)source_side, (uint8_t)source_slot};
    target->status.source_effect = source_effect;
    int start_result = dispatch_owner_lifecycle(
        battle, POKEMON_HANDLER_EVENT_START, (PokemonOwnerRef){
            .kind = POKEMON_OWNER_STATUS, .side = (uint8_t)target_side,
            .slot = (uint8_t)target_slot,
            .effect_id = target->status.descriptor_id,
            .state_generation = target->status.state_generation,
        });
    if (start_result != POKEMON_OK) {
        target->status = previous;
        battle->next_holder_effect_order = previous_effect_order;
        return start_result;
    }
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_STATUS, .side = (uint8_t)target_side,
        .species_id = battle->sides[target_side].sets[target_slot].species_id,
        .move_id = move_id,
    });
    PokemonEventFrame after_set;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_AFTER_SET_STATUS,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = source_effect,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_STATUS,
        .context.status = {
            .proposed = proposed, .emit_immunity = emit_immunity,
        },
    }, &after_set);
    if (result != POKEMON_OK) return result;
    if (previous.kind != POKEMON_STATUS_NONE) {
        for (size_t i = 0; i < target->volatile_count;) {
            const PokemonConditionRule *linked = condition_rule_by_descriptor(
                battle, target->volatiles[i].descriptor_id);
            if (linked == NULL ||
                linked->remove_with_status != previous.kind) {
                i++;
                continue;
            }
            PokemonVolatileKind removed_kind = target->volatiles[i].kind;
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_MOVE,
                POKEMON_CONDITION_VALUE_NONE, target_side, target_slot,
                removed_kind, 0, 0);
            if (result != POKEMON_OK) return result;
            remove_volatile_at(target, i);
        }
        PokemonConditionValueKind removed_value =
            previous.kind == POKEMON_STATUS_SLEEP ?
                POKEMON_CONDITION_VALUE_DURATION :
            previous.kind == POKEMON_STATUS_TOXIC ?
                POKEMON_CONDITION_VALUE_STAGE : POKEMON_CONDITION_VALUE_NONE;
        uint8_t removed_before = previous.kind == POKEMON_STATUS_SLEEP ?
            previous.state.sleep.time : previous.kind == POKEMON_STATUS_TOXIC ?
                previous.state.toxic.stage : 0;
        result = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_STATUS,
            POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_MOVE,
            removed_value, target_side, target_slot,
            previous.kind, removed_before, 0);
        if (result != POKEMON_OK) return result;
        if (previous.kind == POKEMON_STATUS_SLEEP) {
            PokemonConditionTrace *removed =
                &battle->condition_traces[battle->condition_trace_count - 1u];
            removed->has_counter_before = 1;
            removed->counter_before = previous.state.sleep.skipped_time;
        }
    }
    PokemonConditionValueKind added_value = POKEMON_CONDITION_VALUE_NONE;
    uint8_t added_after = 0;
    if (proposed == POKEMON_STATUS_TOXIC) {
        added_value = POKEMON_CONDITION_VALUE_STAGE;
    } else if (proposed == POKEMON_STATUS_SLEEP) {
        added_value = POKEMON_CONDITION_VALUE_DURATION;
        added_after = target->status.state.sleep.time;
    }
    result = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_STATUS, POKEMON_CONDITION_ADD,
        POKEMON_CONDITION_REASON_MOVE, added_value,
        target_side, target_slot, proposed, 0, added_after);
    if (result != POKEMON_OK) return result;
    if (proposed == POKEMON_STATUS_SLEEP) {
        PokemonConditionTrace *added =
            &battle->condition_traces[battle->condition_trace_count - 1u];
        added->has_counter_after = 1;
        added->counter_after = target->status.state.sleep.skipped_time;
    }
    *applied = 1;
    return POKEMON_OK;
}

int pokemon_set_status(
    PokemonBattle *battle, PokemonEntityRef target, PokemonStatus proposed,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    uint8_t emit_immunity, uint8_t *applied
) {
    if (battle == NULL || target.kind != POKEMON_ENTITY_POKEMON ||
        source.kind != POKEMON_ENTITY_POKEMON ||
        target.side >= POKEMON_SIDES || source.side >= POKEMON_SIDES ||
        target.slot >= battle->team_sizes[target.side] ||
        source.slot >= battle->team_sizes[source.side] ||
        source_effect.kind < POKEMON_SOURCE_EFFECT_MOVE ||
        source_effect.kind > POKEMON_SOURCE_EFFECT_CONDITION) {
        return POKEMON_INVALID_ARGUMENT;
    }
    return set_major_status(
        battle, proposed, source_effect.id, source.side, source.slot,
        target.side, target.slot, source_effect,
        POKEMON_STATUS_SET_EMPTY_ONLY, emit_immunity, applied, NULL);
}

int pokemon_set_status_with_policy(
    PokemonBattle *battle, PokemonEntityRef target, PokemonStatus proposed,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect,
    PokemonStatusSetPolicy policy, uint8_t emit_immunity, uint8_t *applied
) {
    if (battle == NULL || target.kind != POKEMON_ENTITY_POKEMON ||
        source.kind != POKEMON_ENTITY_POKEMON ||
        target.side >= POKEMON_SIDES || source.side >= POKEMON_SIDES ||
        target.slot >= battle->team_sizes[target.side] ||
        source.slot >= battle->team_sizes[source.side] ||
        source_effect.kind < POKEMON_SOURCE_EFFECT_MOVE ||
        source_effect.kind > POKEMON_SOURCE_EFFECT_CONDITION ||
        policy > POKEMON_STATUS_SET_REPLACE_DIFFERENT) {
        return POKEMON_INVALID_ARGUMENT;
    }
    return set_major_status(
        battle, proposed, source_effect.id, source.side, source.slot,
        target.side, target.slot, source_effect, policy,
        emit_immunity, applied, NULL);
}

int pokemon_update_status_abilities(PokemonBattle *battle) {
    if (battle == NULL || battle->data == NULL) return POKEMON_INVALID_ARGUMENT;
    return run_update_each_event(battle);
}

int pokemon_ability_blocks_sleep_volatile(
    const PokemonData *data, uint16_t ability_id, uint8_t *blocked
) {
    if (data == NULL || blocked == NULL) return POKEMON_INVALID_ARGUMENT;
    *blocked = 0;
    for (size_t i = 0; i < data->status_immunity_count; i++) {
        const PokemonStatusImmunity *rule = &data->status_immunities[i];
        if (rule->ability_id == ability_id && rule->blocks_sleep_volatile) {
            *blocked = 1;
            break;
        }
    }
    return POKEMON_OK;
}

static size_t major_status_removal_trace_count(
    const PokemonBattle *battle, size_t side, size_t slot
) {
    const PokemonMutable *holder = &battle->sides[side].state[slot];
    if (holder->hp == 0 || holder->status.kind == POKEMON_STATUS_NONE) return 0;
    size_t count = 1;
    for (size_t i = 0; i < holder->volatile_count; i++) {
        const PokemonConditionRule *rule = condition_rule_by_descriptor(
            battle, holder->volatiles[i].descriptor_id);
        count += rule != NULL && rule->remove_with_status == holder->status.kind;
    }
    return count;
}

static int clear_major_status(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonConditionReason reason
) {
    PokemonMutable *holder = &battle->sides[side].state[slot];
    if (holder->status.kind == POKEMON_STATUS_NONE) return POKEMON_OK;
    PokemonStatusState previous = holder->status;
    for (size_t i = 0; i < holder->volatile_count;) {
        const PokemonConditionRule *rule = condition_rule_by_descriptor(
            battle, holder->volatiles[i].descriptor_id);
        if (rule == NULL || rule->remove_with_status != previous.kind) {
            i++;
            continue;
        }
        PokemonVolatileState removed = holder->volatiles[i];
        int linked = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE,
            POKEMON_CONDITION_REMOVE, reason, POKEMON_CONDITION_VALUE_NONE,
            side, slot, removed.kind, 0, 0);
        if (linked != POKEMON_OK) return linked;
        remove_volatile_at(holder, i);
    }
    memset(&holder->status, 0, sizeof(holder->status));
    int result = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_STATUS, POKEMON_CONDITION_REMOVE,
        reason, previous.kind == POKEMON_STATUS_SLEEP ?
            POKEMON_CONDITION_VALUE_DURATION :
            previous.kind == POKEMON_STATUS_TOXIC ?
                POKEMON_CONDITION_VALUE_STAGE : POKEMON_CONDITION_VALUE_NONE,
        side, slot, previous.kind,
        previous.kind == POKEMON_STATUS_SLEEP ? previous.state.sleep.time :
            previous.kind == POKEMON_STATUS_TOXIC ?
                previous.state.toxic.stage : 0,
        0);
    if (result != POKEMON_OK) return result;
    if (previous.kind == POKEMON_STATUS_SLEEP) {
        PokemonConditionTrace *removed =
            &battle->condition_traces[battle->condition_trace_count - 1u];
        removed->has_counter_before = 1;
        removed->counter_before = previous.state.sleep.skipped_time;
    }
    return POKEMON_OK;
}

static int run_move_hit_callback(
    PokemonBattle *battle, const PokemonMoveData *move, PokemonEntityRef user,
    size_t target_side, size_t target_slot, PokemonSourceEffectRef source_effect,
    uint8_t *succeeded, PokemonEventCancellation *cancellation
) {
    PokemonEventFrame frame;
    uint8_t ran = 0;
    int status = run_move_self_event(
        battle, POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK, move, user,
        target_side, target_slot, source_effect,
        (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        &frame, &ran);
    if (status != POKEMON_OK) return status;
    if (cancellation != NULL) {
        *cancellation = ran ? frame.cancellation : POKEMON_EVENT_CANCEL_NONE;
    }
    *succeeded = !ran ||
        (frame.cancellation == POKEMON_EVENT_CANCEL_NONE &&
         frame.relay.kind == POKEMON_RELAY_BOOLEAN && frame.relay.value.boolean) ||
        (frame.cancellation == POKEMON_EVENT_CANCEL_NOT_FAIL &&
         frame.relay.kind == POKEMON_RELAY_NOT_FAIL);
    return POKEMON_OK;
}

static int run_move_hit_field_callback(
    PokemonBattle *battle, const PokemonMoveData *move, PokemonEntityRef user,
    PokemonSourceEffectRef source_effect, uint8_t *succeeded
) {
    PokemonEventFrame frame;
    uint8_t ran = 0;
    int status = run_move_self_event(
        battle, POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK, move, user,
        user.side, user.slot, source_effect,
        (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        &frame, &ran);
    if (status != POKEMON_OK) return status;
    *succeeded = !ran ||
        (frame.cancellation == POKEMON_EVENT_CANCEL_NONE &&
         frame.relay.kind == POKEMON_RELAY_BOOLEAN && frame.relay.value.boolean) ||
        (frame.cancellation == POKEMON_EVENT_CANCEL_NOT_FAIL &&
         frame.relay.kind == POKEMON_RELAY_NOT_FAIL);
    return POKEMON_OK;
}

static int run_move_hit_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    uint8_t *callback_succeeded, PokemonEventCancellation *callback_cancellation
) {
    uint8_t succeeded = 0;
    int status = run_move_hit_callback(
        battle, move,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        target_side, target_slot, active_source_effect(battle, move->id),
        &succeeded, callback_cancellation);
    if (status != POKEMON_OK) return status;
    if (callback_succeeded != NULL) *callback_succeeded = succeeded;
    if (move->target == POKEMON_TARGET_ALL) {
        return POKEMON_OK;
    }
    PokemonEventFrame frame;
    return run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_HIT,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
    }, &frame);
}

static int run_move_global_hit_event(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot
) {
    PokemonEventFrame frame;
    return run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_HIT,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
    }, &frame);
}

static int run_damaging_hit_event(
    PokemonBattle *battle, const PokemonMoveData *move, uint16_t damage,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot
) {
    PokemonEventFrame frame;
    return run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DAMAGING_HIT,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move, .damage = damage},
    }, &frame);
}

typedef enum {
    POKEMON_ITEM_TAKE_EMPTY = 0,
    POKEMON_ITEM_TAKE_OK,
    POKEMON_ITEM_TAKE_BLOCKED,
} PokemonItemTakeResult;

typedef enum {
    POKEMON_ITEM_TAKE_STEAL = 1,
    POKEMON_ITEM_TAKE_SWAP,
} PokemonItemTakeOperation;

/* This is the normalized Pokemon#takeItem boundary.  Operation describes the
 * effective move program, so policy remains generated data rather than a
 * catalog-ID branch. */
static int take_held_item(
    PokemonBattle *battle, size_t holder_side, size_t holder_slot,
    size_t source_side, size_t source_slot, PokemonItemTakeOperation operation,
    uint16_t *taken, PokemonItemTakeResult *take_result
) {
    PokemonMutable *holder = &battle->sides[holder_side].state[holder_slot];
    PokemonMutable *source = &battle->sides[source_side].state[source_slot];
    *taken = 0;
    if (holder->item_knocked_off || source->item_knocked_off) {
        *take_result = POKEMON_ITEM_TAKE_BLOCKED;
        return POKEMON_OK;
    }
    if (holder->item_id == 0) {
        *take_result = POKEMON_ITEM_TAKE_EMPTY;
        return POKEMON_OK;
    }
    const PokemonAbilityData *ability = find_ability(battle, holder->ability_id);
    const PokemonItemData *item = find_item(battle, holder->item_id);
    if ((holder_side != source_side || holder_slot != source_slot) &&
        ability != NULL && (ability->semantic_flags &
            POKEMON_ABILITY_SEMANTIC_BLOCKS_EXTERNAL_ITEM_TAKE) != 0) {
        *take_result = POKEMON_ITEM_TAKE_BLOCKED;
        return POKEMON_OK;
    }
    if (item != NULL &&
        (item->flags & POKEMON_ITEM_FLAG_RESTRICT_EXTERNAL_TAKE) != 0 &&
        operation != POKEMON_ITEM_TAKE_STEAL) {
        *take_result = POKEMON_ITEM_TAKE_BLOCKED;
        return POKEMON_OK;
    }
    *taken = holder->item_id;
    int status = dispatch_owner_lifecycle(
        battle, POKEMON_HANDLER_EVENT_END,
        (PokemonOwnerRef){POKEMON_OWNER_ITEM, (uint8_t)holder_side,
            (uint8_t)holder_slot, *taken, holder->item_generation});
    if (status != POKEMON_OK) return status;
    holder->item_id = 0;
    holder->item_generation++;
    holder->item_effect_order = 0;
    holder->pending_staleness = POKEMON_STALENESS_NONE;
    *take_result = POKEMON_ITEM_TAKE_OK;
    return POKEMON_OK;
}

static int set_held_item(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t item_id
) {
    PokemonMutable *state = &battle->sides[side].state[slot];
    if (state->hp == 0 || battle->sides[side].active != slot) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    state->item_id = item_id;
    /* Pinned Showdown stages setItem acquisitions as internal in Gen 3,
     * including Trick's source-less calls. Only restorative consumption can
     * commit this marker. */
    state->pending_staleness = item_id != 0 ?
        POKEMON_STALENESS_INTERNAL : POKEMON_STALENESS_NONE;
    state->item_generation++;
    state->item_effect_order = item_id != 0 ?
        ++battle->next_holder_effect_order : 0;
    if (item_id == 0) return POKEMON_OK;
    return dispatch_owner_lifecycle(
        battle, POKEMON_HANDLER_EVENT_START,
        (PokemonOwnerRef){POKEMON_OWNER_ITEM, (uint8_t)side, (uint8_t)slot,
            item_id, state->item_generation});
}

static uint8_t item_take_gate_allows(
    const PokemonBattle *battle, uint16_t item_id,
    PokemonItemTakeOperation operation
) {
    const PokemonItemData *item = find_item(battle, item_id);
    return item == NULL ||
        (item->flags & POKEMON_ITEM_FLAG_RESTRICT_EXTERNAL_TAKE) == 0 ||
        operation == POKEMON_ITEM_TAKE_STEAL;
}

static int swap_held_items(
    PokemonBattle *battle, size_t source_side, size_t source_slot,
    size_t target_side, size_t target_slot, uint8_t *applied
) {
    uint16_t target_item = 0;
    uint16_t source_item = 0;
    PokemonItemTakeResult target_take = POKEMON_ITEM_TAKE_EMPTY;
    PokemonItemTakeResult source_take = POKEMON_ITEM_TAKE_EMPTY;
    *applied = 0;
    int status = take_held_item(
        battle, target_side, target_slot, source_side, source_slot,
        POKEMON_ITEM_TAKE_SWAP, &target_item, &target_take);
    if (status != POKEMON_OK) return status;
    status = take_held_item(
        battle, source_side, source_slot, source_side, source_slot,
        POKEMON_ITEM_TAKE_SWAP, &source_item, &source_take);
    if (status != POKEMON_OK) return status;
    if (target_take == POKEMON_ITEM_TAKE_BLOCKED ||
        source_take == POKEMON_ITEM_TAKE_BLOCKED ||
        (target_take == POKEMON_ITEM_TAKE_EMPTY &&
         source_take == POKEMON_ITEM_TAKE_EMPTY) ||
        (source_take == POKEMON_ITEM_TAKE_OK &&
         !item_take_gate_allows(
            battle, source_item, POKEMON_ITEM_TAKE_SWAP)) ||
        (target_take == POKEMON_ITEM_TAKE_OK &&
         !item_take_gate_allows(
            battle, target_item, POKEMON_ITEM_TAKE_SWAP))) {
        /* Showdown deliberately restores only the raw IDs here. Item state
         * already cleared by a successful take remains cleared. */
        if (target_take == POKEMON_ITEM_TAKE_OK) {
            battle->sides[target_side].state[target_slot].item_id = target_item;
        }
        if (source_take == POKEMON_ITEM_TAKE_OK) {
            battle->sides[source_side].state[source_slot].item_id = source_item;
        }
        return POKEMON_OK;
    }
    if (source_take == POKEMON_ITEM_TAKE_OK) {
        status = set_held_item(
            battle, target_side, target_slot, source_item);
        if (status != POKEMON_OK) return status;
    }
    if (target_take == POKEMON_ITEM_TAKE_OK) {
        status = set_held_item(
            battle, source_side, source_slot, target_item);
        if (status != POKEMON_OK) return status;
    }
    *applied = 1;
    return POKEMON_OK;
}

typedef enum {
    POKEMON_HIT_EFFECT_STAGE_ALL = 0,
    POKEMON_HIT_EFFECT_STAGE_PRIMARY,
    POKEMON_HIT_EFFECT_STAGE_AFTER_CALLBACK,
    POKEMON_HIT_EFFECT_STAGE_SECONDARY,
} PokemonHitEffectStage;

static int substitute_creation_is_admitted(
    const PokemonBattle *battle, const PokemonSet *user,
    const PokemonMutable *user_state, uint8_t *admitted
) {
    uint8_t denominator = battle->generation->substitute_cost_denominator;
    if (denominator == 0) return POKEMON_INVALID_CONFIGURATION;
    uint16_t max_hp = user->stats[0];
    uint16_t cost = (uint16_t)(max_hp / denominator);
    *admitted = !(
        (battle->generation->substitute_reject_max_hp_one && max_hp == 1) ||
        user_state->hp <= cost ||
        volatile_index(user_state, POKEMON_VOLATILE_SUBSTITUTE) >= 0);
    return POKEMON_OK;
}

static int apply_hit_effect_stage(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t selected_side, size_t selected_slot,
    uint8_t target_effects_blocked, PokemonHitEffectStage stage
) {
    for (size_t i = 0; i < move->effect_count; i++) {
        const PokemonEffectOp *op = move_effect(battle, move, i);
        if (stage == POKEMON_HIT_EFFECT_STAGE_PRIMARY &&
            op->phase != POKEMON_EFFECT_PHASE_PRIMARY_HIT) continue;
        if (stage == POKEMON_HIT_EFFECT_STAGE_AFTER_CALLBACK &&
            op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK) continue;
        if (stage == POKEMON_HIT_EFFECT_STAGE_SECONDARY &&
            op->phase != POKEMON_EFFECT_PHASE_SELF_DROP &&
            op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT) continue;
        uint8_t primary_hit = op->phase == POKEMON_EFFECT_PHASE_PRIMARY_HIT ||
            op->phase == POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK;
        uint8_t self_drop = op->phase == POKEMON_EFFECT_PHASE_SELF_DROP;
        if (!primary_hit && !self_drop &&
            op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT) continue;
        size_t target_side = op->target == POKEMON_EFFECT_TARGET_USER ?
            source_side : selected_side;
        size_t target_slot = op->target == POKEMON_EFFECT_TARGET_USER ?
            source_slot : selected_slot;
        PokemonMutable *target = &battle->sides[target_side].state[target_slot];
        uint8_t secondary_group = move_effect_secondary_group(battle, move, i);
        if (secondary_group != 0) {
            const PokemonEffectOp *group[POKEMON_STAT_COUNT];
            size_t group_count = 0;
            uint8_t already_processed = 0;
            for (size_t earlier = 0; earlier < i; earlier++) {
                already_processed |= move_effect_secondary_group(
                    battle, move, earlier) == secondary_group;
            }
            if (already_processed) continue;
            for (size_t member = 0; member < move->effect_count; member++) {
                const PokemonEffectOp *candidate =
                    move_effect(battle, move, member);
                if (move_effect_secondary_group(battle, move, member) !=
                    secondary_group) continue;
                if (candidate->phase != POKEMON_EFFECT_PHASE_AFTER_HIT ||
                    candidate->kind != POKEMON_EFFECT_BOOST ||
                    candidate->target != op->target ||
                    candidate->chance != op->chance ||
                    group_count == POKEMON_STAT_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                group[group_count++] = candidate;
            }
            if (group_count == 0) return POKEMON_INVALID_CONFIGURATION;
            PokemonEventFrame secondaries;
            int status = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES,
                .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                    (uint8_t)source_slot},
                .target_side = (uint8_t)selected_side,
                .target_slot = (uint8_t)selected_slot,
                .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
                .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = move,
                    .secondary_self_only =
                        op->target == POKEMON_EFFECT_TARGET_USER},
            }, &secondaries);
            if (status != POKEMON_OK) return status;
            if (!secondaries.relay.value.boolean) continue;
            uint32_t roll = 0;
            status = draw_below(
                battle, POKEMON_DRAW_SECONDARY, 100, &roll);
            if (status != POKEMON_OK) return status;
            if (roll >= secondary_chance(
                    battle, source_side, source_slot, op->chance)) continue;
            /* The chance roll belongs to the move even when its damage just
             * fainted the target; application then sees no live target. */
            if (target->hp == 0) continue;
            status = apply_boost_effects(
                battle, group, group_count, move->id, source_side, source_slot,
                target_side, target_slot);
            if (status != POKEMON_OK) return status;
            continue;
        }
        if (op->kind == POKEMON_EFFECT_STEAL_ITEM ||
            op->kind == POKEMON_EFFECT_KNOCK_OFF_ITEM) {
            if (target_effects_blocked) continue;
            PokemonMutable *source = &battle->sides[source_side].state[source_slot];
            const PokemonAbilityData *ability = find_ability(
                battle, target->ability_id);
            const PokemonItemData *item = find_item(battle, target->item_id);
            uint8_t blocked = ability != NULL &&
                (ability->semantic_flags &
                    POKEMON_ABILITY_SEMANTIC_BLOCKS_EXTERNAL_ITEM_TAKE) != 0;
            if (item != NULL &&
                (item->flags & POKEMON_ITEM_FLAG_RESTRICT_EXTERNAL_TAKE) != 0) {
                /* Gen 3 Mail permits exactly the generated damaging removal
                 * operations represented by these two sum-type variants. */
                blocked = 0;
            }
            if (op->kind == POKEMON_EFFECT_KNOCK_OFF_ITEM) {
                if (target->item_id != 0 && !blocked) {
                    target->item_id = 0;
                    if (battle->generation->knock_off_locks_item_slot) {
                        target->item_knocked_off = 1;
                    }
                }
                continue;
            }
            if (source->item_id != 0 || target->item_id == 0 || blocked ||
                source->item_knocked_off || target->item_knocked_off) continue;
            uint16_t taken = 0;
            PokemonItemTakeResult take_result = POKEMON_ITEM_TAKE_EMPTY;
            int status = take_held_item(
                battle, target_side, target_slot, source_side, source_slot,
                POKEMON_ITEM_TAKE_STEAL, &taken, &take_result);
            if (status != POKEMON_OK) return status;
            if (take_result != POKEMON_ITEM_TAKE_OK) continue;
            status = set_held_item(battle, source_side, source_slot, taken);
            if (status != POKEMON_OK) return status;
            continue;
        }
        if (self_drop) {
            const PokemonEffectOp *boost_ops[POKEMON_STAT_COUNT];
            size_t boost_count = 0;
            size_t end = i;
            if (op->kind != POKEMON_EFFECT_BOOST ||
                op->target != POKEMON_EFFECT_TARGET_USER ||
                battle->sides[source_side].state[source_slot].hp == 0) {
                if (op->kind != POKEMON_EFFECT_BOOST ||
                    op->target != POKEMON_EFFECT_TARGET_USER) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                continue;
            }
            while (end < move->effect_count) {
                const PokemonEffectOp *candidate = move_effect(battle, move, end);
                if (candidate->phase != POKEMON_EFFECT_PHASE_SELF_DROP) break;
                if (candidate->kind != POKEMON_EFFECT_BOOST ||
                    candidate->target != POKEMON_EFFECT_TARGET_USER ||
                    candidate->chance != op->chance ||
                    boost_count == POKEMON_STAT_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                boost_ops[boost_count++] = candidate;
                end++;
            }
            uint32_t roll = 0;
            int result = draw_below(
                battle, POKEMON_DRAW_SECONDARY, 100, &roll);
            if (result != POKEMON_OK) return result;
            if (roll < op->chance) {
                result = apply_boost_effects(
                    battle, boost_ops, boost_count, move->id,
                    source_side, source_slot, source_side, source_slot);
                if (result != POKEMON_OK) return result;
            }
            i = end - 1;
            continue;
        }
        if (!primary_hit && op->target != POKEMON_EFFECT_TARGET_USER) {
            PokemonEventFrame secondaries;
            int event_status = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES,
                .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                    (uint8_t)source_slot},
                .target_side = (uint8_t)target_side,
                .target_slot = (uint8_t)target_slot,
                .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
                .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = move},
            }, &secondaries);
            if (event_status != POKEMON_OK) return event_status;
            if (!secondaries.relay.value.boolean) continue;
        }
        int result = POKEMON_OK;
        if (!primary_hit) {
            uint32_t roll = 0;
            result = draw_below(battle, POKEMON_DRAW_SECONDARY, 100, &roll);
            if (result != POKEMON_OK) return result;
            if (roll >= secondary_chance(
                    battle, source_side, source_slot, op->chance)) continue;
        } else if (op->chance != 100) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        /* A Substitute absorbs effects directed at its holder, but reaching the
         * secondary transaction still owns the chance roll. Self secondaries
         * remain eligible, matching Showdown's null-target moveHit path. */
        if (target_effects_blocked && op->target != POKEMON_EFFECT_TARGET_USER) {
            continue;
        }
        if (!self_drop && op->target == POKEMON_EFFECT_TARGET_MOVE_TARGET &&
            target->hp == 0 && op->kind != POKEMON_EFFECT_SET_STATUS &&
            op->kind != POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION) continue;
        if (op->kind == POKEMON_EFFECT_BOOST) {
            const PokemonEffectOp *single[] = {op};
            result = apply_boost_effects(
                battle, single, 1, move->id,
                source_side, source_slot, target_side, target_slot
            );
            if (result != POKEMON_OK) return result;
            continue;
        }
        if (op->kind == POKEMON_EFFECT_ADD_VOLATILE) {
            PokemonVolatileKind kind = (PokemonVolatileKind)op->argument;
            uint8_t before = volatile_index(target, kind) >= 0;
            uint8_t installed = 0;
            result = install_condition_volatile(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)target_side, (uint8_t)target_slot},
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)source_side, (uint8_t)source_slot},
                (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
                kind, POKEMON_CONDITION_REASON_MOVE, &installed);
            if (result != POKEMON_OK) return result;
            result = trace_effect(
                battle, op, installed == 1 ? POKEMON_EFFECT_APPLIED :
                    POKEMON_EFFECT_FAILED,
                move->id, source_side, source_slot, target_side, target_slot,
                before, volatile_index(target, kind) >= 0);
            if (result != POKEMON_OK) return result;
            continue;
        }
        if (op->kind == POKEMON_EFFECT_REMOVE_VOLATILE) {
            PokemonVolatileKind kind = (PokemonVolatileKind)op->argument;
            int index = volatile_index(target, kind);
            uint8_t before = index >= 0;
            if (index >= 0) {
                PokemonVolatileState removed = target->volatiles[index];
                result = end_and_remove_volatile_exact(
                    battle, target_side, target_slot, removed.descriptor_id,
                    removed.state_generation, removed.effect_order,
                    POKEMON_CONDITION_REASON_MOVE);
                if (result != POKEMON_OK) return result;
            }
            result = trace_effect(
                battle, op, before ? POKEMON_EFFECT_APPLIED :
                    POKEMON_EFFECT_FAILED,
                move->id, source_side, source_slot, target_side, target_slot,
                before, 0);
            if (result != POKEMON_OK) return result;
            continue;
        }
        if (op->kind == POKEMON_EFFECT_REMOVE_SIDE_CONDITION) {
            const PokemonConditionIdentity *identity =
                pokemon_condition_identity(battle->data, op->argument);
            if (identity == NULL ||
                identity->domain != POKEMON_CONDITION_DOMAIN_SIDE) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            int before = side_condition_index(
                &battle->sides[target_side],
                (PokemonSideConditionKind)identity->semantic_kind) >= 0;
            result = remove_side_condition_by_descriptor(
                battle, target_side, op->argument,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)source_side, (uint8_t)source_slot},
                (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
                POKEMON_CONDITION_REASON_MOVE);
            if (result != POKEMON_OK) return result;
            result = trace_effect(
                battle, op, before ? POKEMON_EFFECT_APPLIED :
                    POKEMON_EFFECT_FAILED,
                move->id, source_side, source_slot, target_side, target_slot,
                before, 0);
            if (result != POKEMON_OK) return result;
            continue;
        }
        PokemonStatus selected_status = POKEMON_STATUS_NONE;
        if (op->kind == POKEMON_EFFECT_SET_STATUS) {
            selected_status = (PokemonStatus)op->argument;
        } else if (op->kind == POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION) {
            const PokemonStatusDistribution *distribution =
                status_distribution(battle, op->argument);
            if (distribution == NULL) return POKEMON_INVALID_CONFIGURATION;
            uint32_t selected = 0;
            result = draw_below(
                battle, (PokemonDrawLabel)distribution->draw_label,
                distribution->candidate_count, &selected);
            if (result != POKEMON_OK) return result;
            selected_status = (PokemonStatus)
                battle->data->status_distribution_candidates[
                    distribution->candidate_offset + selected];
        } else {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonStatus before = target->status.kind;
        uint8_t applied = 0;
        result = pokemon_set_status(
            battle,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
                (uint8_t)target_slot},
            selected_status,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                (uint8_t)source_slot},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
            0, &applied);
        if (result != POKEMON_OK) return result;
        PokemonEffectOp traced_op = *op;
        traced_op.argument = selected_status;
        result = trace_effect(
            battle, &traced_op,
            applied ? POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED,
            move->id, source_side, source_slot, target_side, target_slot,
            before, target->status.kind
        );
        if (result != POKEMON_OK) return result;
    }
    if (stage != POKEMON_HIT_EFFECT_STAGE_ALL &&
        stage != POKEMON_HIT_EFFECT_STAGE_SECONDARY) return POKEMON_OK;
    if (battle->move_frame_depth == 0) return POKEMON_INVALID_CONFIGURATION;
    const PokemonActiveMoveFrame *active =
        &battle->move_frames[battle->move_frame_depth - 1];
    for (size_t i = 0; i < active->appended_secondary_count; i++) {
        const PokemonEffectOp *op = &active->appended_secondaries[i];
        if (op->kind != POKEMON_EFFECT_ADD_VOLATILE ||
            op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT ||
            op->target != POKEMON_EFFECT_TARGET_MOVE_TARGET ||
            op->chance == 0 || op->chance > 100) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonEventFrame secondaries;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES,
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                (uint8_t)source_slot},
            .target_side = (uint8_t)selected_side,
            .target_slot = (uint8_t)selected_slot,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move},
        }, &secondaries);
        if (status != POKEMON_OK) return status;
        if (!secondaries.relay.value.boolean) continue;
        uint32_t roll = 0;
        status = draw_below(battle, POKEMON_DRAW_SECONDARY, 100, &roll);
        if (status != POKEMON_OK) return status;
        if (roll >= secondary_chance(
                battle, source_side, source_slot, op->chance)) continue;
        if (target_effects_blocked) continue;
        PokemonMutable *target =
            &battle->sides[selected_side].state[selected_slot];
        PokemonVolatileKind kind = (PokemonVolatileKind)op->argument;
        uint8_t before = volatile_index(target, kind) >= 0;
        uint8_t installed = 0;
        status = install_condition_volatile(
            battle,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)selected_side, (uint8_t)selected_slot},
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                (uint8_t)source_side, (uint8_t)source_slot},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
            kind, POKEMON_CONDITION_REASON_MOVE, &installed);
        if (status != POKEMON_OK) return status;
        status = trace_effect(
            battle, op, installed ? POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED,
            move->id, source_side, source_slot, selected_side, selected_slot,
            before, volatile_index(target, kind) >= 0);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int apply_after_hit_effects(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t selected_side,
    size_t selected_slot, uint8_t target_effects_blocked
) {
    return apply_hit_effect_stage(
        battle, move, source_side, source_slot, selected_side, selected_slot,
        target_effects_blocked, POKEMON_HIT_EFFECT_STAGE_ALL);
}

static int apply_damage_relative_effects_rounded(
    PokemonBattle *battle, const PokemonMoveData *move, PokemonEffectPhase phase,
    size_t source_side, size_t source_slot,
    size_t damage_target_side, size_t damage_target_slot, uint16_t actual_damage,
    uint8_t round_drain_up
) {
    for (size_t i = 0; i < move->effect_count; i++) {
        const PokemonEffectOp *op = move_effect(battle, move, i);
        if (op->phase != phase) continue;
        if (op->kind == POKEMON_EFFECT_ADD_VOLATILE &&
            phase == POKEMON_EFFECT_PHASE_AFTER_MOVE &&
            op->target == POKEMON_EFFECT_TARGET_USER && op->chance == 100) {
            uint8_t installed = 0;
            PokemonEntityRef user = {POKEMON_ENTITY_POKEMON,
                (uint8_t)source_side, (uint8_t)source_slot};
            int status = install_condition_volatile(
                battle, user, user,
                active_source_effect(battle, move->id),
                (PokemonVolatileKind)op->argument,
                POKEMON_CONDITION_REASON_MOVE, &installed);
            if (status != POKEMON_OK) return status;
            status = trace_effect(
                battle, op,
                installed == 0 ? POKEMON_EFFECT_FAILED : POKEMON_EFFECT_APPLIED,
                move->id, source_side, source_slot, source_side, source_slot,
                0, 0);
            if (status != POKEMON_OK) return status;
            continue;
        }
        if (op->kind != POKEMON_EFFECT_DAMAGE_RELATIVE ||
            op->fraction_numerator == 0 || op->fraction_denominator == 0) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonMutable *source = &battle->sides[source_side].state[source_slot];
        uint16_t before = source->hp;
        uint32_t scaled = (uint32_t)actual_damage * op->fraction_numerator;
        uint16_t requested = (uint16_t)(
            (scaled + (round_drain_up &&
                op->argument == POKEMON_DAMAGE_RELATIVE_DRAIN ?
                    op->fraction_denominator - 1u : 0u)) /
            op->fraction_denominator);
        if (requested == 0) requested = 1;
        uint16_t applied = 0;
        PokemonEffectResult effect_result = POKEMON_EFFECT_APPLIED;
        if (op->argument == POKEMON_DAMAGE_RELATIVE_RECOIL) {
            uint8_t prevented = 0;
            int result = POKEMON_OK;
            if (op->damage_preventability == POKEMON_DAMAGE_PREVENTABLE) {
                result = run_damage_handlers(
                    battle, source_side, source_slot,
                    POKEMON_DAMAGE_RELATIVE_RECOIL, move->id, 1, &prevented
                );
                if (result != POKEMON_OK) return result;
            }
            if (prevented) {
                effect_result = POKEMON_EFFECT_FAILED;
                result = trace_effect(
                    battle, op, POKEMON_EFFECT_APPLIED, move->id,
                    source_side, source_slot, source_side, source_slot,
                    (int16_t)before, (int16_t)before
                );
                if (result != POKEMON_OK) return result;
                PokemonEffectTrace *prevention = &battle->effect_traces[
                    battle->effect_trace_count - 1];
                prevention->prevention = 1;
                prevention->damage_basis = actual_damage;
                prevention->requested = requested;
                prevention->numerator = op->fraction_numerator;
                prevention->denominator = op->fraction_denominator;
                prevention->damage_target_side = (uint8_t)damage_target_side;
                prevention->damage_target_slot = (uint8_t)damage_target_slot;
            } else {
                applied = requested > source->hp ? source->hp : requested;
                source->hp = (uint16_t)(source->hp - applied);
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_DAMAGE, .side = (uint8_t)source_side,
                    .slot = (uint8_t)source_slot,
                    .species_id = battle->sides[source_side].sets[source_slot].species_id,
                    .move_id = move->id, .amount = applied, .hp = source->hp,
                    .damage_relative_kind = POKEMON_DAMAGE_RELATIVE_RECOIL,
                });
            }
        } else if (op->argument == POKEMON_DAMAGE_RELATIVE_DRAIN) {
            int heal_status = try_amount_heal(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)damage_target_side, (uint8_t)damage_target_slot},
                active_source_effect(battle, move->id),
                source_side, source_slot, requested, &effect_result, &applied);
            if (heal_status != POKEMON_OK) return heal_status;
        } else {
            return POKEMON_INVALID_CONFIGURATION;
        }
        int result = trace_effect(
            battle, op, effect_result, move->id,
            source_side, source_slot, source_side, source_slot,
            (int16_t)before, (int16_t)source->hp
        );
        if (result != POKEMON_OK) return result;
        PokemonEffectTrace *trace = &battle->effect_traces[
            battle->effect_trace_count - 1];
        trace->value = applied;
        trace->damage_basis = actual_damage;
        trace->requested = requested;
        trace->numerator = op->fraction_numerator;
        trace->denominator = op->fraction_denominator;
        trace->damage_target_side = (uint8_t)damage_target_side;
        trace->damage_target_slot = (uint8_t)damage_target_slot;
    }
    return POKEMON_OK;
}

static int apply_damage_relative_effects(
    PokemonBattle *battle, const PokemonMoveData *move, PokemonEffectPhase phase,
    size_t source_side, size_t source_slot,
    size_t damage_target_side, size_t damage_target_slot, uint16_t actual_damage
) {
    return apply_damage_relative_effects_rounded(
        battle, move, phase, source_side, source_slot,
        damage_target_side, damage_target_slot, actual_damage, 0);
}

static int queue_faint(
    PokemonBattle *battle, PokemonEntityRef target, PokemonEntityRef source,
    PokemonSourceEffectRef source_effect
) {
    if (target.kind != POKEMON_ENTITY_POKEMON || target.side >= POKEMON_SIDES ||
        target.slot >= battle->team_sizes[target.side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonMutable *state = &battle->sides[target.side].state[target.slot];
    if (state->fainted || state->hp != 0) return POKEMON_OK;
    for (size_t i = 0; i < battle->faint_count; i++) {
        PokemonEntityRef queued = battle->faint_queue[i].target;
        if (queued.side == target.side && queued.slot == target.slot) {
            return POKEMON_OK;
        }
    }
    if (battle->faint_count == POKEMON_FAINT_QUEUE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    battle->faint_queue[battle->faint_count++] = (PokemonPendingFaint){
        .target = target, .source = source, .source_effect = source_effect,
    };
    state->faint_queued = 1;
    return POKEMON_OK;
}

static int finalize_faint(PokemonBattle *battle, PokemonPendingFaint pending) {
    size_t fainted_side = pending.target.side;
    size_t fainted_slot = pending.target.slot;
    PokemonMutable *state = &battle->sides[fainted_side].state[fainted_slot];
    if (state->fainted || state->hp != 0) return POKEMON_OK;
    assert(state->faint_queued);
    PokemonEventFrame faint_event;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_FAINT,
        .source = pending.source,
        .target_side = (uint8_t)fainted_side,
        .target_slot = (uint8_t)fainted_slot,
        .source_effect = pending.source_effect,
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
    }, &faint_event);
    if (result != POKEMON_OK) return result;
    result = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
        (PokemonOwnerRef){POKEMON_OWNER_ABILITY, (uint8_t)fainted_side,
            (uint8_t)fainted_slot, state->ability_id, state->ability_generation});
    if (result != POKEMON_OK) return result;
    result = dispatch_owner_lifecycle(battle, POKEMON_HANDLER_EVENT_END,
        (PokemonOwnerRef){POKEMON_OWNER_ITEM, (uint8_t)fainted_side,
            (uint8_t)fainted_slot, state->item_id, state->item_generation});
    if (result != POKEMON_OK) return result;
	result = remove_source_linked_volatiles(
		battle, pending.target, POKEMON_CONDITION_REASON_HANDLER);
	if (result != POKEMON_OK) return result;
    state->fainted = 1;
    state->faint_queued = 0;
    state->last_move_id = 0;
    state->last_move_used = (PokemonLastUsedMove){0};
    memset(&state->last_attacked_by, 0, sizeof(state->last_attacked_by));
    memset(state->boosts, 0, sizeof(state->boosts));
    result = restore_base_battle_profile(battle, fainted_side, fainted_slot);
    if (result != POKEMON_OK) return result;
    /* Showdown's faint transaction records clearVolatile removals without
     * dispatching every volatile's End callback. Preserve insertion order. */
    while (state->volatile_count != 0) {
        PokemonVolatileState removed = state->volatiles[0];
        uint8_t trace_value = removed.kind == POKEMON_VOLATILE_CONFUSION ?
            removed.payload.confusion.time : removed.duration;
        result = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE,
            POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_HANDLER,
            trace_value == 0 ? POKEMON_CONDITION_VALUE_NONE :
                POKEMON_CONDITION_VALUE_DURATION,
            fainted_side, fainted_slot, removed.kind, trace_value, 0);
        if (result != POKEMON_OK) return result;
        if (removed.kind == POKEMON_VOLATILE_STALL) {
            PokemonConditionTrace *trace = &battle->condition_traces[
                battle->condition_trace_count - 1];
            trace->has_counter_before = 1;
            trace->counter_before = removed.counter;
        }
        remove_volatile_at(state, 0);
    }
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_FAINT, .side = (uint8_t)fainted_side,
        .slot = (uint8_t)fainted_slot,
        .species_id = battle->sides[fainted_side].sets[fainted_slot].species_id,
    });
    if (!battle->generation->cancel_all_actions_on_faint) {
        cancel_side_actions(&battle->queue, fainted_side);
    }
    return POKEMON_OK;
}

static int drain_faints_internal(
    PokemonBattle *battle, uint8_t request_replacement
) {
    if (battle->faint_count == 0) return POKEMON_OK;
    PokemonPhase prior_phase = battle->phase;
    battle->phase = POKEMON_PHASE_FAINT_DRAIN;
    uint8_t drained = 0;
    while (drained < battle->faint_count) {
        int result = finalize_faint(battle, battle->faint_queue[drained++]);
        if (result != POKEMON_OK) return result;
    }
    battle->faint_count = 0;
    if (battle->generation->cancel_all_actions_on_faint) {
        for (size_t side = 0; side < POKEMON_SIDES; side++) {
            cancel_side_actions(&battle->queue, side);
        }
    }
    uint8_t left_alive = alive_count(battle, 0) != 0;
    uint8_t right_alive = alive_count(battle, 1) != 0;
    if (!left_alive && !right_alive) return finish_draw(battle);
    if (!left_alive) return finish_battle(battle, 1);
    if (!right_alive) return finish_battle(battle, 0);
    battle->phase = prior_phase;
    if (!request_replacement) return POKEMON_OK;
    battle->turn_suspended = POKEMON_TURN_SUSPENDED_BEFORE_RESIDUAL;
    return project_request(battle);
}

static int drain_faints(PokemonBattle *battle) {
    return drain_faints_internal(battle, 1);
}

static int next_action_is_run_switch(const PokemonBattle *battle) {
    return battle->queue.count != 0 &&
        battle->queue.values[0].kind == POKEMON_ACTION_RUN_SWITCH;
}

static int check_fainted_request(PokemonBattle *battle) {
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        uint8_t active = battle->sides[side].active;
        if (battle->sides[side].state[active].fainted &&
            alive_count(battle, side) != 0) {
            battle->turn_suspended = POKEMON_TURN_SUSPENDED_BEFORE_RESIDUAL;
            return project_request(battle);
        }
    }
    return POKEMON_OK;
}

static int resolve_move_faint(
    PokemonBattle *battle, size_t fainted_side, size_t fainted_slot,
    PokemonEntityRef source, PokemonSourceEffectRef source_effect
) {
    return queue_faint(battle,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)fainted_side,
            (uint8_t)fainted_slot},
        source, source_effect);
}

static int apply_direct_damage_inner(
    PokemonBattle *battle, const PokemonDirectDamageRequest *request,
    uint16_t *applied
) {
    if (battle == NULL || request == NULL || applied == NULL ||
        request->target.kind != POKEMON_ENTITY_POKEMON ||
        request->target.side >= POKEMON_SIDES ||
        (request->source.kind != POKEMON_ENTITY_NONE &&
         (request->source.kind != POKEMON_ENTITY_POKEMON ||
          request->source.side >= POKEMON_SIDES ||
          request->source.slot >= battle->team_sizes[request->source.side])) ||
        request->target.slot >= battle->team_sizes[request->target.side]) {
        return POKEMON_INVALID_ARGUMENT;
    }
    PokemonMutable *target = &battle->sides[request->target.side].state[
        request->target.slot];
    uint16_t amount = request->amount < target->hp ? request->amount : target->hp;
    size_t required_events = 1u + (amount == target->hp && !target->fainted);
    if ((size_t)battle->event_count + required_events > POKEMON_EVENT_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    target->hp = (uint16_t)(target->hp - amount);
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_DAMAGE,
        .side = request->target.side,
        .target_side = request->source.kind == POKEMON_ENTITY_POKEMON ?
            request->source.side : UINT8_MAX,
        .slot = request->target.slot,
        .species_id = battle->sides[request->target.side].sets[
            request->target.slot].species_id,
        .move_id = request->source_effect.kind == POKEMON_SOURCE_EFFECT_MOVE ?
            request->source_effect.id : 0,
        .amount = amount,
        .hp = target->hp,
    });
    int result = resolve_move_faint(
        battle, request->target.side, request->target.slot,
        request->source, request->source_effect);
    if (result != POKEMON_OK) return result;
    *applied = amount;
    return POKEMON_OK;
}

int pokemon_apply_direct_damage(
    PokemonBattle *battle, const PokemonDirectDamageRequest *request,
    uint16_t *applied
) {
    if (battle == NULL || applied == NULL) return POKEMON_INVALID_ARGUMENT;
    PokemonBattle next = *battle;
    uint16_t next_applied = 0;
    int result = apply_direct_damage_inner(&next, request, &next_applied);
    if (result == POKEMON_OK) result = drain_faints(&next);
    if (result != POKEMON_OK) return result;
    *battle = next;
    *applied = next_applied;
    return POKEMON_OK;
}

static int end_and_remove_volatile_exact(
    PokemonBattle *battle, size_t side, size_t slot,
    uint16_t descriptor_id, uint16_t state_generation,
    uint16_t effect_order,
    PokemonConditionReason reason
) {
    PokemonMutable *holder = &battle->sides[side].state[slot];
    int index = volatile_index_by_identity(
        holder, descriptor_id, state_generation, effect_order);
    if (index < 0) return POKEMON_OK;
    PokemonVolatileState removed = holder->volatiles[index];
    PokemonHandlerRef end_handlers[POKEMON_HANDLER_CAPACITY];
    size_t end_handler_count = 0;
    int status = append_owner_handlers(
        battle, POKEMON_HANDLER_EVENT_END, POKEMON_HANDLER_SCOPE_TARGET,
        POKEMON_OWNER_VOLATILE, descriptor_id, state_generation,
        side, slot, holder->cached_speed, removed.effect_order,
        end_handlers, &end_handler_count);
    if (status != POKEMON_OK) return status;
    if ((size_t)battle->handler_count + end_handler_count >
            POKEMON_HANDLER_CAPACITY ||
        battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    for (size_t i = 0; i < end_handler_count; i++) {
        PokemonEventFrame end;
        status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_END,
            .source = removed.source,
            .target_side = (uint8_t)side,
            .target_slot = (uint8_t)slot,
            .source_effect = removed.source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {.kind = removed.kind},
            .has_only_handler = 1,
            .only_handler = end_handlers[i],
        }, &end);
        if (status != POKEMON_OK) return status;
    }
    index = volatile_index_by_identity(
        holder, descriptor_id, state_generation, effect_order);
    if (index < 0) return POKEMON_INVALID_CONFIGURATION;
    status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_VOLATILE,
        POKEMON_CONDITION_REMOVE, reason,
        removed.duration == 0 ? POKEMON_CONDITION_VALUE_NONE :
            POKEMON_CONDITION_VALUE_DURATION,
        side, slot, removed.kind, removed.duration, 0);
    if (status != POKEMON_OK) return status;
    battle->condition_traces[battle->condition_trace_count - 1u].descriptor_id =
        removed.descriptor_id;
    if (removed.counter != 0) {
        PokemonConditionTrace *trace = &battle->condition_traces[
            battle->condition_trace_count - 1];
        trace->has_counter_before = 1;
        trace->counter_before = removed.counter;
    }
    remove_volatile_at(holder, (size_t)index);
    return POKEMON_OK;
}

static int remove_source_linked_volatiles(
	PokemonBattle *battle, PokemonEntityRef source,
	PokemonConditionReason reason
) {
	for (size_t side = 0; side < POKEMON_SIDES; side++) {
		for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
			PokemonMutable *holder = &battle->sides[side].state[slot];
			for (size_t i = 0; i < holder->volatile_count;) {
				PokemonVolatileState current = holder->volatiles[i];
				const PokemonConditionRule *rule = condition_rule_by_descriptor(
					battle, current.descriptor_id);
				if (rule == NULL || !rule->source_linked_kind ||
					current.source.kind != source.kind ||
					current.source.side != source.side ||
					current.source.slot != source.slot) {
					i++;
					continue;
				}
				int status = end_and_remove_volatile_exact(
					battle, side, slot, current.descriptor_id,
					current.state_generation, current.effect_order, reason);
				if (status != POKEMON_OK) return status;
			}
		}
	}
	return POKEMON_OK;
}

static int run_exceptional_handler(
    PokemonBattle *battle, const PokemonEventInput *input,
    const PokemonHandlerRef *handler, PokemonEventFrame *frame,
    PokemonHandlerResult *handler_result
) {
    uint16_t exceptional = handler->descriptor.exceptional_handler_id;
    PokemonMutable *holder = &battle->sides[handler->holder_side].state[
        handler->holder_slot];
    int confusion = volatile_index(holder, POKEMON_VOLATILE_CONFUSION);
    int locked = volatile_index(holder, POKEMON_VOLATILE_LOCKED_MOVE);
    *handler_result = POKEMON_HANDLER_CONTINUE;
    if (exceptional == POKEMON_EXCEPTION_STATUS_CLAUSE) {
        const PokemonStatusClausePolicy *clause = NULL;
        for (size_t i = 0; i < battle->policy.status_clause_count; i++) {
            const PokemonStatusClausePolicy *candidate =
                &battle->policy.status_clauses[i];
            if (candidate->handler_id == handler->descriptor.id) {
                clause = candidate;
                break;
            }
        }
        if (input->event != POKEMON_HANDLER_EVENT_SET_STATUS ||
            input->context_kind != POKEMON_EVENT_CONTEXT_STATUS ||
            handler->owner.kind != POKEMON_OWNER_FORMAT || clause == NULL) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (clause->status != input->context.status.proposed) return POKEMON_OK;
        if (clause->requires_opposing_source &&
            (input->source.kind != POKEMON_ENTITY_POKEMON ||
             input->source.side == input->target_side)) return POKEMON_OK;
        PokemonStatus proposed = input->context.status.proposed;
        for (size_t slot = 0; slot < battle->team_sizes[input->target_side]; slot++) {
            const PokemonMutable *member =
                &battle->sides[input->target_side].state[slot];
            if (member->status.kind != proposed) continue;
            uint8_t blocked = clause->block_any_existing ||
                (clause->block_living_opponent_caused && member->hp != 0 &&
                 member->status.source.kind == POKEMON_ENTITY_POKEMON &&
                 member->status.source.side != input->target_side);
            if (!blocked) continue;
            frame->relay.value.boolean = 0;
            frame->cancellation = POKEMON_EVENT_CANCEL_NULL;
            frame->cancelling_owner = handler->owner;
            frame->cancelling_handler_id = handler->descriptor.id;
            *handler_result = POKEMON_HANDLER_PREVENT;
            return POKEMON_OK;
        }
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_STATUS_IMMUNITY) {
        if (input->event != POKEMON_HANDLER_EVENT_SET_STATUS ||
            input->context_kind != POKEMON_EVENT_CONTEXT_STATUS ||
            handler->owner.kind != POKEMON_OWNER_ABILITY) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        for (size_t i = 0; i < battle->data->status_immunity_count; i++) {
            const PokemonStatusImmunity *rule =
                &battle->data->status_immunities[i];
            if (rule->ability_id != handler->owner.effect_id ||
                rule->event != POKEMON_HANDLER_EVENT_SET_STATUS ||
                rule->blocked_status != input->context.status.proposed) continue;
            frame->relay.value.boolean = 0;
            frame->cancellation = POKEMON_EVENT_CANCEL_NULL;
            frame->cancelling_owner = handler->owner;
            frame->cancelling_handler_id = handler->descriptor.id;
            *handler_result = POKEMON_HANDLER_PREVENT;
            return POKEMON_OK;
        }
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_CHOICE_CONTROL) {
        const PokemonChoiceControlPolicy *policy = choice_control_policy(
            battle->generation->choice_control_policies,
            battle->generation->choice_control_policy_count,
            handler->owner.effect_id);
        PokemonVolatileState *owner = NULL;
        for (size_t i = 0; i < holder->volatile_count; i++) {
            if (holder->volatiles[i].descriptor_id == handler->owner.effect_id &&
                holder->volatiles[i].state_generation ==
                    handler->owner.state_generation &&
                holder->volatiles[i].effect_order == handler->effect_order) {
                owner = &holder->volatiles[i];
                break;
            }
        }
        if (policy == NULL || owner == NULL) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint16_t stored = owner->payload.choice_control.stored_move_id;
        if (input->event == POKEMON_HANDLER_EVENT_RESIDUAL) {
            if (policy->residual_op !=
                    POKEMON_CHOICE_RESIDUAL_END_IF_STORED_MOVE_UNUSABLE ||
                stored == 0) return POKEMON_INVALID_CONFIGURATION;
            uint8_t usable = 0;
            for (size_t move_slot = 0; move_slot < POKEMON_MOVE_CAPACITY;
                 move_slot++) {
                usable |= holder->move_ids[move_slot] == stored &&
                    holder->pp[move_slot] != 0;
            }
            if (usable) return POKEMON_OK;
            return end_and_remove_volatile_exact(
                battle, handler->holder_side, handler->holder_slot,
                handler->owner.effect_id, handler->owner.state_generation,
                handler->effect_order,
                POKEMON_CONDITION_REASON_HANDLER);
        }
        if (input->event == POKEMON_HANDLER_EVENT_START) {
            if (policy->start_op == POKEMON_CHOICE_START_NONE ||
                (owner->duration == 0 && !policy->allows_indefinite_start)) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint16_t last_move_id = holder->last_move_id;
            PokemonMoveSlotState slot_state = POKEMON_MOVE_SLOT_ABSENT;
            for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                if (holder->move_ids[slot] != last_move_id) {
                    continue;
                }
                slot_state = holder->pp[slot] != 0 ?
                    POKEMON_MOVE_SLOT_PRESENT_WITH_PP :
                    POKEMON_MOVE_SLOT_PRESENT_ZERO_PP;
                if (slot_state == POKEMON_MOVE_SLOT_PRESENT_WITH_PP) break;
            }
            const PokemonMoveData *last_move = find_move(battle, last_move_id);
            uint8_t will_move = 0;
            for (size_t i = 0; i < battle->queue.count; i++) {
                const PokemonAction *queued = &battle->queue.values[i];
                will_move |= queued->kind == POKEMON_ACTION_MOVE &&
                    queued->side == handler->holder_side;
            }
            PokemonChoiceControlStart start;
            int status = pokemon_prepare_choice_control_start(
                policy, last_move_id, slot_state,
                last_move != NULL && last_move->encore_eligible,
                will_move, owner->duration, &start);
            if (status != POKEMON_OK) return status;
            if (!start.admitted) {
                frame->cancellation = POKEMON_EVENT_CANCEL_FALSE;
                frame->cancelling_owner = handler->owner;
                frame->cancelling_handler_id = handler->descriptor.id;
                *handler_result = POKEMON_HANDLER_PREVENT;
                return POKEMON_OK;
            }
            owner->payload.choice_control.stored_move_id = start.stored_move_id;
            owner->duration = start.duration;
            return POKEMON_OK;
        }
        if (input->event == POKEMON_HANDLER_EVENT_DISABLE_MOVE) {
            if (input->context_kind !=
                    POKEMON_EVENT_CONTEXT_MOVE_RESTRICTIONS ||
                input->context.move_restrictions == NULL) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (policy->required_held_item_id != 0 &&
                holder->item_id != policy->required_held_item_id) {
                return end_and_remove_volatile_exact(
                    battle, handler->holder_side, handler->holder_slot,
                    handler->owner.effect_id, handler->owner.state_generation,
                    handler->effect_order,
                    POKEMON_CONDITION_REASON_HANDLER);
            }
            PokemonMoveRestrictionBuffer *buffer =
                input->context.move_restrictions;
            if (buffer->count == buffer->capacity) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            PokemonMoveRestriction restriction = {0};
            switch (policy->request_op) {
            case POKEMON_CHOICE_REQUEST_DISABLE_STORED_MOVE:
                restriction.kind = POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL;
                restriction.move_id = stored;
                break;
            case POKEMON_CHOICE_REQUEST_DISABLE_EXCEPT_STORED_MOVE:
                restriction.kind = POKEMON_MOVE_RESTRICTION_DISABLE_UNEQUAL;
                restriction.move_id = stored;
                break;
            case POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY:
                restriction.kind = POKEMON_MOVE_RESTRICTION_DISABLE_CATEGORY;
                restriction.category = policy->category;
                break;
            case POKEMON_CHOICE_REQUEST_DISABLE_LAST_MOVE:
                restriction.kind =
                    POKEMON_MOVE_RESTRICTION_DISABLE_LAST_NONFALLBACK;
                restriction.move_id = buffer->last_move_id;
                restriction.fallback_move_id = buffer->fallback_move_id;
                break;
            case POKEMON_CHOICE_REQUEST_NONE:
            case POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC:
                return POKEMON_INVALID_CONFIGURATION;
            }
            buffer->values[buffer->count++] = restriction;
            return POKEMON_OK;
        }
        if (input->event == POKEMON_HANDLER_EVENT_OVERRIDE_ACTION) {
            if (policy->action_op !=
                    POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE ||
                input->relay.kind != POKEMON_RELAY_SELECTOR || stored == 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            frame->relay.value.selector = stored;
            return POKEMON_OK;
        }
        if (input->event == POKEMON_HANDLER_EVENT_BEFORE_MOVE) {
            if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE ||
                input->context.move.move == NULL ||
                input->relay.kind != POKEMON_RELAY_BOOLEAN) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint8_t consume = policy->action_op ==
                    POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC &&
                policy->synthetic_move_id == input->context.move.move->id;
            uint8_t reject = policy->action_op ==
                    POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE ?
                stored != 0 && input->context.move.move->id == stored :
                policy->action_op == POKEMON_CHOICE_ACTION_REJECT_CATEGORY ?
                    input->context.move.move->category == policy->category :
                consume;
            if (reject) {
                if (consume) {
                    uint16_t descriptor_id = owner->descriptor_id;
                    uint16_t state_generation = owner->state_generation;
                    uint16_t effect_order = owner->effect_order;
                    int status = end_and_remove_volatile_exact(
                        battle, handler->holder_side, handler->holder_slot,
                        descriptor_id, state_generation, effect_order,
                        POKEMON_CONDITION_REASON_HANDLER);
                    if (status != POKEMON_OK) return status;
                }
                frame->relay.value.boolean = 0;
                frame->cancellation = POKEMON_EVENT_CANCEL_FALSE;
                frame->cancelling_owner = handler->owner;
                frame->cancelling_handler_id = handler->descriptor.id;
                *handler_result = POKEMON_HANDLER_PREVENT;
            }
            return POKEMON_OK;
        }
        if (input->event == POKEMON_HANDLER_EVENT_LOCK_MOVE) {
            if (policy->request_op !=
                    POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC ||
                policy->synthetic_move_id == 0 ||
                input->relay.kind != POKEMON_RELAY_SELECTOR) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            frame->relay.value.selector = policy->synthetic_move_id;
            return POKEMON_OK;
        }
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (exceptional == POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_TYPE ||
        exceptional == POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_MOVE) {
        if (battle->move_frame_depth == 0 ||
            input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonActiveMoveFrame *active =
            &battle->move_frames[battle->move_frame_depth - 1];
        PokemonWeatherKind weather = effective_weather(battle);
        if (weather > POKEMON_WEATHER_SUN) return POKEMON_INVALID_CONFIGURATION;
        const PokemonWeatherMovePolicy *policy =
            &input->context.move.move->weather_policy[weather];
        if (exceptional == POKEMON_EXCEPTION_WEATHER_BALL_MODIFY_TYPE) {
            if (policy->flags & POKEMON_WEATHER_MOVE_TYPE) active->type = policy->type;
        } else {
            if (policy->flags & POKEMON_WEATHER_MOVE_TYPE) active->type = policy->type;
            if (policy->flags & POKEMON_WEATHER_MOVE_CATEGORY) active->category = policy->category;
            if (policy->flags & POKEMON_WEATHER_MOVE_POWER) active->base_power =
                (uint16_t)((uint32_t)active->base_power * policy->power_q12 / 4096u);
        }
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_THUNDER_MODIFY_MOVE) {
        if (battle->move_frame_depth == 0 ||
            input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonWeatherKind weather = effective_weather(battle);
        if (weather > POKEMON_WEATHER_SUN) return POKEMON_INVALID_CONFIGURATION;
        PokemonActiveMoveFrame *active =
            &battle->move_frames[battle->move_frame_depth - 1];
        const PokemonWeatherMovePolicy *policy =
            &input->context.move.move->weather_policy[weather];
        if (policy->flags & POKEMON_WEATHER_MOVE_ACCURACY) {
            active->accuracy = policy->accuracy;
        }
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_TWO_TURN_TRY_MOVE) {
        if (battle->move_frame_depth == 0 ||
            input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        int marker = volatile_index(holder, POKEMON_VOLATILE_TWO_TURN_MARKER);
        if (marker >= 0) {
            if (holder->volatiles[marker].payload.two_turn.move_id !=
                input->context.move.move->id) return POKEMON_INVALID_CONFIGURATION;
            int lock = volatile_index(holder, POKEMON_VOLATILE_TWO_TURN_MOVE);
            if (lock < 0) return POKEMON_INVALID_CONFIGURATION;
            holder->volatiles[lock].payload.two_turn.released = 1;
            remove_volatile_at(holder, (size_t)marker);
            return POKEMON_OK;
        }
        PokemonWeatherKind weather = effective_weather(battle);
        const PokemonWeatherMovePolicy *policy =
            &input->context.move.move->weather_policy[weather];
        if (policy->flags & POKEMON_WEATHER_MOVE_SKIP_CHARGE) {
            battle->move_frames[battle->move_frame_depth - 1].suppress_protocol_target =
                (policy->flags & POKEMON_WEATHER_MOVE_SUPPRESS_TARGET) != 0;
            return POKEMON_OK;
        }
        const PokemonTwoTurnMoveDescriptor *two_turn =
            two_turn_move_descriptor(battle, input->context.move.move->id);
        if (two_turn == NULL || two_turn->marker_descriptor_id == 0) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (two_turn->charge_boost_delta != 0) {
            PokemonEffectOp charge_boost = {
                .kind = POKEMON_EFFECT_BOOST,
                .phase = POKEMON_EFFECT_PHASE_PRIMARY,
                .target = POKEMON_EFFECT_TARGET_USER,
                .chance = 100,
                .argument = two_turn->charge_boost_stat,
                .amount = two_turn->charge_boost_delta,
            };
            const PokemonEffectOp *charge_ops[] = {&charge_boost};
            int boost_status = apply_boost_effects(
                battle, charge_ops, 1, input->context.move.move->id,
                handler->holder_side, handler->holder_slot,
                handler->holder_side, handler->holder_slot);
            if (boost_status != POKEMON_OK) return boost_status;
        }
        /* Showdown admits the move marker and generic lock independently,
         * then starts the installed generic condition.  These are observable
         * event boundaries even though the pair commits transactionally. */
        PokemonEventFrame admission;
        int admission_status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
            .source = input->source,
            .target_side = handler->holder_side,
            .target_slot = handler->holder_slot,
            .source_effect = input->source_effect,
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {
                .kind = POKEMON_VOLATILE_TWO_TURN_MOVE,
            },
        }, &admission);
        if (admission_status != POKEMON_OK) return admission_status;
        if (admission.cancellation != POKEMON_EVENT_CANCEL_NONE ||
            !admission.relay.value.boolean) {
            frame->cancellation = POKEMON_EVENT_CANCEL_NULL;
            frame->relay.value.boolean = 0;
            return POKEMON_OK;
        }
        int status = install_two_turn_pair(
            battle,
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                handler->holder_side, handler->holder_slot},
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                input->target_side, input->target_slot},
            input->context.move.move->id, two_turn->marker_descriptor_id,
            two_turn->marker_duration);
        if (status != POKEMON_OK) return status;
        PokemonEventFrame start;
        status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_START,
            .source = input->source,
            .target_side = handler->holder_side,
            .target_slot = handler->holder_slot,
            .source_effect = input->source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {
                .kind = POKEMON_VOLATILE_TWO_TURN_MOVE,
            },
        }, &start);
        if (status != POKEMON_OK) return status;
        {
            PokemonEventFrame marker_admission;
            status = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
                .source = input->source,
                .target_side = handler->holder_side,
                .target_slot = handler->holder_slot,
                .source_effect = input->source_effect,
                .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
                .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                .context.volatile_condition = {
                    .kind = POKEMON_VOLATILE_TWO_TURN_MARKER,
                },
            }, &marker_admission);
            if (status != POKEMON_OK) return status;
            if (marker_admission.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                !marker_admission.relay.value.boolean) {
                return abort_two_turn_pair(battle, handler->holder_side,
                    handler->holder_slot, POKEMON_CONDITION_REASON_HANDLER);
            }
        }
        frame->cancellation = POKEMON_EVENT_CANCEL_NULL;
        frame->relay.value.boolean = 0;
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_SOLAR_BEAM_BASE_POWER) {
        if (battle->move_frame_depth == 0 ||
            input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonWeatherKind weather = effective_weather(battle);
        if (weather > POKEMON_WEATHER_SUN) return POKEMON_INVALID_CONFIGURATION;
        PokemonActiveMoveFrame *active =
            &battle->move_frames[battle->move_frame_depth - 1];
        const PokemonWeatherMovePolicy *policy =
            &input->context.move.move->weather_policy[weather];
        if (policy->flags & POKEMON_WEATHER_MOVE_POWER) active->base_power =
            (uint16_t)((uint32_t)active->base_power * policy->power_q12 / 4096u);
        frame->relay.value.u32 = active->base_power;
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_TWO_TURN_LOCK_MOVE) {
        int two_turn = volatile_index(holder, POKEMON_VOLATILE_TWO_TURN_MOVE);
        if (two_turn < 0 || input->relay.kind != POKEMON_RELAY_SELECTOR) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        frame->relay.value.selector =
            holder->volatiles[two_turn].payload.two_turn.move_id;
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_TWO_TURN_MOVE_ABORTED) {
        PokemonEventFrame end;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_END,
            .source = input->source,
            .target_side = handler->holder_side,
            .target_slot = handler->holder_slot,
            .source_effect = input->source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {
                .kind = POKEMON_VOLATILE_TWO_TURN_MOVE,
            },
        }, &end);
        if (status != POKEMON_OK) return status;
        return abort_two_turn_pair(
            battle, handler->holder_side, handler->holder_slot,
            POKEMON_CONDITION_REASON_HANDLER);
    }
    if (exceptional == POKEMON_EXCEPTION_TWO_TURN_END) {
        remove_two_turn_marker(holder);
        return POKEMON_OK;
    }
    if (exceptional >= POKEMON_EXCEPTION_LOCKED_MOVE_START &&
        exceptional <= POKEMON_EXCEPTION_LOCKED_MOVE_SELECTOR) {
        if (locked < 0) return POKEMON_INVALID_CONFIGURATION;
        PokemonVolatileState *lock = &holder->volatiles[locked];
        if (exceptional == POKEMON_EXCEPTION_LOCKED_MOVE_START) return POKEMON_OK;
        if (exceptional == POKEMON_EXCEPTION_LOCKED_MOVE_RESTART) {
            if (lock->payload.locked_move.true_duration >= 2) lock->duration = 2;
            return POKEMON_OK;
        }
        if (exceptional == POKEMON_EXCEPTION_LOCKED_MOVE_RESIDUAL) {
            if (holder->status.kind == POKEMON_STATUS_SLEEP) {
                PokemonVolatileState old = *lock;
                int result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                    POKEMON_CONDITION_REMOVE, POKEMON_CONDITION_REASON_HANDLER,
                    POKEMON_CONDITION_VALUE_DURATION, handler->holder_side,
                    handler->holder_slot, POKEMON_VOLATILE_LOCKED_MOVE,
                    old.duration, 0);
                if (result != POKEMON_OK) return result;
                remove_volatile_at(holder, (size_t)locked);
                return POKEMON_OK;
            }
            if (lock->payload.locked_move.true_duration != 0) {
                lock->payload.locked_move.true_duration--;
            }
            return POKEMON_OK;
        }
        if (exceptional == POKEMON_EXCEPTION_LOCKED_MOVE_END) {
            if (lock->payload.locked_move.true_duration > 1) return POKEMON_OK;
            uint8_t installed = 0;
            PokemonEntityRef self = {POKEMON_ENTITY_POKEMON,
                handler->holder_side, handler->holder_slot};
            return install_condition_volatile(
                battle, self, self,
                (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_CONDITION,
                    lock->descriptor_id},
                POKEMON_VOLATILE_CONFUSION,
                POKEMON_CONDITION_REASON_HANDLER, &installed);
        }
        if (input->event != POKEMON_HANDLER_EVENT_LOCK_MOVE ||
            input->relay.kind != POKEMON_RELAY_SELECTOR) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        frame->relay.value.selector = lock->payload.locked_move.move_id;
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_OWN_TEMPO_TRY_ADD) {
        if (input->context_kind != POKEMON_EVENT_CONTEXT_VOLATILE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (input->context.volatile_condition.kind == POKEMON_VOLATILE_CONFUSION) {
            frame->relay.value.boolean = 0;
            frame->cancellation = POKEMON_EVENT_CANCEL_FALSE;
            frame->cancelling_owner = handler->owner;
            frame->cancelling_handler_id = handler->descriptor.id;
            *handler_result = POKEMON_HANDLER_PREVENT;
        }
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_OWN_TEMPO_UPDATE) {
        if (confusion < 0) return POKEMON_OK;
        PokemonVolatileState old = holder->volatiles[confusion];
        PokemonEventFrame end;
        int result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_END,
            .source = {POKEMON_ENTITY_POKEMON, handler->holder_side,
                handler->holder_slot},
            .target_side = handler->holder_side,
            .target_slot = handler->holder_slot,
            .source_effect = old.source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {.kind = POKEMON_VOLATILE_CONFUSION},
        }, &end);
        if (result != POKEMON_OK) return result;
        result = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_REMOVE,
            POKEMON_CONDITION_REASON_HANDLER, POKEMON_CONDITION_VALUE_DURATION,
            handler->holder_side, handler->holder_slot,
            POKEMON_VOLATILE_CONFUSION, old.payload.confusion.time, 0);
        if (result != POKEMON_OK) return result;
        remove_volatile_at(holder, (size_t)confusion);
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_OWN_TEMPO_HIT) {
        if (input->context_kind != POKEMON_EVENT_CONTEXT_MOVE)
            return POKEMON_INVALID_CONFIGURATION;
        const PokemonMoveData *move = input->context.move.move;
        if (move == NULL || move->effect_count == 0) return POKEMON_OK;
        uint8_t adds_confusion = 0;
        for (size_t i = 0; i < move->effect_count; i++) {
            const PokemonEffectOp *effect = move_effect(battle, move, i);
            if (effect != NULL && effect->phase == POKEMON_EFFECT_PHASE_PRIMARY &&
                effect->kind == POKEMON_EFFECT_ADD_VOLATILE &&
                effect->argument == POKEMON_VOLATILE_CONFUSION) {
                adds_confusion = 1;
                break;
            }
        }
        if (!adds_confusion) return POKEMON_OK;
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_IMMUNE, .side = handler->holder_side,
            .target_side = input->source.side,
            .species_id = battle->sides[handler->holder_side].sets[
                handler->holder_slot].species_id,
            .move_id = move->id,
            .handler_id = handler->descriptor.id,
        });
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_SHIELD_DUST_MODIFY_SECONDARIES) {
        if (input->event != POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES ||
            input->relay.kind != POKEMON_RELAY_BOOLEAN ||
            input->context_kind != POKEMON_EVENT_CONTEXT_MOVE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (input->context.move.secondary_self_only) return POKEMON_OK;
        frame->relay.value.boolean = 0;
        return POKEMON_OK;
    }
    if (exceptional == POKEMON_EXCEPTION_CONFUSION_START ||
        exceptional == POKEMON_EXCEPTION_CONFUSION_END) return POKEMON_OK;
    if (exceptional != POKEMON_EXCEPTION_CONFUSION_BEFORE_MOVE || confusion < 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonVolatileState *state = &holder->volatiles[confusion];
    if (state->payload.confusion.time == 0) return POKEMON_INVALID_CONFIGURATION;
    uint8_t before = state->payload.confusion.time;
    state->payload.confusion.time--;
    if (state->payload.confusion.time == 0) {
        PokemonVolatileState old = *state;
        PokemonEventFrame end;
        int result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_END,
            .source = old.source, .target_side = handler->holder_side,
            .target_slot = handler->holder_slot,
            .source_effect = old.source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
            .context.volatile_condition = {.kind = POKEMON_VOLATILE_CONFUSION},
        }, &end);
        if (result != POKEMON_OK) return result;
        result = trace_condition(
            battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_REMOVE,
            POKEMON_CONDITION_REASON_HANDLER, POKEMON_CONDITION_VALUE_DURATION,
            handler->holder_side, handler->holder_slot,
            POKEMON_VOLATILE_CONFUSION, 0, 0);
        if (result == POKEMON_OK) {
            remove_volatile_at(holder, (size_t)confusion);
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_HANDLER,
                POKEMON_CONDITION_VALUE_DURATION, handler->holder_side,
                handler->holder_slot, POKEMON_VOLATILE_CONFUSION, before, 0);
        }
        return result;
    }
    int result = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_VOLATILE, POKEMON_CONDITION_UPDATE,
        POKEMON_CONDITION_REASON_HANDLER, POKEMON_CONDITION_VALUE_DURATION,
        handler->holder_side, handler->holder_slot, POKEMON_VOLATILE_CONFUSION,
        before, state->payload.confusion.time);
    if (result != POKEMON_OK) return result;
    uint32_t action = 0;
    result = draw_below(battle, POKEMON_DRAW_CONFUSION_ACTION,
        battle->generation->confusion_action_denominator, &action);
    /* verificationRandomChance records 0 for the branch that permits the
     * selected move and 1 for the complementary self-hit branch. */
    if (result != POKEMON_OK || action == 0) return result;
    PokemonMoveData synthetic = {
        .category = POKEMON_CATEGORY_PHYSICAL, .power = 40,
        .damage_formula = POKEMON_DAMAGE_STANDARD,
    };
    PokemonCalculatedDamage damage;
    PokemonEntityRef self = {POKEMON_ENTITY_POKEMON, handler->holder_side,
        handler->holder_slot};
    result = calculate_damage_inner(battle, &(PokemonDamageRequest){
        .mode = POKEMON_DAMAGE_MODE_SYNTHETIC_SELF_HIT,
        .source = self, .target = self, .move = &synthetic,
    }, &damage);
    if (result != POKEMON_OK) return result;
    uint16_t applied = 0;
    result = apply_direct_damage_inner(battle, &(PokemonDirectDamageRequest){
        .source = self, .target = self,
        .source_effect = {POKEMON_SOURCE_EFFECT_CONDITION,
            state->descriptor_id}, .amount = damage.damage,
    }, &applied);
    if (result != POKEMON_OK) return result;
    frame->relay.value.boolean = 0;
    frame->cancellation = POKEMON_EVENT_CANCEL_FALSE;
    *handler_result = POKEMON_HANDLER_PREVENT;
    return POKEMON_OK;
}

static int consume_substitute_hit(
    PokemonBattle *battle, const PokemonMoveData *move,
    size_t source_side, size_t source_slot, size_t target_side,
    size_t target_slot, uint8_t hit_index, uint8_t requested_hits,
    const SubstituteHit *sub
) {
    if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    PokemonMutable *source = &battle->sides[source_side].state[source_slot];
    PokemonMutable *target = &battle->sides[target_side].state[target_slot];
    size_t hit_trace_index = battle->hit_trace_count++;
    battle->hit_traces[hit_trace_index] = (PokemonHitTrace){
        .semantic_sequence = next_semantic_sequence(battle),
        .kind = POKEMON_HIT_SUBSTITUTE, .move_id = move->id,
        .source_side = (uint8_t)source_side, .source_slot = (uint8_t)source_slot,
        .target_side = (uint8_t)target_side, .target_slot = (uint8_t)target_slot,
        .hit_index = hit_index, .requested_hits = requested_hits,
        .dynamic_plan = battle->move_frame_depth != 0 &&
            battle->move_frames[battle->move_frame_depth - 1].party_hit_plan_active,
        .critical = sub->critical, .damage_roll = sub->damage_roll,
        .damage = sub->absorbed_damage,
        .calculated_damage = sub->calculated_damage,
        .substitute_broke = sub->broke,
        .hp_before = target->hp, .hp_after = target->hp,
        .source_hp_after = source->hp,
    };
    /* These phases are normally separated by target mutation. Substitute's
     * handler owns both and bases them on capped absorbed damage. */
    int result = apply_damage_relative_effects_rounded(
        battle, move, POKEMON_EFFECT_PHASE_AFTER_DAMAGE,
        source_side, source_slot, target_side, target_slot,
        sub->absorbed_damage, 1);
    if (result != POKEMON_OK) return result;
    result = apply_damage_relative_effects(
        battle, move, POKEMON_EFFECT_PHASE_AFTER_MOVE,
        source_side, source_slot, target_side, target_slot,
        sub->absorbed_damage);
    if (result != POKEMON_OK) return result;
    PokemonEventFrame after_sub_damage;
    result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_AFTER_SUB_DAMAGE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
            (uint8_t)source_slot},
        .target_side = (uint8_t)target_side,
        .target_slot = (uint8_t)target_slot,
        .source_effect = active_source_effect(battle, move->id),
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        .include_move_self = 1,
    }, &after_sub_damage);
    if (result != POKEMON_OK) return result;
    battle->hit_traces[hit_trace_index].after_sub_damage_dispatched = 1;
    return resolve_move_faint(battle, source_side, source_slot,
        (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_NONE, 0});
}

typedef struct {
    PokemonEntityRef values[POKEMON_SIDES];
    uint8_t count;
} PokemonResolvedTargetList;

/* Normalize target topology before applying effects. The current state owns
 * one active slot per side; formats with wider geometry fail closed instead
 * of silently losing targets. */
static int collect_move_targets(
    const PokemonBattle *battle, PokemonEntityRef user,
    PokemonMoveTarget mode, PokemonResolvedTarget fallback,
    PokemonResolvedTargetList *targets
) {
    if (battle == NULL || targets == NULL || user.kind != POKEMON_ENTITY_POKEMON ||
        user.side >= POKEMON_SIDES || battle->format.active_per_side != 1) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *targets = (PokemonResolvedTargetList){0};
    if (mode == POKEMON_TARGET_ALL) {
        size_t side = 1u - user.side;
        uint8_t slot = battle->sides[side].active;
        if (battle->sides[side].state[slot].hp == 0) return POKEMON_OK;
        targets->values[targets->count++] = (PokemonEntityRef){
            POKEMON_ENTITY_POKEMON, (uint8_t)side, slot};
        return POKEMON_OK;
    }
    if (mode == POKEMON_TARGET_ALL_ADJACENT) {
        for (size_t side = 0; side < POKEMON_SIDES; side++) {
            uint8_t slot = battle->sides[side].active;
            if (side == user.side && slot == user.slot) continue;
            if (battle->sides[side].state[slot].hp == 0) continue;
            targets->values[targets->count++] = (PokemonEntityRef){
                POKEMON_ENTITY_POKEMON, (uint8_t)side, slot};
        }
        return POKEMON_OK;
    }
    if (mode == POKEMON_TARGET_ALL_ADJACENT_FOES ||
        fallback == POKEMON_RESOLVED_TARGET_FOE ||
        fallback == POKEMON_RESOLVED_TARGET_FOE_SIDE) {
        size_t side = 1u - user.side;
        uint8_t slot = battle->sides[side].active;
        if (battle->sides[side].state[slot].hp == 0) return POKEMON_OK;
        targets->values[targets->count++] = (PokemonEntityRef){
            POKEMON_ENTITY_POKEMON, (uint8_t)side, slot};
    } else if (fallback == POKEMON_RESOLVED_TARGET_USER) {
        targets->values[targets->count++] = user;
    }
    return POKEMON_OK;
}

static int run_move_self_event(
    PokemonBattle *battle, PokemonEventId event, const PokemonMoveData *move,
    PokemonEntityRef user, size_t target_side, size_t target_slot,
    PokemonSourceEffectRef source_effect, PokemonRelay relay,
    PokemonEventFrame *last, uint8_t *ran
) {
    *ran = 0;
    for (size_t i = 0; i < battle->data->handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor = &battle->data->handlers[i];
        if (descriptor->event != event ||
            descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
            descriptor->source_id != move->id ||
            descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) continue;
        if (descriptor->required_move_profile_tag != 0) {
            if (battle->move_frame_depth == 0 ||
                battle->move_frames[battle->move_frame_depth - 1].profile_tag !=
                    descriptor->required_move_profile_tag) continue;
        }
        *ran = 1;
        size_t holder_side = (event == POKEMON_HANDLER_EVENT_TRY_HIT ||
            event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY ||
            event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
            event == POKEMON_HANDLER_EVENT_MOVE_FAIL) ?
            target_side : user.side;
        size_t holder_slot = (event == POKEMON_HANDLER_EVENT_TRY_HIT ||
            event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY ||
            event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
            event == POKEMON_HANDLER_EVENT_MOVE_FAIL) ?
            target_slot : user.slot;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = event, .source = user,
            .target_side = (uint8_t)target_side,
            .target_slot = (uint8_t)target_slot,
            .source_effect = source_effect, .relay = relay,
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move}, .has_only_handler = 1,
            .only_handler = {
                .descriptor = *descriptor, .binding_index = (uint16_t)i,
                .owner = {POKEMON_OWNER_MOVE, user.side, user.slot, move->id, 1},
                .holder_side = (uint8_t)holder_side,
                .holder_slot = (uint8_t)holder_slot,
                .speed = battle->sides[holder_side].state[
                    holder_slot].cached_speed,
            },
        }, last);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int slot_condition_index(
    const PokemonSide *side, uint8_t position, uint16_t descriptor_id
) {
    if (position >= POKEMON_ACTIVE_POSITION_CAPACITY) return -1;
    for (size_t i = 0; i < side->slot_condition_count[position]; i++) {
        if (side->slot_conditions[position][i].descriptor_id == descriptor_id) {
            return (int)i;
        }
    }
    return -1;
}

/* Install delayed work on a battlefield position, not on its current roster
 * occupant. Duplicate rejection precedes payload construction, so a rejected
 * Future Sight/Doom Desire consumes no damage-roll draw. */
static int install_move_slot_condition(
    PokemonBattle *battle, const PokemonMoveData *move,
    PokemonEntityRef source, size_t target_side, uint8_t position,
    uint8_t *installed
) {
    if (move == NULL || installed == NULL || target_side >= POKEMON_SIDES ||
        position >= battle->format.active_per_side ||
        position >= POKEMON_ACTIVE_POSITION_CAPACITY ||
        move->slot_condition_descriptor == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *installed = 0;
    const PokemonSlotConditionPolicy *policy = slot_condition_policy(
        battle->data, move->slot_condition_descriptor);
    const PokemonConditionIdentity *identity = pokemon_condition_identity(
        battle->data, move->slot_condition_descriptor);
    if (policy == NULL || identity == NULL ||
        identity->domain != POKEMON_CONDITION_DOMAIN_SLOT ||
        identity->semantic_kind != policy->semantic_kind ||
        policy->duration == 0 || policy->residual_order == 0 ||
        (policy->effect_kind == POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION &&
         (policy->numerator == 0 || policy->denominator == 0 ||
          policy->numerator > policy->denominator))) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonSide *side = &battle->sides[target_side];
    if (slot_condition_index(side, position, policy->descriptor_id) >= 0) {
        return POKEMON_OK;
    }
    if (side->slot_condition_count[position] == POKEMON_SLOT_CONDITION_CAPACITY ||
        battle->next_holder_effect_order == UINT16_MAX ||
        battle->condition_trace_count == POKEMON_CONDITION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    size_t index = side->slot_condition_count[position]++;
    PokemonSlotConditionState *condition =
        &side->slot_conditions[position][index];
    *condition = (PokemonSlotConditionState){
        .descriptor_id = policy->descriptor_id,
        .semantic_kind = policy->semantic_kind,
        .duration = policy->duration,
        .position = position,
        .state_generation = 1,
        .effect_order = ++battle->next_holder_effect_order,
        .source = source,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
    };
    int status = trace_condition(
        battle, POKEMON_CONDITION_SCOPE_SLOT, POKEMON_CONDITION_ADD,
        POKEMON_CONDITION_REASON_MOVE, POKEMON_CONDITION_VALUE_DURATION,
        target_side, position, policy->semantic_kind, 0, policy->duration);
    if (status != POKEMON_OK) return status;
    battle->condition_traces[battle->condition_trace_count - 1].descriptor_id =
        policy->descriptor_id;
    if (policy->effect_kind == POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE) {
        PokemonMoveData snapshot_move = *move;
        snapshot_move.type = battle->data->non_interacting_type;
        snapshot_move.critical_stage = 0;
        snapshot_move.slot_condition_descriptor = 0;
        PokemonCalculatedDamage calculated;
        status = calculate_damage_inner(battle, &(PokemonDamageRequest){
            .mode = POKEMON_DAMAGE_MODE_ORDINARY_MOVE,
            .source = source,
            .target = {POKEMON_ENTITY_POKEMON, (uint8_t)target_side,
                battle->sides[target_side].active},
            .move = &snapshot_move,
            .critical = 0,
        }, &calculated);
        if (status != POKEMON_OK) return status;
        condition->payload.delayed_move.move_id = move->id;
        condition->payload.delayed_move.fixed_damage = calculated.damage;
    } else if (policy->effect_kind !=
            POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *installed = 1;
    return POKEMON_OK;
}

static int reresolve_active_move_target(
    PokemonBattle *battle, const PokemonMoveInvocation *invocation,
    const PokemonMoveData *move, PokemonResolvedTarget *resolved
) {
    PokemonMoveInvocation request = *invocation;
    PokemonTargetRule rule;
    if (!pokemon_resolve_move_target(&battle->format, move->target, &rule)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (rule.resolved != POKEMON_RESOLVED_TARGET_FOE &&
        rule.resolved != POKEMON_RESOLVED_TARGET_FOE_SIDE) {
        request.target_request = (PokemonTargetRequest){
            .kind = POKEMON_TARGET_REQUEST_RESOLVE,
            .explicit_target = {POKEMON_ENTITY_NONE, 0, 0},
        };
    }
    PokemonEntityRef target;
    int status = resolve_invocation_target(
        battle, &request, move, &target, resolved);
    if (status != POKEMON_OK) return status;
    PokemonActiveMoveFrame *active =
        &battle->move_frames[battle->move_frame_depth - 1];
    active->resolved_target = target;
    for (size_t i = battle->move_invocation_count; i > 0; i--) {
        PokemonMoveInvocationTrace *trace = &battle->move_invocations[i - 1];
        if (trace->invocation.invocation_id == invocation->invocation_id) {
            trace->resolved_target = target;
            return POKEMON_OK;
        }
    }
    return POKEMON_INVALID_CONFIGURATION;
}

static int execute_move_body(
    PokemonBattle *battle, const PokemonMoveInvocation *invocation,
    PokemonResolvedTarget resolved_target
) {
    PokemonAction action_value = {
        .kind = POKEMON_ACTION_MOVE,
        .side = invocation->user.side,
        .slot = invocation->selected_slot,
        .priority = invocation->inherited_priority,
        .resolved_target = resolved_target,
    };
    const PokemonAction *action = &action_value;
    size_t side = invocation->user.side;
    size_t target_side = 1u - side;
    PokemonSide *attacking_side = &battle->sides[side];
    PokemonSide *defending_side = &battle->sides[target_side];
    uint8_t attacker_slot = invocation->user.slot;
    uint8_t defender_slot = defending_side->active;
    if (attacking_side->state[attacker_slot].hp == 0) return POKEMON_OK;

    PokemonSet *attacker = &attacking_side->sets[attacker_slot];
    PokemonSet *defender = &defending_side->sets[defender_slot];
    PokemonMutable *attacker_state = &attacking_side->state[attacker_slot];
    PokemonMutable *defender_state = &defending_side->state[defender_slot];
    const PokemonMoveData *base_move = find_move(battle, invocation->move_id);
    const PokemonSpeciesData *attacker_species = find_species(battle, attacker->species_id);
    const PokemonSpeciesData *defender_species = find_species(battle, defender->species_id);
    assert(base_move != NULL && attacker_species != NULL && defender_species != NULL);
    PokemonActiveMoveFrame *active =
        &battle->move_frames[battle->move_frame_depth - 1];
    size_t mutation_target_side =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        target_side : side;
    uint8_t mutation_target_slot =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        defender_slot : attacker_slot;
    static const PokemonEventId mutation_events[] = {
        POKEMON_HANDLER_EVENT_MODIFY_TYPE,
        POKEMON_HANDLER_EVENT_MODIFY_MOVE,
    };
    size_t first_mutation_event =
        battle->generation->has_separate_modify_type_phase ? 0 : 1;
    for (size_t event = first_mutation_event;
         event < sizeof(mutation_events) / sizeof(mutation_events[0]);
         event++) {
        for (size_t i = 0; i < battle->data->handler_count; i++) {
            const PokemonHandlerDescriptor *descriptor = &battle->data->handlers[i];
            if (descriptor->event != mutation_events[event] ||
                descriptor->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                descriptor->source_id != base_move->id ||
                descriptor->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) continue;
            PokemonEventFrame mutation;
            int mutation_status = run_event_inner(battle, &(PokemonEventInput){
                .event = mutation_events[event],
                .source = invocation->user,
                .target_side = (uint8_t)mutation_target_side,
                .target_slot = mutation_target_slot,
                .source_effect = invocation->source_effect,
                .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = base_move},
                .has_only_handler = 1,
                .only_handler = {
                    .descriptor = *descriptor, .binding_index = (uint16_t)i,
                    .owner = {POKEMON_OWNER_MOVE, (uint8_t)side, attacker_slot,
                        base_move->id, 1},
                    .holder_side = (uint8_t)side, .holder_slot = attacker_slot,
                    .speed = attacker_state->cached_speed,
                },
            }, &mutation);
            if (mutation_status != POKEMON_OK) return mutation_status;
        }
    }
    PokemonMoveData resolved_move = *base_move;
    resolved_move.target = active->target_mode;
    resolved_move.type = active->type;
    resolved_move.category = active->category;
    resolved_move.power = active->base_power;
    resolved_move.accuracy = active->accuracy;
    resolved_move.flags = active->flags;
    resolved_move.effect_offset = active->effect_offset;
    resolved_move.effect_count = active->effect_count;
    resolved_move.multihit_min = active->multihit_min;
    resolved_move.multihit_max = active->multihit_max;
    int target_status = reresolve_active_move_target(
        battle, invocation, &resolved_move, &resolved_target);
    if (target_status != POKEMON_OK) return target_status;
    action_value.resolved_target = resolved_target;
    mutation_target_side =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        target_side : side;
    mutation_target_slot =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        defender_slot : attacker_slot;
    /* Showdown runs move-owned singleEvent callbacks before the ordinary
     * holder-discovered ModifyMove event.  Status, volatile, ability and item
     * owners therefore share the same ordered dispatcher instead of requiring
     * phase-specific adapters in execute_move. */
    PokemonEventFrame holder_mutation;
    int holder_mutation_status = run_event_inner(
        battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_MODIFY_MOVE,
            .source = invocation->user,
            .target_side = invocation->user.side,
            .target_slot = invocation->user.slot,
            .source_effect = invocation->source_effect,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = &resolved_move},
        }, &holder_mutation);
    if (holder_mutation_status != POKEMON_OK) return holder_mutation_status;
    attacker_state->last_move_used = (PokemonLastUsedMove){
        .present = 1, .move_id = base_move->id, .resolved_type = active->type,
    };
    resolved_move = *base_move;
    resolved_move.target = active->target_mode;
    resolved_move.type = active->type;
    resolved_move.category = active->category;
    resolved_move.power = active->base_power;
    resolved_move.accuracy = active->accuracy;
    resolved_move.flags = active->flags;
    resolved_move.effect_offset = active->effect_offset;
    resolved_move.effect_count = active->effect_count;
    resolved_move.multihit_min = active->multihit_min;
    resolved_move.multihit_max = active->multihit_max;
    const PokemonMoveData *move = &resolved_move;
    target_status = reresolve_active_move_target(
        battle, invocation, move, &resolved_target);
    if (target_status != POKEMON_OK) return target_status;
    action_value.resolved_target = resolved_target;
    mutation_target_side =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        target_side : side;
    mutation_target_slot =
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
        defender_slot : attacker_slot;
    PokemonResolvedTargetList resolved_targets;
    target_status = collect_move_targets(
        battle, invocation->user, move->target, resolved_target,
        &resolved_targets);
    if (target_status != POKEMON_OK) return target_status;
    if (move->category == POKEMON_CATEGORY_STATUS &&
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_USER) &&
        resolved_targets.count != 1) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (invocation->owns_pp_deduction) {
        if (invocation->entry != POKEMON_MOVE_ENTRY_SELECTED ||
            invocation->selected_slot >= POKEMON_MOVE_CAPACITY ||
            invocation->source_effect.kind != POKEMON_SOURCE_EFFECT_NONE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint32_t extra_pp = 0;
        for (size_t i = 0; i < resolved_targets.count; i++) {
            PokemonEntityRef pressure_target = resolved_targets.values[i];
            PokemonEventFrame deduct;
            int deduct_status = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_DEDUCT_PP,
                .source = invocation->user,
                .target_side = pressure_target.side,
                .target_slot = pressure_target.slot,
                .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
                .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = 0},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = move},
            }, &deduct);
            if (deduct_status != POKEMON_OK) return deduct_status;
            if (UINT32_MAX - extra_pp < deduct.relay.value.u32) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            extra_pp += deduct.relay.value.u32;
        }
        uint8_t pp = attacker_state->pp[invocation->selected_slot];
        set_current_pp(battle, invocation->user.side,
            invocation->user.slot, invocation->selected_slot,
            extra_pp >= pp ? 0 : (uint8_t)(pp - extra_pp));
    }
    const PokemonEffectOp *primary = move->effect_count != 0 ?
        move_effect(battle, move, 0) : NULL;

    const size_t move_event_index = battle->event_count;
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_MOVE,
        .side = (uint8_t)side,
        .target_side = (uint8_t)(
            primary != NULL && primary->kind == POKEMON_EFFECT_ADD_WEATHER &&
            battle->field.weather.kind == (PokemonWeatherKind)primary->argument ?
                UINT8_MAX :
            (action->resolved_target == POKEMON_RESOLVED_TARGET_NONE ?
                UINT8_MAX :
             (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
              action->resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
                target_side : side)),
        .slot = action->slot,
        .species_id = attacker->species_id,
        .move_id = move->id,
    });

    if (resolved_targets.count == 0 &&
        (resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
         resolved_target == POKEMON_RESOLVED_TARGET_FOE_SIDE)) {
        active->attempt_outcome = POKEMON_MOVE_ATTEMPT_NO_TARGET;
        battle->events[move_event_index].target_side = UINT8_MAX;
        return POKEMON_OK;
    }

    PokemonEventFrame try_move;
    int try_move_status;
    try_move_status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_TRY_MOVE,
        .source = invocation->user,
        .target_side = (uint8_t)mutation_target_side,
        .target_slot = mutation_target_slot,
        .source_effect = invocation->source_effect,
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
        .include_move_self = 1,
    }, &try_move);
    if (try_move_status != POKEMON_OK) return try_move_status;
    if (active->suppress_protocol_target) {
        battle->events[move_event_index].target_side = UINT8_MAX;
    }
    if (try_move.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        !try_move.relay.value.boolean) {
        /* A TryMove null/false result announces the move without a resolved
         * protocol target.  Keep the event identity, but do not claim the hit
         * pipeline selected a target it never reached. */
        battle->events[move_event_index].target_side = UINT8_MAX;
        active->attempt_outcome = POKEMON_MOVE_ATTEMPT_ABORTED_BEFORE_HIT;
        return POKEMON_OK;
    }

    const PokemonSlotConditionPolicy *move_slot_policy =
        move->slot_condition_descriptor == 0 ? NULL : slot_condition_policy(
            battle->data, move->slot_condition_descriptor);
    if (move->slot_condition_descriptor != 0 && move_slot_policy == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (move_slot_policy != NULL && move_slot_policy->effect_kind ==
            POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE) {
        size_t slot_side = resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
            target_side : side;
        uint8_t installed = 0;
        int slot_status = install_move_slot_condition(
            battle, move, invocation->user, slot_side, 0, &installed);
        if (slot_status != POKEMON_OK) return slot_status;
        if (installed) active->move_succeeded = 1;
        return POKEMON_OK;
    }

    /* Showdown announces a move-owned power variant only after TryMove has
     * admitted the action, while its ModifyMove sampling already occurred.
     * Keep this as an ordinary generated single-event boundary. */
    {
        PokemonEventFrame message_frame;
        uint8_t ran_message = 0;
        int message_status = run_move_self_event(
            battle, POKEMON_HANDLER_EVENT_USE_MOVE_MESSAGE, move,
            invocation->user, mutation_target_side, mutation_target_slot,
            invocation->source_effect,
            (PokemonRelay){.kind = POKEMON_RELAY_UNDEFINED},
            &message_frame, &ran_message);
        if (message_status != POKEMON_OK) return message_status;
    }

    if (move->self_faint_timing == POKEMON_SELF_FAINT_PRE_HIT &&
        attacker_state->hp != 0 && !attacker_state->fainted) {
        if (battle->faint_count == POKEMON_FAINT_QUEUE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        attacker_state->hp = 0;
        int faint_status = queue_faint(
            battle, invocation->user, invocation->user,
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id});
        if (faint_status != POKEMON_OK) return faint_status;
    }

    int stalling_guard_index = -1;
    int stalling_stall_index = -1;
    uint8_t stalling_guard_admitted = 0;
    /* PrepareHit owns interception before accuracy or any move effect.  Its
     * event target is the invocation target; ANY handlers retain their own
     * holder identity in PokemonHandlerRef and may re-enter this stack. */
    {
        size_t prepare_target_side = resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
            target_side : side;
        size_t prepare_target_slot = resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
            defender_slot : attacker_slot;
        PokemonEventFrame prepare_frame;
        int prepare_status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_PREPARE_HIT,
            .source = invocation->user,
            .target_side = (uint8_t)prepare_target_side,
            .target_slot = (uint8_t)prepare_target_slot,
            .source_effect = invocation->source_effect,
            .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move},
            .include_move_self = 1,
        }, &prepare_frame);
        if (prepare_status != POKEMON_OK) return prepare_status;
        if (prepare_frame.cancellation != POKEMON_EVENT_CANCEL_NONE) {
            return POKEMON_OK;
        }
        /* Stalling guards express Showdown's move-owned onPrepareHit gate.
         * Admission, including its PRNG draw, precedes generic Try/TryHit;
         * successful installation remains the primary effect below. */
        if (primary != NULL &&
            primary->kind == POKEMON_EFFECT_INSTALL_STALLING_GUARD) {
            PokemonVolatileKind guard_kind =
                (PokemonVolatileKind)primary->argument;
            stalling_guard_index = volatile_index(attacker_state, guard_kind);
            stalling_stall_index = volatile_index(
                attacker_state, POKEMON_VOLATILE_STALL);
            if (battle->queue.count == 0 || stalling_guard_index >= 0) {
                battle->events[move_event_index].target_side = UINT8_MAX;
                return POKEMON_OK;
            }
            if (stalling_stall_index >= 0) {
                uint32_t roll = 0;
                int stall_status = draw_below(
                    battle, POKEMON_DRAW_STALL_SUCCESS,
                    attacker_state->volatiles[stalling_stall_index].counter,
                    &roll);
                if (stall_status != POKEMON_OK) return stall_status;
                battle->draws[battle->draw_count - 1].semantic_sequence =
                    next_semantic_sequence(battle);
                if (roll != 0) {
                    battle->events[move_event_index].target_side = UINT8_MAX;
                    return POKEMON_OK;
                }
            }
            size_t needed = stalling_stall_index < 0 ? 2u : 1u;
            if ((size_t)attacker_state->volatile_count + needed >
                POKEMON_VOLATILE_CAPACITY) return POKEMON_CAPACITY_EXCEEDED;
            stalling_guard_admitted = 1;
        }
        uint8_t ran_try = 0;
        try_move_status = run_move_self_event(
            battle, POKEMON_HANDLER_EVENT_TRY, move, invocation->user,
            prepare_target_side, prepare_target_slot, invocation->source_effect,
            (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                .value.boolean = 1},
            &try_move, &ran_try);
        if (try_move_status != POKEMON_OK) return try_move_status;
        if (ran_try &&
            (try_move.cancellation != POKEMON_EVENT_CANCEL_NONE ||
             !try_move.relay.value.boolean)) {
            if (active->suppress_protocol_target) {
                battle->events[move_event_index].target_side = UINT8_MAX;
            } else if (move->target == POKEMON_TARGET_SELF) {
                battle->events[move_event_index].target_side = (uint8_t)side;
            }
            return POKEMON_OK;
        }
    }

    if (move_resolution(move) == POKEMON_MOVE_RESOLUTION_NONE) {
        int result = POKEMON_OK;
        PokemonImmunityCause handler_cause = POKEMON_IMMUNITY_NONE;
        uint16_t handler_effect = 0;
        PokemonHandlerId handler_id = 0;
        PokemonHandlerId pending_immunity_handler_id = 0;
        uint8_t pending_natural_type_immunity = 0;
        uint8_t emit_immunity = 1;
        PokemonEventCancellation cancellation = POKEMON_EVENT_CANCEL_NONE;
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_NONE) {
            return POKEMON_OK;
        }
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE) {
            uint8_t invulnerability_admitted = 0;
            result = resolve_invulnerability(
                battle, move, side, attacker_slot, target_side, defender_slot,
                &invulnerability_admitted);
            if (result != POKEMON_OK) return result;
            if (!invulnerability_admitted) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_MISS, .side = (uint8_t)side,
                    .target_side = (uint8_t)target_side,
                    .species_id = attacker->species_id, .move_id = move->id,
                });
                return POKEMON_OK;
            }
            if (move->checks_natural_type_immunity) {
                uint8_t immunity_negated = 0;
                result = resolve_negate_immunity(
                    battle, move, side, attacker_slot,
                    target_side, defender_slot, &immunity_negated);
                if (result != POKEMON_OK) return result;
                pending_natural_type_immunity =
                    !(battle->data->has_non_interacting_type &&
                      move->type == battle->data->non_interacting_type) &&
                    type_is_immune(battle, move->type, defender_state) &&
                    !immunity_negated;
            }
            if (!pending_natural_type_immunity) {
                PokemonEventFrame try_immunity;
                uint8_t ran_try_immunity = 0;
                result = run_move_self_event(
                    battle, POKEMON_HANDLER_EVENT_TRY_IMMUNITY, move,
                    invocation->user, target_side, defender_slot,
                    active_source_effect(battle, move->id),
                    (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 1},
                    &try_immunity, &ran_try_immunity);
                if (result != POKEMON_OK) return result;
                if (ran_try_immunity &&
                    (try_immunity.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                     !try_immunity.relay.value.boolean)) {
                    pending_immunity_handler_id =
                        try_immunity.cancelling_handler_id;
                }
            }
        }
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
            primary == NULL || move->category != POKEMON_CATEGORY_STATUS) {
            size_t accuracy_target_side =
                action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                    target_side : side;
            size_t accuracy_target_slot =
                action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                    defender_slot : attacker_slot;
            uint8_t accuracy_hit = 0;
            PokemonImmunityCause accuracy_immunity = POKEMON_IMMUNITY_NONE;
            result = resolve_move_accuracy(
                battle, move, side, attacker_slot, accuracy_target_side,
                accuracy_target_slot, &accuracy_hit, &accuracy_immunity);
            if (result != POKEMON_OK) return result;
            if (accuracy_immunity != POKEMON_IMMUNITY_NONE) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE,
                    .side = (uint8_t)accuracy_target_side,
                    .target_side = (uint8_t)side,
                    .species_id = action->resolved_target ==
                        POKEMON_RESOLVED_TARGET_FOE ? defender->species_id :
                        attacker->species_id,
                    .move_id = move->id,
                    .immunity_cause = accuracy_immunity,
                });
                return POKEMON_OK;
            }
            if (!accuracy_hit) {
                append_event(battle, pending_natural_type_immunity ?
                    (PokemonEvent){.kind = POKEMON_EVENT_IMMUNE,
                        .side = (uint8_t)target_side,
                        .target_side = (uint8_t)side,
                        .species_id = defender->species_id, .move_id = move->id,
                        .immunity_cause = POKEMON_IMMUNITY_NATURAL_TYPE} :
                    pending_immunity_handler_id != 0 ?
                    (PokemonEvent){.kind = POKEMON_EVENT_IMMUNE,
                        .side = (uint8_t)target_side,
                        .target_side = (uint8_t)side,
                        .species_id = defender->species_id, .move_id = move->id,
                        .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                        .handler_id = pending_immunity_handler_id} :
                    (PokemonEvent){.kind = POKEMON_EVENT_MISS,
                        .side = (uint8_t)side,
                        .target_side = (uint8_t)accuracy_target_side,
                        .species_id = attacker->species_id, .move_id = move->id});
                return POKEMON_OK;
            }
        }
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE) {
            result = run_try_hit_handlers(
                battle, side, attacker_slot, target_side, defender_slot, move,
                &handler_cause, &handler_effect, &handler_id, &emit_immunity,
                &cancellation);
            if (result != POKEMON_OK) return result;
            if (cancellation == POKEMON_EVENT_CANCEL_NOT_FAIL) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_BLOCK, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                });
                return POKEMON_OK;
            }
            if (cancellation == POKEMON_EVENT_CANCEL_NULL ||
                cancellation == POKEMON_EVENT_CANCEL_FALSE) return POKEMON_OK;
            if (handler_cause != POKEMON_IMMUNITY_NONE) {
                if (emit_immunity) append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                    .immunity_cause = handler_cause, .handler_id = handler_id,
                });
                return POKEMON_OK;
            }
            if (pending_natural_type_immunity) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE,
                    .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id,
                    .move_id = move->id,
                    .immunity_cause = POKEMON_IMMUNITY_NATURAL_TYPE,
                });
                return POKEMON_OK;
            }
            if (pending_immunity_handler_id != 0) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                    .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                    .handler_id = pending_immunity_handler_id,
                });
                return POKEMON_OK;
            }
            PokemonEventFrame move_try_hit;
            uint8_t ran_move_try_hit = 0;
            result = run_move_self_event(
                battle, POKEMON_HANDLER_EVENT_TRY_HIT, move,
                invocation->user, target_side, defender_slot,
                active_source_effect(battle, move->id),
                (PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
                    .value.boolean = 1},
                &move_try_hit, &ran_move_try_hit);
            if (result != POKEMON_OK) return result;
            if (ran_move_try_hit &&
                (move_try_hit.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                 !move_try_hit.relay.value.boolean)) {
                battle->events[move_event_index].target_side = UINT8_MAX;
                record_attack(battle, target_side, defender_slot, side,
                    attacker_slot, move->id, 0, 0);
                return POKEMON_OK;
            }
            /* Move-owned TryImmunity runs after accuracy but before TryHit
             * and Hit. Trick uses the generated swap operation to select
             * this boundary; the runtime does not know its catalog ID. */
            if (primary != NULL && primary->kind == POKEMON_EFFECT_SWAP_ITEMS) {
                const PokemonAbilityData *target_ability = find_ability(
                    battle, defender_state->ability_id);
                if (target_ability != NULL &&
                    (target_ability->semantic_flags &
                        POKEMON_ABILITY_SEMANTIC_BLOCKS_EXTERNAL_ITEM_TAKE) != 0) {
                    append_event(battle, (PokemonEvent){
                        .kind = POKEMON_EVENT_IMMUNE,
                        .side = (uint8_t)target_side,
                        .target_side = (uint8_t)side,
                        .species_id = defender->species_id,
                        .move_id = move->id,
                        .immunity_cause = POKEMON_IMMUNITY_HANDLER,
                    });
                    return POKEMON_OK;
                }
            }
            /* Generic TryPrimaryHit interception: a foe's non-damaging
             * primary never reaches runMoveEffects through Substitute. */
            uint8_t primary_intercepted = 0;
            result = discover_try_primary_hit(
                battle, move, side, attacker_slot, target_side, defender_slot,
                &primary_intercepted);
            if (result != POKEMON_OK) return result;
            if (primary_intercepted) {
                /* Showdown's blocked non-damaging primary reports the move
                 * without a resolved protocol target.  This belongs to the
                 * generic TryPrimaryHit interception boundary. */
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_BLOCK, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                });
                record_attack(battle, target_side, defender_slot, side,
                    attacker_slot, move->id, 0, 0);
                return POKEMON_OK;
            }
        }
        if (action->resolved_target != POKEMON_RESOLVED_TARGET_FOE &&
            move->target != POKEMON_TARGET_ALL) {
			if (action->resolved_target != POKEMON_RESOLVED_TARGET_USER) {
				PokemonEventFrame move_try_hit;
				uint8_t ran_move_try_hit = 0;
				result = run_move_self_event(
					battle, POKEMON_HANDLER_EVENT_TRY_HIT, move,
					invocation->user, side, attacker_slot,
					active_source_effect(battle, move->id),
					(PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
						.value.boolean = 1},
					&move_try_hit, &ran_move_try_hit);
				if (result != POKEMON_OK) return result;
				if (ran_move_try_hit &&
					(move_try_hit.cancellation != POKEMON_EVENT_CANCEL_NONE ||
					 !move_try_hit.relay.value.boolean)) {
					battle->events[move_event_index].target_side = UINT8_MAX;
					return POKEMON_OK;
				}
			}
			/* Target-owned TryHit discovery applies to self-targeting status
			 * moves. Side and field targets have no Pokemon target whose
			 * handlers could participate. */
			if (action->resolved_target == POKEMON_RESOLVED_TARGET_USER) {
				result = run_try_hit_handlers(
					battle, side, attacker_slot, side, attacker_slot, move,
					&handler_cause, &handler_effect, &handler_id, &emit_immunity,
					&cancellation);
				if (result != POKEMON_OK) return result;
				if (cancellation != POKEMON_EVENT_CANCEL_NONE ||
					handler_cause != POKEMON_IMMUNITY_NONE) return POKEMON_OK;
				PokemonEventFrame move_try_hit;
				uint8_t ran_move_try_hit = 0;
				result = run_move_self_event(
					battle, POKEMON_HANDLER_EVENT_TRY_HIT, move,
					invocation->user, side, attacker_slot,
					active_source_effect(battle, move->id),
					(PokemonRelay){.kind = POKEMON_RELAY_BOOLEAN,
						.value.boolean = 1},
					&move_try_hit, &ran_move_try_hit);
				if (result != POKEMON_OK) return result;
				if (ran_move_try_hit &&
					(move_try_hit.cancellation != POKEMON_EVENT_CANCEL_NONE ||
					 !move_try_hit.relay.value.boolean)) {
					battle->events[move_event_index].target_side = UINT8_MAX;
					return POKEMON_OK;
				}
				/* A move-owned TryHit rejection follows global target TryHit but
				 * precedes TryPrimaryHit. CREATE_SUBSTITUTE carries that semantic
				 * precondition as a typed effect rather than a move ID. */
				if (primary != NULL &&
					primary->kind == POKEMON_EFFECT_CREATE_SUBSTITUTE) {
					uint8_t admitted = 0;
					result = substitute_creation_is_admitted(
						battle, attacker, attacker_state, &admitted);
					if (result != POKEMON_OK) return result;
					if (!admitted) return POKEMON_OK;
				}
                uint8_t ignored_interception = 0;
                result = discover_try_primary_hit(
                    battle, move, side, attacker_slot, side, attacker_slot,
                    &ignored_interception);
                if (result != POKEMON_OK) return result;
                assert(!ignored_interception);
			}
        }
        if (move_slot_policy != NULL) {
            size_t slot_side = action->resolved_target ==
                    POKEMON_RESOLVED_TARGET_FOE ? target_side : side;
            uint8_t installed = 0;
            result = install_move_slot_condition(
                battle, move, invocation->user, slot_side, 0, &installed);
            if (result != POKEMON_OK) return result;
            if (installed) active->move_succeeded = 1;
            return POKEMON_OK;
        }
        if (primary != NULL &&
            primary->phase == POKEMON_EFFECT_PHASE_SELF_DROP) {
            for (size_t i = 0; i < move->effect_count; i++) {
                const PokemonEffectOp *op = move_effect(battle, move, i);
                if (op->phase != POKEMON_EFFECT_PHASE_SELF_DROP ||
                    op->kind != POKEMON_EFFECT_BOOST ||
                    op->target != POKEMON_EFFECT_TARGET_USER) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
            }
            uint8_t callback_succeeded = 0;
            PokemonEventCancellation callback_cancellation =
                POKEMON_EVENT_CANCEL_NONE;
            result = run_move_hit_event(
                battle, move, side, attacker_slot, side, attacker_slot,
                &callback_succeeded, &callback_cancellation);
            if (result != POKEMON_OK) return result;
            if (!callback_succeeded ||
                callback_cancellation != POKEMON_EVENT_CANCEL_NONE) {
                battle->events[move_event_index].target_side = UINT8_MAX;
                return POKEMON_OK;
            }
            result = apply_hit_effect_stage(
                battle, move, side, attacker_slot, side, attacker_slot, 0,
                POKEMON_HIT_EFFECT_STAGE_SECONDARY);
            if (result != POKEMON_OK) return result;
            active->move_succeeded = 1;
            return POKEMON_OK;
        }
        if (primary == NULL) {
            if (move->target == POKEMON_TARGET_ALL) {
                uint8_t callback_succeeded = 0;
                result = run_move_hit_field_callback(
                    battle, move, invocation->user,
                    active_source_effect(battle, move->id),
                    &callback_succeeded);
                if (result != POKEMON_OK) return result;
                if (!callback_succeeded) {
                    battle->events[move_event_index].target_side = UINT8_MAX;
                } else {
                    active->move_succeeded = 1;
                }
                return POKEMON_OK;
            }
            size_t hit_side = action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                target_side : side;
            uint8_t hit_slot = action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                defender_slot : attacker_slot;
            uint8_t callback_succeeded = 0;
            PokemonEventCancellation callback_cancellation =
                POKEMON_EVENT_CANCEL_NONE;
            result = run_move_hit_event(
                battle, move, side, attacker_slot, hit_side, hit_slot,
                &callback_succeeded, &callback_cancellation);
            if (result != POKEMON_OK) return result;
            if (!callback_succeeded &&
                callback_cancellation != POKEMON_EVENT_CANCEL_NULL) {
                battle->events[move_event_index].target_side = UINT8_MAX;
            } else {
                active->move_succeeded = 1;
            }
            if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE) {
                record_attack(battle, target_side, defender_slot, side,
                    attacker_slot, move->id, 0, 0);
            }
            return POKEMON_OK;
        }
        if (primary->phase != POKEMON_EFFECT_PHASE_PRIMARY) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        size_t effect_target_side = primary->target == POKEMON_EFFECT_TARGET_USER ?
            side : resolved_targets.values[0].side;
        size_t effect_target_slot = primary->target == POKEMON_EFFECT_TARGET_USER ?
            attacker_slot : resolved_targets.values[0].slot;
        uint8_t primary_effect_succeeded = 1;
        uint8_t primary_status_immune = 0;
        switch (primary->kind) {
        case POKEMON_EFFECT_SET_STATUS: {
            PokemonMutable *effect_target =
                &battle->sides[effect_target_side].state[effect_target_slot];
            PokemonStatus before_status = effect_target->status.kind;
            uint8_t applied = 0;
            size_t event_count_before_status = battle->event_count;
            result = pokemon_set_status(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)effect_target_side, (uint8_t)effect_target_slot},
                (PokemonStatus)primary->argument,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
                    attacker_slot},
                (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
                1, &applied);
            if (result == POKEMON_OK) result = trace_effect(
                battle, primary,
                applied ? POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED,
                move->id, side, attacker_slot,
                effect_target_side, effect_target_slot, before_status,
                effect_target->status.kind);
            if (result == POKEMON_OK && !applied) {
                primary_effect_succeeded = 0;
                for (size_t event = event_count_before_status;
                     event < battle->event_count; event++) {
                    primary_status_immune |=
                        battle->events[event].kind == POKEMON_EVENT_IMMUNE;
                }
                /* trySetStatus asks setStatus for the existing status when a
                 * target is already afflicted. Showdown marks the move log
                 * "[still]" only when that existing status differs from the
                 * move's requested status; repeating Toxic on a toxic target
                 * retains the target, and event/ability rejection does too. */
                if (!primary_status_immune &&
                    before_status != POKEMON_STATUS_NONE &&
                    before_status != (PokemonStatus)primary->argument) {
                    battle->events[move_event_index].target_side = UINT8_MAX;
                }
            }
            break;
        }
        case POKEMON_EFFECT_ADD_VOLATILE: {
            uint8_t installed = 0;
            result = install_condition_volatile(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)effect_target_side,
                    (uint8_t)effect_target_slot},
                invocation->user,
                active_source_effect(battle, move->id),
                (PokemonVolatileKind)primary->argument,
                POKEMON_CONDITION_REASON_MOVE, &installed);
            if (result != POKEMON_OK) break;
            if (installed == CONDITION_INSTALL_FAILED ||
                installed == CONDITION_INSTALL_IMMUNE ||
                installed == CONDITION_INSTALL_START_REJECTED) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
            }
            break;
        }
        case POKEMON_EFFECT_ADD_SOURCE_BOUND_VOLATILE: {
            if (action->resolved_target != POKEMON_RESOLVED_TARGET_FOE ||
                primary->target != POKEMON_EFFECT_TARGET_USER) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint8_t installed = CONDITION_INSTALL_FAILED;
            result = install_condition_volatile(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
                    attacker_slot},
                resolved_targets.values[0],
                active_source_effect(battle, move->id),
                (PokemonVolatileKind)primary->argument,
                POKEMON_CONDITION_REASON_MOVE, &installed);
            if (result != POKEMON_OK) break;
            if (installed != CONDITION_INSTALL_APPLIED) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
                primary_effect_succeeded = 0;
            }
            break;
        }
        case POKEMON_EFFECT_INSTALL_STALLING_GUARD: {
            PokemonVolatileKind guard_kind =
                (PokemonVolatileKind)primary->argument;
            uint16_t guard_descriptor = battle->generation->condition_descriptor(
                POKEMON_OWNER_VOLATILE, guard_kind);
            const PokemonConditionRule *guard_rule =
                condition_rule_by_descriptor(battle, guard_descriptor);
            const PokemonConditionRule *stall_rule = condition_rule(
                battle, POKEMON_RULE_CONDITION_STALL);
            if (guard_rule == NULL || stall_rule == NULL) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (!stalling_guard_admitted || stalling_guard_index >= 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint8_t guard_duration = 0;
            uint8_t stall_duration = 0;
            if (fixed_condition_duration(guard_rule, &guard_duration) !=
                    POKEMON_OK ||
                fixed_condition_duration(stall_rule, &stall_duration) !=
                    POKEMON_OK) return POKEMON_INVALID_CONFIGURATION;
            int stall = stalling_stall_index;
            uint8_t guard_installed = CONDITION_INSTALL_FAILED;
            result = install_condition_volatile(
                battle,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
                    attacker_slot},
                invocation->user, active_source_effect(battle, move->id),
                guard_kind, POKEMON_CONDITION_REASON_MOVE, &guard_installed);
            if (result != POKEMON_OK) return result;
            if (guard_installed != CONDITION_INSTALL_APPLIED) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
                primary_effect_succeeded = 0;
                break;
            }
            if (stall < 0) {
                uint8_t stall_installed = CONDITION_INSTALL_FAILED;
                result = install_condition_volatile(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
                        attacker_slot},
                    invocation->user, active_source_effect(battle, move->id),
                    POKEMON_VOLATILE_STALL, POKEMON_CONDITION_REASON_MOVE,
                    &stall_installed);
                if (result != POKEMON_OK) return result;
                if (stall_installed != CONDITION_INSTALL_APPLIED) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                stall = volatile_index(attacker_state, POKEMON_VOLATILE_STALL);
                if (stall < 0 || battle->condition_trace_count == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                attacker_state->volatiles[stall].counter =
                    battle->generation->stall.initial_denominator;
                PokemonConditionTrace *trace = &battle->condition_traces[
                    battle->condition_trace_count - 1];
                trace->value_kind = POKEMON_CONDITION_VALUE_COUNTER;
                trace->after_value = battle->generation->stall.initial_denominator;
                trace->has_counter_after = 1;
                trace->counter_after =
                    battle->generation->stall.initial_denominator;
                trace->has_duration_after = 1;
                trace->duration_after = stall_duration;
            } else {
                uint8_t before = attacker_state->volatiles[stall].counter;
                uint16_t advanced = (uint16_t)before *
                    battle->generation->stall.multiplier;
                attacker_state->volatiles[stall].counter =
                    advanced < battle->generation->stall.denominator_cap ?
                        (uint8_t)advanced :
                        battle->generation->stall.denominator_cap;
                uint8_t duration_before =
                    attacker_state->volatiles[stall].duration;
                attacker_state->volatiles[stall].duration = stall_duration;
                result = trace_condition(
                    battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                    POKEMON_CONDITION_UPDATE, POKEMON_CONDITION_REASON_MOVE,
                    POKEMON_CONDITION_VALUE_COUNTER,
                    side, attacker_slot, POKEMON_VOLATILE_STALL, before,
                    attacker_state->volatiles[stall].counter
                );
                if (result == POKEMON_OK) {
                    PokemonConditionTrace *trace = &battle->condition_traces[
                        battle->condition_trace_count - 1];
                    trace->has_duration_before = 1;
                    trace->has_duration_after = 1;
                    trace->duration_before = duration_before;
                    trace->duration_after = stall_duration;
                }
            }
            break;
        }
        case POKEMON_EFFECT_ADD_SIDE_CONDITION: {
            uint8_t installed = 0;
            result = install_side_condition(
                battle, effect_target_side,
                (PokemonSideConditionKind)primary->argument,
                invocation->user, active_source_effect(battle, move->id),
                POKEMON_CONDITION_REASON_MOVE, &installed);
            if (result == POKEMON_OK && installed != CONDITION_INSTALL_APPLIED) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
            }
            break;
        }
        case POKEMON_EFFECT_ADD_WEATHER: {
            PokemonWeatherKind requested = (PokemonWeatherKind)primary->argument;
            if (requested == POKEMON_WEATHER_NONE ||
                battle->field.weather.kind == requested) break;
            const PokemonConditionRule *weather_rule = condition_rule(
                battle, weather_rule_kind(requested));
            assert(weather_rule != NULL);
            uint8_t duration = 0;
            if (fixed_condition_duration(weather_rule, &duration) != POKEMON_OK) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint16_t next_generation =
                (uint16_t)(battle->field.weather.state_generation + 1u);
            if (next_generation == 0) next_generation = 1;
            battle->field.weather = (PokemonWeatherState){
                .kind = requested,
                .descriptor_id = weather_rule->descriptor_id,
                .duration = duration,
                .source_side = (uint8_t)side, .source_slot = attacker_slot
            };
            battle->field.weather.state_generation = next_generation;
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_FIELD, POKEMON_CONDITION_ADD,
                POKEMON_CONDITION_REASON_MOVE,
                POKEMON_CONDITION_VALUE_DURATION, side, attacker_slot,
                primary->argument, 0, duration
            );
            if (result == POKEMON_OK) {
                result = run_weather_change_each_event(battle);
            }
            break;
        }
        case POKEMON_EFFECT_FORCE_SWITCH:
        {
            uint8_t eligible[POKEMON_TEAM_CAPACITY];
            uint8_t can_switch = attacker_state->hp != 0 &&
                defender_state->hp != 0 && living_inactive_slots(
                    battle, (uint8_t)effect_target_side, eligible) != 0;
            result = trace_effect(
                battle, primary,
                can_switch ? POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED,
                move->id, side, attacker_slot,
                effect_target_side, effect_target_slot, 0, can_switch);
            if (!can_switch) {
                battle->events[move_event_index].target_side = UINT8_MAX;
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_BLOCK,
                    .side = (uint8_t)effect_target_side,
                    .target_side = (uint8_t)side,
                    .slot = (uint8_t)effect_target_slot,
                    .species_id = battle->sides[effect_target_side]
                        .sets[effect_target_slot].species_id,
                    .move_id = move->id,
                });
                primary_effect_succeeded = 0;
            }
            break;
        }
        case POKEMON_EFFECT_BOOST:
        {
            const PokemonEffectOp *boost_ops[POKEMON_STAT_COUNT];
            size_t boost_count = 0;
            size_t next_effect = 0;
            if (move->effect_count > POKEMON_EFFECT_TRACE_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            for (size_t i = 0; i < move->effect_count; i++) {
                const PokemonEffectOp *op = move_effect(battle, move, i);
                if (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                    op->target != primary->target ||
                    op->chance != primary->chance) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (op->kind != POKEMON_EFFECT_BOOST) {
                    next_effect = i;
                    break;
                }
                if (boost_count == POKEMON_STAT_COUNT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                boost_ops[boost_count++] = op;
                next_effect = i + 1;
            }
            result = apply_boost_effects(
                battle, boost_ops, boost_count, move->id, side, attacker_slot,
                effect_target_side, effect_target_slot);
            if (result != POKEMON_OK) break;
            for (size_t i = next_effect; i < move->effect_count; i++) {
                const PokemonEffectOp *op = move_effect(battle, move, i);
                if (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                    op->target != primary->target ||
                    op->chance != primary->chance ||
                    op->kind != POKEMON_EFFECT_ADD_VOLATILE ||
                    (PokemonVolatileKind)op->argument ==
                        POKEMON_VOLATILE_PROTECT) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                uint8_t installed = 0;
                result = install_condition_volatile(
                    battle,
                    (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                        (uint8_t)effect_target_side,
                        (uint8_t)effect_target_slot},
                    invocation->user,
                    active_source_effect(battle, move->id),
                    (PokemonVolatileKind)op->argument,
                    POKEMON_CONDITION_REASON_MOVE, &installed);
                if (result != POKEMON_OK) break;
                if (installed == CONDITION_INSTALL_FAILED ||
                    installed == CONDITION_INSTALL_START_REJECTED) {
                    battle->events[battle->event_count - 1].target_side =
                        UINT8_MAX;
                }
            }
            break;
        }
        case POKEMON_EFFECT_CREATE_SUBSTITUTE:
        {
            uint8_t denominator = battle->generation->substitute_cost_denominator;
            uint8_t admitted = 0;
            result = substitute_creation_is_admitted(
                battle, attacker, attacker_state, &admitted);
            if (result != POKEMON_OK) break;
            if (!admitted) break;
            uint16_t max_hp = attacker->stats[0];
            uint16_t cost = (uint16_t)(max_hp / denominator);
            PokemonEntityRef substitute_target = {
                POKEMON_ENTITY_POKEMON, (uint8_t)side, attacker_slot};
            PokemonSourceEffectRef substitute_effect =
                active_source_effect(battle, move->id);
            PokemonEventFrame admission;
            result = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_IMMUNITY,
                .source = invocation->user, .target_side = (uint8_t)side,
                .target_slot = attacker_slot, .source_effect = substitute_effect,
                .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
                .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                .context.volatile_condition = {
                    .kind = POKEMON_VOLATILE_SUBSTITUTE},
            }, &admission);
            if (result != POKEMON_OK) break;
            if (admission.cancellation == POKEMON_EVENT_CANCEL_NONE &&
                admission.relay.value.boolean) {
                result = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE,
                    .source = invocation->user, .target_side = (uint8_t)side,
                    .target_slot = attacker_slot,
                    .source_effect = substitute_effect,
                    .relay = {.kind = POKEMON_RELAY_BOOLEAN,
                        .value.boolean = 1},
                    .context_kind = POKEMON_EVENT_CONTEXT_VOLATILE,
                    .context.volatile_condition = {
                        .kind = POKEMON_VOLATILE_SUBSTITUTE},
                }, &admission);
                if (result != POKEMON_OK) break;
            }
            if (admission.cancellation != POKEMON_EVENT_CANCEL_NONE ||
                !admission.relay.value.boolean) {
                break;
            }
            if (attacker_state->volatile_count == POKEMON_VOLATILE_CAPACITY ||
                battle->condition_trace_count ==
                    POKEMON_CONDITION_TRACE_CAPACITY ||
                battle->next_holder_effect_order == UINT16_MAX) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            int trapped = volatile_index(
                attacker_state, POKEMON_VOLATILE_PARTIALLY_TRAPPED);
            if (trapped >= 0) remove_volatile_at(attacker_state, (size_t)trapped);
            attacker_state->hp = (uint16_t)(attacker_state->hp - cost);
            append_event(battle, (PokemonEvent){
                .kind = POKEMON_EVENT_DAMAGE, .side = (uint8_t)side,
                .slot = attacker_slot, .species_id = attacker->species_id,
                .move_id = move->id, .amount = cost, .hp = attacker_state->hp,
            });
            attacker_state->volatiles[attacker_state->volatile_count++] =
                (PokemonVolatileState){
                    .kind = POKEMON_VOLATILE_SUBSTITUTE,
                    .descriptor_id = battle->generation->condition_descriptor(
                        POKEMON_OWNER_VOLATILE, POKEMON_VOLATILE_SUBSTITUTE),
                    .state_generation = 1,
                    .effect_order = ++battle->next_holder_effect_order,
                    .source = substitute_target,
                    .source_effect = substitute_effect,
                    .payload.substitute.hp = cost,
                };
            result = trace_condition(
                battle, POKEMON_CONDITION_SCOPE_VOLATILE,
                POKEMON_CONDITION_ADD, POKEMON_CONDITION_REASON_MOVE,
                POKEMON_CONDITION_VALUE_COUNTER, side, attacker_slot,
                POKEMON_VOLATILE_SUBSTITUTE, 0, cost);
            break;
        }
        case POKEMON_EFFECT_RECYCLE_ITEM:
            if (attacker_state->item_id != 0 ||
                attacker_state->last_item_id == 0) break;
            attacker_state->item_id = attacker_state->last_item_id;
            attacker_state->last_item_id = 0;
            attacker_state->pending_staleness = POKEMON_STALENESS_INTERNAL;
            attacker_state->item_generation++;
            attacker_state->item_effect_order =
                ++battle->next_holder_effect_order;
            result = dispatch_owner_lifecycle(
                battle, POKEMON_HANDLER_EVENT_START,
                (PokemonOwnerRef){POKEMON_OWNER_ITEM, (uint8_t)side,
                    attacker_slot, attacker_state->item_id,
                    attacker_state->item_generation});
            break;
        case POKEMON_EFFECT_SWAP_ITEMS:
        {
            uint8_t applied = 0;
            result = swap_held_items(
                battle, side, attacker_slot,
                effect_target_side, effect_target_slot, &applied);
            if (result == POKEMON_OK) result = trace_effect(
                battle, primary,
                applied ? POKEMON_EFFECT_APPLIED : POKEMON_EFFECT_FAILED,
                move->id, side, attacker_slot,
                effect_target_side, effect_target_slot, 0, 0);
            if (!applied) battle->events[move_event_index].target_side = UINT8_MAX;
            break;
        }
        case POKEMON_EFFECT_ADD_TIMED_VOLATILE:
        {
            PokemonVolatileKind kind = (PokemonVolatileKind)primary->argument;
            PokemonEntityRef effect_target = {
                POKEMON_ENTITY_POKEMON, (uint8_t)effect_target_side,
                (uint8_t)effect_target_slot};
            uint8_t installed = 0;
            result = install_condition_volatile(
                battle, effect_target, invocation->user,
                active_source_effect(battle, move->id), kind,
                POKEMON_CONDITION_REASON_MOVE, &installed);
            if (result != POKEMON_OK) break;
            if (!installed) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
            }
            break;
        }
        case POKEMON_EFFECT_CALL_LAST_ATTACK_MOVE:
        {
            const PokemonAttackRecord *record =
                &attacker_state->last_attacked_by;
            const PokemonMoveData *called = record->present ?
                find_move(battle, record->move_id) : NULL;
            const PokemonMutable *recorded_source =
                record->present && record->source.kind == POKEMON_ENTITY_POKEMON &&
                record->source.side < POKEMON_SIDES &&
                record->source.slot < battle->team_sizes[record->source.side] ?
                &battle->sides[record->source.side].state[record->source.slot] : NULL;
            if (called == NULL || !called->mirror_eligible ||
                recorded_source == NULL || recorded_source->last_move_id == 0 ||
                recorded_source->hp == 0 ||
                battle->sides[record->source.side].active != record->source.slot ||
                !pokemon_knows_move(battle, record->source, record->move_id)) {
                battle->events[battle->event_count - 1].target_side = UINT8_MAX;
                break;
            }
            result = invoke_move_inner(battle, (PokemonMoveInvocation){
                .entry = POKEMON_MOVE_ENTRY_CALLED,
                .move_id = called->id,
                .user = {POKEMON_ENTITY_POKEMON, (uint8_t)side, attacker_slot},
                .target_request = {POKEMON_TARGET_REQUEST_RESOLVE,
                    {POKEMON_ENTITY_NONE, 0, 0}},
                .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
                .inherited_priority = move->priority,
                .selected_slot = UINT8_MAX,
            });
            break;
        }
        case POKEMON_EFFECT_HEAL_FRACTION:
        case POKEMON_EFFECT_HEAL_WEATHER_FRACTION:
            result = apply_fraction_heal(
                battle, primary, move->id, side, attacker_slot,
                effect_target_side, effect_target_slot);
            if (primary->kind == POKEMON_EFFECT_HEAL_FRACTION &&
                result == POKEMON_OK &&
                battle->effect_traces[battle->effect_trace_count - 1].result ==
                    POKEMON_EFFECT_FAILED) {
                primary_effect_succeeded = 0;
                battle->events[battle->event_count - 1].target_side =
                    UINT8_MAX;
            }
            break;
        default:
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (result != POKEMON_OK) return result;
        /* A failed primary move effect terminates runMoveEffects before the
         * generic holder Hit event. Keep that outcome explicit instead of
         * inferring it from protocol-event decoration. */
        if (!primary_effect_succeeded) {
            /* Failed phazing is still a targeted attack in Showdown's
             * `gotAttacked` bookkeeping, despite producing no numeric
             * damage and skipping the holder Hit event. */
            if ((primary->kind == POKEMON_EFFECT_FORCE_SWITCH ||
                 primary->kind == POKEMON_EFFECT_SET_STATUS) &&
                action->resolved_target == POKEMON_RESOLVED_TARGET_FOE) {
                record_attack(battle, target_side, defender_slot, side,
                    attacker_slot, move->id, 0, 0);
            }
            return POKEMON_OK;
        }
        active->move_succeeded = 1;
        for (size_t i = primary->kind == POKEMON_EFFECT_BOOST ?
                move->effect_count : 1; i < move->effect_count; i++) {
            const PokemonEffectOp *op = move_effect(battle, move, i);
            if (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                op->kind != POKEMON_EFFECT_BOOST) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            size_t op_target_side = op->target == POKEMON_EFFECT_TARGET_USER ?
                side : target_side;
            const PokemonEffectOp *single[] = {op};
            result = apply_boost_effects(
                battle, single, 1, move->id, side, attacker_slot,
                op_target_side, battle->sides[op_target_side].active);
            if (result != POKEMON_OK) return result;
        }
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ||
            action->resolved_target == POKEMON_RESOLVED_TARGET_USER) {
            /* Only Pokemon-targeted moves conclude their primary effect with
             * the generic holder Hit event. Side and field effects dispatch
             * their own lifecycle callbacks in Showdown. */
            size_t hit_side = action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                target_side : side;
            uint8_t hit_slot = action->resolved_target == POKEMON_RESOLVED_TARGET_FOE ?
                defender_slot : attacker_slot;
            result = run_move_hit_event(
                battle, move, side, attacker_slot, hit_side, hit_slot,
                NULL, NULL);
            if (result != POKEMON_OK) return result;
        }
        if (primary->kind == POKEMON_EFFECT_FORCE_SWITCH) {
            uint8_t force_switch_succeeded = 0;
            result = admit_force_switch_effect(
                battle, move, invocation->user,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
                    (uint8_t)target_side, defender_slot},
                &force_switch_succeeded);
            if (result != POKEMON_OK) return result;
            if (!force_switch_succeeded) active->move_succeeded = 0;
        }
        if (action->resolved_target == POKEMON_RESOLVED_TARGET_FOE) {
            record_attack(battle, target_side, defender_slot, side,
                attacker_slot, move->id, 0, 0);
        }
        return result;
    }

    if (move->multihit_min != 0) {
        uint8_t requested_hits = 0;
        uint8_t completed_hits = 0;
        uint16_t total_damage = 0;
        uint16_t last_hit_damage = 0;
        uint8_t stopped_on_accuracy = 0;
        uint8_t stopped_source_asleep = 0;
        for (uint8_t hit_index = 0;
             hit_index < (requested_hits == 0 ? 1 : requested_hits);
             hit_index++) {
            if (hit_index > 0 && attacker_state->status.kind == POKEMON_STATUS_SLEEP &&
                !move->sleep_usable) {
                stopped_source_asleep = 1;
                break;
            }
            HitResult hit;
            int result = resolve_hit(
                battle, attacker, defender,
                defender_state, move, side, attacker_slot, target_side, defender_slot,
                hit_index, &requested_hits, &hit
            );
            if (result != POKEMON_OK) return result;
            if (hit.kind == HIT_MISSED) {
                if (hit_index > 0) {
                    stopped_on_accuracy = 1;
                    break;
                }
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_MISS, .side = (uint8_t)side,
                    .target_side = (uint8_t)target_side,
                    .species_id = attacker->species_id, .move_id = move->id,
                });
                return POKEMON_OK;
            }
            if (hit.kind == HIT_IMMUNE) {
                if (!hit.value.immune.emit_event) return POKEMON_OK;
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_IMMUNE, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                    .immunity_cause = hit.value.immune.cause,
                    .handler_id = hit.value.immune.handler_id,
                });
                return POKEMON_OK;
            }
            if (hit.kind == HIT_BLOCKED) {
                append_event(battle, (PokemonEvent){
                    .kind = POKEMON_EVENT_BLOCK, .side = (uint8_t)target_side,
                    .target_side = (uint8_t)side,
                    .species_id = defender->species_id, .move_id = move->id,
                });
                return POKEMON_OK;
            }
            if (hit.kind == HIT_SUBSTITUTE) {
                completed_hits++;
                active->move_succeeded = 1;
                /* Gen 3 moveHit reports numeric zero through a Substitute;
                 * absorbed HP remains in the hit trace, not attackedBy. */
                last_hit_damage = 0;
                result = consume_substitute_hit(
                    battle, move, side, attacker_slot, target_side, defender_slot,
                    completed_hits, requested_hits, &hit.value.substitute);
                if (result != POKEMON_OK) return result;
                result = run_move_hit_event(
                    battle, move, side, attacker_slot, target_side, defender_slot,
                    NULL, NULL);
                if (result != POKEMON_OK) return result;
                result = apply_after_hit_effects(
                    battle, move, side, attacker_slot, target_side, defender_slot, 1
                );
                if (result != POKEMON_OK) return result;
                result = run_update_each_event(battle);
                if (result != POKEMON_OK) return result;
                if (attacker_state->hp == 0) break;
                continue;
            }
            assert(hit.kind == HIT_CONNECTED);
            uint16_t hp_before = defender_state->hp;
            uint16_t damage = hit.value.connected.damage;
            uint16_t calculated_damage = damage;
            result = run_ordinary_move_damage_event(
                battle, move, side, attacker_slot,
                target_side, defender_slot, damage, &damage);
            if (result != POKEMON_OK) return result;
            last_hit_damage = damage;
            defender_state->hp = (uint16_t)(defender_state->hp - damage);
            total_damage = (uint16_t)(total_damage + damage);
            active->actual_damage = total_damage;
            active->move_succeeded = 1;
            completed_hits++;
            PokemonHitTrace completed_trace = {
                .kind = POKEMON_HIT_CONNECTED, .move_id = move->id,
                .source_side = (uint8_t)side, .source_slot = attacker_slot,
                .target_side = (uint8_t)target_side, .target_slot = defender_slot,
                .hit_index = completed_hits, .requested_hits = requested_hits,
                .dynamic_plan = active->party_hit_plan_active,
                .critical = hit.value.connected.critical,
                .damage_roll = hit.value.connected.damage_roll,
                .damage = damage, .calculated_damage = calculated_damage,
                .hp_before = hp_before,
                .hp_after = defender_state->hp,
                .source_hp_after = attacker_state->hp,
            };
            append_event(battle, (PokemonEvent){
                .kind = POKEMON_EVENT_DAMAGE, .side = (uint8_t)target_side,
                .target_side = (uint8_t)side, .species_id = defender->species_id,
                .move_id = move->id, .amount = damage, .hp = defender_state->hp,
            });
            result = apply_damage_relative_effects(
                battle, move, POKEMON_EFFECT_PHASE_AFTER_DAMAGE,
                side, attacker_slot, target_side, defender_slot, damage
            );
            if (result != POKEMON_OK) return result;
            result = run_move_hit_event(
                battle, move, side, attacker_slot, target_side, defender_slot,
                NULL, NULL);
            if (result != POKEMON_OK) return result;
            result = apply_after_hit_effects(
                battle, move, side, attacker_slot, target_side, defender_slot, 0
            );
            if (result != POKEMON_OK) return result;
            result = run_damaging_hit_event(
                battle, move, damage, side, attacker_slot,
                target_side, defender_slot);
            if (result != POKEMON_OK) return result;
            if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
                return POKEMON_CAPACITY_EXCEEDED;
            }
            completed_trace.semantic_sequence = next_semantic_sequence(battle);
            battle->hit_traces[battle->hit_trace_count++] = completed_trace;
            result = run_update_each_event(battle);
            if (result != POKEMON_OK) return result;
            if (move->thaws_target &&
                defender_state->status.kind == POKEMON_STATUS_FREEZE) {
                result = clear_major_status(
                    battle, target_side, defender_slot,
                    POKEMON_CONDITION_REASON_HANDLER);
                if (result != POKEMON_OK) return result;
            }
            result = resolve_move_faint(battle, target_side, defender_slot,
                (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
                    attacker_slot},
                active_source_effect(battle, move->id));
            if (result != POKEMON_OK) return result;
            if (defender_state->hp == 0 || attacker_state->hp == 0) break;
        }
        /* Gen 3 runs one Update after every moveHit above, then another after
         * the complete multi-hit sequence before AfterMoveSecondary. */
        int result = run_update_each_event(battle);
        if (result != POKEMON_OK) return result;
        result = apply_damage_relative_effects(
            battle, move, POKEMON_EFFECT_PHASE_AFTER_MOVE,
            side, attacker_slot, target_side, defender_slot, total_damage
        );
        if (result != POKEMON_OK) return result;
        result = resolve_move_faint(battle, side, attacker_slot,
            (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
            (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_NONE, 0});
        if (result != POKEMON_OK) return result;
        if (battle->hit_trace_count == POKEMON_HIT_TRACE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        PokemonHitStopReason stop_reason = POKEMON_HIT_STOP_COMPLETED;
        if (completed_hits < requested_hits && defender_state->hp == 0) {
            stop_reason = POKEMON_HIT_STOP_TARGET_FAINTED;
        } else if (completed_hits < requested_hits && attacker_state->hp == 0) {
            stop_reason = POKEMON_HIT_STOP_SOURCE_FAINTED;
        } else if (stopped_on_accuracy) {
            stop_reason = POKEMON_HIT_STOP_ACCURACY;
        } else if (stopped_source_asleep) {
            stop_reason = POKEMON_HIT_STOP_SOURCE_ASLEEP;
        }
        battle->hit_traces[battle->hit_trace_count++] = (PokemonHitTrace){
            .semantic_sequence = next_semantic_sequence(battle),
            .kind = POKEMON_HIT_RESULT, .move_id = move->id,
            .source_side = (uint8_t)side, .source_slot = attacker_slot,
            .target_side = (uint8_t)target_side, .target_slot = defender_slot,
            .requested_hits = requested_hits, .actual_hits = completed_hits,
            .dynamic_plan = active->party_hit_plan_active,
            .total_damage = total_damage, .stop_reason = stop_reason,
            .hp_after = defender_state->hp,
            .source_hp_after = attacker_state->hp,
        };
        record_attack(battle, target_side, defender_slot, side, attacker_slot,
            move->id, last_hit_damage, 1);
        return completed_hits == 0 ? POKEMON_INVALID_CONFIGURATION : POKEMON_OK;
    }

    HitResult hit;
    uint8_t requested_hits = 1;
    int result = resolve_hit(
        battle, attacker, defender,
        defender_state, move, side, attacker_slot, target_side, defender_slot,
        0, &requested_hits, &hit
    );
    if (result != POKEMON_OK) return result;
    if (hit.kind == HIT_MISSED) {
        active->attempt_outcome = POKEMON_MOVE_ATTEMPT_FAILED_AFTER_TARGET;
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_MISS,
            .side = (uint8_t)side,
            .target_side = (uint8_t)target_side,
            .species_id = attacker->species_id,
            .move_id = move->id,
        });
        return POKEMON_OK;
    }
    if (hit.kind == HIT_IMMUNE) {
        active->attempt_outcome = POKEMON_MOVE_ATTEMPT_FAILED_AFTER_TARGET;
        if (!hit.value.immune.emit_event) return POKEMON_OK;
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_IMMUNE,
            .side = (uint8_t)target_side,
            .target_side = (uint8_t)side,
            .species_id = defender->species_id,
            .move_id = move->id,
            .immunity_cause = hit.value.immune.cause,
            .handler_id = hit.value.immune.handler_id,
        });
        return POKEMON_OK;
    }
    if (hit.kind == HIT_BLOCKED) {
        active->attempt_outcome = POKEMON_MOVE_ATTEMPT_FAILED_AFTER_TARGET;
        if (active->party_hit_plan_active && active->party_hit_count == 0) {
            battle->events[move_event_index].target_side = UINT8_MAX;
            record_attack(battle, target_side, defender_slot, side,
                attacker_slot, move->id, 0, 0);
            return POKEMON_OK;
        }
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_BLOCK, .side = (uint8_t)target_side,
            .target_side = (uint8_t)side, .species_id = defender->species_id,
            .move_id = move->id,
        });
        return POKEMON_OK;
    }
    if (hit.kind == HIT_SUBSTITUTE) {
        active->move_succeeded = 1;
        result = consume_substitute_hit(
            battle, move, side, attacker_slot, target_side, defender_slot,
            1, 1, &hit.value.substitute);
        if (result != POKEMON_OK) return result;
        result = apply_hit_effect_stage(
            battle, move, side, attacker_slot, target_side, defender_slot, 1,
            POKEMON_HIT_EFFECT_STAGE_PRIMARY);
        if (result != POKEMON_OK) return result;
        /* Showdown replaces an intercepted target with null before
         * runMoveEffects. Target-scoped declarative effects and the move's
         * onHit callback therefore do not run; self drops and later
         * source-owned stages remain independent below. */
        result = apply_hit_effect_stage(
            battle, move, side, attacker_slot, target_side, defender_slot, 1,
            POKEMON_HIT_EFFECT_STAGE_AFTER_CALLBACK);
        if (result != POKEMON_OK) return result;
        /* Showdown replaces the target with null when Substitute intercepts
         * a hit, so target-owned Hit handlers are not discovered. */
        result = apply_hit_effect_stage(
            battle, move, side, attacker_slot, target_side, defender_slot, 1,
            POKEMON_HIT_EFFECT_STAGE_SECONDARY);
        if (result != POKEMON_OK) return result;
        result = run_update_each_event(battle);
        if (result != POKEMON_OK) return result;
        record_attack(battle, target_side, defender_slot, side, attacker_slot,
            move->id, 0, 1);
        return POKEMON_OK;
    }

    if (hit.kind == HIT_HEALED) {
        active->move_succeeded = hit.value.healed.succeeded;
        if (!hit.value.healed.succeeded) {
            battle->events[battle->event_count - 1].target_side = UINT8_MAX;
            record_attack(battle, target_side, defender_slot, side,
                attacker_slot, move->id, 0, 0);
            return POKEMON_OK;
        }
        uint8_t callback_succeeded = 0;
        result = run_move_hit_callback(
            battle, move, invocation->user, target_side, defender_slot,
            active_source_effect(battle, move->id), &callback_succeeded, NULL);
        if (result != POKEMON_OK) return result;
        result = run_move_global_hit_event(
            battle, move, side, attacker_slot, target_side, defender_slot);
        if (result != POKEMON_OK) return result;
        record_attack(battle, target_side, defender_slot, side, attacker_slot,
            move->id, 0, 0);
        return POKEMON_OK;
    }

    assert(hit.kind == HIT_CONNECTED);
    uint16_t damage = hit.value.connected.damage;
    result = run_ordinary_move_damage_event(
        battle, move, side, attacker_slot,
        target_side, defender_slot, damage, &damage);
    if (result != POKEMON_OK) return result;
    defender_state->hp = (uint16_t)(defender_state->hp - damage);
    active->actual_damage = damage;
    active->move_succeeded = 1;
    append_event(battle, (PokemonEvent){
        .kind = POKEMON_EVENT_DAMAGE,
        .side = (uint8_t)target_side,
        .target_side = (uint8_t)side,
        .species_id = defender->species_id,
        .move_id = move->id,
        .amount = damage,
        .hp = defender_state->hp,
    });
    result = apply_damage_relative_effects(
        battle, move, POKEMON_EFFECT_PHASE_AFTER_DAMAGE,
        side, attacker_slot, target_side, defender_slot, damage
    );
    if (result != POKEMON_OK) return result;
    result = apply_hit_effect_stage(
        battle, move, side, attacker_slot, target_side, defender_slot, 0,
        POKEMON_HIT_EFFECT_STAGE_PRIMARY);
    if (result != POKEMON_OK) return result;
    uint8_t callback_succeeded = 0;
    result = run_move_hit_callback(
        battle, move, invocation->user, target_side, defender_slot,
        active_source_effect(battle, move->id), &callback_succeeded, NULL);
    if (result != POKEMON_OK) return result;
    /* Showdown completes the target-facing Hit event before it executes the
     * move's `self` hit effect.  Keep this ordering generic: self volatiles,
     * self drops, and self callbacks all compose with target-owned Hit
     * handlers through the same move pipeline. */
    result = run_move_global_hit_event(
        battle, move, side, attacker_slot, target_side, defender_slot);
    if (result != POKEMON_OK) return result;
    result = apply_hit_effect_stage(
        battle, move, side, attacker_slot, target_side, defender_slot, 0,
        POKEMON_HIT_EFFECT_STAGE_AFTER_CALLBACK);
    if (result != POKEMON_OK) return result;
    result = apply_hit_effect_stage(
        battle, move, side, attacker_slot, target_side, defender_slot, 0,
        POKEMON_HIT_EFFECT_STAGE_SECONDARY);
    if (result != POKEMON_OK) return result;
    result = run_damaging_hit_event(
        battle, move, damage, side, attacker_slot, target_side, defender_slot);
    if (result != POKEMON_OK) return result;
    result = run_update_each_event(battle);
    if (result != POKEMON_OK) return result;
    if (move->thaws_target && defender_state->status.kind == POKEMON_STATUS_FREEZE) {
        result = clear_major_status(
            battle, target_side, defender_slot,
            POKEMON_CONDITION_REASON_HANDLER);
        if (result != POKEMON_OK) return result;
    }
    result = apply_damage_relative_effects(
        battle, move, POKEMON_EFFECT_PHASE_AFTER_MOVE,
        side, attacker_slot, target_side, defender_slot, damage
    );
    if (result != POKEMON_OK) return result;
    result = resolve_move_faint(battle, target_side, defender_slot,
        (PokemonEntityRef){POKEMON_ENTITY_POKEMON, (uint8_t)side,
            attacker_slot},
        active_source_effect(battle, move->id));
    if (result != POKEMON_OK) return result;
    result = resolve_move_faint(battle, side, attacker_slot,
        (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0},
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_NONE, 0});
    if (result != POKEMON_OK) return result;
    record_attack(battle, target_side, defender_slot, side, attacker_slot,
        move->id, damage, 1);
    return POKEMON_OK;
}

static int resolve_invocation_target(
    const PokemonBattle *battle, const PokemonMoveInvocation *invocation,
    const PokemonMoveData *move, PokemonEntityRef *target,
    PokemonResolvedTarget *resolved
) {
    if (invocation->target_request.kind == POKEMON_TARGET_REQUEST_EXPLICIT) {
        *target = invocation->target_request.explicit_target;
        if (target->kind == POKEMON_ENTITY_NONE) {
            *resolved = POKEMON_RESOLVED_TARGET_NONE;
            return POKEMON_OK;
        }
        if (target->kind != POKEMON_ENTITY_POKEMON ||
            target->side >= POKEMON_SIDES ||
            target->slot >= battle->team_sizes[target->side]) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        PokemonTargetRule rule;
        if (!pokemon_resolve_move_target(&battle->format, move->target, &rule)) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        if (rule.resolved == POKEMON_RESOLVED_TARGET_FOE_SIDE &&
            target->side != invocation->user.side) {
            *resolved = POKEMON_RESOLVED_TARGET_FOE_SIDE;
        } else {
            *resolved = target->side == invocation->user.side ?
                POKEMON_RESOLVED_TARGET_USER : POKEMON_RESOLVED_TARGET_FOE;
        }
        return POKEMON_OK;
    }
    if (invocation->target_request.kind != POKEMON_TARGET_REQUEST_RESOLVE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonTargetRule rule;
    if (!pokemon_resolve_move_target(&battle->format, move->target, &rule)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (rule.resolved == POKEMON_RESOLVED_TARGET_NONE) {
        *target = (PokemonEntityRef){POKEMON_ENTITY_NONE, 0, 0};
    } else {
        uint8_t side = (rule.resolved == POKEMON_RESOLVED_TARGET_FOE ||
            rule.resolved == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
            (uint8_t)(1u - invocation->user.side) : invocation->user.side;
        *target = (PokemonEntityRef){POKEMON_ENTITY_POKEMON, side,
            battle->sides[side].active};
    }
    *resolved = rule.resolved;
    return POKEMON_OK;
}

static int invoke_move_inner(
    PokemonBattle *battle, PokemonMoveInvocation invocation
) {
    const PokemonMoveData *move = find_move(battle, invocation.move_id);
    if (move == NULL || invocation.user.kind != POKEMON_ENTITY_POKEMON ||
        invocation.user.side >= POKEMON_SIDES ||
        invocation.user.slot >= battle->team_sizes[invocation.user.side]) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (battle->move_frame_depth == POKEMON_MOVE_FRAME_CAPACITY ||
        battle->move_invocation_count == POKEMON_MOVE_INVOCATION_TRACE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    PokemonEntityRef target;
    PokemonResolvedTarget resolved;
    int status = resolve_invocation_target(
        battle, &invocation, move, &target, &resolved);
    if (status != POKEMON_OK) return status;
    invocation.parent_invocation_id = battle->move_frame_depth == 0 ? 0 :
        battle->move_frames[battle->move_frame_depth - 1].invocation.invocation_id;
    invocation.invocation_id = ++battle->next_move_invocation_id;
    PokemonActiveMoveFrame frame = {
        .invocation = invocation,
        .resolved_target = target,
        .target_mode = move->target,
        .flags = move->flags,
        .type = move->type,
        .category = move->category,
        .base_power = move->power,
        .accuracy = move->accuracy,
        .effect_offset = move->effect_offset,
        .effect_count = move->effect_count,
        .multihit_min = move->multihit_min,
        .multihit_max = move->multihit_max,
        .priority = invocation.inherited_priority,
        .result = POKEMON_OK,
    };
    if (invocation.target_switching) {
        if (move->switching_target_always_hit) {
            frame.accuracy = (PokemonAccuracy){POKEMON_ACCURACY_ALWAYS, 0};
        }
        if (move->switching_target_power_multiplier != 0) {
            uint32_t power = (uint32_t)frame.base_power *
                move->switching_target_power_multiplier;
            if (power > UINT16_MAX) return POKEMON_INVALID_CONFIGURATION;
            frame.base_power = (uint16_t)power;
        }
    }
    size_t trace_index = battle->move_invocation_count++;
    battle->move_invocations[trace_index] = (PokemonMoveInvocationTrace){
        .invocation = invocation, .resolved_target = target,
        .result = POKEMON_OK,
    };
    battle->move_frames[battle->move_frame_depth++] = frame;
    battle->sides[invocation.user.side].state[
        invocation.user.slot].last_move_used = (PokemonLastUsedMove){
            .present = 1, .move_id = move->id, .resolved_type = move->type,
        };
    status = execute_move_body(battle, &invocation, resolved);
    PokemonActiveMoveFrame *completed =
        &battle->move_frames[battle->move_frame_depth - 1];
    if (status == POKEMON_OK && completed->move_succeeded) {
        completed->attempt_outcome = POKEMON_MOVE_ATTEMPT_SUCCEEDED;
    }
    if (status == POKEMON_OK && completed->attempt_outcome ==
            POKEMON_MOVE_ATTEMPT_FAILED_AFTER_TARGET &&
        move->failure_policy.kind != POKEMON_MOVE_FAILURE_NONE) {
        PokemonEntityRef failed_target = completed->resolved_target;
        PokemonEventFrame move_fail;
        uint8_t ran_move_fail = 0;
        status = run_move_self_event(
            battle, POKEMON_HANDLER_EVENT_MOVE_FAIL, move, invocation.user,
            failed_target.side, failed_target.slot,
            active_source_effect(battle, move->id),
            (PokemonRelay){.kind = POKEMON_RELAY_UNDEFINED},
            &move_fail, &ran_move_fail);
        if (status == POKEMON_OK && !ran_move_fail) {
            status = POKEMON_INVALID_CONFIGURATION;
        }
        if (status == POKEMON_OK) {
            status = apply_move_failure_policy(
                battle, move, invocation.user, failed_target);
        }
    }
    if (status == POKEMON_OK && completed->move_succeeded &&
        move->self_faint_timing == POKEMON_SELF_FAINT_IF_HIT) {
        PokemonMutable *user = &battle->sides[invocation.user.side].state[
            invocation.user.slot];
        if (user->hp != 0 && !user->fainted) {
            if (battle->faint_count == POKEMON_FAINT_QUEUE_CAPACITY) {
                status = POKEMON_CAPACITY_EXCEEDED;
            } else {
                user->hp = 0;
                status = queue_faint(
                    battle, invocation.user, invocation.user,
                    (PokemonSourceEffectRef){
                        POKEMON_SOURCE_EFFECT_MOVE, move->id});
            }
        }
    }
    uint8_t after_secondary_self_applicable = 0;
    if (status == POKEMON_OK && completed->move_succeeded) {
        status = unsupported_event_applicable(
            battle, POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF,
            invocation.user.side, invocation.user.slot,
            invocation.user.side, invocation.user.slot,
            &after_secondary_self_applicable);
    }
    if (status == POKEMON_OK && completed->move_succeeded &&
        after_secondary_self_applicable) {
        PokemonEntityRef event_source =
            completed->resolved_target.kind == POKEMON_ENTITY_POKEMON ?
                completed->resolved_target : invocation.user;
        PokemonEventFrame after_secondary_self;
        status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF,
            .source = event_source,
            .target_side = invocation.user.side,
            .target_slot = invocation.user.slot,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = move,
                .damage = completed->actual_damage},
            }, &after_secondary_self);
    }
    if (status == POKEMON_OK && completed->move_succeeded &&
        move->self_switch_transfer != POKEMON_SWITCH_TRANSFER_NONE &&
        battle->sides[invocation.user.side].state[invocation.user.slot].hp != 0) {
        uint8_t eligible[POKEMON_TEAM_CAPACITY];
        if (living_inactive_slots(battle, invocation.user.side, eligible) == 0) {
            completed->move_succeeded = 0;
            for (size_t i = battle->event_count; i != 0; i--) {
                PokemonEvent *event = &battle->events[i - 1];
                if (event->kind == POKEMON_EVENT_MOVE &&
                    event->side == invocation.user.side &&
                    event->move_id == move->id) {
                    event->target_side = UINT8_MAX;
                    break;
                }
            }
        } else {
            if (battle->pending_move_switch.active) {
                status = POKEMON_INVALID_CONFIGURATION;
            } else {
                battle->pending_move_switch = (PokemonPendingMoveSwitch){
                    .active = 1,
                    .side = invocation.user.side,
                    .outgoing_slot = invocation.user.slot,
                    .source_move_id = move->id,
                    .transfer = move->self_switch_transfer,
                    .skip_before_switch_out =
                        move->self_switch_skip_before_switch_out,
                };
            }
        }
    }
    battle->move_frames[battle->move_frame_depth - 1].result = status;
    battle->move_invocations[trace_index].result = status;
    battle->move_frame_depth--;
    return status;
}

/* One phase boundary owns every installed condition which can prevent a
 * selected move. Generated status/volatile/ability/item handlers enter
 * through one ordered event. */
static int dispatch_before_move_phase(
    PokemonBattle *battle, const PokemonAction *action,
    const PokemonMoveData *move, PokemonEntityRef target, uint8_t *may_move
) {
    PokemonSide *side = &battle->sides[action->side];
    uint8_t user_slot = side->active;
    *may_move = 1;
    const PokemonEventSpec *spec = event_spec(
        battle, POKEMON_HANDLER_EVENT_BEFORE_MOVE);
    if (spec == NULL || !spec->supported) return POKEMON_OK;
    PokemonEventFrame frame;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_BEFORE_MOVE,
        .source = target,
        .target_side = action->side,
        .target_slot = user_slot,
        .source_effect = active_source_effect(battle, move->id),
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
    }, &frame);
    if (result != POKEMON_OK) return result;
    *may_move = frame.cancellation == POKEMON_EVENT_CANCEL_NONE &&
        frame.relay.value.boolean;
    if (!*may_move) return POKEMON_OK;
    return POKEMON_OK;
}

static int execute_before_turn_move(
    PokemonBattle *battle, const PokemonAction *action
) {
    if (action->side >= POKEMON_SIDES ||
        action->slot >= POKEMON_MOVE_CAPACITY ||
        action->selected_move_id == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    size_t active = battle->sides[action->side].active;
    PokemonMutable *state = &battle->sides[action->side].state[active];
    if (state->hp == 0 || state->fainted) return POKEMON_OK;
    const PokemonMoveData *move = find_move(battle, action->selected_move_id);
    if (move == NULL || move->pre_turn_condition_descriptor == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    const PokemonConditionIdentity *identity = pokemon_condition_identity(
        battle->data, move->pre_turn_condition_descriptor);
    if (identity == NULL || identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
        identity->semantic_kind == POKEMON_VOLATILE_NONE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonPreTurnTarget pre_turn_target = move->pre_turn_target == 0 ?
        POKEMON_PRE_TURN_TARGET_USER :
        (PokemonPreTurnTarget)move->pre_turn_target;
    if (pre_turn_target < POKEMON_PRE_TURN_TARGET_USER ||
        pre_turn_target > POKEMON_PRE_TURN_TARGET_MOVE_TARGET) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if ((move->pre_turn_blocked_status_mask &
         (UINT16_C(1) << state->status.kind)) != 0) return POKEMON_OK;
    PokemonEntityRef user = {
        POKEMON_ENTITY_POKEMON, action->side, (uint8_t)active};
    PokemonEntityRef install_target = user;
    if (pre_turn_target == POKEMON_PRE_TURN_TARGET_MOVE_TARGET) {
        PokemonTargetRule target_rule;
        if (!pokemon_resolve_move_target(
                &battle->format, move->target, &target_rule) ||
            target_rule.resolved != POKEMON_RESOLVED_TARGET_FOE) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        uint8_t target_side = (uint8_t)(1u - action->side);
        install_target = (PokemonEntityRef){POKEMON_ENTITY_POKEMON,
            target_side, battle->sides[target_side].active};
    }
    uint8_t installed = CONDITION_INSTALL_FAILED;
    return install_descriptor_volatile(
        battle, install_target, user,
        (PokemonSourceEffectRef){POKEMON_SOURCE_EFFECT_MOVE, move->id},
        (PokemonVolatileKind)identity->semantic_kind,
        move->pre_turn_condition_descriptor,
        POKEMON_CONDITION_REASON_MOVE, &installed);
}

static int execute_switch(PokemonBattle *battle, const PokemonAction *action);

static int run_move_pre_use_program(
    const PokemonBattle *battle, uint16_t move_id,
    size_t side, size_t slot, uint8_t *may_continue
) {
    *may_continue = 1;
    for (size_t i = 0; i < battle->data->move_pre_use_program_count; i++) {
        const PokemonMovePreUseProgram *program =
            &battle->data->move_pre_use_programs[i];
        if (program->move_id != move_id) continue;
        switch (program->operation) {
        case POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND: {
            const PokemonMutable *holder = &battle->sides[side].state[slot];
            for (size_t volatile_index = 0;
                 volatile_index < holder->volatile_count; volatile_index++) {
                if (holder->volatiles[volatile_index].kind ==
                        program->volatile_kind) {
                    *may_continue = 0;
                    return POKEMON_OK;
                }
            }
            break;
        }
        default:
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    return POKEMON_OK;
}

/* Complete an already-admitted displacement after the move's AfterMove
 * boundary. The incoming member is selected uniformly, the displaced
 * Pokemon's stale queued work is removed, and ordinary switch/runSwitch
 * lifecycle code owns all state cleanup and entry handlers. */
static int execute_drag_transaction(PokemonBattle *battle) {
    PokemonPendingDrag pending = battle->pending_drag;
    memset(&battle->pending_drag, 0, sizeof(battle->pending_drag));
    if (!pending.active || pending.target.side >= POKEMON_SIDES ||
        pending.target.slot != battle->sides[pending.target.side].active ||
        battle->sides[pending.target.side].state[pending.target.slot].hp == 0) {
        return POKEMON_OK;
    }
    uint8_t side = pending.target.side;
    uint8_t eligible[POKEMON_TEAM_CAPACITY];
    uint8_t count = living_inactive_slots(battle, side, eligible);
    if (count == 0) return POKEMON_OK;
    uint32_t selected = 0;
    int result = draw_below(
        battle, POKEMON_DRAW_FORCED_SWITCH_TARGET, count, &selected);
    if (result != POKEMON_OK) return result;
    PokemonEventFrame drag_out;
    result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DRAG_OUT,
        .source = {POKEMON_ENTITY_NONE, 0, 0},
        .target_side = pending.target.side,
        .target_slot = pending.target.slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_NONE, 0},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
    }, &drag_out);
    if (result != POKEMON_OK) return result;
    if (drag_out.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        drag_out.relay.kind != POKEMON_RELAY_BOOLEAN ||
        !drag_out.relay.value.boolean) return POKEMON_OK;
    PokemonAction action = {
        .kind = POKEMON_ACTION_SWITCH,
        .side = side,
        .slot = eligible[selected],
        .switch_cause = POKEMON_SWITCH_CAUSE_DRAG,
    };
    result = execute_switch(battle, &action);
    if (result != POKEMON_OK) return result;
    /* Native move actions identify a side rather than retaining Showdown's
     * Pokemon object. Remove the displaced Pokemon's queued choice so it
     * cannot be reinterpreted as an action by the incoming member. */
    cancel_side_actions(&battle->queue, side);
    return enqueue_run_switch(battle, side);
}

/* Execute a normalized selected action after its one-and-only BeforeMove
 * gate. Ordinary actions and switch interception share PP, history, move
 * invocation, AfterMove, and pending-drag ownership here. */
static int execute_selected_move_after_before_move(
    PokemonBattle *battle, const PokemonAction *action,
    const PokemonMoveData *move, PokemonEntityRef target,
    uint8_t target_switching
) {
    PokemonSide *side = &battle->sides[action->side];
    uint8_t user_slot = side->active;
    uint8_t pre_use_allowed = 1;
    int result = run_move_pre_use_program(
        battle, move->id, action->side, user_slot, &pre_use_allowed);
    if (result != POKEMON_OK || !pre_use_allowed) return result;
    PokemonMoveChoiceSlot choice_slots[POKEMON_MOVE_CAPACITY];
    result = build_move_choice_slots(battle, action->side, choice_slots);
    if (result != POKEMON_OK) return result;
    uint8_t executed_slot = action->slot;
    if (action->move_choice_kind == POKEMON_MOVE_CHOICE_FORCED) {
        /* Showdown asks LockMove again at the post-pre-use PP boundary.  The
         * direct pre-use guard above can cancel before this observable query;
         * ordinary two-turn releases reach it and spend no additional PP. */
        uint16_t locked = 0;
        result = query_locked_move(battle, action->side, &locked);
        if (result != POKEMON_OK) return result;
        if (locked != move->id) return POKEMON_INVALID_CONFIGURATION;
    } else if (action->move_choice_kind == POKEMON_MOVE_CHOICE_SELECTED_SLOT) {
        executed_slot = POKEMON_MOVE_CAPACITY;
        for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
            if (choice_slots[slot].move_id == move->id) {
                executed_slot = (uint8_t)slot;
                break;
            }
        }
        if (executed_slot == POKEMON_MOVE_CAPACITY ||
            side->state[user_slot].pp[executed_slot] == 0) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        set_current_pp(battle, action->side, user_slot, executed_slot,
            (uint8_t)(side->state[user_slot].pp[executed_slot] - 1u));
    }
    side->state[user_slot].last_move_id = move->id;
    result = invoke_move_inner(battle, (PokemonMoveInvocation){
        .entry = POKEMON_MOVE_ENTRY_SELECTED,
        .move_id = move->id,
        .user = {POKEMON_ENTITY_POKEMON, action->side, user_slot},
        .target_request = {POKEMON_TARGET_REQUEST_EXPLICIT, target},
        .source_effect = {POKEMON_SOURCE_EFFECT_NONE, 0},
        .has_bounced = 0,
        .inherited_priority = action->priority,
        .selected_slot = executed_slot,
        .owns_pp_deduction = action->move_choice_kind ==
            POKEMON_MOVE_CHOICE_SELECTED_SLOT,
        .target_switching = target_switching,
    });
    if (result != POKEMON_OK) return result;
    assert(battle->move_invocation_count != 0);
    const PokemonMoveInvocationTrace *completed =
        &battle->move_invocations[battle->move_invocation_count - 1];
    const PokemonMoveData *after_move_owner =
        find_move(battle, completed->invocation.move_id);
    if (after_move_owner == NULL) return POKEMON_INVALID_CONFIGURATION;
    /* Showdown's selected runMove retains the outer action target for
     * AfterMove, even when a delegated inner invocation replaces activeMove.
     * The final invocation supplies the move owner only. */
    PokemonEntityRef event_target =
        target.kind == POKEMON_ENTITY_POKEMON ?
            target :
            (PokemonEntityRef){POKEMON_ENTITY_POKEMON, action->side, user_slot};
    uint8_t after_move_applicable = 0;
    for (size_t handler = 0; handler < battle->data->handler_count; handler++) {
        const PokemonHandlerDescriptor *descriptor =
            &battle->data->handlers[handler];
        if (descriptor->event == POKEMON_HANDLER_EVENT_AFTER_MOVE &&
            descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
            descriptor->source_id == after_move_owner->id &&
            descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF) {
            after_move_applicable = 1;
            break;
        }
    }
    if (!after_move_applicable) {
        result = unsupported_event_applicable(
            battle, POKEMON_HANDLER_EVENT_AFTER_MOVE,
            action->side, user_slot, event_target.side, event_target.slot,
            &after_move_applicable);
        if (result != POKEMON_OK) return result;
    }
    if (after_move_applicable) {
        PokemonEventFrame after_move;
        result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_AFTER_MOVE,
            .source = {POKEMON_ENTITY_POKEMON, action->side, user_slot},
            .target_side = event_target.side, .target_slot = event_target.slot,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, after_move_owner->id},
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = after_move_owner},
            .include_move_self = 1,
        }, &after_move);
        if (result != POKEMON_OK) return result;
    }
    return battle->pending_drag.active ?
        execute_drag_transaction(battle) : POKEMON_OK;
}

static int execute_move(PokemonBattle *battle, const PokemonAction *action) {
    PokemonSide *side = &battle->sides[action->side];
    uint8_t user_slot = side->active;
    if (side->state[user_slot].hp == 0) return POKEMON_OK;
    uint16_t locked_id = locked_move_id(battle, action->side);
    if (action->selected_move_id == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    switch (action->move_choice_kind) {
    case POKEMON_MOVE_CHOICE_SELECTED_SLOT:
        if (action->slot >= POKEMON_MOVE_CAPACITY || locked_id != 0 ||
            side->state[user_slot].pp[action->slot] == 0 ||
            action->selected_move_id !=
                side->state[user_slot].move_ids[action->slot]) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        break;
    case POKEMON_MOVE_CHOICE_FORCED:
        if (locked_id == 0 || action->selected_move_id != locked_id) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        break;
    case POKEMON_MOVE_CHOICE_FALLBACK:
        if (locked_id != 0 || action->slot != 0 ||
            action->selected_move_id != battle->generation->fallback_move_id) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        break;
    default:
        return POKEMON_INVALID_CONFIGURATION;
    }
    int result = POKEMON_OK;
    /* Showdown's runMove owns this count before OverrideAction, target
     * resolution, and BeforeMove. Called moves enter below this boundary. */
    if (side->state[user_slot].active_move_actions == UINT32_MAX) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    side->state[user_slot].active_move_actions++;
    PokemonChoiceActionDecision decision = {
        .executed_move_id = action->selected_move_id, .allowed = 1,
    };
    if (has_choice_control_event(
            battle, action->side, POKEMON_HANDLER_EVENT_OVERRIDE_ACTION)) {
        const PokemonMoveData *selected = find_move(
            battle, action->selected_move_id);
        if (selected == NULL) return POKEMON_INVALID_CONFIGURATION;
        PokemonEventFrame override_action;
        result = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_OVERRIDE_ACTION,
            .source = {POKEMON_ENTITY_POKEMON, action->side, user_slot},
            .target_side = action->side, .target_slot = user_slot,
            .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, selected->id},
            .relay = {.kind = POKEMON_RELAY_SELECTOR,
                .value.selector = selected->id},
            .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
            .context.move = {.move = selected},
        }, &override_action);
        if (result != POKEMON_OK) return result;
        decision.executed_move_id = override_action.relay.value.selector;
    }
    const PokemonMoveData *move = find_move(battle, decision.executed_move_id);
    if (move == NULL) return POKEMON_INVALID_CONFIGURATION;
    PokemonTargetRule target_rule;
    if (!pokemon_resolve_move_target(&battle->format, move->target, &target_rule)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonEntityRef target = {POKEMON_ENTITY_NONE, 0, 0};
    if (target_rule.resolved != POKEMON_RESOLVED_TARGET_NONE) {
        uint8_t target_side =
            (target_rule.resolved == POKEMON_RESOLVED_TARGET_FOE ||
             target_rule.resolved == POKEMON_RESOLVED_TARGET_FOE_SIDE) ?
            (uint8_t)(1u - action->side) : action->side;
        target = (PokemonEntityRef){POKEMON_ENTITY_POKEMON, target_side,
            battle->sides[target_side].active};
    }
    uint8_t may_move = 0;
    result = dispatch_before_move_phase(
        battle, action, move, target, &may_move);
    if (result != POKEMON_OK) return result;
    if (!may_move) {
        uint8_t move_aborted_applicable = 0;
        result = unsupported_event_applicable(
            battle, POKEMON_HANDLER_EVENT_MOVE_ABORTED,
            action->side, user_slot, action->side, user_slot,
            &move_aborted_applicable);
        if (result != POKEMON_OK) return result;
        if (move_aborted_applicable) {
            PokemonEventFrame aborted;
            result = run_event_inner(battle, &(PokemonEventInput){
                .event = POKEMON_HANDLER_EVENT_MOVE_ABORTED,
                .source = {POKEMON_ENTITY_POKEMON, action->side, user_slot},
                .target_side = action->side, .target_slot = user_slot,
                .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
                .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
                .context.move = {.move = move},
            }, &aborted);
        }
        return result;
    }
    return execute_selected_move_after_before_move(
        battle, action, move, target, 0);
}
#line 11641 "pokemon.c"
