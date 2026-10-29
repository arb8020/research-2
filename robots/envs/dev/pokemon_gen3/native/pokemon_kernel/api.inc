#line 19633 "pokemon.c"
int pokemon_battle_init(PokemonBattle *battle, const PokemonBattleInit *init) {
    if (battle == NULL || init == NULL || init->bundle == NULL) {
        return POKEMON_INVALID_ARGUMENT;
    }
    const PokemonResolvedBundle *bundle = init->bundle;
    if (!valid_resolved_bundle(bundle)) return POKEMON_INVALID_CONFIGURATION;
    const PokemonGeneration *generation = bundle->rules;
    const PokemonData *data = bundle->data;
    const PokemonFormat *format = bundle->runtime_format;
    const PokemonFormatPolicy *policy = bundle->policy;
    const PokemonFormatManifest *manifest = bundle->manifest;
    /* This entire check precedes construction of `next`, and therefore every
     * state mutation and PRNG draw. */
    if (manifest->game_type != POKEMON_GAME_TYPE_SINGLES ||
        format->team_size < manifest->min_team_size ||
        format->team_size > manifest->max_team_size ||
        format->team_size == 0 || format->team_size > POKEMON_TEAM_CAPACITY ||
        format->active_per_side != 1 ||
        generation->base_damage == NULL ||
        generation->resolve_damage_formula == NULL ||
        generation->residual_damage == NULL ||
        generation->toxic_stage_cap == 0 ||
        !valid_generation_rules(generation) ||
        data->species == NULL ||
        data->moves == NULL || data->type_chart == NULL ||
        (data->effect_count != 0 && data->effects == NULL) ||
        (data->ability_count != 0 && data->abilities == NULL) ||
        (data->item_count != 0 && data->items == NULL) ||
        (data->status_immunity_count != 0 && data->status_immunities == NULL) ||
        (data->handler_count != 0 && data->handlers == NULL) ||
        data->type_count == 0 || data->type_count > POKEMON_TYPE_CAPACITY ||
        data->has_non_interacting_type > 1 ||
        (data->has_non_interacting_type &&
            data->non_interacting_type >= data->type_count) ||
        format->target_rules == NULL || format->target_rule_count == 0) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonBattle next;
    memset(&next, 0, sizeof(next));
    next.generation = generation;
    next.data = data;
    next.format = *format;
    next.policy = *policy;
    if (find_move(&next, generation->fallback_move_id) == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        next.team_sizes[side] = init->team_sizes[side] == 0 ?
            next.format.team_size : init->team_sizes[side];
        if (next.team_sizes[side] == 0 ||
            next.team_sizes[side] > next.format.team_size) {
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    next.turn = 1;
    next.winner = -1;
    next.phase = POKEMON_PHASE_AWAITING_CHOICES;
    memcpy(next.seed, init->seed, sizeof(next.seed));
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t slot = 0; slot < next.team_sizes[side]; slot++) {
            next.sides[side].party_order[slot] = (uint8_t)slot;
            const PokemonSet *set = &init->teams[side].members[slot];
            if (find_species(&next, set->species_id) == NULL || set->level == 0 ||
                set->level > 100) return POKEMON_INVALID_CONFIGURATION;
            if (set->ability_id != 0 && find_ability(&next, set->ability_id) == NULL) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (set->item_id != 0 && find_item(&next, set->item_id) == NULL) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (init->initial_status[side][slot] > POKEMON_STATUS_FREEZE) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            uint8_t initial_sleep_time =
                init->initial_sleep_time[side][slot];
            uint8_t initial_sleep_skipped =
                init->initial_sleep_skipped_time[side][slot];
            uint8_t initial_toxic_stage =
                init->initial_toxic_stage[side][slot];
            if (init->initial_status[side][slot] == POKEMON_STATUS_SLEEP) {
                if (initial_sleep_time == 0 || initial_sleep_time > 5 ||
                    initial_sleep_skipped > 5) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
            } else if (initial_sleep_time != 0 || initial_sleep_skipped != 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (init->initial_status[side][slot] == POKEMON_STATUS_TOXIC) {
                if (initial_toxic_stage > next.generation->toxic_stage_cap) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
            } else if (initial_toxic_stage != 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            for (size_t stat = 0; stat < 6; stat++) {
                if (set->stats[stat] == 0) return POKEMON_INVALID_CONFIGURATION;
            }
            next.sides[side].sets[slot] = *set;
            if (set->ivs_specified > 1) return POKEMON_INVALID_CONFIGURATION;
            for (size_t stat = 0; stat < 6; stat++) {
                if (set->ivs_specified && set->ivs[stat] > 31) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                next.sides[side].sets[slot].ivs[stat] =
                    set->ivs_specified ? set->ivs[stat] : 31;
            }
            next.sides[side].sets[slot].ivs_specified = 1;
            PokemonNature nature = set->nature == POKEMON_NATURE_UNSPECIFIED ?
                POKEMON_NATURE_HARDY : set->nature;
            if (nature > POKEMON_NATURE_QUIRKY) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            PokemonFlavor disliked = nature_disliked_flavor(nature);
            if (set->disliked_flavor != POKEMON_FLAVOR_NONE &&
                set->disliked_flavor != disliked) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            next.sides[side].sets[slot].nature = nature;
            next.sides[side].sets[slot].disliked_flavor = disliked;
            if (set->happiness_specified > 1) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            next.sides[side].sets[slot].happiness =
                set->happiness_specified ? set->happiness : 255;
            next.sides[side].sets[slot].happiness_specified = 1;
            int type_status = restore_effective_types(&next, side, slot);
            if (type_status != POKEMON_OK) return type_status;
            memcpy(next.sides[side].state[slot].stored_stats, &set->stats[1],
                sizeof(next.sides[side].state[slot].stored_stats));
            if (set->gender == POKEMON_GENDER_UNSPECIFIED) {
                uint32_t gender = 0;
                int result = draw_below(
                    &next, POKEMON_DRAW_TEAM_GENDER, 2, &gender
                );
                if (result != POKEMON_OK) return result;
                next.sides[side].sets[slot].gender = gender == 0 ?
                    POKEMON_GENDER_MALE : POKEMON_GENDER_FEMALE;
            } else if (set->gender > POKEMON_GENDER_NONE) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (init->initial_hp[side][slot] > set->stats[0]) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            next.sides[side].state[slot].hp = init->initial_hp[side][slot] == 0 ?
                set->stats[0] : init->initial_hp[side][slot];
            next.sides[side].state[slot].ability_id = set->ability_id;
            next.sides[side].state[slot].item_id = set->item_id;
            /* Pokemon construction seeds the speed cache from the stored stat
             * for every team member, including the bench. Field-dependent
             * modifiers are applied only at explicit updateSpeed stages. */
            next.sides[side].state[slot].cached_speed =
                set->stats[POKEMON_STAT_SPE + 1];
            next.sides[side].state[slot].ability_generation = 1;
            next.sides[side].state[slot].item_generation = 1;
            if (slot == 0) {
                next.sides[side].state[slot].active_turns = 1;
                if (set->ability_id) {
                    next.sides[side].state[slot].ability_effect_order =
                        ++next.next_holder_effect_order;
                }
                if (set->item_id) {
                    next.sides[side].state[slot].item_effect_order =
                        ++next.next_holder_effect_order;
                }
            }
            next.sides[side].state[slot].status.kind =
                (PokemonStatus)init->initial_status[side][slot];
            if (next.sides[side].state[slot].status.kind != POKEMON_STATUS_NONE) {
                next.sides[side].state[slot].status.descriptor_id =
                    next.generation->condition_descriptor(
                        POKEMON_OWNER_STATUS,
                        next.sides[side].state[slot].status.kind);
                if (next.sides[side].state[slot].status.descriptor_id == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                next.sides[side].state[slot].status.state_generation = 1;
                /* Benched effect states have Showdown effectOrder zero until
                 * they are installed by a live transition. Initial status is
                 * canonical state, not a fresh switch-in installation. */
                next.sides[side].state[slot].status.effect_order = slot == 0 ?
                    ++next.next_holder_effect_order : 0;
                if (next.sides[side].state[slot].status.kind ==
                    POKEMON_STATUS_SLEEP) {
                    next.sides[side].state[slot].status.state.sleep.time =
                        initial_sleep_time;
                    next.sides[side].state[slot].status.state.sleep.skipped_time =
                        initial_sleep_skipped;
                } else if (next.sides[side].state[slot].status.kind ==
                    POKEMON_STATUS_TOXIC) {
                    next.sides[side].state[slot].status.state.toxic.stage =
                        initial_toxic_stage;
                }
            }
            int move_count = 0;
            uint16_t personal_move_profile_kind = 0;
            for (size_t move_slot = 0; move_slot < POKEMON_MOVE_CAPACITY; move_slot++) {
                uint16_t move_id = set->move_ids[move_slot];
                if (move_id == 0) continue;
                const PokemonMoveData *move = find_move(&next, move_id);
                PokemonTargetRule target_rule;
                if (move == NULL ||
                    move->raw_pp == 0 || move->no_pp_boosts > 1 ||
                    move->pp != (move->no_pp_boosts ? move->raw_pp :
                        (uint8_t)(((uint16_t)move->raw_pp * 8u) / 5u)) ||
                    !valid_ohko_move(data, move) ||
                    (!valid_accuracy(move->accuracy) ||
                     move->ignore_accuracy > 1 ||
                     move->ignore_evasion > 1) ||
                    move->damage_formula < POKEMON_DAMAGE_STANDARD ||
                    move->damage_formula >
                        POKEMON_DAMAGE_OWNER_CONDITION_VALUE ||
                    move->base_power_policy >
                        POKEMON_BASE_POWER_TARGET_WEIGHT ||
                    ((move->target_status_power_mask == 0) !=
                        (move->target_status_power_multiplier == 0)) ||
                    (move->target_status_power_mask != 0 &&
                        (move->target_status_power_multiplier < 2 ||
                         (move->target_status_power_mask &
                            (uint16_t)~(((UINT16_C(1) <<
                                (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                                ~UINT16_C(1))) != 0 ||
                         (uint32_t)move->power *
                            move->target_status_power_multiplier >
                                UINT16_MAX)) ||
                    ((move->base_power_policy ==
                          POKEMON_BASE_POWER_PERSONAL_MOVE_PROFILE) !=
                         (move->personal_move_profile_kind != 0)) ||
                    (move->semi_invulnerable_hit_mask &
                        (uint8_t)~(POKEMON_SEMI_INVULNERABLE_AIRBORNE |
                            POKEMON_SEMI_INVULNERABLE_UNDERGROUND |
                            POKEMON_SEMI_INVULNERABLE_UNDERWATER)) != 0 ||
                    (move->semi_invulnerable_double_mask &
                        (uint8_t)~move->semi_invulnerable_hit_mask) != 0 ||
                    (((move->damage_formula == POKEMON_DAMAGE_FIXED_LITERAL ||
                       move->damage_formula ==
                           POKEMON_DAMAGE_TARGET_HP_FRACTION ||
                       move->damage_formula ==
                           POKEMON_DAMAGE_OWNER_CONDITION_VALUE)) !=
                     (move->damage_parameter != 0)) ||
                    (move->retaliation_class_mask &
                        (uint8_t)~(POKEMON_RETALIATION_PHYSICAL |
                            POKEMON_RETALIATION_SPECIAL)) != 0 ||
                    move->retaliation_class_policy >
                        POKEMON_RETALIATION_FIXED_CLASS ||
                    move->self_faint_timing > POKEMON_SELF_FAINT_IF_HIT ||
                    move->failure_policy.kind >
                        POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE ||
                    (move->failure_policy.kind == POKEMON_MOVE_FAILURE_NONE &&
                     (move->failure_policy.numerator != 0 ||
                      move->failure_policy.denominator != 0 ||
                      move->failure_policy.target_max_hp_cap_numerator != 0 ||
                      move->failure_policy.target_max_hp_cap_denominator != 0 ||
                      move->failure_policy.minimum != 0 ||
                      move->failure_policy.require_target_type_admission != 0)) ||
                    (move->failure_policy.kind ==
                         POKEMON_MOVE_FAILURE_HYPOTHETICAL_DAMAGE_TO_SOURCE &&
                     (move->category == POKEMON_CATEGORY_STATUS ||
                      move->damage_formula != POKEMON_DAMAGE_STANDARD ||
                      move->multihit_min != 0 ||
                      move->failure_policy.numerator == 0 ||
                      move->failure_policy.denominator == 0 ||
                      move->failure_policy.target_max_hp_cap_numerator == 0 ||
                      move->failure_policy.target_max_hp_cap_denominator == 0 ||
                      move->failure_policy.minimum == 0 ||
                      move->failure_policy.require_target_type_admission > 1)) ||
                    move->defense_policy >
                        POKEMON_DEFENSE_POLICY_SELF_DESTRUCT ||
                    move->self_switch_transfer >
                        POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES ||
                    move->self_switch_skip_before_switch_out > 1 ||
                    (move->self_switch_skip_before_switch_out &&
                     move->self_switch_transfer ==
                        POKEMON_SWITCH_TRANSFER_NONE) ||
                    move->resolution > POKEMON_MOVE_RESOLUTION_DAMAGE ||
                    (move->self_faint_timing == POKEMON_SELF_FAINT_PRE_HIT &&
                     (move->category == POKEMON_CATEGORY_STATUS ||
                      move->multihit_min != 0)) ||
                    (move->self_faint_timing == POKEMON_SELF_FAINT_IF_HIT &&
                     (move->category != POKEMON_CATEGORY_STATUS ||
                      move->multihit_min != 0 ||
                      move->defense_policy !=
                          POKEMON_DEFENSE_POLICY_STANDARD)) ||
                    (move->defense_policy !=
                         POKEMON_DEFENSE_POLICY_STANDARD &&
                     move->category != POKEMON_CATEGORY_PHYSICAL) ||
                    move->bypass_substitute > 1 ||
                    (move_resolution(move) == POKEMON_MOVE_RESOLUTION_NONE &&
                     (move->power != 0 ||
                      move->damage_formula != POKEMON_DAMAGE_STANDARD)) ||
                    (move_resolution(move) == POKEMON_MOVE_RESOLUTION_DAMAGE &&
                     ((move->damage_formula == POKEMON_DAMAGE_STANDARD &&
                      move->power == 0 &&
                      move->base_power_policy == POKEMON_BASE_POWER_STANDARD &&
                       !move_has_dynamic_power_handler(data, move->id)) ||
                      (move->damage_formula != POKEMON_DAMAGE_STANDARD &&
                       move->power != 0))) ||
                    move->target < POKEMON_TARGET_ADJACENT_ALLY ||
                    move->target > POKEMON_TARGET_SELF ||
                    ((move->multihit_min == 0) != (move->multihit_max == 0)) ||
                    move->multihit_accuracy >
                        POKEMON_MULTIHIT_ACCURACY_EACH_HIT ||
                    (move->multihit_accuracy !=
                         POKEMON_MULTIHIT_ACCURACY_ONCE &&
                     move->multihit_min == 0) ||
                    (move->base_power_policy == POKEMON_BASE_POWER_HIT_INDEX &&
                     move->multihit_min == 0) ||
                    (move->multihit_min != 0 &&
                     (move->multihit_min < 2 ||
                      move->multihit_max < move->multihit_min ||
                      (move->multihit_min != move->multihit_max &&
                       (move->multihit_min != generation->multihit.minimum ||
                        move->multihit_max != generation->multihit.maximum)) ||
                      move->damage_formula != POKEMON_DAMAGE_STANDARD)) ||
                    (size_t)move->effect_offset + move->effect_count >
                        data->effect_count) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (move->personal_move_profile_kind != 0) {
                    if (personal_move_profile_kind != 0 &&
                        personal_move_profile_kind !=
                            move->personal_move_profile_kind) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    personal_move_profile_kind =
                        move->personal_move_profile_kind;
                }
                if (move->damage_formula ==
                    POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT) {
                    uint8_t found_random_policy = 0;
                    for (size_t policy_index = 0;
                         policy_index <
                            generation->random_damage_formula_count;
                         policy_index++) {
                        found_random_policy |=
                            generation->random_damage_formulas[policy_index].formula ==
                                move->damage_formula;
                    }
                    if (!found_random_policy) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                }
                if (move->pre_turn_condition_descriptor != 0) {
                    const PokemonConditionIdentity *identity =
                        pokemon_condition_identity(
                            data, move->pre_turn_condition_descriptor);
                    const PokemonConditionRule *pre_turn_rule =
                        condition_rule_by_descriptor(
                            &next, move->pre_turn_condition_descriptor);
                    if (identity == NULL ||
                        identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
                        identity->semantic_kind == POKEMON_VOLATILE_NONE ||
                        pre_turn_rule == NULL) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                }
                for (size_t weather = POKEMON_WEATHER_NONE;
                     weather <= POKEMON_WEATHER_SUN; weather++) {
                    const PokemonWeatherMovePolicy *weather_policy =
                        &move->weather_policy[weather];
                    const uint8_t allowed = POKEMON_WEATHER_MOVE_TYPE |
                        POKEMON_WEATHER_MOVE_CATEGORY |
                        POKEMON_WEATHER_MOVE_ACCURACY |
                        POKEMON_WEATHER_MOVE_POWER |
                        POKEMON_WEATHER_MOVE_SKIP_CHARGE |
                        POKEMON_WEATHER_MOVE_SUPPRESS_TARGET;
                    if ((weather_policy->flags & ~allowed) != 0 ||
                        ((weather_policy->flags & POKEMON_WEATHER_MOVE_TYPE) != 0 ?
                            weather_policy->type > data->type_count :
                            weather_policy->type != 0) ||
                        ((weather_policy->flags & POKEMON_WEATHER_MOVE_CATEGORY) != 0 ?
                            weather_policy->category > POKEMON_CATEGORY_STATUS :
                            weather_policy->category != 0) ||
                        ((weather_policy->flags & POKEMON_WEATHER_MOVE_ACCURACY) != 0 ?
                            !valid_accuracy(weather_policy->accuracy) :
                            (weather_policy->accuracy.kind != 0 ||
                             weather_policy->accuracy.percent != 0)) ||
                        ((weather_policy->flags & POKEMON_WEATHER_MOVE_POWER) != 0 ?
                            weather_policy->power_q12 == 0 : weather_policy->power_q12 != 0) ||
                        ((weather_policy->flags & POKEMON_WEATHER_MOVE_SUPPRESS_TARGET) != 0 &&
                         (weather_policy->flags & POKEMON_WEATHER_MOVE_SKIP_CHARGE) == 0)) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                }
                if (!pokemon_resolve_move_target(
                        format, move->target, &target_rule)) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                if (move_resolution(move) == POKEMON_MOVE_RESOLUTION_DAMAGE &&
                    target_rule.resolved != POKEMON_RESOLVED_TARGET_FOE) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                for (size_t effect = 0; effect < move->effect_count; effect++) {
                    const PokemonEffectOp *op = &data->effects[
                        move->effect_offset + effect];
                    if (op->kind < POKEMON_EFFECT_SET_STATUS ||
                    op->kind > POKEMON_EFFECT_FORCE_SWITCH ||
                        op->phase < POKEMON_EFFECT_PHASE_PRIMARY ||
                        op->phase > POKEMON_EFFECT_PHASE_AFTER_MOVE ||
                        op->target < POKEMON_EFFECT_TARGET_USER ||
                        op->target > POKEMON_EFFECT_TARGET_MOVE_TARGET ||
                        op->chance == 0 || op->chance > 100 ||
                        (move_resolution(move) == POKEMON_MOVE_RESOLUTION_NONE &&
                         op->phase != POKEMON_EFFECT_PHASE_PRIMARY) ||
                        (move_resolution(move) == POKEMON_MOVE_RESOLUTION_DAMAGE &&
                         op->phase == POKEMON_EFFECT_PHASE_PRIMARY) ||
                        (move_resolution(move) == POKEMON_MOVE_RESOLUTION_DAMAGE &&
                         op->kind == POKEMON_EFFECT_ADD_VOLATILE &&
                         ((op->target == POKEMON_EFFECT_TARGET_USER &&
                           op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK &&
                           op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT &&
                           op->phase != POKEMON_EFFECT_PHASE_AFTER_MOVE) ||
                          (op->target == POKEMON_EFFECT_TARGET_MOVE_TARGET &&
                           op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT &&
                           op->phase != POKEMON_EFFECT_PHASE_PRIMARY_HIT))) ||
                        (op->kind == POKEMON_EFFECT_REMOVE_VOLATILE &&
                         (op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK ||
                          op->target != POKEMON_EFFECT_TARGET_USER ||
                          op->argument == POKEMON_VOLATILE_NONE ||
                          op->argument > POKEMON_VOLATILE_LEECH_SEED)) ||
                        (op->kind == POKEMON_EFFECT_REMOVE_SIDE_CONDITION &&
                         (op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT_CALLBACK ||
                          op->target != POKEMON_EFFECT_TARGET_USER ||
                          pokemon_condition_identity(data, op->argument) == NULL ||
                          pokemon_condition_identity(data, op->argument)->domain !=
                              POKEMON_CONDITION_DOMAIN_SIDE)) ||
                        (op->kind == POKEMON_EFFECT_INSTALL_STALLING_GUARD &&
                         (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                          op->target != POKEMON_EFFECT_TARGET_USER ||
                          op->chance != 100 ||
                          op->argument == POKEMON_VOLATILE_NONE ||
                          op->argument >= POKEMON_VOLATILE_KIND_COUNT)) ||
                        (op->kind == POKEMON_EFFECT_ADD_SOURCE_BOUND_VOLATILE &&
                         (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                          op->target != POKEMON_EFFECT_TARGET_USER ||
                          op->chance != 100 ||
                          op->argument == POKEMON_VOLATILE_NONE ||
                          op->argument >= POKEMON_VOLATILE_KIND_COUNT)) ||
                        (op->kind == POKEMON_EFFECT_FORCE_SWITCH &&
                         (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                          op->target != POKEMON_EFFECT_TARGET_MOVE_TARGET ||
                          op->chance != 100 || op->argument != 0 ||
                          op->amount != 0 || op->fraction_numerator != 0 ||
                          op->fraction_denominator != 0)) ||
                        (op->kind ==
                            POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION &&
                         (op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT ||
                          op->target != POKEMON_EFFECT_TARGET_MOVE_TARGET ||
                          status_distribution((const PokemonBattle *)&
                              (PokemonBattle){.data = data},
                              op->argument) == NULL)) ||
                        (op->phase == POKEMON_EFFECT_PHASE_PRIMARY &&
                         op->chance != 100) ||
                        (op->kind == POKEMON_EFFECT_BOOST &&
                         (op->argument >= POKEMON_STAT_COUNT || op->amount == 0)) ||
                        ((op->kind == POKEMON_EFFECT_HEAL_FRACTION ||
                          op->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION) &&
                         (op->phase != POKEMON_EFFECT_PHASE_PRIMARY ||
                          op->target != POKEMON_EFFECT_TARGET_USER ||
                          op->fraction_numerator == 0 ||
                          op->fraction_denominator == 0)) ||
                        (op->kind == POKEMON_EFFECT_DAMAGE_RELATIVE &&
                         ((op->argument != POKEMON_DAMAGE_RELATIVE_DRAIN &&
                           op->argument != POKEMON_DAMAGE_RELATIVE_RECOIL) ||
                          op->fraction_numerator == 0 ||
                          op->fraction_denominator == 0 ||
                          (op->argument == POKEMON_DAMAGE_RELATIVE_DRAIN &&
                           (op->phase != POKEMON_EFFECT_PHASE_AFTER_DAMAGE ||
                            op->damage_preventability !=
                                POKEMON_DAMAGE_PREVENTABILITY_NONE)) ||
                          (op->argument == POKEMON_DAMAGE_RELATIVE_RECOIL &&
                           (op->phase != POKEMON_EFFECT_PHASE_AFTER_MOVE ||
                            (op->damage_preventability !=
                                POKEMON_DAMAGE_UNPREVENTABLE &&
                             op->damage_preventability !=
                                POKEMON_DAMAGE_PREVENTABLE))))) ||
                        (op->kind != POKEMON_EFFECT_DAMAGE_RELATIVE &&
                         op->damage_preventability !=
                            POKEMON_DAMAGE_PREVENTABILITY_NONE)) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                    if (op->kind == POKEMON_EFFECT_INSTALL_STALLING_GUARD) {
                        uint16_t descriptor = generation->condition_descriptor(
                            POKEMON_OWNER_VOLATILE, op->argument);
                        const PokemonConditionRule *guard_rule = NULL;
                        const PokemonConditionRule *stall_rule = NULL;
                        for (size_t rule_index = 0;
                             rule_index < generation->condition_rule_count;
                             rule_index++) {
                            if (generation->condition_rules[rule_index]
                                    .descriptor_id == descriptor) {
                                guard_rule = &generation->condition_rules[rule_index];
                            }
                            if (generation->condition_rules[rule_index].kind ==
                                    POKEMON_RULE_CONDITION_STALL) {
                                stall_rule = &generation->condition_rules[rule_index];
                            }
                        }
                        if (descriptor == 0 || guard_rule == NULL ||
                            !(guard_rule->flags &
							POKEMON_CONDITION_RULE_STALLING_GUARD) ||
                            guard_rule->lifecycle_duration.kind !=
                                POKEMON_CONDITION_DURATION_FIXED ||
                            guard_rule->lifecycle_duration.minimum != 1 ||
                            guard_rule->lifecycle_duration.maximum != 1 ||
                            stall_rule == NULL ||
                            stall_rule->lifecycle_duration.kind !=
                                POKEMON_CONDITION_DURATION_FIXED) {
                            return POKEMON_INVALID_CONFIGURATION;
                        }
                    }
                    uint8_t secondary_group =
                        data->effect_secondary_groups != NULL ?
                        data->effect_secondary_groups[
                            move->effect_offset + effect] : 0;
                    if (secondary_group != 0 &&
                        (op->phase != POKEMON_EFFECT_PHASE_AFTER_HIT ||
                         op->kind != POKEMON_EFFECT_BOOST)) {
                        return POKEMON_INVALID_CONFIGURATION;
                    }
                }
                PokemonMutable *move_state =
                    &next.sides[side].state[slot];
                move_state->move_ids[move_slot] = move_id;
                move_state->pp[move_slot] = move->pp;
                move_state->max_pp[move_slot] = move->pp;
                move_state->base_move_ids[move_slot] = move_id;
                move_state->base_pp[move_slot] = move->pp;
                move_state->base_max_pp[move_slot] = move->pp;
                move_state->pp_ups[move_slot] =
                    move->no_pp_boosts ? 0 : 3;
                move_count++;
            }
            if (personal_move_profile_kind != 0) {
                PokemonPersonalMoveProfile profile;
                int profile_status = generation->resolve_personal_move_profile(
                    personal_move_profile_kind,
                    next.sides[side].sets[slot].ivs, &profile);
                if (profile_status != POKEMON_OK ||
                    profile.kind != personal_move_profile_kind ||
                    profile.type >= data->type_count ||
                    profile.category < POKEMON_CATEGORY_PHYSICAL ||
                    profile.category > POKEMON_CATEGORY_SPECIAL ||
                    profile.power == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                next.sides[side].state[slot].personal_move_profile = profile;
            }
            next.sides[side].state[slot].base_personal_move_profile =
                next.sides[side].state[slot].personal_move_profile;
            if (move_count == 0) return POKEMON_INVALID_CONFIGURATION;
        }
        append_event(&next, (PokemonEvent){
            .kind = POKEMON_EVENT_SWITCH,
            .side = (uint8_t)side,
            .slot = 0,
            .species_id = next.sides[side].sets[0].species_id,
            .hp = next.sides[side].state[0].hp,
            .switch_cause = POKEMON_SWITCH_CAUSE_INITIAL,
        });
    }
    int lifecycle_status = POKEMON_OK;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        lifecycle_status = enqueue_run_switch(&next, (uint8_t)side);
        if (lifecycle_status != POKEMON_OK) return lifecycle_status;
    }
    /* Showdown's start action installs both actives and inserts their
     * runSwitch actions before the Gen 3 post-action Update. Queue-tie PRNG
     * therefore precedes any tied Update ordering draw. */
    lifecycle_status = run_update_each_event_inner(&next, 1);
    if (lifecycle_status != POKEMON_OK) return lifecycle_status;
    while (next.queue.count != 0) {
        PokemonAction action = queue_pop(&next.queue);
        assert(action.kind == POKEMON_ACTION_RUN_SWITCH);
        lifecycle_status = execute_run_switch(&next, &action);
        if (lifecycle_status == POKEMON_OK) {
            lifecycle_status = drain_faints_internal(
                &next, !next_action_is_run_switch(&next));
        }
        if (lifecycle_status == POKEMON_OK &&
            !next_action_is_run_switch(&next)) {
            lifecycle_status = check_fainted_request(&next);
        }
        uint8_t replacement_requested =
            next.request.kind[0] == POKEMON_REQUEST_SWITCH ||
            next.request.kind[1] == POKEMON_REQUEST_SWITCH;
        if (lifecycle_status == POKEMON_OK && !next.terminal &&
            !replacement_requested) {
            lifecycle_status = run_update_each_event_inner(&next, 1);
        }
        if (lifecycle_status != POKEMON_OK) return lifecycle_status;
        if (next.terminal || replacement_requested) break;
    }
    /* Battle construction drains start and runSwitch actions, then endTurn
     * projects the first request. beforeTurn is inserted only after choices
     * begin the next turn, so there is no additional Update here. */
    if (!next.terminal &&
        next.request.kind[0] != POKEMON_REQUEST_SWITCH &&
        next.request.kind[1] != POKEMON_REQUEST_SWITCH) {
        next.initial_setup_complete = 1;
    }
    const PokemonSharedTurnSpeedPolicy *speed_policy =
        &next.generation->shared_turn_speed;
    if (speed_policy->numerator != 0) {
        int speed_status = refresh_active_speeds(&next);
        if (speed_status != POKEMON_OK) return speed_status;
        uint32_t sampled = 0;
        int result = draw_below(
            &next, POKEMON_DRAW_END_TURN, speed_policy->denominator, &sampled
        );
        if (result != POKEMON_OK) return result;
        next.shared_turn_speed_active = sampled < speed_policy->numerator;
    }
    int request_status = project_request(&next);
    if (request_status != POKEMON_OK) return request_status;
    if (!pokemon_battle_check_invariants(&next)) return POKEMON_INVALID_CONFIGURATION;
    memcpy(battle, &next, sizeof(*battle));
    return POKEMON_OK;
}

int pokemon_battle_step(
    PokemonBattle *battle, const PokemonChoice choices[POKEMON_SIDES]
) {
    if (battle == NULL || choices == NULL) return POKEMON_INVALID_ARGUMENT;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        PokemonRequestKind kind = battle->request.kind[side];
        if (kind == POKEMON_REQUEST_WAIT || kind == POKEMON_REQUEST_TERMINAL) {
            if (!validate_choice(battle, side, choices[side])) {
                return POKEMON_ILLEGAL_CHOICE;
            }
            continue;
        }
        PokemonSwitchChoiceRequest switches =
            battle->request.switch_choices[side];
        if (switches.mode == 0) {
            PokemonSwitchChoiceMode mode = kind == POKEMON_REQUEST_SWITCH ?
                POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT :
                POKEMON_SWITCH_CHOICE_VOLUNTARY;
            int request_status = pokemon_make_switch_choice_request(
                battle->request.legal_switches[side], mode, NULL, 0,
                POKEMON_TRAP_DISCLOSURE_NONE, &switches);
            if (request_status != POKEMON_OK) return request_status;
        }
        PokemonChoiceAttemptState attempt = {
            .request_kind = kind,
            .legal_move_mask = battle->request.legal_moves[side],
            .switches = switches,
        };
        PokemonChoiceAttemptOutcome outcome;
        int attempt_status = pokemon_attempt_choice(
            &attempt, choices[side], &outcome);
        if (attempt_status != POKEMON_OK) return attempt_status;
        if (outcome == POKEMON_CHOICE_ATTEMPT_REJECTED_HIDDEN_TRAP) {
            battle->request.switch_choices[side] = attempt.switches;
            battle->request.legal_switches[side] =
                attempt.switches.definitive_mask;
            return POKEMON_ILLEGAL_CHOICE;
        }
        if (outcome != POKEMON_CHOICE_ATTEMPT_ACCEPTED) {
            return POKEMON_ILLEGAL_CHOICE;
        }
    }
    PokemonBattle before = *battle;
    uint8_t was_move_switch = battle->pending_move_switch.active;
    int was_forced = !was_move_switch &&
        (battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
         battle->request.kind[1] == POKEMON_REQUEST_SWITCH);
    battle->event_count = 0;
    battle->draw_count = 0;
    battle->handler_count = 0;
    battle->immunity_count = 0;
    battle->modifier_count = 0;
    battle->relay_result_count = 0;
    battle->damage_stage_count = 0;
    battle->effect_trace_count = 0;
    battle->hit_trace_count = 0;
    battle->damage_formula_trace_count = 0;
    battle->condition_trace_count = 0;
    battle->move_invocation_count = 0;
    for (size_t i = 0; i < battle->residual_count; i++) {
        battle->residuals[i].semantic_sequence = 0;
    }
    battle->semantic_sequence = 0;
    /* Choice normalization asks the condition-owned selector before queue
     * construction asks again for the action it will enqueue. */
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        if (choices[side].kind != POKEMON_CHOICE_MOVE) continue;
        uint16_t locked = 0;
        int lock_status = query_locked_move(battle, side, &locked);
        if (lock_status != POKEMON_OK) {
            *battle = before;
            return lock_status;
        }
        if ((locked != 0 || battle->request.forced_move_id[side] != 0) &&
            choices[side].slot != 0) {
            *battle = before;
            return POKEMON_ILLEGAL_CHOICE;
        }
    }
    /* commitChoices refreshes cached speed before constructing and sorting the
     * action queue. */
    int result = was_move_switch ? POKEMON_OK : refresh_active_speeds(battle);
    if (result != POKEMON_OK) {
        *battle = before;
        return result;
    }
    result = was_move_switch ?
        compile_move_switch_choice(battle, choices) :
        compile_choices(battle, choices);
    if (result != POKEMON_OK) {
        *battle = before;
        return result;
    }
    if (was_forced || was_move_switch) {
        /* The accepted replacement request has been consumed. Any switch
         * request after runSwitch is newly projected by checkFainted and
         * suppresses Gen 3's trailing Update. */
        memset(&battle->request, 0, sizeof(battle->request));
    }
    /* A fresh turn queues beforeTurn after the move queue has already been
     * constructed. Like every Gen 3 runAction, it is followed by Update.
     * Forced replacement choices resume the existing turn and do not add it. */
    if (!was_forced && !was_move_switch) {
        result = each_event_active_order(
            battle, POKEMON_DRAW_EACH_EVENT_BEFORE_TURN_ACTIVE_ORDER);
        if (result == POKEMON_OK) result = run_update_each_event(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
    }
    uint8_t replacement_requested = 0;
    while (battle->queue.count != 0 && !battle->terminal) {
        battle->phase = POKEMON_PHASE_EXECUTING_ACTION;
        PokemonAction action = queue_pop(&battle->queue);
        if (action.kind == POKEMON_ACTION_SWITCH) {
            result = execute_switch(battle, &action);
            if (result == POKEMON_OK) {
                if (action.switch_cause == POKEMON_SWITCH_CAUSE_MOVE_DRIVEN) {
                    memset(&battle->pending_move_switch, 0,
                        sizeof(battle->pending_move_switch));
                }
                result = enqueue_run_switch(battle, action.side);
            }
            if (result != POKEMON_OK) {
                *battle = before;
                return result;
            }
        } else if (action.kind == POKEMON_ACTION_RUN_SWITCH) {
            result = execute_run_switch(battle, &action);
        } else if (action.kind == POKEMON_ACTION_BEFORE_TURN_MOVE) {
            result = execute_before_turn_move(battle, &action);
        } else {
            result = execute_move(battle, &action);
            if (result == POKEMON_OK) result = drain_faints(battle);
            if (result != POKEMON_OK) {
                *battle = before;
                return result;
            }
        }
        if (action.kind == POKEMON_ACTION_MOVE &&
            battle->pending_move_switch.active) {
            const PokemonPendingMoveSwitch *pending =
                &battle->pending_move_switch;
            if (battle->sides[pending->side].active != pending->outgoing_slot ||
                battle->sides[pending->side].state[pending->outgoing_slot].hp == 0) {
                memset(&battle->pending_move_switch, 0,
                    sizeof(battle->pending_move_switch));
            } else {
                result = project_move_switch_request(battle);
                if (result != POKEMON_OK) {
                    *battle = before;
                    return result;
                }
            }
        }
        if (action.kind == POKEMON_ACTION_RUN_SWITCH && result == POKEMON_OK) {
            uint8_t request_fainted = battle->queue.count == 0 ||
                battle->queue.values[0].kind == POKEMON_ACTION_MOVE;
            result = drain_faints_internal(battle, request_fainted);
            if (result == POKEMON_OK && request_fainted) {
                result = check_fainted_request(battle);
            }
        }
        replacement_requested =
            battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
            battle->request.kind[1] == POKEMON_REQUEST_SWITCH;
        /* Showdown represents simultaneous faint replacements as adjacent
         * instaswitch actions. runAction returns before its Gen < 5 Update
         * while another instaswitch is at the queue head. */
        uint8_t next_is_forced_switch =
            action.kind == POKEMON_ACTION_SWITCH &&
            action.switch_cause == POKEMON_SWITCH_CAUSE_FORCED_REPLACEMENT &&
            battle->queue.count != 0 &&
            battle->queue.values[0].kind == POKEMON_ACTION_SWITCH &&
            battle->queue.values[0].switch_cause ==
                POKEMON_SWITCH_CAUSE_FORCED_REPLACEMENT;
        if (!battle->terminal && !replacement_requested &&
            !next_is_forced_switch) {
            result = run_update_each_event(battle);
        }
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        if (battle->terminal || replacement_requested) break;
    }
    uint8_t residual_already_completed = was_forced &&
        battle->turn_suspended == POKEMON_TURN_SUSPENDED_AFTER_RESIDUAL;
    if ((was_forced || was_move_switch) && !battle->terminal &&
        battle->queue.count == 0 &&
        !replacement_requested) {
        /* Replacement completion resumes the suspended turn directly.  There
         * is no externally observable request between runSwitch and Residual. */
        memset(&battle->request, 0, sizeof(battle->request));
    }
    if (!battle->initial_setup_complete && !battle->terminal &&
        battle->queue.count == 0 && !replacement_requested) {
        battle->initial_setup_complete = 1;
        result = project_and_stage_next_turn(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        goto finish_step;
    }
    if (!battle->terminal && battle->queue.count == 0 &&
        !replacement_requested &&
        !residual_already_completed &&
        (was_forced || was_move_switch ||
         battle->turn_suspended == POKEMON_TURN_NOT_SUSPENDED) &&
        (was_forced || was_move_switch ||
         (battle->request.kind[0] != POKEMON_REQUEST_SWITCH &&
          battle->request.kind[1] != POKEMON_REQUEST_SWITCH))) {
        battle->turn_suspended = POKEMON_TURN_NOT_SUSPENDED;
        result = run_residual(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        if (!battle->terminal &&
            battle->request.kind[0] != POKEMON_REQUEST_SWITCH &&
            battle->request.kind[1] != POKEMON_REQUEST_SWITCH) {
            result = run_update_each_event(battle);
        }
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        if (battle->terminal || battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
            battle->request.kind[1] == POKEMON_REQUEST_SWITCH) goto finish_step;
        result = begin_next_turn(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        result = project_and_stage_next_turn(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
    }
    if (residual_already_completed && !battle->terminal &&
        !replacement_requested) {
        battle->turn_suspended = POKEMON_TURN_NOT_SUSPENDED;
        result = begin_next_turn(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
        result = project_and_stage_next_turn(battle);
        if (result != POKEMON_OK) {
            *battle = before;
            return result;
        }
    }
finish_step:
    if (battle->terminal) {
        battle->phase = POKEMON_PHASE_TERMINAL;
    } else if (battle->pending_move_switch.active) {
        battle->phase = POKEMON_PHASE_MOVE_SWITCH;
    } else if (battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
        battle->request.kind[1] == POKEMON_REQUEST_SWITCH) {
        battle->phase = POKEMON_PHASE_FORCED_REPLACEMENT;
    } else {
        battle->phase = POKEMON_PHASE_AWAITING_CHOICES;
    }
    if (!pokemon_battle_check_invariants(battle)) {
        *battle = before;
        return POKEMON_INVALID_CONFIGURATION;
    }
    return POKEMON_OK;
}

PokemonRequest pokemon_battle_request(const PokemonBattle *battle) {
    PokemonRequest empty;
    memset(&empty, 0, sizeof(empty));
    return battle == NULL ? empty : battle->request;
}

void pokemon_battle_view(const PokemonBattle *battle, PokemonBattleView *view) {
    if (battle == NULL || view == NULL) return;
    memset(view, 0, sizeof(*view));
    memcpy(view->team_sizes, battle->team_sizes, sizeof(view->team_sizes));
    memcpy(view->sides, battle->sides, sizeof(view->sides));
    view->field = battle->field;
    view->last_queue = battle->last_queue;
    view->request = battle->request;
    memcpy(view->events, battle->events, sizeof(view->events));
    memcpy(view->draws, battle->draws, sizeof(view->draws));
    memcpy(view->handlers, battle->handlers, sizeof(view->handlers));
    memcpy(view->immunities, battle->immunities, sizeof(view->immunities));
    memcpy(view->modifiers, battle->modifiers, sizeof(view->modifiers));
    memcpy(view->relay_results, battle->relay_results, sizeof(view->relay_results));
    memcpy(view->damage_stages, battle->damage_stages, sizeof(view->damage_stages));
    memcpy(view->effect_traces, battle->effect_traces, sizeof(view->effect_traces));
    memcpy(view->hit_traces, battle->hit_traces, sizeof(view->hit_traces));
    memcpy(view->damage_formula_traces, battle->damage_formula_traces,
        sizeof(view->damage_formula_traces));
    memcpy(view->condition_traces, battle->condition_traces,
        sizeof(view->condition_traces));
    memcpy(view->residuals, battle->residuals, sizeof(view->residuals));
    memcpy(view->seed, battle->seed, sizeof(view->seed));
    view->turn = battle->turn;
    view->semantic_sequence = battle->semantic_sequence;
    view->event_count = battle->event_count;
    view->draw_count = battle->draw_count;
    view->handler_count = battle->handler_count;
    view->immunity_count = battle->immunity_count;
    view->modifier_count = battle->modifier_count;
    view->relay_result_count = battle->relay_result_count;
    view->damage_stage_count = battle->damage_stage_count;
    view->effect_trace_count = battle->effect_trace_count;
    view->hit_trace_count = battle->hit_trace_count;
    view->damage_formula_trace_count = battle->damage_formula_trace_count;
    view->condition_trace_count = battle->condition_trace_count;
    view->residual_count = battle->residual_count;
    view->residual_index = battle->residual_index;
    view->residual_pending = battle->residual_pending;
    view->terminal = battle->terminal;
    view->winner = battle->winner;
    view->phase = battle->phase;
}

static int valid_action_shape(
    const PokemonBattle *battle, const PokemonAction *action
) {
    if (action->side >= POKEMON_SIDES) return 0;
    if (action->kind == POKEMON_ACTION_SWITCH) {
        return action->move_choice_kind == 0 && action->selected_move_id == 0 &&
            action->switch_cause >= POKEMON_SWITCH_CAUSE_VOLUNTARY &&
            action->switch_cause <= POKEMON_SWITCH_CAUSE_MOVE_DRIVEN &&
            action->switch_transfer <=
                POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES &&
            action->skip_before_switch_out <= 1 &&
            ((action->switch_cause == POKEMON_SWITCH_CAUSE_MOVE_DRIVEN) ==
             (action->switch_transfer != POKEMON_SWITCH_TRANSFER_NONE)) &&
            (action->switch_cause == POKEMON_SWITCH_CAUSE_MOVE_DRIVEN ||
             action->skip_before_switch_out == 0);
    }
    if (action->kind == POKEMON_ACTION_RUN_SWITCH) {
        return action->slot < battle->team_sizes[action->side] &&
            action->move_choice_kind == 0 && action->selected_move_id == 0 &&
            action->order == 101 && action->priority == 0 &&
            action->target_mode == 0 && action->resolved_target == 0 &&
            action->target_loc == 0 && action->switch_cause == 0;
    }
    if (action->kind == POKEMON_ACTION_BEFORE_TURN_MOVE) {
        const PokemonMoveData *move = find_move(
            battle, action->selected_move_id);
        return action->slot < POKEMON_MOVE_CAPACITY && move != NULL &&
            move->pre_turn_condition_descriptor != 0 &&
            action->move_choice_kind >= POKEMON_MOVE_CHOICE_SELECTED_SLOT &&
            action->move_choice_kind <= POKEMON_MOVE_CHOICE_FALLBACK &&
            action->order == 5 && action->priority == 0 &&
            action->target_mode == 0 && action->resolved_target == 0 &&
            action->target_loc == 0;
    }
    if (action->kind != POKEMON_ACTION_MOVE ||
        action->move_choice_kind < POKEMON_MOVE_CHOICE_SELECTED_SLOT ||
        action->move_choice_kind > POKEMON_MOVE_CHOICE_FALLBACK ||
        find_move(battle, action->selected_move_id) == NULL) return 0;
    if (action->move_choice_kind == POKEMON_MOVE_CHOICE_SELECTED_SLOT &&
        action->slot >= POKEMON_MOVE_CAPACITY) return 0;
    if (action->move_choice_kind == POKEMON_MOVE_CHOICE_FORCED &&
        action->slot != UINT8_MAX && action->slot >= POKEMON_MOVE_CAPACITY) {
        return 0;
    }
    return action->move_choice_kind != POKEMON_MOVE_CHOICE_FALLBACK ||
        (action->slot == 0 &&
         action->selected_move_id == battle->generation->fallback_move_id);
}

static int side_condition_payload_is_valid(
    const PokemonBattle *battle, const PokemonSideConditionState *condition
) {
    uint8_t minimum = 0;
    uint8_t maximum = 0;
    for (size_t i = 0; i < battle->data->handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor = &battle->data->handlers[i];
        if (descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
            descriptor->source_id != condition->descriptor_id ||
            descriptor->route != POKEMON_HANDLER_ROUTE_OWNER) continue;
        if ((size_t)descriptor->program_offset + descriptor->program_count >
                battle->data->handler_program_count) return 0;
        for (size_t j = 0; j < descriptor->program_count; j++) {
            const PokemonHandlerOp *op = &battle->data->handler_programs[
                descriptor->program_offset + j];
            if (op->opcode == POKEMON_HANDLER_OP_SET_OWNER_SIDE_COUNTER) {
                minimum = (uint8_t)op->argument;
                if (maximum == 0) maximum = minimum;
            } else if (op->opcode ==
                    POKEMON_HANDLER_OP_INCREMENT_OWNER_SIDE_COUNTER_UP_TO) {
                maximum = (uint8_t)op->argument;
            }
        }
    }
    if (maximum == 0) return condition->counter == 0;
    return minimum != 0 && minimum <= maximum &&
        condition->counter >= minimum && condition->counter <= maximum;
}

static int ramping_volatile_payload_is_valid(
    const PokemonBattle *battle, const PokemonVolatileState *condition
) {
    uint8_t initial = 0;
    uint8_t maximum = 0;
    for (size_t i = 0; i < battle->data->handler_count; i++) {
        const PokemonHandlerDescriptor *descriptor = &battle->data->handlers[i];
        if (descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
            descriptor->source_id != condition->descriptor_id ||
            descriptor->route != POKEMON_HANDLER_ROUTE_OWNER) continue;
        if ((size_t)descriptor->program_offset + descriptor->program_count >
                battle->data->handler_program_count) return 0;
        for (size_t j = 0; j < descriptor->program_count; j++) {
            const PokemonHandlerOp *op = &battle->data->handler_programs[
                descriptor->program_offset + j];
            if (op->opcode ==
                    POKEMON_HANDLER_OP_SET_OWNER_VOLATILE_COUNTER) {
                initial = (uint8_t)op->argument;
            } else if (op->opcode ==
                    POKEMON_HANDLER_OP_ADVANCE_OWNER_VOLATILE_COUNTER) {
                maximum = (uint8_t)(op->argument & UINT32_C(0xffff));
            }
        }
    }
    return initial != 0 && maximum >= initial &&
        condition->counter >= initial && condition->counter <= maximum;
}

int pokemon_battle_check_invariants(const PokemonBattle *battle) {
    if (battle == NULL || battle->generation == NULL ||
        !valid_generation_rules(battle->generation)) return 0;
    const PokemonConditionRule *protect_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_PROTECT);
    const PokemonConditionRule *stall_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_STALL);
    const PokemonConditionRule *magic_coat_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_MAGIC_COAT);
    const PokemonConditionRule *snatch_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_SNATCH);
    const PokemonConditionRule *partial_trap_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED);
    const PokemonConditionRule *nightmare_rule = condition_rule(
        battle, POKEMON_RULE_CONDITION_NIGHTMARE);
    if (battle->data == NULL ||
        battle->format.team_size == 0 ||
        battle->format.team_size > POKEMON_TEAM_CAPACITY ||
        battle->format.active_per_side != 1 ||
        battle->queue.count > POKEMON_QUEUE_CAPACITY ||
        battle->last_queue.count > POKEMON_QUEUE_CAPACITY ||
        battle->event_count > POKEMON_EVENT_CAPACITY ||
        battle->draw_count > POKEMON_DRAW_CAPACITY ||
        battle->handler_count > POKEMON_HANDLER_CAPACITY ||
        battle->immunity_count > POKEMON_IMMUNITY_CAPACITY ||
        battle->modifier_count > POKEMON_MODIFIER_CAPACITY ||
        battle->relay_result_count > POKEMON_RELAY_RESULT_CAPACITY ||
        battle->damage_stage_count > POKEMON_DAMAGE_STAGE_CAPACITY ||
        battle->effect_trace_count > POKEMON_EFFECT_TRACE_CAPACITY ||
        battle->hit_trace_count > POKEMON_HIT_TRACE_CAPACITY ||
        battle->damage_formula_trace_count >
            POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY ||
        battle->condition_trace_count > POKEMON_CONDITION_TRACE_CAPACITY ||
        battle->move_frame_depth != 0 ||
        battle->pending_drag.active ||
        battle->move_invocation_count > POKEMON_MOVE_INVOCATION_TRACE_CAPACITY ||
        battle->residual_count > POKEMON_RESIDUAL_CAPACITY ||
        battle->residual_index > battle->residual_count ||
        battle->residual_pending > 1 ||
        battle->initial_setup_complete > 1 ||
        (!battle->residual_pending && battle->residual_index != 0) ||
        battle->field.weather.kind > POKEMON_WEATHER_SUN ||
        (battle->field.weather.kind == POKEMON_WEATHER_NONE &&
         (battle->field.weather.descriptor_id != 0 ||
          battle->field.weather.duration != 0 ||
          battle->field.weather.state_generation != 0 ||
          battle->field.weather.effect_order != 0)) ||
        (battle->field.weather.kind != POKEMON_WEATHER_NONE &&
         (battle->field.weather.descriptor_id !=
            condition_rule(battle, weather_rule_kind(battle->field.weather.kind))->descriptor_id ||
          battle->field.weather.state_generation == 0 ||
          battle->field.weather.effect_order != 0 ||
          battle->field.weather.duration > condition_duration_maximum(
            condition_rule(battle,
                weather_rule_kind(battle->field.weather.kind))) ||
          battle->field.weather.source_side >= POKEMON_SIDES ||
          battle->field.weather.source_slot >=
            battle->team_sizes[battle->field.weather.source_side]))) return 0;
    uint32_t residual_trace_count = 0;
    for (size_t i = 0; i < battle->residual_count; i++) {
        residual_trace_count += battle->residuals[i].semantic_sequence != 0;
    }
    uint32_t sequenced_draw_count = 0;
    for (size_t i = 0; i < battle->draw_count; i++) {
        sequenced_draw_count += battle->draws[i].semantic_sequence != 0;
    }
    uint32_t trace_count = (uint32_t)battle->handler_count +
        battle->modifier_count + battle->relay_result_count +
        battle->damage_stage_count + battle->effect_trace_count +
        battle->hit_trace_count +
        battle->damage_formula_trace_count +
        battle->condition_trace_count +
        residual_trace_count + sequenced_draw_count;
    if (battle->semantic_sequence != trace_count) return 0;
    uint8_t seen_sequence[POKEMON_HANDLER_CAPACITY + POKEMON_MODIFIER_CAPACITY +
        POKEMON_RELAY_RESULT_CAPACITY + POKEMON_DAMAGE_STAGE_CAPACITY +
        POKEMON_EFFECT_TRACE_CAPACITY + POKEMON_HIT_TRACE_CAPACITY +
        POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY +
        POKEMON_CONDITION_TRACE_CAPACITY + POKEMON_RESIDUAL_CAPACITY +
        POKEMON_DRAW_CAPACITY + 1] = {0};
    if (battle->phase < POKEMON_PHASE_AWAITING_CHOICES ||
        battle->phase > POKEMON_PHASE_MOVE_SWITCH) return 0;
    for (size_t i = 0; i < battle->queue.count; i++) {
        if (!valid_action_shape(battle, &battle->queue.values[i])) return 0;
    }
    for (size_t i = 0; i < battle->last_queue.count; i++) {
        if (!valid_action_shape(battle, &battle->last_queue.values[i])) return 0;
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        if (battle->request.kind[side] == POKEMON_REQUEST_MOVE) {
            uint16_t forced = battle->request.forced_move_id[side];
            uint16_t locked = locked_move_id(battle, side);
            if (battle->request.legal_moves[side] == 0 ||
                (battle->request.required_sides & (1u << side)) == 0 ||
                (forced != 0 &&
                 (battle->request.legal_moves[side] != 1 ||
                  find_move(battle, forced) == NULL ||
                  (forced != locked &&
                   (locked != 0 ||
                    forced != battle->generation->fallback_move_id)))) ||
                (forced == 0 && locked != 0)) return 0;
        } else if (battle->request.legal_moves[side] != 0 ||
            battle->request.forced_move_id[side] != 0) {
            return 0;
        }
    }
    for (size_t i = 0; i < battle->draw_count; i++) {
        const PokemonDraw *draw = &battle->draws[i];
        if (draw->semantic_sequence == 0) continue;
        if (draw->semantic_sequence > trace_count ||
            seen_sequence[draw->semantic_sequence]++ ||
            (draw->label != POKEMON_DRAW_STALL_SUCCESS &&
             draw->label != POKEMON_DRAW_SET_STATUS_HANDLER_ORDER &&
             draw->label != POKEMON_DRAW_SET_STATUS_HANDLER_ORDER_OFFSET_ONE &&
             !(draw->label == POKEMON_DRAW_EVENT_HANDLER_ORDER &&
               draw->context_event_id == POKEMON_HANDLER_EVENT_SET_STATUS))) {
            return 0;
        }
    }
    if (battle->faint_count > POKEMON_FAINT_QUEUE_CAPACITY) return 0;
    for (size_t i = 0; i < battle->faint_count; i++) {
        PokemonEntityRef target = battle->faint_queue[i].target;
        if (target.kind != POKEMON_ENTITY_POKEMON ||
            target.side >= POKEMON_SIDES ||
            target.slot >= battle->team_sizes[target.side]) return 0;
        const PokemonMutable *state =
            &battle->sides[target.side].state[target.slot];
        if (state->hp != 0 || state->fainted || !state->faint_queued) return 0;
        for (size_t j = i + 1; j < battle->faint_count; j++) {
            PokemonEntityRef other = battle->faint_queue[j].target;
            if (other.side == target.side && other.slot == target.slot) return 0;
        }
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        if (battle->team_sizes[side] == 0 ||
            battle->team_sizes[side] > battle->format.team_size ||
            battle->sides[side].active >= battle->team_sizes[side]) return 0;
        uint8_t party_slots_seen[POKEMON_TEAM_CAPACITY] = {0};
        for (size_t position = 0; position < POKEMON_TEAM_CAPACITY;
             position++) {
            uint8_t slot = battle->sides[side].party_order[position];
            if (position < battle->team_sizes[side]) {
                if (slot >= battle->team_sizes[side] ||
                    party_slots_seen[slot]++) return 0;
            } else if (slot != 0) {
                return 0;
            }
        }
        if (battle->sides[side].party_order[0] !=
                battle->sides[side].active) return 0;
        if (battle->sides[side].condition_count >
            POKEMON_SIDE_CONDITION_CAPACITY) return 0;
        for (size_t i = 0; i < battle->sides[side].condition_count; i++) {
            const PokemonSideConditionState *condition =
                &battle->sides[side].conditions[i];
            const PokemonConditionRule *rule =
                condition_rule_by_descriptor(battle, condition->descriptor_id);
            if (condition->kind == POKEMON_SIDE_CONDITION_NONE || rule == NULL ||
                battle->generation->condition_descriptor(
                    POKEMON_OWNER_SIDE, condition->kind) !=
                    condition->descriptor_id ||
                battle->sides[side].conditions[i].state_generation == 0 ||
                battle->sides[side].conditions[i].effect_order == 0 ||
                (rule->lifecycle_duration.kind ==
                    POKEMON_CONDITION_DURATION_NONE ?
                    battle->sides[side].conditions[i].duration != 0 :
                    (battle->sides[side].conditions[i].duration == 0 ||
                     battle->sides[side].conditions[i].duration >
                        condition_duration_maximum(rule))) ||
                !side_condition_payload_is_valid(battle, condition)) return 0;
            for (size_t j = i + 1; j < battle->sides[side].condition_count; j++) {
                if (battle->sides[side].conditions[i].kind ==
                    battle->sides[side].conditions[j].kind) return 0;
            }
        }
        for (size_t position = 0;
             position < POKEMON_ACTIVE_POSITION_CAPACITY; position++) {
            const PokemonSide *owner = &battle->sides[side];
            if (owner->slot_condition_count[position] >
                    POKEMON_SLOT_CONDITION_CAPACITY ||
                (position >= battle->format.active_per_side &&
                 owner->slot_condition_count[position] != 0)) return 0;
            for (size_t i = 0; i < owner->slot_condition_count[position]; i++) {
                const PokemonSlotConditionState *condition =
                    &owner->slot_conditions[position][i];
                const PokemonSlotConditionPolicy *policy =
                    slot_condition_policy(battle->data, condition->descriptor_id);
                if (policy == NULL ||
                    condition->semantic_kind != policy->semantic_kind ||
                    condition->position != position ||
                    condition->duration == 0 ||
                    condition->duration > policy->duration ||
                    condition->state_generation == 0 ||
                    condition->effect_order == 0 ||
                    condition->source.kind != POKEMON_ENTITY_POKEMON ||
                    condition->source.side >= POKEMON_SIDES ||
                    condition->source.slot >=
                        battle->team_sizes[condition->source.side] ||
                    condition->source_effect.kind != POKEMON_SOURCE_EFFECT_MOVE ||
                    condition->source_effect.id == 0 ||
                    (policy->effect_kind ==
                        POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE &&
                     (condition->payload.delayed_move.move_id !=
                        condition->source_effect.id ||
                      condition->payload.delayed_move.fixed_damage == 0)) ||
                    (policy->effect_kind ==
                        POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION &&
                     (condition->payload.delayed_move.move_id != 0 ||
                      condition->payload.delayed_move.fixed_damage != 0))) {
                    return 0;
                }
                for (size_t j = i + 1;
                     j < owner->slot_condition_count[position]; j++) {
                    if (owner->slot_conditions[position][j].descriptor_id ==
                        condition->descriptor_id) return 0;
                }
            }
        }
        for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
            const PokemonSet *set = &battle->sides[side].sets[slot];
            const PokemonMutable *state = &battle->sides[side].state[slot];
            if ((state->boolean_states &
                    (UINT32_C(1) |
                     (UINT32_MAX << POKEMON_BOOLEAN_STATE_COUNT))) != 0) {
                return 0;
            }
            if (state->staleness > POKEMON_STALENESS_EXTERNAL ||
                state->pending_staleness > POKEMON_STALENESS_EXTERNAL ||
                state->volatile_staleness > POKEMON_STALENESS_EXTERNAL ||
                state->volatile_staleness == POKEMON_STALENESS_INTERNAL) {
                return 0;
            }
            if (set->ivs_specified != 1) return 0;
            for (size_t stat = 0; stat < 6; stat++) {
                if (set->ivs[stat] > 31) return 0;
            }
            uint16_t expected_profile_kind = 0;
            for (size_t move_slot = 0; move_slot < POKEMON_MOVE_CAPACITY;
                 move_slot++) {
                const PokemonMoveData *move = find_move(
                    battle, set->move_ids[move_slot]);
                if (move == NULL || move->personal_move_profile_kind == 0) {
                    continue;
                }
                if (expected_profile_kind != 0 && expected_profile_kind !=
                        move->personal_move_profile_kind) return 0;
                expected_profile_kind = move->personal_move_profile_kind;
            }
            if (expected_profile_kind == 0) {
                if (state->base_personal_move_profile.kind != 0 ||
                    (!state->transformed &&
                     state->personal_move_profile.kind != 0)) return 0;
            } else {
                PokemonPersonalMoveProfile expected_profile;
                if (battle->generation->resolve_personal_move_profile(
                        expected_profile_kind, set->ivs, &expected_profile) !=
                        POKEMON_OK ||
                    expected_profile.kind !=
                        state->base_personal_move_profile.kind ||
                    expected_profile.type !=
                        state->base_personal_move_profile.type ||
                    expected_profile.category !=
                        state->base_personal_move_profile.category ||
                    expected_profile.power !=
                        state->base_personal_move_profile.power ||
                    (!state->transformed &&
                     (expected_profile.kind != state->personal_move_profile.kind ||
                      expected_profile.type != state->personal_move_profile.type ||
                      expected_profile.category !=
                        state->personal_move_profile.category ||
                      expected_profile.power !=
                        state->personal_move_profile.power))) return 0;
            }
            for (size_t stat = 0; stat < 5; stat++) {
                if (state->stored_stats[stat] == 0 ||
                    (!state->transformed &&
                     state->stored_stats[stat] != set->stats[stat + 1])) return 0;
            }
            if (set->gender < POKEMON_GENDER_MALE ||
                set->gender > POKEMON_GENDER_NONE) return 0;
            if (set->nature < POKEMON_NATURE_HARDY ||
                set->nature > POKEMON_NATURE_QUIRKY ||
                set->disliked_flavor != nature_disliked_flavor(set->nature)) {
                return 0;
            }
            if (set->ability_id != 0 && find_ability(battle, set->ability_id) == NULL) {
                return 0;
            }
            if (set->item_id != 0 && find_item(battle, set->item_id) == NULL) return 0;
            if (state->status.kind > POKEMON_STATUS_FREEZE) return 0;
            if (state->status.kind == POKEMON_STATUS_SLEEP) {
                if (state->status.state.sleep.time == 0 ||
                    state->status.state.sleep.time > 5 ||
                    state->status.state.sleep.skipped_time > 5) return 0;
            } else if (state->status.kind != POKEMON_STATUS_TOXIC &&
                state->status.state.toxic.stage != 0) return 0;
            if (state->status.state.toxic.stage >
                    battle->generation->toxic_stage_cap ||
                state->volatile_count > POKEMON_VOLATILE_CAPACITY) return 0;
            for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
                if (state->boosts[stat] < battle->generation->stages->minimum ||
                    state->boosts[stat] > battle->generation->stages->maximum) return 0;
            }
            for (size_t i = 0; i < state->volatile_count; i++) {
                const PokemonVolatileState *volatile_state = &state->volatiles[i];
                switch (volatile_state->kind) {
                case POKEMON_VOLATILE_PROTECT:
                    if (volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(protect_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                case POKEMON_VOLATILE_STALL:
                    if (volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(stall_rule) ||
                        volatile_state->counter <
                            battle->generation->stall.initial_denominator ||
                        volatile_state->counter >
                            battle->generation->stall.denominator_cap) return 0;
                    break;
                case POKEMON_VOLATILE_SUBSTITUTE:
                    if (volatile_state->duration != 0 ||
                        volatile_state->payload.substitute.hp == 0 ||
                        volatile_state->payload.substitute.hp >
                            set->stats[0] /
                                battle->generation->substitute_cost_denominator) return 0;
                    break;
                case POKEMON_VOLATILE_SUBSTITUTE_BROKEN:
                    if (volatile_state->duration != 0 ||
                        volatile_state->payload.substitute_broken.breaking_move_id == 0) return 0;
                    break;
                case POKEMON_VOLATILE_PARTIALLY_TRAPPED:
                    if (partial_trap_rule == NULL ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(partial_trap_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                case POKEMON_VOLATILE_MAGIC_COAT:
                    if (magic_coat_rule == NULL || volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(magic_coat_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                case POKEMON_VOLATILE_SNATCH:
                    if (snatch_rule == NULL || volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(snatch_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                case POKEMON_VOLATILE_CONFUSION:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.confusion.time == 0 ||
                        volatile_state->payload.confusion.time >
                            battle->generation->confusion_duration_max) return 0;
                    break;
                case POKEMON_VOLATILE_LOCKED_MOVE:
                    if (volatile_state->duration == 0 ||
                        volatile_state->duration > 2 ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.locked_move.move_id == 0 ||
                        volatile_state->payload.locked_move.true_duration == 0 ||
                        volatile_state->payload.locked_move.true_duration >
                            battle->generation->locked_move_duration_max) return 0;
                    break;
                case POKEMON_VOLATILE_TWO_TURN_MOVE:
                    if (volatile_state->duration == 0 ||
                        volatile_state->duration > 2 ||
                        volatile_state->payload.two_turn.move_id == 0 ||
                        (!volatile_state->payload.two_turn.released &&
                         volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MARKER) < 0)) return 0;
                    break;
                case POKEMON_VOLATILE_TWO_TURN_MARKER:
                {
                    const PokemonTwoTurnMoveDescriptor *two_turn =
                        two_turn_move_descriptor(
                            battle, volatile_state->payload.two_turn.move_id);
                    if (two_turn == NULL ||
                        volatile_state->descriptor_id !=
                            two_turn->marker_descriptor_id ||
                        volatile_state->duration > two_turn->marker_duration ||
                        volatile_state->payload.two_turn.move_id == 0 ||
                        volatile_state->payload.two_turn.released ||
                        volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MOVE) < 0) return 0;
                    break;
                }
                case POKEMON_VOLATILE_FOCUS_ENERGY:
                case POKEMON_VOLATILE_MUD_SPORT:
                case POKEMON_VOLATILE_WATER_SPORT:
                case POKEMON_VOLATILE_CHARGE:
                case POKEMON_VOLATILE_LEECH_SEED:
                case POKEMON_VOLATILE_FLASH_FIRE:
                case POKEMON_VOLATILE_FORESIGHT:
				case POKEMON_VOLATILE_RAGE:
				case POKEMON_VOLATILE_MINIMIZE:
                case POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE:
                case POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE:
                case POKEMON_VOLATILE_IMPRISON:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0) return 0;
                    break;
                case POKEMON_VOLATILE_UPROAR: {
                    const PokemonConditionRule *uproar_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (uproar_rule == NULL ||
                        uproar_rule->kind !=
                            POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(uproar_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                }
                case POKEMON_VOLATILE_PREPARED_ACTION: {
                    const PokemonConditionRule *prepared_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (prepared_rule == NULL ||
                        prepared_rule->kind !=
                            POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(prepared_rule) ||
                        volatile_state->counter > 1) return 0;
                    break;
                }
                case POKEMON_VOLATILE_COUNTDOWN_FAINT: {
                    const PokemonConditionRule *countdown_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (countdown_rule == NULL ||
                        countdown_rule->kind !=
                            POKEMON_RULE_CONDITION_COUNTDOWN_FAINT ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(countdown_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                }
                case POKEMON_VOLATILE_TAUNT:
                    if (volatile_state->duration == 0 ||
                        volatile_state->duration > 2 ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.choice_control.stored_move_id != 0) {
                        return 0;
                    }
                    break;
                case POKEMON_VOLATILE_TORMENT:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.choice_control.stored_move_id != 0) {
                        return 0;
                    }
                    break;
                case POKEMON_VOLATILE_DISABLE:
                case POKEMON_VOLATILE_ENCORE: {
                    const PokemonConditionRule *choice_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (volatile_state->duration == 0 ||
                        choice_rule == NULL ||
                        volatile_state->duration >
                            condition_duration_maximum(choice_rule) ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.choice_control.stored_move_id == 0) {
                        return 0;
                    }
                    break;
                }
                case POKEMON_VOLATILE_CHOICE_LOCK:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.choice_control.stored_move_id == 0) {
                        return 0;
                    }
                    break;
				case POKEMON_VOLATILE_TRAPPED:
					if (volatile_state->duration != 0 ||
						volatile_state->counter != 0) return 0;
					break;
				case POKEMON_VOLATILE_TRAPPER:
					/* Hidden linkedStatus markers are normalized into the
					 * visible relation and must never occupy a public slot. */
					return 0;
                case POKEMON_VOLATILE_YAWN: {
                    const PokemonConditionRule *yawn_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (yawn_rule == NULL || volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(yawn_rule) ||
                        volatile_state->counter != 0) return 0;
                    break;
                }
                case POKEMON_VOLATILE_MUST_RECHARGE: {
                    const PokemonConditionRule *recharge_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (recharge_rule == NULL ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(recharge_rule) ||
                        volatile_state->counter != 0 ||
                        volatile_state->payload.choice_control.stored_move_id != 0) {
                        return 0;
                    }
                    break;
                }
                case POKEMON_VOLATILE_NIGHTMARE:
                    if (nightmare_rule == NULL ||
                        volatile_state->descriptor_id !=
                            nightmare_rule->descriptor_id ||
                        volatile_state->duration != 0 ||
                        volatile_state->counter != 0 ||
                        state->status.kind !=
                            nightmare_rule->remove_with_status) return 0;
                    break;
                case POKEMON_VOLATILE_ATTRACT:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0 ||
                        volatile_state->source.kind != POKEMON_ENTITY_POKEMON ||
                        volatile_state->source.side >= POKEMON_SIDES ||
                        volatile_state->source.slot >= battle->team_sizes[
                            volatile_state->source.side] ||
                        (volatile_state->source_effect.kind !=
                             POKEMON_SOURCE_EFFECT_MOVE &&
                         volatile_state->source_effect.kind !=
                             POKEMON_SOURCE_EFFECT_ABILITY) ||
                        volatile_state->source_effect.id == 0) return 0;
                    break;
                case POKEMON_VOLATILE_LOCK_ON: {
                    const PokemonConditionRule *lock_on_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (lock_on_rule == NULL ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(lock_on_rule) ||
                        volatile_state->counter != 0 ||
                        volatile_state->source.kind != POKEMON_ENTITY_POKEMON ||
                        volatile_state->source.side >= POKEMON_SIDES ||
                        volatile_state->source.slot >= battle->team_sizes[
                            volatile_state->source.side] ||
                        volatile_state->source_effect.kind !=
                            POKEMON_SOURCE_EFFECT_MOVE ||
                        volatile_state->source_effect.id == 0) return 0;
                    break;
                }
                case POKEMON_VOLATILE_PREPARED_RETALIATION: {
                    const PokemonConditionRule *retaliation_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (retaliation_rule == NULL ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(retaliation_rule) ||
                        volatile_state->counter != 0 ||
                        (volatile_state->payload.retaliation.captured &&
                         volatile_state->payload.retaliation.source_side >=
                            POKEMON_SIDES)) return 0;
                    break;
                }
                case POKEMON_VOLATILE_STORED_DAMAGE: {
                    const PokemonConditionRule *stored_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    const PokemonEntityRef captured_source =
                        volatile_state->payload.stored_damage.last_source;
                    if (stored_rule == NULL ||
                        stored_rule->kind !=
                            POKEMON_RULE_CONDITION_STORED_DAMAGE ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(stored_rule) ||
                        volatile_state->counter != 0 ||
                        (volatile_state->payload.stored_damage.captured != 0 &&
                         (volatile_state->payload.stored_damage.value == 0 ||
                          captured_source.kind != POKEMON_ENTITY_POKEMON ||
                          captured_source.side >= POKEMON_SIDES ||
                          captured_source.slot >= battle->team_sizes[
                              captured_source.side])) ||
                        (!volatile_state->payload.stored_damage.captured &&
                         (volatile_state->payload.stored_damage.value != 0 ||
                          captured_source.kind != POKEMON_ENTITY_NONE))) {
                        return 0;
                    }
                    break;
                }
                case POKEMON_VOLATILE_FURY_CUTTER: {
                    const PokemonConditionRule *ramp_rule =
                        condition_rule_by_descriptor(
                            battle, volatile_state->descriptor_id);
                    if (ramp_rule == NULL ||
                        ramp_rule->kind !=
                            POKEMON_RULE_CONDITION_RAMPING_POWER ||
                        volatile_state->duration == 0 ||
                        volatile_state->duration >
                            condition_duration_maximum(ramp_rule) ||
                        !ramping_volatile_payload_is_valid(
                            battle, volatile_state)) return 0;
                    break;
                }
                case POKEMON_VOLATILE_INGRAIN:
                    if (volatile_state->duration != 0 ||
                        volatile_state->counter != 0) return 0;
                    break;
                default: {
					const PokemonCounterHealPolicy *counter_policy = NULL;
					for (size_t policy_index = 0;
						 policy_index < battle->data->counter_heal_policy_count;
						 policy_index++) {
						const PokemonCounterHealPolicy *candidate =
							&battle->data->counter_heal_policies[policy_index];
						if (candidate->volatile_kind == volatile_state->kind &&
							candidate->condition_descriptor_id ==
								volatile_state->descriptor_id) {
							counter_policy = candidate;
							break;
						}
					}
					if (counter_policy != NULL) {
						if (volatile_state->duration != 0 ||
							volatile_state->counter == 0 ||
							volatile_state->counter >
								counter_policy->maximum_counter) return 0;
						break;
					}
					const PokemonLockedRampPolicy *policy =
						locked_ramp_policy_for_condition(battle, volatile_state);
					uint8_t is_marker = 0;
					for (size_t policy_index = 0;
						 policy_index < battle->data->locked_ramp_policy_count;
						 policy_index++) {
						const PokemonLockedRampPolicy *candidate =
							&battle->data->locked_ramp_policies[policy_index];
						is_marker |= candidate->marker_kind == volatile_state->kind &&
							candidate->marker_descriptor_id ==
								volatile_state->descriptor_id;
					}
					if (policy != NULL) {
						if (volatile_state->duration == 0 ||
							volatile_state->duration > policy->refresh_duration ||
							volatile_state->counter > policy->maximum_hits ||
							volatile_state->source_effect.kind !=
								POKEMON_SOURCE_EFFECT_MOVE ||
							volatile_state->source_effect.id != policy->move_id) return 0;
					} else if (is_marker) {
						if (volatile_state->duration != 0 ||
							volatile_state->counter != 0) return 0;
					} else {
						uint8_t durationless_persistent = 0;
						for (size_t rule_index = 0;
							 rule_index < battle->generation->condition_rule_count;
							 rule_index++) {
							const PokemonConditionRule *candidate =
								&battle->generation->condition_rules[rule_index];
							durationless_persistent |=
								candidate->descriptor_id ==
									volatile_state->descriptor_id &&
								candidate->kind ==
									POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN &&
								candidate->lifecycle_duration.kind ==
									POKEMON_CONDITION_DURATION_NONE;
						}
						if (!durationless_persistent ||
							volatile_state->duration != 0 ||
							volatile_state->counter != 0) return 0;
					}
					break;
				}
                }
                for (size_t j = i + 1; j < state->volatile_count; j++) {
                    if (state->volatiles[i].kind == state->volatiles[j].kind) {
                        return 0;
                    }
                }
            }
            if (state->hp > set->stats[0] || state->cached_speed == 0) return 0;
            if ((state->status.kind == POKEMON_STATUS_NONE) !=
                    (state->status.descriptor_id == 0 &&
                     state->status.state_generation == 0 &&
                     state->status.effect_order == 0)) return 0;
            if (state->status.kind != POKEMON_STATUS_NONE &&
                state->status.descriptor_id !=
                    battle->generation->condition_descriptor(
                        POKEMON_OWNER_STATUS, state->status.kind)) return 0;
            for (size_t condition = 0; condition < state->volatile_count; condition++) {
                const PokemonVolatileState *volatile_state =
                    &state->volatiles[condition];
                if (volatile_state->state_generation == 0 ||
                    volatile_state->effect_order == 0) return 0;
                if (volatile_state->kind == POKEMON_VOLATILE_TWO_TURN_MARKER) {
                    const PokemonTwoTurnMoveDescriptor *two_turn =
                        two_turn_move_descriptor(
                            battle, volatile_state->payload.two_turn.move_id);
                    if (two_turn == NULL ||
                        volatile_state->descriptor_id !=
                            two_turn->marker_descriptor_id ||
                        find_move(battle, volatile_state->payload.two_turn.move_id) == NULL ||
                        volatile_state->payload.two_turn.target_side >= POKEMON_SIDES ||
                        volatile_state->payload.two_turn.target_slot >=
                            battle->team_sizes[volatile_state->payload.two_turn.target_side]) {
                        return 0;
                    }
                    int lock = volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MOVE);
                    if (lock < 0 ||
                        state->volatiles[lock].payload.two_turn.move_id !=
                            volatile_state->payload.two_turn.move_id ||
                        state->volatiles[lock].payload.two_turn.target_side !=
                            volatile_state->payload.two_turn.target_side ||
                        state->volatiles[lock].payload.two_turn.target_slot !=
                            volatile_state->payload.two_turn.target_slot) return 0;
                } else if (volatile_state->descriptor_id == 0) {
                    return 0;
                } else if (volatile_state->kind ==
                        POKEMON_VOLATILE_PREPARED_RETALIATION) {
                    const PokemonConditionIdentity *identity =
                        pokemon_condition_identity(
                            battle->data, volatile_state->descriptor_id);
                    if (identity == NULL ||
                        identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
                        identity->semantic_kind != volatile_state->kind) {
                        return 0;
                    }
                } else if (volatile_state->descriptor_id !=
                        battle->generation->condition_descriptor(
                            POKEMON_OWNER_VOLATILE, volatile_state->kind)) {
                    return 0;
                }
                const PokemonConditionRule *volatile_rule =
                    condition_rule_by_descriptor(
                        battle, volatile_state->descriptor_id);
                if (volatile_rule != NULL &&
                    volatile_rule->source_linked_kind !=
                        POKEMON_VOLATILE_NONE) {
                    if (volatile_state->source.kind !=
                            POKEMON_ENTITY_POKEMON ||
                        volatile_state->source.side >= POKEMON_SIDES ||
                        volatile_state->source.slot >= battle->team_sizes[
                            volatile_state->source.side] ||
                        volatile_state->linked_source_state_generation == 0 ||
                        volatile_state->linked_source_effect_order == 0) {
                        return 0;
                    }
                } else if (volatile_state->linked_source_state_generation != 0 ||
                    volatile_state->linked_source_effect_order != 0) {
                    return 0;
                }
            }
            if (state->ability_generation == 0 || state->item_generation == 0 ||
                (state->ability_id != 0 &&
                 find_ability(battle, state->ability_id) == NULL) ||
                (state->item_id != 0 && find_item(battle, state->item_id) == NULL)) {
                return 0;
            }
            if (state->fainted && state->faint_queued) return 0;
            if ((state->hp == 0) !=
                ((state->fainted != 0) || (state->faint_queued != 0))) return 0;
            if (state->last_move_id != 0 &&
                find_move(battle, state->last_move_id) == NULL) return 0;
            if (state->last_move_used.present) {
                if (state->last_move_used.move_id == 0 ||
                    find_move(battle, state->last_move_used.move_id) == NULL ||
                    state->last_move_used.resolved_type >=
                        battle->data->type_count) return 0;
            } else if (state->last_move_used.move_id != 0 ||
                state->last_move_used.resolved_type != 0) {
                return 0;
            }
            const PokemonAttackRecord *attack = &state->last_attacked_by;
            if (attack->present) {
                if (attack->source.kind != POKEMON_ENTITY_POKEMON ||
                    attack->source.side >= POKEMON_SIDES ||
                    attack->source.slot >=
                        battle->team_sizes[attack->source.side] ||
                    attack->source.side == side || attack->move_id == 0 ||
                    find_move(battle, attack->move_id) == NULL ||
                    attack->damage_was_number > 1 || attack->this_turn > 1) {
                    return 0;
                }
            } else if (attack->source.kind != POKEMON_ENTITY_NONE ||
                attack->move_id != 0 || attack->damage != 0 ||
                attack->damage_was_number != 0 || attack->this_turn != 0) {
                return 0;
            }
            if (state->transformed > 1 ||
                (state->temporary_move_slots &
                    (uint8_t)~((1u << POKEMON_MOVE_CAPACITY) - 1u)) != 0) {
                return 0;
            }
            for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++) {
                if (state->pp_ups[move] > 3) return 0;
                const PokemonMoveData *current =
                    find_move(battle, state->move_ids[move]);
                const PokemonMoveData *base =
                    find_move(battle, state->base_move_ids[move]);
                if ((state->move_ids[move] == 0) != (current == NULL) ||
                    (state->base_move_ids[move] == 0) != (base == NULL)) {
                    return 0;
                }
                if ((state->move_ids[move] == 0 &&
                     (state->pp[move] != 0 || state->max_pp[move] != 0)) ||
                    (state->move_ids[move] != 0 &&
                     (state->max_pp[move] == 0 ||
                      state->pp[move] > state->max_pp[move])) ||
                    (state->base_move_ids[move] == 0 &&
                     (state->base_pp[move] != 0 ||
                      state->base_max_pp[move] != 0)) ||
                    (state->base_move_ids[move] != 0 &&
                     (state->base_max_pp[move] == 0 ||
                      state->base_pp[move] > state->base_max_pp[move]))) {
                    return 0;
                }
                if ((state->temporary_move_slots & (1u << move)) == 0 &&
                    (state->move_ids[move] != state->base_move_ids[move] ||
                     state->pp[move] != state->base_pp[move] ||
                     state->max_pp[move] != state->base_max_pp[move])) {
                    return 0;
                }
            }
        }
    }
    for (size_t i = 0; i < battle->handler_count; i++) {
        const PokemonHandlerInvocation *invocation = &battle->handlers[i];
        if (invocation->semantic_sequence == 0 ||
            invocation->semantic_sequence > trace_count ||
            seen_sequence[invocation->semantic_sequence]++ ||
            invocation->handler.holder_side >= POKEMON_SIDES ||
            invocation->handler.holder_slot >=
                battle->team_sizes[invocation->handler.holder_side] ||
            event_spec(battle, invocation->handler.descriptor.event) == NULL ||
            !event_spec(battle, invocation->handler.descriptor.event)->supported ||
            invocation->invoked > 1 ||
            invocation->result > POKEMON_HANDLER_HIT_SUBSTITUTE) return 0;
    }
    for (size_t i = 0; i < battle->immunity_count; i++) {
        if (battle->immunities[i].target_side >= POKEMON_SIDES ||
            battle->immunities[i].target_slot >=
                battle->team_sizes[battle->immunities[i].target_side] ||
            battle->immunities[i].cause > POKEMON_IMMUNITY_HANDLER) return 0;
    }
    for (size_t i = 0; i < battle->modifier_count; i++) {
        const PokemonModifierInvocation *invocation = &battle->modifiers[i];
        if (invocation->semantic_sequence == 0 ||
            invocation->semantic_sequence > trace_count ||
            seen_sequence[invocation->semantic_sequence]++ ||
            invocation->handler.holder_side >= POKEMON_SIDES ||
            invocation->handler.holder_slot >=
                battle->team_sizes[invocation->handler.holder_side] ||
            (invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_BASE_POWER &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_ATK &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_ACCURACY &&
             invocation->handler.descriptor.event !=
                POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO &&
             invocation->handler.descriptor.event !=
                POKEMON_HANDLER_EVENT_MODIFY_DAMAGE &&
             invocation->handler.descriptor.event !=
                POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_DEF &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_SPA &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_SPD &&
             invocation->handler.descriptor.event != POKEMON_HANDLER_EVENT_MODIFY_SPE &&
             invocation->handler.descriptor.event !=
                POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE) ||
            (invocation->handler.descriptor.source_kind !=
                POKEMON_HANDLER_SOURCE_ABILITY &&
             invocation->handler.descriptor.source_kind !=
                POKEMON_HANDLER_SOURCE_ITEM &&
             invocation->handler.descriptor.source_kind !=
                POKEMON_HANDLER_SOURCE_CONDITION &&
             invocation->handler.descriptor.source_kind !=
                POKEMON_HANDLER_SOURCE_MOVE) ||
            invocation->modifier_before_q12 == 0 ||
            invocation->modifier_q12 == 0 ||
            invocation->modifier_after_q12 == 0) return 0;
        if (invocation->invoked > 1) return 0;
    }
    for (size_t i = 0; i < battle->relay_result_count; i++) {
        const PokemonRelayResult *relay = &battle->relay_results[i];
        if (relay->semantic_sequence == 0 ||
            relay->semantic_sequence > trace_count ||
            seen_sequence[relay->semantic_sequence]++ ||
            (relay->event != POKEMON_HANDLER_EVENT_BASE_POWER &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_ATK &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_ACCURACY &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_DEF &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_SPA &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_SPD &&
             relay->event != POKEMON_HANDLER_EVENT_MODIFY_SPE &&
             relay->event != POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE) ||
            relay->holder_side >= POKEMON_SIDES ||
            relay->holder_slot >= battle->team_sizes[relay->holder_side] ||
            relay->modifier_q12 == 0) return 0;
    }
    for (size_t i = 0; i < battle->damage_stage_count; i++) {
        const PokemonDamageStageTrace *stage = &battle->damage_stages[i];
        if (stage->semantic_sequence == 0 ||
            stage->semantic_sequence > trace_count ||
            seen_sequence[stage->semantic_sequence]++ ||
            stage->kind != POKEMON_DAMAGE_STAGE_BURN ||
            stage->source_side >= POKEMON_SIDES ||
            stage->target_side >= POKEMON_SIDES ||
            (stage->mode != POKEMON_DAMAGE_MODE_ORDINARY_MOVE &&
             stage->mode != POKEMON_DAMAGE_MODE_SYNTHETIC_SELF_HIT) ||
            (stage->mode == POKEMON_DAMAGE_MODE_ORDINARY_MOVE &&
             stage->kind == POKEMON_DAMAGE_STAGE_BURN &&
             stage->source_side == stage->target_side) ||
            stage->reason < POKEMON_BURN_NOT_BURNED ||
            stage->reason > POKEMON_BURN_APPLIED ||
            stage->applied != (stage->reason == POKEMON_BURN_APPLIED)) return 0;
    }
    for (size_t i = 0; i < battle->effect_trace_count; i++) {
        const PokemonEffectTrace *trace = &battle->effect_traces[i];
        if (trace->semantic_sequence == 0 ||
            trace->semantic_sequence > trace_count ||
            seen_sequence[trace->semantic_sequence]++ ||
            trace->kind < POKEMON_EFFECT_SET_STATUS ||
            trace->kind > POKEMON_EFFECT_CRASH_DAMAGE ||
            trace->phase < POKEMON_EFFECT_PHASE_PRIMARY ||
            trace->phase > POKEMON_EFFECT_PHASE_MOVE_FAIL ||
            trace->target < POKEMON_EFFECT_TARGET_USER ||
            trace->target > POKEMON_EFFECT_TARGET_MOVE_TARGET ||
            trace->result < POKEMON_EFFECT_APPLIED ||
            trace->result > POKEMON_EFFECT_FAILED ||
            trace->source_side >= POKEMON_SIDES ||
            trace->target_side >= POKEMON_SIDES ||
            trace->source_slot >= battle->team_sizes[trace->source_side] ||
            trace->target_slot >= battle->team_sizes[trace->target_side] ||
            (trace->kind == POKEMON_EFFECT_DAMAGE_RELATIVE &&
             ((trace->argument != POKEMON_DAMAGE_RELATIVE_DRAIN &&
               trace->argument != POKEMON_DAMAGE_RELATIVE_RECOIL) ||
              trace->numerator == 0 || trace->denominator == 0 ||
              trace->damage_target_side >= POKEMON_SIDES ||
              trace->damage_target_slot >=
                battle->team_sizes[trace->damage_target_side] ||
              (trace->prevention &&
               trace->argument != POKEMON_DAMAGE_RELATIVE_RECOIL))) ||
            (trace->kind == POKEMON_EFFECT_CRASH_DAMAGE &&
             (trace->phase != POKEMON_EFFECT_PHASE_MOVE_FAIL ||
              trace->target != POKEMON_EFFECT_TARGET_USER ||
              trace->numerator == 0 || trace->denominator == 0 ||
              trace->minimum == 0 || trace->cap_numerator == 0 ||
              trace->cap_denominator == 0 ||
              trace->damage_target_side != trace->source_side ||
              trace->damage_target_slot != trace->source_slot))) return 0;
    }
    for (size_t i = 0; i < battle->hit_trace_count; i++) {
        const PokemonHitTrace *trace = &battle->hit_traces[i];
        if (trace->semantic_sequence == 0 ||
            trace->semantic_sequence > trace_count ||
            seen_sequence[trace->semantic_sequence]++ ||
            trace->kind < POKEMON_HIT_PLAN || trace->kind > POKEMON_HIT_SUBSTITUTE ||
            trace->source_side >= POKEMON_SIDES ||
            trace->target_side >= POKEMON_SIDES ||
            trace->source_slot >= battle->team_sizes[trace->source_side] ||
            trace->target_slot >= battle->team_sizes[trace->target_side] ||
            trace->requested_hits == 0 ||
            trace->requested_hits > POKEMON_TEAM_CAPACITY ||
            (trace->kind == POKEMON_HIT_CONNECTED &&
             (trace->hit_index == 0 ||
              trace->hit_index > trace->requested_hits ||
              trace->calculated_damage == 0 ||
              trace->calculated_damage < trace->damage ||
              trace->hp_before < trace->hp_after ||
              trace->damage != trace->hp_before - trace->hp_after ||
              trace->damage_roll >= 16 || trace->critical > 1)) ||
            (trace->kind == POKEMON_HIT_SUBSTITUTE &&
             (trace->hit_index == 0 ||
              trace->hit_index > trace->requested_hits ||
              trace->damage == 0 || trace->calculated_damage < trace->damage ||
              trace->hp_before != trace->hp_after ||
              trace->damage_roll >= 16 || trace->critical > 1 ||
              trace->substitute_broke > 1 ||
              trace->after_sub_damage_dispatched != 1)) ||
            (trace->kind == POKEMON_HIT_RESULT &&
             (trace->actual_hits == 0 ||
              trace->actual_hits > trace->requested_hits ||
              trace->stop_reason < POKEMON_HIT_STOP_COMPLETED ||
             trace->stop_reason > POKEMON_HIT_STOP_SOURCE_ASLEEP))) return 0;
    }
    for (size_t i = 0; i < battle->damage_formula_trace_count; i++) {
        const PokemonDamageFormulaTrace *trace =
            &battle->damage_formula_traces[i];
        if (trace->semantic_sequence == 0 ||
            trace->semantic_sequence > trace_count ||
            seen_sequence[trace->semantic_sequence]++ ||
            (trace->formula != POKEMON_DAMAGE_FIXED_LEVEL &&
             trace->formula != POKEMON_DAMAGE_FIXED_LITERAL &&
             trace->formula != POKEMON_DAMAGE_TARGET_HP_FRACTION &&
             trace->formula != POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE &&
             trace->formula != POKEMON_DAMAGE_TARGET_CURRENT_HP &&
             trace->formula != POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT &&
             trace->formula != POKEMON_DAMAGE_HP_BRACKET &&
             trace->formula != POKEMON_DAMAGE_OWNER_CONDITION_VALUE) ||
            trace->source_side >= POKEMON_SIDES ||
            trace->target_side >= POKEMON_SIDES ||
            trace->source_slot >= battle->team_sizes[trace->source_side] ||
            trace->target_slot >= battle->team_sizes[trace->target_side] ||
            trace->resolved_value == 0 ||
            ((trace->formula == POKEMON_DAMAGE_FIXED_LEVEL ||
              trace->formula == POKEMON_DAMAGE_FIXED_LITERAL ||
              trace->formula == POKEMON_DAMAGE_TARGET_HP_FRACTION ||
              trace->formula == POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE ||
              trace->formula == POKEMON_DAMAGE_TARGET_CURRENT_HP ||
              trace->formula == POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT ||
              trace->formula == POKEMON_DAMAGE_OWNER_CONDITION_VALUE) &&
             (trace->hp != 0 || trace->max_hp != 0 || trace->ratio != 0 ||
              trace->bracket != 0)) ||
            (trace->formula == POKEMON_DAMAGE_HP_BRACKET &&
             (trace->hp == 0 || trace->max_hp == 0 ||
              trace->hp > trace->max_hp || trace->ratio == 0 ||
              trace->ratio > 48 || trace->bracket > 5))) return 0;
    }
    for (size_t i = 0; i < battle->condition_trace_count; i++) {
        const PokemonConditionTrace *trace = &battle->condition_traces[i];
        if (trace->semantic_sequence == 0 ||
            trace->semantic_sequence > trace_count ||
            seen_sequence[trace->semantic_sequence]++ ||
            trace->scope < POKEMON_CONDITION_SCOPE_STATUS ||
            trace->scope > POKEMON_CONDITION_SCOPE_SLOT ||
            trace->operation < POKEMON_CONDITION_ADD ||
            trace->operation > POKEMON_CONDITION_REMOVE ||
            trace->value_kind > POKEMON_CONDITION_VALUE_COUNTER ||
            trace->side >= POKEMON_SIDES) return 0;
    }
    for (size_t i = 0; i < battle->residual_count; i++) {
        const PokemonResidualWork *work = &battle->residuals[i];
        if (work->kind < POKEMON_RESIDUAL_WEATHER ||
            work->kind > POKEMON_RESIDUAL_SLOT_CONDITION ||
            work->side >= POKEMON_SIDES) return 0;
        if (work->semantic_sequence != 0 &&
            (work->semantic_sequence > trace_count ||
             seen_sequence[work->semantic_sequence]++)) return 0;
    }
    if (battle->terminal) {
        if (battle->winner < -1 || battle->winner >= (int8_t)POKEMON_SIDES ||
            battle->queue.count != 0 || battle->request.required_sides != 0 ||
            battle->request.kind[0] != POKEMON_REQUEST_TERMINAL ||
            battle->request.kind[1] != POKEMON_REQUEST_TERMINAL) return 0;
        if (battle->phase != POKEMON_PHASE_TERMINAL ||
            (battle->winner == -1 &&
             (battle->event_count == 0 ||
              battle->events[battle->event_count - 1].kind !=
                  POKEMON_EVENT_TIE))) return 0;
    } else if (battle->pending_move_switch.active) {
        const PokemonPendingMoveSwitch *pending = &battle->pending_move_switch;
        const PokemonMoveData *source_move =
            find_move(battle, pending->source_move_id);
        uint8_t expected_candidates = 0;
        if (pending->side < POKEMON_SIDES) {
            for (size_t slot = 0; slot < battle->team_sizes[pending->side];
                 slot++) {
                if (slot != pending->outgoing_slot &&
                    battle->sides[pending->side].state[slot].hp != 0) {
                    expected_candidates |= (uint8_t)(1u << slot);
                }
            }
        }
        if (battle->phase != POKEMON_PHASE_MOVE_SWITCH ||
            pending->side >= POKEMON_SIDES ||
            pending->outgoing_slot >= battle->team_sizes[pending->side] ||
            battle->sides[pending->side].active != pending->outgoing_slot ||
            battle->sides[pending->side].state[pending->outgoing_slot].hp == 0 ||
            source_move == NULL ||
            source_move->self_switch_transfer != pending->transfer ||
            source_move->self_switch_skip_before_switch_out !=
                pending->skip_before_switch_out ||
            pending->transfer == POKEMON_SWITCH_TRANSFER_NONE ||
            pending->transfer >
                POKEMON_SWITCH_TRANSFER_BOOSTS_AND_VOLATILES ||
            pending->skip_before_switch_out > 1 ||
            battle->request.kind[pending->side] != POKEMON_REQUEST_SWITCH ||
            battle->request.kind[1u - pending->side] != POKEMON_REQUEST_WAIT ||
            battle->request.required_sides != (uint8_t)(1u << pending->side) ||
            expected_candidates == 0 ||
            battle->request.legal_switches[pending->side] !=
                expected_candidates ||
            battle->request.switch_choices[pending->side].candidate_mask !=
                expected_candidates ||
            battle->request.switch_choices[pending->side].definitive_mask !=
                expected_candidates ||
            battle->request.switch_choices[pending->side].mode !=
                POKEMON_SWITCH_CHOICE_MOVE_DRIVEN) return 0;
    } else if (battle->request.kind[0] == POKEMON_REQUEST_SWITCH ||
        battle->request.kind[1] == POKEMON_REQUEST_SWITCH) {
        if (battle->phase != POKEMON_PHASE_FORCED_REPLACEMENT) return 0;
    } else if (battle->phase != POKEMON_PHASE_AWAITING_CHOICES) {
        return 0;
    }
    return 1;
}
#line 19633 "pokemon.c"
