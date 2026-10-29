#line 18651 "pokemon.c"
static PokemonFlavor nature_disliked_flavor(PokemonNature nature) {
    switch (nature) {
    case POKEMON_NATURE_BOLD:
    case POKEMON_NATURE_TIMID:
    case POKEMON_NATURE_MODEST:
    case POKEMON_NATURE_CALM:
        return POKEMON_FLAVOR_SPICY;
    case POKEMON_NATURE_ADAMANT:
    case POKEMON_NATURE_IMPISH:
    case POKEMON_NATURE_JOLLY:
    case POKEMON_NATURE_CAREFUL:
        return POKEMON_FLAVOR_DRY;
    case POKEMON_NATURE_BRAVE:
    case POKEMON_NATURE_RELAXED:
    case POKEMON_NATURE_QUIET:
    case POKEMON_NATURE_SASSY:
        return POKEMON_FLAVOR_SWEET;
    case POKEMON_NATURE_NAUGHTY:
    case POKEMON_NATURE_LAX:
    case POKEMON_NATURE_NAIVE:
    case POKEMON_NATURE_RASH:
        return POKEMON_FLAVOR_BITTER;
    case POKEMON_NATURE_LONELY:
    case POKEMON_NATURE_HASTY:
    case POKEMON_NATURE_MILD:
    case POKEMON_NATURE_GENTLE:
        return POKEMON_FLAVOR_SOUR;
    default:
        return POKEMON_FLAVOR_NONE;
    }
}

static int valid_ohko_move(
    const PokemonData *data, const PokemonMoveData *move
) {
    if (move->ohko.kind < POKEMON_OHKO_NONE ||
        move->ohko.kind > POKEMON_OHKO_EXCLUDED_TYPE) return 0;
    if (move->ohko.kind == POKEMON_OHKO_NONE) {
        return move->ohko.excluded_type == 0 &&
            move->damage_formula != POKEMON_DAMAGE_TARGET_CURRENT_HP;
    }
    if (move->ohko.kind == POKEMON_OHKO_EXCLUDED_TYPE) {
        if (move->ohko.excluded_type == 0 ||
            move->ohko.excluded_type >= data->type_count) return 0;
    } else if (move->ohko.excluded_type != 0) {
        return 0;
    }
    return move->category != POKEMON_CATEGORY_STATUS && move->power == 0 &&
        move->accuracy.kind == POKEMON_ACCURACY_PERCENT &&
        move->target == POKEMON_TARGET_NORMAL && move->multihit_min == 0 &&
        move->multihit_max == 0 &&
        move->damage_formula == POKEMON_DAMAGE_TARGET_CURRENT_HP &&
        move->damage_parameter == 0;
}

static int valid_move_pre_use_programs(const PokemonData *data) {
    if ((data->move_pre_use_program_count != 0) !=
        (data->move_pre_use_programs != NULL)) return 0;
    for (size_t i = 0; i < data->move_pre_use_program_count; i++) {
        const PokemonMovePreUseProgram *program =
            &data->move_pre_use_programs[i];
        uint8_t found_move = 0;
        for (size_t move = 0; move < data->move_count; move++) {
            found_move |= data->moves[move].id == program->move_id;
        }
        if (!found_move ||
            program->operation !=
                POKEMON_MOVE_PRE_USE_CANCEL_IF_VOLATILE_KIND ||
            program->volatile_kind <= POKEMON_VOLATILE_NONE ||
            program->volatile_kind >= POKEMON_VOLATILE_KIND_COUNT) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->move_pre_use_programs[earlier].move_id ==
                    program->move_id) return 0;
        }
    }
    return 1;
}

static int valid_locked_ramp_policies(
    const PokemonData *data, const PokemonGeneration *generation
) {
	if ((data->locked_ramp_policy_count != 0) !=
		(data->locked_ramp_policies != NULL)) return 0;
	for (size_t i = 0; i < data->locked_ramp_policy_count; i++) {
		const PokemonLockedRampPolicy *policy =
			&data->locked_ramp_policies[i];
		const PokemonMoveData *move = NULL;
		const PokemonConditionRule *condition = NULL;
		const PokemonConditionRule *marker = NULL;
		const PokemonConditionIdentity *condition_identity = NULL;
		const PokemonConditionIdentity *marker_identity = NULL;
		for (size_t j = 0; j < data->move_count; j++) {
			if (data->moves[j].id == policy->move_id) move = &data->moves[j];
		}
		for (size_t j = 0; j < generation->condition_rule_count; j++) {
			if (generation->condition_rules[j].descriptor_id ==
					policy->condition_descriptor_id) {
				condition = &generation->condition_rules[j];
			}
			if (generation->condition_rules[j].descriptor_id ==
					policy->marker_descriptor_id) {
				marker = &generation->condition_rules[j];
			}
		}
		for (size_t j = 0; j < data->condition_catalog_count; j++) {
			if (data->condition_catalog[j].catalog_id ==
					policy->condition_descriptor_id) {
				condition_identity = &data->condition_catalog[j];
			}
			if (data->condition_catalog[j].catalog_id ==
					policy->marker_descriptor_id) {
				marker_identity = &data->condition_catalog[j];
			}
		}
		if (policy->id == 0 || move == NULL || move->target != POKEMON_TARGET_NORMAL ||
			condition == NULL || condition->kind !=
				POKEMON_RULE_CONDITION_RAMPING_POWER ||
			!(condition->flags & POKEMON_CONDITION_RULE_REPEATABLE_FAMILY) ||
			condition->lifecycle_duration.kind !=
				POKEMON_CONDITION_DURATION_FIXED ||
			condition->lifecycle_duration.minimum != 1 ||
			condition->lifecycle_duration.maximum != 1 ||
			marker == NULL || marker->kind !=
				POKEMON_RULE_CONDITION_RAMPING_POWER ||
			!(marker->flags & POKEMON_CONDITION_RULE_REPEATABLE_FAMILY) ||
			marker->lifecycle_duration.kind != POKEMON_CONDITION_DURATION_NONE ||
			condition_identity == NULL || marker_identity == NULL ||
			condition_identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
			marker_identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
			condition_identity->semantic_kind != policy->volatile_kind ||
			marker_identity->semantic_kind != policy->marker_kind ||
			policy->volatile_kind == POKEMON_VOLATILE_NONE ||
			policy->marker_kind == POKEMON_VOLATILE_NONE ||
			policy->maximum_hits == 0 || policy->power_multiplier < 2 ||
			policy->refresh_duration <= 1) return 0;
		for (size_t j = 0; j < i; j++) {
			const PokemonLockedRampPolicy *earlier =
				&data->locked_ramp_policies[j];
			if (earlier->id == policy->id || earlier->move_id == policy->move_id ||
				earlier->volatile_kind == policy->volatile_kind ||
				earlier->condition_descriptor_id ==
					policy->condition_descriptor_id) return 0;
		}
	}
	for (size_t i = 0; i < generation->condition_rule_count; i++) {
		for (size_t j = 0; j < i; j++) {
			if (generation->condition_rules[i].kind !=
					generation->condition_rules[j].kind) continue;
			if (generation->condition_rules[i].kind ==
					POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN) continue;
			if (!(generation->condition_rules[i].flags &
					POKEMON_CONDITION_RULE_REPEATABLE_FAMILY) ||
				!(generation->condition_rules[j].flags &
					POKEMON_CONDITION_RULE_REPEATABLE_FAMILY)) return 0;
		}
	}
	return 1;
}

static int valid_counter_heal_policies(
    const PokemonData *data, const PokemonGeneration *generation
) {
    if ((data->counter_heal_policy_count != 0) !=
        (data->counter_heal_policies != NULL)) return 0;
    for (size_t i = 0; i < data->counter_heal_policy_count; i++) {
        const PokemonCounterHealPolicy *policy =
            &data->counter_heal_policies[i];
        const PokemonConditionRule *rule = NULL;
        const PokemonConditionIdentity *identity = NULL;
        for (size_t j = 0; j < generation->condition_rule_count; j++) {
            if (generation->condition_rules[j].descriptor_id ==
                    policy->condition_descriptor_id) {
                rule = &generation->condition_rules[j];
            }
        }
        for (size_t j = 0; j < data->condition_catalog_count; j++) {
            if (data->condition_catalog[j].catalog_id ==
                    policy->condition_descriptor_id) {
                identity = &data->condition_catalog[j];
            }
        }
        if (policy->id == 0 ||
            policy->volatile_kind <= POKEMON_VOLATILE_NONE ||
            policy->volatile_kind >= POKEMON_VOLATILE_KIND_COUNT ||
            policy->default_counter == 0 ||
            policy->maximum_counter == 0 ||
            policy->default_counter > policy->maximum_counter ||
            policy->maximum_counter > POKEMON_COUNTER_HEAL_MAX_ENTRIES ||
            rule == NULL ||
            rule->lifecycle_duration.kind != POKEMON_CONDITION_DURATION_NONE ||
            identity == NULL ||
            identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
            identity->semantic_kind != policy->volatile_kind) return 0;
        for (uint8_t counter = 0; counter < policy->maximum_counter; counter++) {
            if (policy->modifiers_q12[counter] == 0 ||
                policy->modifiers_q12[counter] > 4096) return 0;
        }
        for (uint8_t counter = policy->maximum_counter;
             counter < POKEMON_COUNTER_HEAL_MAX_ENTRIES; counter++) {
            if (policy->modifiers_q12[counter] != 0) return 0;
        }
        for (size_t j = 0; j < i; j++) {
            if (data->counter_heal_policies[j].id == policy->id ||
                data->counter_heal_policies[j].condition_descriptor_id ==
                    policy->condition_descriptor_id) return 0;
        }
    }
    return 1;
}

static int valid_type_response_policies(const PokemonData *data) {
    if ((data->type_response_policy_count != 0) !=
        (data->type_response_policies != NULL)) return 0;
    for (size_t i = 0; i < data->type_response_policy_count; i++) {
        const PokemonTypeResponsePolicy *policy =
            &data->type_response_policies[i];
        uint8_t found_override_move = 0;
        for (size_t move = 0; move < data->move_catalog_count; move++) {
            found_override_move |= data->move_catalog[move].catalog_id ==
                policy->move_type_override_catalog_id;
        }
        if (policy->id == 0 || policy->candidate_types == NULL ||
            policy->candidate_count == 0 ||
            policy->candidate_count > data->type_count ||
            policy->resistant_multiplier_q2 ==
                policy->immune_multiplier_q2 ||
            policy->resistant_multiplier_q2 > 8 ||
            policy->immune_multiplier_q2 > 8 ||
            policy->exclude_source_current_types > 1 ||
            !found_override_move ||
            policy->move_type_override >= data->type_count) return 0;
        for (size_t candidate = 0;
             candidate < policy->candidate_count; candidate++) {
            if (policy->candidate_types[candidate] >= data->type_count) return 0;
            for (size_t earlier = 0; earlier < candidate; earlier++) {
                if (policy->candidate_types[earlier] ==
                    policy->candidate_types[candidate]) return 0;
            }
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->type_response_policies[earlier].id == policy->id) return 0;
        }
    }
    return 1;
}

static int valid_move_invocation_profiles(const PokemonData *data) {
    if ((data->move_invocation_profile_count != 0) !=
            (data->move_invocation_profiles != NULL) ||
        (data->move_profile_selection_count != 0) !=
            (data->move_profile_selections != NULL) ||
        data->type_count > 32) return 0;
    uint32_t valid_type_mask = data->type_count == 32 ? UINT32_MAX :
        ((UINT32_C(1) << data->type_count) - 1u);
    for (size_t i = 0; i < data->move_invocation_profile_count; i++) {
        const PokemonMoveInvocationProfile *profile =
            &data->move_invocation_profiles[i];
        uint8_t owner_exists = 0;
        for (size_t move = 0; move < data->move_count; move++) {
            owner_exists |= data->moves[move].id == profile->owner_move_id;
        }
        if (profile->id == 0 || profile->tag == 0 || !owner_exists ||
            profile->target < POKEMON_TARGET_ADJACENT_ALLY ||
            profile->target > POKEMON_TARGET_SELF ||
            (size_t)profile->effect_offset + profile->effect_count >
                data->effect_count) return 0;
        uint8_t has_self_drop = 0;
        for (size_t effect = 0; effect < profile->effect_count; effect++) {
            const PokemonEffectOp *op =
                &data->effects[profile->effect_offset + effect];
            if (op->phase == POKEMON_EFFECT_PHASE_SELF_DROP) {
                has_self_drop = 1;
                if (op->kind != POKEMON_EFFECT_BOOST ||
                    op->target != POKEMON_EFFECT_TARGET_USER ||
                    op->chance == 0 || op->chance > 100 ||
                    op->argument >= POKEMON_STAT_COUNT || op->amount == 0) {
                    return 0;
                }
            } else if (op->phase != POKEMON_EFFECT_PHASE_PRIMARY) {
                return 0;
            }
        }
        if (has_self_drop) {
            for (size_t effect = 0; effect < profile->effect_count; effect++) {
                if (data->effects[profile->effect_offset + effect].phase !=
                    POKEMON_EFFECT_PHASE_SELF_DROP) return 0;
            }
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            const PokemonMoveInvocationProfile *other =
                &data->move_invocation_profiles[earlier];
            if (other->id == profile->id ||
                (other->owner_move_id == profile->owner_move_id &&
                 other->tag == profile->tag)) return 0;
        }
    }
    for (size_t i = 0; i < data->move_profile_selection_count; i++) {
        const PokemonMoveProfileSelection *selection =
            &data->move_profile_selections[i];
        const PokemonMoveInvocationProfile *matching =
            find_move_invocation_profile(data, selection->matching_profile_id);
        const PokemonMoveInvocationProfile *nonmatching =
            find_move_invocation_profile(data, selection->nonmatching_profile_id);
        if (selection->id == 0 || selection->current_user_type_mask == 0 ||
            (selection->current_user_type_mask & ~valid_type_mask) != 0 ||
            selection->matching_profile_id ==
                selection->nonmatching_profile_id ||
            matching == NULL || nonmatching == NULL ||
            matching->owner_move_id != nonmatching->owner_move_id) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->move_profile_selections[earlier].id == selection->id) {
                return 0;
            }
        }
    }
    return 1;
}

static int valid_resolved_bundle(const PokemonResolvedBundle *bundle) {
    if (bundle == NULL || bundle->rules == NULL || bundle->data == NULL ||
        bundle->runtime_format == NULL || bundle->policy == NULL ||
        bundle->manifest == NULL || bundle->plugin_fingerprint == 0 ||
        bundle->capability_version != POKEMON_KERNEL_PLUGIN_ABI_VERSION ||
        (bundle->capabilities & ~POKEMON_CAP_KNOWN) != 0 ||
        (bundle->capabilities & POKEMON_CAP_REQUIRED_BASE) !=
            POKEMON_CAP_REQUIRED_BASE) {
        return 0;
    }
    const PokemonGeneration *rules = bundle->rules;
    const PokemonData *data = bundle->data;
    const PokemonFormat *format = bundle->runtime_format;
    const PokemonFormatPolicy *policy = bundle->policy;
    const PokemonFormatManifest *manifest = bundle->manifest;
#define POKEMON_COMPONENT_MATCHES(component) \
    ((component)->plugin_fingerprint == bundle->plugin_fingerprint && \
     (component)->capability_version == bundle->capability_version && \
     (component)->capabilities == bundle->capabilities && \
     (component)->generation == bundle->generation)
    int coherent = bundle->generation != 0 &&
        POKEMON_COMPONENT_MATCHES(rules) &&
        POKEMON_COMPONENT_MATCHES(data) &&
        POKEMON_COMPONENT_MATCHES(format) &&
        POKEMON_COMPONENT_MATCHES(policy) &&
        POKEMON_COMPONENT_MATCHES(manifest) && policy->manifest == manifest;
#undef POKEMON_COMPONENT_MATCHES
    if (!coherent || rules->hit_staging !=
            POKEMON_HIT_STAGING_DEFER_IMMUNITY_AFTER_ACCURACY_AND_TRY_HIT ||
        !pokemon_validate_move_call_pools(data) ||
        !valid_move_pre_use_programs(data) ||
		!valid_locked_ramp_policies(data, rules) ||
        !valid_counter_heal_policies(data, rules) ||
        !valid_type_response_policies(data) ||
        !valid_move_invocation_profiles(data) ||
        !pokemon_validate_constructed_hit_templates(data)) return 0;
    if ((policy->status_clause_count != 0) !=
            (policy->status_clauses != NULL)) return 0;
    if (policy->voluntary_switch_order !=
            POKEMON_VOLUNTARY_SWITCH_ORDER_SPEED ||
        policy->protocol.report_hp_percentages > 1 ||
        policy->protocol.allow_uncommitted_choice_cancel > 1 ||
        policy->protocol.hide_beat_up_party_identity > 1 ||
        policy->terminal.endless_battle_clause > 1 ||
        (policy->terminal.endless_battle_clause &&
         policy->terminal.endless_minimum_turn == 0) ||
        (policy->terminal.turn_limit != 0 &&
         policy->terminal.turn_limit <=
            policy->terminal.endless_minimum_turn)) return 0;
    for (size_t i = 0; i < policy->status_clause_count; i++) {
        const PokemonStatusClausePolicy *clause =
            &policy->status_clauses[i];
        const PokemonHandlerDescriptor *descriptor = NULL;
        for (size_t handler = 0; handler < data->handler_count; handler++) {
            if (data->handlers[handler].id == clause->handler_id) {
                descriptor = &data->handlers[handler];
                break;
            }
        }
        if (clause->status <= POKEMON_STATUS_NONE ||
            clause->status > POKEMON_STATUS_FREEZE ||
            clause->handler_id == 0 || clause->requires_opposing_source > 1 ||
            clause->block_any_existing > 1 ||
            clause->block_living_opponent_caused > 1 ||
            clause->block_any_existing ==
                clause->block_living_opponent_caused ||
            descriptor == NULL ||
            descriptor->event != POKEMON_HANDLER_EVENT_SET_STATUS ||
            descriptor->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
            descriptor->exceptional_handler_id !=
                POKEMON_EXCEPTION_STATUS_CLAUSE ||
            descriptor->scope != POKEMON_HANDLER_SCOPE_TARGET ||
            descriptor->route != POKEMON_HANDLER_ROUTE_OWNER ||
            descriptor->program_count != 0) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (policy->status_clauses[earlier].status == clause->status ||
                policy->status_clauses[earlier].handler_id ==
                    clause->handler_id) return 0;
        }
    }
    uint8_t has_events = data->event_spec_count != 0;
    uint8_t has_handlers = data->handler_count != 0 ||
        data->owner_binding_index_count != 0 || data->handler_program_count != 0;
    uint8_t has_effects = data->effect_count != 0;
    if ((has_events && !(bundle->capabilities & POKEMON_CAP_EVENT_INTERPRETER)) ||
        (has_handlers && !(bundle->capabilities & POKEMON_CAP_HANDLER_PROGRAMS)) ||
        (has_effects && !(bundle->capabilities & POKEMON_CAP_EFFECT_PROGRAMS)) ||
        (has_events && data->event_specs == NULL) ||
        (data->handler_count != 0 && data->handlers == NULL) ||
        (data->owner_binding_index_count != 0 &&
            data->owner_binding_index == NULL) ||
        (data->handler_program_count != 0 && data->handler_programs == NULL) ||
        ((data->two_turn_move_count != 0) !=
            (data->two_turn_moves != NULL)) ||
        ((data->weighted_move_outcome_count != 0) !=
            (data->weighted_move_outcomes != NULL)) ||
        ((data->weighted_move_distribution_count != 0) !=
            (data->weighted_move_distributions != NULL)) ||
        ((data->status_distribution_count != 0) !=
            (data->status_distributions != NULL)) ||
        ((data->status_distribution_candidate_count != 0) !=
            (data->status_distribution_candidates != NULL)) ||
        ((data->weather_form_policy_count != 0) !=
            (data->weather_form_policies != NULL)) ||
        ((data->weight_power_policy_count != 0) !=
            (data->weight_power_policies != NULL)) ||
        ((data->transform_policy_count != 0) !=
            (data->transform_policies != NULL)) ||
        (data->transform_policy_count != 0 &&
            rules->recalculate_species_stat == NULL) ||
        ((data->constructed_hit_template_count != 0) !=
            (data->constructed_hit_templates != NULL)) ||
        (has_effects && data->effects == NULL) ||
        ((data->effect_secondary_group_count != 0) !=
            (data->effect_secondary_groups != NULL)) ||
        (data->effect_secondary_group_count != 0 &&
            data->effect_secondary_group_count != data->effect_count) ||
        ((data->secondary_chance_policy_count != 0) !=
            (data->secondary_chance_policies != NULL)) ||
        ((data->status_residual_policy_count != 0) !=
            (data->status_residual_policies != NULL)) ||
        data->slot_condition_policy_count == 0 ||
        data->slot_condition_policies == NULL ||
        data->slot_condition_policy_count > POKEMON_SLOT_CONDITION_CAPACITY ||
        data->weather_policy_count == 0 || data->weather_policies == NULL ||
        rules->condition_rule_count == 0 || rules->condition_rules == NULL ||
        rules->critical_chance == NULL || rules->multihit.outcomes == NULL ||
        rules->base_damage == NULL || rules->resolve_damage_formula == NULL ||
        rules->residual_damage == NULL || rules->fraction == NULL ||
        format->target_rules == NULL || format->target_rule_count == 0 ||
        manifest->game_type != POKEMON_GAME_TYPE_SINGLES ||
        format->active_per_side != 1) return 0;
    for (size_t handler_index = 0; handler_index < data->handler_count;
         handler_index++) {
        const PokemonHandlerDescriptor *handler =
            &data->handlers[handler_index];
        if ((size_t)handler->program_offset + handler->program_count >
                data->handler_program_count) return 0;
        if (handler->required_move_profile_tag != 0) {
            uint8_t found_profile = 0;
            if (handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) return 0;
            for (size_t profile = 0;
                 profile < data->move_invocation_profile_count; profile++) {
                const PokemonMoveInvocationProfile *candidate =
                    &data->move_invocation_profiles[profile];
                found_profile |= candidate->owner_move_id == handler->source_id &&
                    candidate->tag == handler->required_move_profile_tag;
            }
            if (!found_profile) return 0;
        }
        for (size_t program_index = 0; program_index < handler->program_count;
             program_index++) {
            const PokemonHandlerOp *op = &data->handler_programs[
                handler->program_offset + program_index];
            if (op->opcode ==
                    POKEMON_HANDLER_OP_CLEAR_LIVING_ACTIVE_STATUS_MASK &&
                !valid_clear_living_active_status_op(handler, op)) return 0;
            if (op->opcode ==
                    POKEMON_HANDLER_OP_GUARD_HOLDER_ATTACKED_BY_TARGET_THIS_TURN &&
                !valid_attacked_by_target_guard(handler, op)) return 0;
            if (op->opcode ==
                    POKEMON_HANDLER_OP_REQUIRE_HOLDER_WITHOUT_VOLATILE_KIND &&
                !valid_require_holder_without_volatile_op(handler, op)) return 0;
            if (op->opcode == POKEMON_HANDLER_OP_MULTIPLY_RELAY_U32 &&
                !valid_direct_u32_relay_multiplier(handler, op)) return 0;
            if (op->opcode ==
                    POKEMON_HANDLER_OP_COPY_EVENT_TARGET_BATTLE_PROFILE &&
                (handler->program_count != 1 ||
                 handler->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                 handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                 handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                 handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                 transform_policy(data, (uint16_t)op->argument) == NULL)) {
                return 0;
            }
            if (op->opcode ==
                    POKEMON_HANDLER_OP_GUARD_ACTIVE_MOVE_TARGET_STATUS_MASK) {
                const uint32_t valid_statuses =
                    ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
                    ~UINT32_C(1);
                if (handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    op->argument == 0 ||
                    (op->argument & ~valid_statuses) != 0) return 0;
            }
            if (op->opcode ==
                    POKEMON_HANDLER_OP_CLEAR_ACTIVE_MOVE_TARGET_MAJOR_STATUS &&
                (handler->event !=
                    POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                 handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                 handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                 handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                 op->argument != 0)) return 0;
            if (op->opcode ==
                    POKEMON_HANDLER_OP_PAY_MAX_HP_FRACTION_AND_MAXIMIZE_HOLDER_STAT) {
                uint8_t stat = (uint8_t)(op->argument >> 16);
                uint8_t numerator = (uint8_t)(op->argument >> 8);
                uint8_t denominator = (uint8_t)op->argument;
                if (handler->program_count != 1 ||
                    handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    (op->argument >> 24) != 0 ||
                    stat >= POKEMON_STAT_COUNT || numerator == 0 ||
                    denominator == 0 || numerator >= denominator) return 0;
            }
        }
    }
    for (size_t i = 0; i < data->weather_policy_count; i++) {
        const PokemonWeatherPolicy *weather = &data->weather_policies[i];
        if (weather->descriptor_id == 0 ||
            weather->kind <= POKEMON_WEATHER_NONE ||
            weather->kind > POKEMON_WEATHER_SUN ||
            weather->residual_damage_formula > POKEMON_RESIDUAL_FORMULA_TOXIC ||
            (weather->blocked_status_mask >> (POKEMON_STATUS_FREEZE + 1u)) != 0) {
            return 0;
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->weather_policies[earlier].kind == weather->kind ||
                data->weather_policies[earlier].descriptor_id ==
                    weather->descriptor_id) return 0;
        }
    }
    for (size_t i = 0; i < data->slot_condition_policy_count; i++) {
        const PokemonSlotConditionPolicy *slot =
            &data->slot_condition_policies[i];
        const PokemonConditionIdentity *identity =
            pokemon_condition_identity(data, slot->descriptor_id);
        if (slot->descriptor_id == 0 || slot->semantic_kind == 0 ||
            slot->effect_kind < POKEMON_SLOT_EFFECT_DELAYED_FIXED_DAMAGE ||
            slot->effect_kind >
                POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION ||
            slot->duration == 0 || slot->residual_order == 0 ||
            identity == NULL || identity->domain != POKEMON_CONDITION_DOMAIN_SLOT ||
            identity->semantic_kind != slot->semantic_kind ||
            ((slot->effect_kind ==
                POKEMON_SLOT_EFFECT_HEAL_ACTIVE_MAX_HP_FRACTION) !=
             (slot->numerator != 0 && slot->denominator != 0 &&
              slot->numerator <= slot->denominator))) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->slot_condition_policies[earlier].descriptor_id ==
                    slot->descriptor_id ||
                data->slot_condition_policies[earlier].semantic_kind ==
                    slot->semantic_kind) return 0;
        }
    }
    for (size_t i = 0; i < data->move_count; i++) {
        const PokemonMoveData *move = &data->moves[i];
        if (!valid_ohko_move(data, move) ||
            (move->ohko.kind != POKEMON_OHKO_NONE &&
             move->accuracy.percent != rules->ohko.base_accuracy) ||
            move->pre_turn_target > POKEMON_PRE_TURN_TARGET_MOVE_TARGET ||
            move->checks_natural_type_immunity > 1 ||
            (move->pre_turn_blocked_status_mask >>
                (POKEMON_STATUS_FREEZE + 1u)) != 0 ||
            move->switching_target_always_hit > 1 ||
            ((move->base_power_policy == POKEMON_BASE_POWER_TARGET_WEIGHT) !=
                (move->weight_power_policy_id != 0)) ||
            (move->weight_power_policy_id != 0 &&
                weight_power_policy(data, move->weight_power_policy_id) == NULL) ||
            ((move->switching_target_always_hit != 0 ||
              move->switching_target_power_multiplier != 0 ||
              move->pre_turn_target == POKEMON_PRE_TURN_TARGET_MOVE_TARGET) &&
             move->pre_turn_condition_descriptor == 0) ||
            (move->pre_turn_condition_descriptor != 0 &&
             condition_rule_by_descriptor((const PokemonBattle *)&(PokemonBattle){
                 .generation = rules}, move->pre_turn_condition_descriptor) == NULL)) {
            return 0;
        }
        if (move->slot_condition_descriptor != 0 &&
            slot_condition_policy(
                data, move->slot_condition_descriptor) == NULL) {
            return 0;
        }
    }
    for (size_t i = 0; i < data->species_count; i++) {
        if (data->species[i].id == 0 || data->species[i].weight_hg == 0) return 0;
    }
    for (size_t i = 0; i < data->species_catalog_count; i++) {
        if (data->species_catalog[i].catalog_id == 0 ||
            data->species_catalog[i].weight_hg == 0) return 0;
    }
    for (size_t i = 0; i < data->weight_power_policy_count; i++) {
        const PokemonWeightPowerPolicy *weight =
            &data->weight_power_policies[i];
        if (weight->id == 0 || weight->bracket_count < 2 ||
            weight->bracket_count > POKEMON_WEIGHT_POWER_MAX_BRACKETS) return 0;
        for (size_t bracket = 0; bracket < weight->bracket_count; bracket++) {
            if (weight->powers[bracket] == 0 ||
                weight->powers[bracket] > UINT8_MAX) return 0;
            if (bracket + 1u < weight->bracket_count &&
                (weight->upper_bounds_hg[bracket] == 0 ||
                 (bracket != 0 && weight->upper_bounds_hg[bracket] <=
                    weight->upper_bounds_hg[bracket - 1]))) return 0;
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->weight_power_policies[earlier].id == weight->id) return 0;
        }
    }
    for (size_t i = 0; i < data->transform_policy_count; i++) {
        const PokemonTransformPolicy *policy = &data->transform_policies[i];
        if (policy->id == 0 || policy->personal_move_profile_kind == 0 ||
            policy->copied_move_pp_cap == 0 ||
            policy->reject_source_transformed > 1 ||
            policy->reject_target_transformed > 1 ||
            policy->reject_target_substitute > 1 ||
            policy->copied_ability_runs_start > 1) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->transform_policies[earlier].id == policy->id) return 0;
        }
    }
    for (size_t i = 0; i < data->constructed_hit_template_count; i++) {
        const PokemonConstructedHitTemplate *template =
            &data->constructed_hit_templates[i];
        const PokemonMoveData *move = &template->move;
        const PokemonConditionIdentity *identity = pokemon_condition_identity(
            data, template->owner_condition_descriptor);
        const PokemonConditionRule *rule = condition_rule_by_descriptor(
            (const PokemonBattle *)&(PokemonBattle){.generation = rules},
            template->owner_condition_descriptor);
        const PokemonMoveData *source_move = NULL;
        for (size_t source = 0; source < data->move_count; source++) {
            if (data->moves[source].id == move->id) {
                source_move = &data->moves[source];
                break;
            }
        }
        if (template->id == 0 ||
            template->target_policy !=
                POKEMON_CONSTRUCTED_TARGET_LAST_SOURCE_OR_CURRENT_FOE ||
            identity == NULL ||
            identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
            identity->semantic_kind != POKEMON_VOLATILE_STORED_DAMAGE ||
            rule == NULL || rule->kind != POKEMON_RULE_CONDITION_STORED_DAMAGE ||
            source_move == NULL ||
            source_move->catalog_id != move->catalog_id ||
            move_resolution(move) != POKEMON_MOVE_RESOLUTION_DAMAGE ||
            move->category == POKEMON_CATEGORY_STATUS || move->power != 0 ||
            !valid_accuracy(move->accuracy) ||
            move->damage_formula != POKEMON_DAMAGE_OWNER_CONDITION_VALUE ||
            move->damage_parameter != template->owner_condition_descriptor ||
            move->owner_condition_damage_multiplier == 0 ||
            move->effect_count != 0 || move->multihit_min != 0 ||
            move->multihit_max != 0 || move->target != POKEMON_TARGET_NORMAL ||
            move->call_pool_id != 0 || move->pre_turn_condition_descriptor != 0 ||
            move->slot_condition_descriptor != 0) {
            return 0;
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->constructed_hit_templates[earlier].id == template->id ||
                data->constructed_hit_templates[earlier]
                    .owner_condition_descriptor ==
                    template->owner_condition_descriptor) return 0;
        }
    }
    for (size_t i = 0; i < data->secondary_chance_policy_count; i++) {
        const PokemonSecondaryChancePolicy *policy =
            &data->secondary_chance_policies[i];
        if (policy->ability_id == 0 || policy->numerator == 0 ||
            policy->denominator == 0) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->secondary_chance_policies[earlier].ability_id ==
                policy->ability_id) return 0;
        }
    }
    for (size_t i = 0; i < data->ability_count; i++) {
        const uint8_t known_flags =
            POKEMON_ABILITY_SEMANTIC_BLOCKS_EXTERNAL_ITEM_TAKE |
            POKEMON_ABILITY_SEMANTIC_CANT_SUPPRESS |
            POKEMON_ABILITY_SEMANTIC_FAIL_ROLE_PLAY |
            POKEMON_ABILITY_SEMANTIC_FAIL_SKILL_SWAP |
            POKEMON_ABILITY_SEMANTIC_CYCLES_RESTORATIVE_ITEM;
        if ((data->abilities[i].semantic_flags &
                (uint8_t)~known_flags) != 0) return 0;
    }
    for (size_t i = 0; i < data->status_residual_policy_count; i++) {
        const PokemonStatusResidualPolicy *status_policy =
            &data->status_residual_policies[i];
        const PokemonConditionIdentity *condition =
            pokemon_condition_identity(data, status_policy->descriptor_id);
        const PokemonConditionRule *rule = NULL;
        for (size_t j = 0; j < rules->condition_rule_count; j++) {
            if (rules->condition_rules[j].descriptor_id ==
                    status_policy->descriptor_id) {
                rule = &rules->condition_rules[j];
                break;
            }
        }
        if (status_policy->status <= POKEMON_STATUS_NONE ||
            status_policy->status > POKEMON_STATUS_FREEZE || condition == NULL ||
            condition->domain != POKEMON_CONDITION_DOMAIN_STATUS ||
            condition->semantic_kind != status_policy->status || rule == NULL ||
            !rule->has_residual || !rule->has_order ||
            status_policy->formula < POKEMON_RESIDUAL_FORMULA_BURN ||
            status_policy->formula > POKEMON_RESIDUAL_FORMULA_TOXIC ||
            status_policy->state_policy < POKEMON_STATUS_RESIDUAL_STATELESS ||
            status_policy->state_policy >
                POKEMON_STATUS_RESIDUAL_ESCALATE ||
            ((status_policy->formula == POKEMON_RESIDUAL_FORMULA_TOXIC) !=
             (status_policy->state_policy ==
                POKEMON_STATUS_RESIDUAL_ESCALATE))) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            const PokemonStatusResidualPolicy *other =
                &data->status_residual_policies[earlier];
            if (other->descriptor_id == status_policy->descriptor_id ||
                other->status == status_policy->status) return 0;
        }
    }
    for (size_t i = 0; i < data->item_count; i++) {
        const uint8_t known_flags =
            POKEMON_ITEM_FLAG_RESTRICT_EXTERNAL_TAKE |
            POKEMON_ITEM_FLAG_SHARED_TURN_SPEED_SENTINEL |
            POKEMON_ITEM_FLAG_RESTORATIVE;
        const PokemonItemData *item = &data->items[i];
        if ((item->flags & (uint8_t)~known_flags) != 0 ||
            (item->eligible_boost_mask &
                (uint8_t)~((UINT8_C(1) << POKEMON_STAT_COUNT) - 1u)) != 0 ||
            (item->eligible_boost_mask != 0 && item->boost_delta == 0) ||
            ((item->flags & POKEMON_ITEM_FLAG_SHARED_TURN_SPEED_SENTINEL) != 0 &&
             rules->shared_turn_speed.numerator == 0)) return 0;
    }
    for (size_t i = 0; i < data->two_turn_move_count; i++) {
        const PokemonTwoTurnMoveDescriptor *descriptor =
            &data->two_turn_moves[i];
        uint8_t found_move = 0;
        uint8_t found_marker = 0;
        if (descriptor->move_id == 0 || descriptor->marker_descriptor_id == 0 ||
            descriptor->marker_duration > 2 ||
            (descriptor->charge_boost_delta == 0 &&
                descriptor->charge_boost_stat != 0) ||
            descriptor->charge_boost_stat >= POKEMON_STAT_COUNT ||
            descriptor->charge_boost_delta < 0 ||
            descriptor->charge_boost_delta > 6) {
            return 0;
        }
        for (size_t move = 0; move < data->move_count; move++) {
            found_move |= data->moves[move].id == descriptor->move_id;
        }
        for (size_t condition = 0; condition < data->condition_catalog_count;
             condition++) {
            const PokemonConditionIdentity *identity =
                &data->condition_catalog[condition];
            found_marker |= identity->catalog_id ==
                    descriptor->marker_descriptor_id &&
                identity->domain == POKEMON_CONDITION_DOMAIN_VOLATILE &&
                identity->semantic_kind == POKEMON_VOLATILE_TWO_TURN_MARKER;
        }
        if (!found_move || !found_marker) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->two_turn_moves[earlier].move_id == descriptor->move_id) {
                return 0;
            }
        }
    }
    for (size_t i = 0;
         i < data->weighted_move_distribution_count; i++) {
        const PokemonWeightedMoveOutcomeDistribution *distribution =
            &data->weighted_move_distributions[i];
        if (distribution->id == 0 || distribution->outcome_count == 0 ||
            (distribution->draw_label !=
                 POKEMON_DRAW_MOVE_POWER_DISTRIBUTION &&
             distribution->draw_label !=
                 POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION) ||
            distribution->outcome_offset >
                data->weighted_move_outcome_count ||
            distribution->outcome_count >
                data->weighted_move_outcome_count -
                    distribution->outcome_offset) return 0;
        uint32_t total = 0;
        for (size_t outcome = 0; outcome < distribution->outcome_count;
             outcome++) {
            const PokemonWeightedMoveOutcome *entry =
                &data->weighted_move_outcomes[
                    distribution->outcome_offset + outcome];
            if (entry->weight == 0 || UINT32_MAX - total < entry->weight) {
                return 0;
            }
            if (entry->kind == POKEMON_WEIGHTED_MOVE_OUTCOME_DAMAGE) {
                if (entry->value.damage.power == 0) return 0;
            } else if (entry->kind ==
                    POKEMON_WEIGHTED_MOVE_OUTCOME_TARGET_MAX_HP_HEAL) {
                if (entry->value.heal.numerator == 0 ||
                    entry->value.heal.denominator == 0 ||
                    entry->value.heal.numerator >
                        entry->value.heal.denominator) return 0;
            } else {
                return 0;
            }
            total += entry->weight;
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->weighted_move_distributions[earlier].id ==
                    distribution->id) return 0;
        }
    }
    for (size_t i = 0; i < data->status_distribution_count; i++) {
        const PokemonStatusDistribution *distribution =
            &data->status_distributions[i];
        if (distribution->id == 0 || distribution->candidate_count == 0 ||
            distribution->draw_label !=
                POKEMON_DRAW_MOVE_STATUS_SELECTION ||
            distribution->candidate_offset >
                data->status_distribution_candidate_count ||
            distribution->candidate_count >
                data->status_distribution_candidate_count -
                    distribution->candidate_offset) return 0;
        for (size_t candidate = 0;
             candidate < distribution->candidate_count; candidate++) {
            uint8_t status = data->status_distribution_candidates[
                distribution->candidate_offset + candidate];
            if (status <= POKEMON_STATUS_NONE ||
                status > POKEMON_STATUS_FREEZE) return 0;
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->status_distributions[earlier].id == distribution->id) {
                return 0;
            }
        }
    }
    for (size_t i = 0; i < data->weather_form_policy_count; i++) {
        const PokemonWeatherFormPolicy *policy =
            &data->weather_form_policies[i];
        const uint16_t ids[4] = {policy->clear_species_id,
            policy->sun_species_id, policy->rain_species_id,
            policy->hail_species_id};
        const PokemonSpeciesIdentity *base =
            species_identity_by_executable_id(data, policy->base_species_id);
        if (policy->id == 0 || base == NULL ||
            policy->base_species_id != policy->clear_species_id) return 0;
        for (size_t form = 0; form < 4; form++) {
            const PokemonSpeciesIdentity *identity =
                species_identity_by_executable_id(data, ids[form]);
            if (identity == NULL || identity->source_num != base->source_num ||
                memcmp(identity->base_stats, base->base_stats,
                    sizeof(base->base_stats)) != 0) return 0;
            for (size_t earlier = 0; earlier < form; earlier++) {
                if (ids[earlier] == ids[form]) return 0;
            }
        }
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->weather_form_policies[earlier].id == policy->id ||
                data->weather_form_policies[earlier].base_species_id ==
                    policy->base_species_id) return 0;
        }
    }
    /* Hidden linkedStatus counterparts are normalized into their visible
     * relation.  This kernel capability preserves their admission and effect
     * ordering but intentionally admits only callback-free marker
     * descriptors; a generation needing executable marker callbacks must
     * request a stronger kernel capability instead of silently dropping them. */
    for (size_t i = 0; i < rules->condition_rule_count; i++) {
        const PokemonConditionRule *owner = &rules->condition_rules[i];
        if (owner->source_linked_kind == POKEMON_VOLATILE_NONE) continue;
        uint16_t linked_descriptor = rules->condition_descriptor(
            POKEMON_OWNER_VOLATILE, owner->source_linked_kind);
        const PokemonConditionRule *linked_rule = NULL;
        const PokemonConditionIdentity *linked_identity = NULL;
        for (size_t j = 0; j < rules->condition_rule_count; j++) {
            if (rules->condition_rules[j].descriptor_id == linked_descriptor) {
                linked_rule = &rules->condition_rules[j];
                break;
            }
        }
        linked_identity = pokemon_condition_identity(data, linked_descriptor);
        if (linked_descriptor == 0 || linked_descriptor == owner->descriptor_id ||
            linked_rule == NULL || linked_identity == NULL ||
            linked_identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE ||
            linked_identity->semantic_kind != owner->source_linked_kind ||
            linked_rule->source_linked_kind != POKEMON_VOLATILE_NONE ||
            linked_rule->has_residual ||
            linked_rule->lifecycle_duration.kind !=
                POKEMON_CONDITION_DURATION_NONE) return 0;
        for (size_t binding = 0; binding < data->owner_binding_index_count;
             binding++) {
            const PokemonOwnerBindingIndex *index =
                &data->owner_binding_index[binding];
            if (index->owner_kind == POKEMON_OWNER_VOLATILE &&
                index->owner_id == linked_descriptor) return 0;
        }
    }
    /* Ability/item Start and End are direct void lifecycle notifications.
     * Condition Start may legitimately reject installation, so cancellation
     * opcodes are forbidden only at this narrower owner boundary. */
    for (size_t i = 0; i < data->handler_count; i++) {
        const PokemonHandlerDescriptor *handler = &data->handlers[i];
        if ((handler->event != POKEMON_HANDLER_EVENT_START &&
             handler->event != POKEMON_HANDLER_EVENT_END) ||
            (handler->source_kind != POKEMON_HANDLER_SOURCE_ABILITY &&
             handler->source_kind != POKEMON_HANDLER_SOURCE_ITEM)) continue;
        if ((size_t)handler->program_offset + handler->program_count >
            data->handler_program_count) return 0;
        for (size_t program = 0; program < handler->program_count; program++) {
            PokemonHandlerOpcode opcode = data->handler_programs[
                handler->program_offset + program].opcode;
            if (opcode == POKEMON_HANDLER_OP_RETURN_TRUE ||
                opcode == POKEMON_HANDLER_OP_RETURN_FALSE ||
                opcode == POKEMON_HANDLER_OP_RETURN_NOT_FAIL) return 0;
        }
    }
    for (size_t i = 0; i < rules->choice_control_policy_count; i++) {
        const PokemonChoiceControlPolicy *choice =
            &rules->choice_control_policies[i];
        uint16_t descriptor =
            choice->owner_descriptor_id;
        uint8_t found_rule = 0;
        uint8_t found_catalog = 0;
        const PokemonConditionRule *matched_rule = NULL;
        for (size_t j = 0; j < rules->condition_rule_count; j++) {
            if (rules->condition_rules[j].descriptor_id == descriptor) {
                found_rule = 1;
                matched_rule = &rules->condition_rules[j];
            }
        }
        for (size_t j = 0; j < data->condition_catalog_count; j++) {
            const PokemonConditionIdentity *condition =
                &data->condition_catalog[j];
            found_catalog |= condition->catalog_id == descriptor &&
                condition->domain == POKEMON_CONDITION_DOMAIN_VOLATILE &&
                condition->semantic_kind != 0;
        }
        if (!found_rule || !found_catalog ||
            (choice->residual_op != POKEMON_CHOICE_RESIDUAL_NONE &&
             (!matched_rule->has_residual ||
              matched_rule->lifecycle_duration.kind ==
                  POKEMON_CONDITION_DURATION_NONE))) {
            return 0;
        }
        if (choice->synthetic_move_id != 0) {
            uint8_t found_synthetic = 0;
            for (size_t move = 0; move < data->move_count; move++) {
                found_synthetic |=
                    data->moves[move].id == choice->synthetic_move_id;
            }
            if (!found_synthetic) return 0;
        }
        if (choice->required_held_item_id != 0) {
            uint8_t found_item = 0;
            for (size_t item = 0; item < data->item_count; item++) {
                found_item |= data->items[item].id ==
                    choice->required_held_item_id;
            }
            if (!found_item) return 0;
        }
        const uint16_t ids[] = {
            choice->start_handler_id, choice->request_handler_id,
            choice->action_handler_id, choice->residual_handler_id,
        };
        for (size_t id_index = 0; id_index < sizeof(ids) / sizeof(ids[0]);
             id_index++) {
            if (ids[id_index] == 0) continue;
            for (size_t handler = 0; handler < data->handler_count; handler++) {
                if (data->handlers[handler].id == ids[id_index]) return 0;
            }
            for (size_t earlier = 0; earlier <= i; earlier++) {
                const PokemonChoiceControlPolicy *other =
                    &rules->choice_control_policies[earlier];
                const uint16_t other_ids[] = {
                    other->start_handler_id, other->request_handler_id,
                    other->action_handler_id, other->residual_handler_id,
                };
                size_t limit = earlier == i ? id_index :
                    sizeof(other_ids) / sizeof(other_ids[0]);
                for (size_t other_index = 0; other_index < limit;
                     other_index++) {
                    if (ids[id_index] == other_ids[other_index]) return 0;
                }
            }
        }
    }
    return 1;
}
#line 18651 "pokemon.c"
