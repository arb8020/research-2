#line 17 "pokemon.c"
static int valid_clear_living_active_status_op(
    const PokemonHandlerDescriptor *descriptor, const PokemonHandlerOp *op
) {
    const uint32_t valid_statuses =
        ((UINT32_C(1) << (POKEMON_STATUS_FREEZE + 1u)) - 1u) &
        ~UINT32_C(1);
    return descriptor->event == POKEMON_HANDLER_EVENT_TRY_HIT &&
        descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
        descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
        descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF &&
        op->argument != 0 && (op->argument & ~valid_statuses) == 0;
}

static int valid_attacked_by_target_guard(
    const PokemonHandlerDescriptor *descriptor, const PokemonHandlerOp *op
) {
    return descriptor->event == POKEMON_HANDLER_EVENT_BASE_POWER &&
        descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
        descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
        descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF &&
        op->argument == 0;
}

static int valid_require_holder_without_volatile_op(
    const PokemonHandlerDescriptor *descriptor, const PokemonHandlerOp *op
) {
    return descriptor->event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY &&
        descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
        descriptor->scope == POKEMON_HANDLER_SCOPE_TARGET &&
        descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF &&
        op->argument > POKEMON_VOLATILE_NONE &&
        op->argument < POKEMON_VOLATILE_KIND_COUNT;
}

static int valid_direct_u32_relay_multiplier(
    const PokemonHandlerDescriptor *descriptor, const PokemonHandlerOp *op
) {
    return descriptor->event == POKEMON_HANDLER_EVENT_BASE_POWER &&
        descriptor->source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
        descriptor->scope == POKEMON_HANDLER_SCOPE_SOURCE &&
        descriptor->route == POKEMON_HANDLER_ROUTE_MOVE_SELF &&
        op->argument >= 2;
}

const PokemonSpeciesIdentity *pokemon_species_identity(
    const PokemonData *data, uint16_t catalog_id
) {
    if (data == NULL || data->species_catalog == NULL || catalog_id == 0 ||
        catalog_id > data->species_catalog_count) return NULL;
    const PokemonSpeciesIdentity *value = &data->species_catalog[catalog_id - 1];
    return value->catalog_id == catalog_id ? value : NULL;
}

static const PokemonSpeciesIdentity *species_identity_by_executable_id(
    const PokemonData *data, uint16_t executable_id
) {
    for (size_t i = 0; i < data->species_catalog_count; i++) {
        if (data->species_catalog[i].executable_id == executable_id) {
            return &data->species_catalog[i];
        }
    }
    return NULL;
}

const PokemonMoveIdentity *pokemon_move_identity(
    const PokemonData *data, uint16_t catalog_id
) {
    if (data == NULL || data->move_catalog == NULL || catalog_id == 0 ||
        catalog_id > data->move_catalog_count) return NULL;
    const PokemonMoveIdentity *value = &data->move_catalog[catalog_id - 1];
    return value->catalog_id == catalog_id ? value : NULL;
}

static int executable_move_matches_identity(
    const PokemonData *data, const PokemonMoveIdentity *identity
) {
    if (identity->executable_id == 0) return 1;
    for (size_t i = 0; i < data->move_count; i++) {
        const PokemonMoveData *move = &data->moves[i];
        if (move->id != identity->executable_id) continue;
        return move->catalog_id == identity->catalog_id;
    }
    return 0;
}

static int pool_has_exact_call_handler(
    const PokemonData *data, const PokemonMoveCallPool *pool
) {
    if ((data->handler_count != 0 && data->handlers == NULL) ||
        (data->handler_program_count != 0 && data->handler_programs == NULL) ||
        (data->owner_binding_index_count != 0 &&
            data->owner_binding_index == NULL)) return 0;
    size_t descriptor_matches = 0;
    size_t binding_matches = 0;
    size_t matched_descriptor = 0;
    for (size_t i = 0; i < data->handler_count; i++) {
        const PokemonHandlerDescriptor *handler = &data->handlers[i];
        if ((size_t)handler->program_offset + handler->program_count >
            data->handler_program_count) return 0;
        for (size_t op = 0; op < handler->program_count; op++) {
            const PokemonHandlerOp *program =
                &data->handler_programs[handler->program_offset + op];
            if (program->opcode != POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL) {
                continue;
            }
            if (handler->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                handler->source_id != pool->caller_move_id ||
                handler->program_count != 1 || program->argument != pool->id) {
                continue;
            }
            descriptor_matches++;
            matched_descriptor = i;
        }
    }
    if (descriptor_matches != 1) return 0;
    for (size_t i = 0; i < data->owner_binding_index_count; i++) {
        const PokemonOwnerBindingIndex *binding =
            &data->owner_binding_index[i];
        if ((size_t)binding->binding_offset + binding->binding_count >
            data->handler_count) return 0;
        if (binding->owner_kind != POKEMON_OWNER_MOVE ||
            binding->owner_id != pool->caller_move_id ||
            binding->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
            binding->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
            binding->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) continue;
        if (binding->binding_count != 1 ||
            binding->binding_offset != matched_descriptor) return 0;
        binding_matches++;
    }
    return binding_matches == 1;
}

static int template_has_exact_release_handler(
    const PokemonData *data, const PokemonConstructedHitTemplate *template
) {
    size_t descriptor_matches = 0;
    size_t binding_matches = 0;
    size_t matched_descriptor = 0;
    for (size_t i = 0; i < data->handler_count; i++) {
        const PokemonHandlerDescriptor *handler = &data->handlers[i];
        if ((size_t)handler->program_offset + handler->program_count >
            data->handler_program_count) return 0;
        for (size_t op = 0; op < handler->program_count; op++) {
            const PokemonHandlerOp *program =
                &data->handler_programs[handler->program_offset + op];
            if (program->opcode !=
                    POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT ||
                program->argument != template->id) continue;
            if (handler->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
                handler->source_kind != POKEMON_HANDLER_SOURCE_CONDITION ||
                handler->source_id != template->owner_condition_descriptor ||
                handler->scope != POKEMON_HANDLER_SCOPE_TARGET ||
                handler->route != POKEMON_HANDLER_ROUTE_OWNER ||
                handler->program_count != 1) return 0;
            descriptor_matches++;
            matched_descriptor = i;
        }
    }
    if (descriptor_matches != 1) return 0;
    for (size_t i = 0; i < data->owner_binding_index_count; i++) {
        const PokemonOwnerBindingIndex *binding =
            &data->owner_binding_index[i];
        if (binding->owner_kind != POKEMON_OWNER_VOLATILE ||
            binding->owner_id != template->owner_condition_descriptor ||
            binding->event != POKEMON_HANDLER_EVENT_BEFORE_MOVE ||
            binding->scope != POKEMON_HANDLER_SCOPE_TARGET ||
            binding->route != POKEMON_HANDLER_ROUTE_OWNER) continue;
        if (binding->binding_offset > matched_descriptor ||
            binding->binding_count == 0 ||
            matched_descriptor - binding->binding_offset >=
                binding->binding_count) return 0;
        binding_matches++;
    }
    return binding_matches == 1;
}

static int pokemon_validate_constructed_hit_templates(const PokemonData *data) {
    if (data == NULL ||
        ((data->constructed_hit_template_count != 0) !=
            (data->constructed_hit_templates != NULL)) ||
        (data->handler_count != 0 && data->handlers == NULL) ||
        (data->handler_program_count != 0 &&
            data->handler_programs == NULL) ||
        (data->owner_binding_index_count != 0 &&
            data->owner_binding_index == NULL)) return 0;
    for (size_t i = 0; i < data->constructed_hit_template_count; i++) {
        if (!template_has_exact_release_handler(
                data, &data->constructed_hit_templates[i])) return 0;
    }
    for (size_t handler_index = 0; handler_index < data->handler_count;
         handler_index++) {
        const PokemonHandlerDescriptor *handler =
            &data->handlers[handler_index];
        if ((size_t)handler->program_offset + handler->program_count >
            data->handler_program_count) return 0;
        for (size_t op = 0; op < handler->program_count; op++) {
            const PokemonHandlerOp *program =
                &data->handler_programs[handler->program_offset + op];
            if (program->opcode !=
                    POKEMON_HANDLER_OP_RELEASE_OWNER_STORED_DAMAGE_HIT) {
                continue;
            }
            size_t matches = 0;
            for (size_t template_index = 0;
                 template_index < data->constructed_hit_template_count;
                 template_index++) {
                matches += data->constructed_hit_templates[template_index].id ==
                    program->argument;
            }
            if (matches != 1) return 0;
        }
    }
    return 1;
}

int pokemon_validate_move_call_pools(const PokemonData *data) {
    if (data == NULL ||
        ((data->move_call_pool_count != 0) !=
            (data->move_call_pools != NULL)) ||
        ((data->move_call_pool_candidate_count != 0) !=
            (data->move_call_pool_candidates != NULL)) ||
        (data->handler_count != 0 && data->handlers == NULL) ||
        (data->handler_program_count != 0 &&
            data->handler_programs == NULL) ||
        (data->owner_binding_index_count != 0 &&
            data->owner_binding_index == NULL)) return 0;
    for (size_t i = 0; i < data->move_call_pool_count; i++) {
        const PokemonMoveCallPool *pool = &data->move_call_pools[i];
        if (pool->id == 0 || pool->caller_move_id == 0 ||
            pool->candidate_count == 0 ||
            pool->candidate_offset > data->move_call_pool_candidate_count ||
            pool->candidate_count > data->move_call_pool_candidate_count -
                pool->candidate_offset) return 0;
        const PokemonMoveData *caller = NULL;
        for (size_t move = 0; move < data->move_count; move++) {
            if (data->moves[move].id == pool->caller_move_id) {
                caller = &data->moves[move];
                break;
            }
        }
        if (caller == NULL || caller->call_pool_id != pool->id) return 0;
        for (size_t earlier = 0; earlier < i; earlier++) {
            if (data->move_call_pools[earlier].id == pool->id ||
                data->move_call_pools[earlier].caller_move_id ==
                    pool->caller_move_id) return 0;
        }
        uint16_t previous_num = 0;
        for (size_t candidate = 0; candidate < pool->candidate_count;
             candidate++) {
            uint16_t catalog_id = data->move_call_pool_candidates[
                pool->candidate_offset + candidate];
            const PokemonMoveIdentity *identity = pokemon_move_identity(
                data, catalog_id);
            if (identity == NULL || identity->source_num < previous_num ||
                identity->executable_id == pool->caller_move_id ||
                !executable_move_matches_identity(data, identity)) return 0;
            for (size_t earlier = 0; earlier < candidate; earlier++) {
                if (data->move_call_pool_candidates[
                        pool->candidate_offset + earlier] == catalog_id) {
                    return 0;
                }
            }
            previous_num = identity->source_num;
        }
        if (!pool_has_exact_call_handler(data, pool)) return 0;
    }
    for (size_t handler_index = 0; handler_index < data->handler_count;
         handler_index++) {
        const PokemonHandlerDescriptor *handler =
            &data->handlers[handler_index];
        if ((size_t)handler->program_offset + handler->program_count >
            data->handler_program_count) return 0;
        for (size_t op = 0; op < handler->program_count; op++) {
            const PokemonHandlerOp *program =
                &data->handler_programs[handler->program_offset + op];
            if (program->opcode == POKEMON_HANDLER_OP_CALL_FIXED_MOVE) {
                size_t caller_matches = 0;
                size_t called_matches = 0;
                for (size_t move = 0; move < data->move_count; move++) {
                    caller_matches += data->moves[move].id ==
                        handler->source_id;
                    called_matches += data->moves[move].id ==
                        program->argument;
                }
                if (handler->program_count != 1 ||
                    handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF ||
                    caller_matches != 1 || called_matches != 1 ||
                    handler->source_id == program->argument) return 0;
                continue;
            }
            if (program->opcode ==
                    POKEMON_HANDLER_OP_CALL_MOVE_FROM_USER_SLOTS) {
                if (handler->program_count != 1 || program->argument == 0 ||
                    (program->argument & (program->argument - 1u)) != 0 ||
                    (program->argument &
                        ~POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK) != 0 ||
                    handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
                    return 0;
                }
                continue;
            }
            if (program->opcode ==
                    POKEMON_HANDLER_OP_CALL_MOVE_FROM_PARTY_SLOTS) {
                if (handler->program_count != 1 ||
                    program->argument != POKEMON_MOVE_CALL_ELIGIBLE_ASSIST ||
                    handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
                    return 0;
                }
                continue;
            }
            if (program->opcode ==
                    POKEMON_HANDLER_OP_COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT) {
                uint32_t eligibility = program->argument & UINT32_C(0xff);
                uint32_t known = UINT32_C(0xff) |
                    POKEMON_MOVE_COPY_PERSIST_BASE | UINT32_C(0xff0000);
                if (handler->program_count != 1 || eligibility == 0 ||
                    (eligibility & (eligibility - 1u)) != 0 ||
                    (eligibility & ~(POKEMON_MOVE_COPY_ELIGIBLE_MIMIC |
                        POKEMON_MOVE_COPY_ELIGIBLE_SKETCH)) != 0 ||
                    (program->argument & ~known) != 0 ||
                    handler->event !=
                        POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                    handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                    handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                    handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) {
                    return 0;
                }
                continue;
            }
            if (program->opcode != POKEMON_HANDLER_OP_CALL_MOVE_FROM_POOL) {
                continue;
            }
            size_t matches = 0;
            for (size_t pool = 0; pool < data->move_call_pool_count; pool++) {
                matches += data->move_call_pools[pool].id ==
                        program->argument &&
                    data->move_call_pools[pool].caller_move_id ==
                        handler->source_id;
            }
            if (matches != 1 || handler->program_count != 1 ||
                handler->event != POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ||
                handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                handler->scope != POKEMON_HANDLER_SCOPE_SOURCE ||
                handler->route != POKEMON_HANDLER_ROUTE_MOVE_SELF) return 0;
        }
    }
    for (size_t move = 0; move < data->move_count; move++) {
        if ((data->moves[move].call_eligibility &
                ~(POKEMON_MOVE_CALL_ELIGIBLE_SLEEP_TALK |
                    POKEMON_MOVE_CALL_ELIGIBLE_ASSIST)) != 0) return 0;
        uint16_t pool_id = data->moves[move].call_pool_id;
        if (pool_id == 0) continue;
        size_t matches = 0;
        for (size_t pool = 0; pool < data->move_call_pool_count; pool++) {
            matches += data->move_call_pools[pool].id == pool_id &&
                data->move_call_pools[pool].caller_move_id ==
                    data->moves[move].id;
        }
        if (matches != 1) return 0;
    }
    return 1;
}

static const PokemonNamedIdentity *named_identity(
    const PokemonNamedIdentity *values, size_t count, uint16_t catalog_id
) {
    if (values == NULL || catalog_id == 0 || catalog_id > count) return NULL;
    const PokemonNamedIdentity *value = &values[catalog_id - 1];
    return value->catalog_id == catalog_id ? value : NULL;
}

const PokemonNamedIdentity *pokemon_ability_identity(
    const PokemonData *data, uint16_t catalog_id
) {
    return data == NULL ? NULL : named_identity(
        data->ability_catalog, data->ability_catalog_count, catalog_id);
}

const PokemonNamedIdentity *pokemon_item_identity(
    const PokemonData *data, uint16_t catalog_id
) {
    return data == NULL ? NULL : named_identity(
        data->item_catalog, data->item_catalog_count, catalog_id);
}

const PokemonConditionIdentity *pokemon_condition_identity(
    const PokemonData *data, uint16_t catalog_id
) {
    if (data == NULL || data->condition_catalog == NULL || catalog_id == 0 ||
        catalog_id > data->condition_catalog_count) return NULL;
    const PokemonConditionIdentity *value =
        &data->condition_catalog[catalog_id - 1];
    return value->catalog_id == catalog_id ? value : NULL;
}

static int set_has_operand(
    const PokemonData *data, const PokemonCatalogSet *set,
    const PokemonFormatOperand *operand
) {
    if (operand->kind == POKEMON_FORMAT_OPERAND_SPECIES) {
        return set->species_catalog_id == operand->catalog_id;
    }
    if (operand->kind == POKEMON_FORMAT_OPERAND_ABILITY) {
        return set->ability_catalog_id == operand->catalog_id;
    }
    if (operand->kind == POKEMON_FORMAT_OPERAND_ITEM) {
        return set->item_catalog_id == operand->catalog_id;
    }
    if (operand->kind == POKEMON_FORMAT_OPERAND_MOVE) {
        for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++) {
            if (set->move_catalog_ids[move] == operand->catalog_id) return 1;
        }
        return 0;
    }
    if (operand->kind == POKEMON_FORMAT_OPERAND_SPECIES_TIER) {
        const PokemonSpeciesIdentity *species = pokemon_species_identity(
            data, set->species_catalog_id);
        return species != NULL && strcmp(species->tier, "Uber") == 0;
    }
    return 0;
}

PokemonValidationResult pokemon_validate_catalog_team(
    const PokemonFormatManifest *format, const PokemonData *data,
    const PokemonCatalogTeam *team, uint8_t team_size
) {
    PokemonValidationResult result = {
        .decision = POKEMON_VALIDATION_ACCEPTED_BOUNDED,
        .reason = POKEMON_VALIDATION_NONE,
        .rule_index = UINT16_MAX,
        .team_slot = UINT8_MAX,
    };
    if (format == NULL || data == NULL || team == NULL ||
        team_size < format->min_team_size || team_size > format->max_team_size ||
        team_size > POKEMON_TEAM_CAPACITY) {
        result.decision = POKEMON_VALIDATION_REJECTED;
        result.reason = POKEMON_VALIDATION_TEAM_SIZE;
        return result;
    }
    for (size_t slot = 0; slot < team_size; slot++) {
        const PokemonCatalogSet *set = &team->members[slot];
        result.team_slot = (uint8_t)slot;
        if (set->level < format->min_level || set->level > format->max_level) {
            result.decision = POKEMON_VALIDATION_REJECTED;
            result.reason = POKEMON_VALIDATION_LEVEL;
            return result;
        }
        if (pokemon_species_identity(data, set->species_catalog_id) == NULL ||
            (set->ability_catalog_id != 0 && pokemon_ability_identity(
                data, set->ability_catalog_id) == NULL) ||
            (set->item_catalog_id != 0 && pokemon_item_identity(
                data, set->item_catalog_id) == NULL)) {
            result.decision = POKEMON_VALIDATION_REJECTED;
            result.reason = POKEMON_VALIDATION_UNKNOWN_DESCRIPTOR;
            return result;
        }
        uint8_t move_count = 0;
        for (size_t move = 0; move < POKEMON_MOVE_CAPACITY; move++) {
            if (set->move_catalog_ids[move] == 0) continue;
            move_count++;
            if (pokemon_move_identity(data, set->move_catalog_ids[move]) == NULL) {
                result.decision = POKEMON_VALIDATION_REJECTED;
                result.reason = POKEMON_VALIDATION_UNKNOWN_DESCRIPTOR;
                return result;
            }
        }
        if (move_count == 0 || move_count > format->max_move_count) {
            result.decision = POKEMON_VALIDATION_REJECTED;
            result.reason = POKEMON_VALIDATION_MOVE_COUNT;
            return result;
        }
    }
    for (size_t rule_index = 0; rule_index < format->rule_count; rule_index++) {
        const PokemonFormatRule *rule = &format->rules[rule_index];
        if (rule->kind == POKEMON_FORMAT_RULE_UNSUPPORTED_SET_FIELDS ||
            rule->kind == POKEMON_FORMAT_RULE_UNSUPPORTED_ADMISSION_UNIVERSE) {
            result.unsupported_rule_count++;
            continue;
        }
        if (rule->kind == POKEMON_FORMAT_RULE_SPECIES_CLAUSE) {
            for (size_t left = 0; left < team_size; left++) {
                const PokemonSpeciesIdentity *left_species =
                    pokemon_species_identity(data,
                        team->members[left].species_catalog_id);
                for (size_t right = left + 1; right < team_size; right++) {
                    const PokemonSpeciesIdentity *right_species =
                        pokemon_species_identity(data,
                            team->members[right].species_catalog_id);
                    if (left_species->source_num == right_species->source_num) {
                        result.decision = POKEMON_VALIDATION_REJECTED;
                        result.reason = POKEMON_VALIDATION_SPECIES_CLAUSE;
                        result.rule_index = (uint16_t)rule_index;
                        result.team_slot = (uint8_t)right;
                        return result;
                    }
                }
            }
        } else if (rule->kind == POKEMON_FORMAT_RULE_BAN ||
            rule->kind == POKEMON_FORMAT_RULE_COMPLEX_SET_BAN) {
            for (size_t slot = 0; slot < team_size; slot++) {
                uint8_t matches = 1;
                for (size_t operand = 0; operand < rule->operand_count; operand++) {
                    if (!set_has_operand(data, &team->members[slot],
                            &rule->operands[operand])) {
                        matches = 0;
                        break;
                    }
                }
                if (matches) {
                    result.decision = POKEMON_VALIDATION_REJECTED;
                    result.reason = rule->kind == POKEMON_FORMAT_RULE_BAN ?
                        POKEMON_VALIDATION_BANNED : POKEMON_VALIDATION_COMPLEX_BAN;
                    result.rule_index = (uint16_t)rule_index;
                    result.team_slot = (uint8_t)slot;
                    return result;
                }
            }
        }
    }
    result.team_slot = UINT8_MAX;
    return result;
}

static const PokemonSpeciesData *find_species(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->species_count; i++) {
        if (battle->data->species[i].id == id) return &battle->data->species[i];
    }
    return NULL;
}

static const PokemonMoveData *find_move(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->move_count; i++) {
        if (battle->data->moves[i].id == id) return &battle->data->moves[i];
    }
    return NULL;
}

static const PokemonWeightPowerPolicy *weight_power_policy(
    const PokemonData *data, uint16_t id
) {
    for (size_t i = 0; i < data->weight_power_policy_count; i++) {
        if (data->weight_power_policies[i].id == id) {
            return &data->weight_power_policies[i];
        }
    }
    return NULL;
}

static const PokemonTransformPolicy *transform_policy(
    const PokemonData *data, uint16_t id
) {
    for (size_t i = 0; i < data->transform_policy_count; i++) {
        if (data->transform_policies[i].id == id) {
            return &data->transform_policies[i];
        }
    }
    return NULL;
}

static const PokemonWeatherFormPolicy *weather_form_policy(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->weather_form_policy_count; i++) {
        const PokemonWeatherFormPolicy *policy =
            &battle->data->weather_form_policies[i];
        if (policy->id == id) return policy;
    }
    return NULL;
}

static const PokemonMoveInvocationProfile *find_move_invocation_profile(
    const PokemonData *data, uint16_t id
) {
    for (size_t i = 0; i < data->move_invocation_profile_count; i++) {
        if (data->move_invocation_profiles[i].id == id) {
            return &data->move_invocation_profiles[i];
        }
    }
    return NULL;
}

static const PokemonMoveProfileSelection *find_move_profile_selection(
    const PokemonData *data, uint16_t id
) {
    for (size_t i = 0; i < data->move_profile_selection_count; i++) {
        if (data->move_profile_selections[i].id == id) {
            return &data->move_profile_selections[i];
        }
    }
    return NULL;
}

static const PokemonConstructedHitTemplate *find_constructed_hit_template(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->constructed_hit_template_count; i++) {
        if (battle->data->constructed_hit_templates[i].id == id) {
            return &battle->data->constructed_hit_templates[i];
        }
    }
    return NULL;
}

static uint16_t current_move_id(
    const PokemonBattle *battle, size_t side, size_t team_slot,
    size_t move_slot
) {
    return battle->sides[side].state[team_slot].move_ids[move_slot];
}

static uint8_t pokemon_knows_current_move(
    const PokemonBattle *battle, size_t side, size_t team_slot,
    uint16_t move_id
) {
    if (move_id == 0) return 0;
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        if (current_move_id(battle, side, team_slot, slot) == move_id) return 1;
    }
    return 0;
}

static uint8_t active_foes_share_current_move(
    const PokemonBattle *battle, size_t holder_side, size_t holder_slot
) {
    size_t foe_side = 1u - holder_side;
    size_t foe_slot = battle->sides[foe_side].active;
    if (battle->sides[foe_side].state[foe_slot].hp == 0) return 0;
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        uint16_t move_id = current_move_id(
            battle, holder_side, holder_slot, slot);
        if (move_id != 0 && move_id != battle->generation->fallback_move_id &&
            pokemon_knows_current_move(
                battle, foe_side, foe_slot, move_id)) return 1;
    }
    return 0;
}

/* Showdown's initial current/base move slots share their PP state. Temporary
 * current slots do not. Keep that ownership fact behind one mutation point
 * instead of relying on PokemonSet, which is immutable normalized input. */
static void set_current_pp(
    PokemonBattle *battle, size_t side, size_t team_slot, size_t move_slot,
    uint8_t pp
) {
    PokemonMutable *state = &battle->sides[side].state[team_slot];
    state->pp[move_slot] = pp;
    if ((state->temporary_move_slots & (uint8_t)(1u << move_slot)) == 0) {
        state->base_pp[move_slot] = pp;
    }
}

static void restore_base_move_slots(PokemonMutable *state) {
    memcpy(state->move_ids, state->base_move_ids, sizeof(state->move_ids));
    memcpy(state->pp, state->base_pp, sizeof(state->pp));
    memcpy(state->max_pp, state->base_max_pp, sizeof(state->max_pp));
    state->temporary_move_slots = 0;
    state->transformed = 0;
}

static const PokemonMoveCallPool *find_move_call_pool(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->move_call_pool_count; i++) {
        if (battle->data->move_call_pools[i].id == id) {
            return &battle->data->move_call_pools[i];
        }
    }
    return NULL;
}

static int invoke_move_inner(
    PokemonBattle *battle, PokemonMoveInvocation invocation
);
static int resolve_invocation_target(
    const PokemonBattle *battle, const PokemonMoveInvocation *invocation,
    const PokemonMoveData *move, PokemonEntityRef *target,
    PokemonResolvedTarget *resolved);
static int drain_faints(PokemonBattle *battle);
static uint8_t living_inactive_slots(
    const PokemonBattle *battle, uint8_t side,
    uint8_t slots[POKEMON_TEAM_CAPACITY]);
static int execute_stored_damage_constructed_hit(
    PokemonBattle *battle, const PokemonConstructedHitTemplate *template,
    PokemonEntityRef source, PokemonEntityRef target,
    const PokemonVolatileState *condition);
static int residual_damage_deferred(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t amount,
    PokemonConditionScope condition_scope, uint16_t condition_id,
    uint16_t *applied);
static int execute_selected_move_after_before_move(
    PokemonBattle *battle, const PokemonAction *action,
    const PokemonMoveData *move, PokemonEntityRef target,
    uint8_t target_switching);
static void remove_volatile_at(PokemonMutable *state, size_t index);
static int end_and_remove_volatile_exact(
    PokemonBattle *battle, size_t side, size_t slot,
    uint16_t descriptor_id, uint16_t state_generation,
    uint16_t effect_order, PokemonConditionReason reason);
static int remove_source_linked_volatiles(
	PokemonBattle *battle, PokemonEntityRef source,
	PokemonConditionReason reason);

static int pokemon_knows_move(
    const PokemonBattle *battle, PokemonEntityRef pokemon, uint16_t move_id
) {
    if (pokemon.kind != POKEMON_ENTITY_POKEMON || pokemon.side >= POKEMON_SIDES ||
        pokemon.slot >= battle->team_sizes[pokemon.side]) return 0;
    const PokemonMutable *state =
        &battle->sides[pokemon.side].state[pokemon.slot];
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        if (state->move_ids[slot] == move_id) return 1;
    }
    return 0;
}

static void set_attack_record(
    PokemonBattle *battle, size_t target_side, size_t target_slot,
    size_t source_side, size_t source_slot, uint16_t move_id,
    uint16_t damage, uint8_t damage_was_number
) {
    battle->sides[target_side].state[target_slot].last_attacked_by =
        (PokemonAttackRecord){
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)source_side,
                (uint8_t)source_slot},
            .move_id = move_id, .damage = damage,
            .damage_was_number = damage_was_number,
            .this_turn = 1, .present = 1,
        };
}

static void record_attack(
    PokemonBattle *battle, size_t target_side, size_t target_slot,
    size_t source_side, size_t source_slot, uint16_t move_id,
    uint16_t damage, uint8_t damage_was_number
) {
    if (source_side == target_side) return;
    if (battle->sides[target_side].state[target_slot].hp == 0) return;
    set_attack_record(battle, target_side, target_slot, source_side,
        source_slot, move_id, damage, damage_was_number);
}

static const PokemonAbilityData *find_ability(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->ability_count; i++) {
        if (battle->data->abilities[i].id == id) return &battle->data->abilities[i];
    }
    return NULL;
}

static int weather_is_suppressed(const PokemonBattle *battle) {
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        size_t slot = battle->sides[side].active;
        const PokemonMutable *state = &battle->sides[side].state[slot];
        if (state->hp == 0 || state->fainted) continue;
        const PokemonAbilityData *ability = find_ability(
            battle, state->ability_id);
        if (ability != NULL && ability->suppresses_weather &&
            !state->ability_ending) return 1;
    }
    return 0;
}

static PokemonWeatherKind effective_weather(const PokemonBattle *battle) {
    return weather_is_suppressed(battle) ? POKEMON_WEATHER_NONE :
        battle->field.weather.kind;
}

static const PokemonWeatherPolicy *weather_policy(
    const PokemonBattle *battle, PokemonWeatherKind kind
) {
    for (size_t i = 0; i < battle->data->weather_policy_count; i++) {
        const PokemonWeatherPolicy *policy = &battle->data->weather_policies[i];
        if (policy->kind == kind) return policy;
    }
    return NULL;
}

static const PokemonWeatherPolicy *weather_policy_by_descriptor(
    const PokemonBattle *battle, uint16_t descriptor_id
) {
    for (size_t i = 0; i < battle->data->weather_policy_count; i++) {
        const PokemonWeatherPolicy *policy = &battle->data->weather_policies[i];
        if (policy->descriptor_id == descriptor_id) return policy;
    }
    return NULL;
}

static const PokemonConditionRule *condition_rule(
    const PokemonBattle *battle, PokemonRuleConditionKind kind
) {
    for (size_t i = 0; i < battle->generation->condition_rule_count; i++) {
        const PokemonConditionRule *rule = &battle->generation->condition_rules[i];
        if (rule->kind == kind &&
			!(rule->flags & POKEMON_CONDITION_RULE_REPEATABLE_FAMILY)) {
			return rule;
		}
    }
    return NULL;
}

static const PokemonLockedRampPolicy *locked_ramp_policy(
    const PokemonBattle *battle, uint16_t id
) {
	for (size_t i = 0; i < battle->data->locked_ramp_policy_count; i++) {
		const PokemonLockedRampPolicy *policy =
			&battle->data->locked_ramp_policies[i];
		if (policy->id == id) return policy;
	}
	return NULL;
}

static const PokemonLockedRampPolicy *locked_ramp_policy_for_condition(
    const PokemonBattle *battle, const PokemonVolatileState *condition
) {
	for (size_t i = 0; i < battle->data->locked_ramp_policy_count; i++) {
		const PokemonLockedRampPolicy *policy =
			&battle->data->locked_ramp_policies[i];
		if (policy->volatile_kind == condition->kind &&
			policy->condition_descriptor_id == condition->descriptor_id) {
			return policy;
		}
	}
	return NULL;
}

static const PokemonCounterHealPolicy *counter_heal_policy(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->counter_heal_policy_count; i++) {
        const PokemonCounterHealPolicy *policy =
            &battle->data->counter_heal_policies[i];
        if (policy->id == id) return policy;
    }
    return NULL;
}

static const PokemonTypeResponsePolicy *type_response_policy(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->type_response_policy_count; i++) {
        const PokemonTypeResponsePolicy *policy =
            &battle->data->type_response_policies[i];
        if (policy->id == id) return policy;
    }
    return NULL;
}

static const PokemonConditionRule *condition_rule_by_descriptor(
    const PokemonBattle *battle, uint16_t descriptor_id
) {
    for (size_t i = 0; i < battle->generation->condition_rule_count; i++) {
        const PokemonConditionRule *rule = &battle->generation->condition_rules[i];
        if (rule->descriptor_id == descriptor_id) return rule;
    }
    return NULL;
}

static PokemonMoveResolution move_resolution(const PokemonMoveData *move) {
    if (move->resolution != POKEMON_MOVE_RESOLUTION_DEFAULT) {
        return move->resolution;
    }
    /* Compatibility for small hand-built test plugins. Generated resolved
     * bundles set this explicitly. */
    return move->category == POKEMON_CATEGORY_STATUS ?
        POKEMON_MOVE_RESOLUTION_NONE : POKEMON_MOVE_RESOLUTION_DAMAGE;
}

static const PokemonStatusResidualPolicy *status_residual_policy(
    const PokemonData *data, uint16_t descriptor_id
) {
    for (size_t i = 0; i < data->status_residual_policy_count; i++) {
        const PokemonStatusResidualPolicy *policy =
            &data->status_residual_policies[i];
        if (policy->descriptor_id == descriptor_id) return policy;
    }
    return NULL;
}

static const PokemonSlotConditionPolicy *slot_condition_policy(
    const PokemonData *data, uint16_t descriptor_id
) {
    for (size_t i = 0; i < data->slot_condition_policy_count; i++) {
        const PokemonSlotConditionPolicy *policy =
            &data->slot_condition_policies[i];
        if (policy->descriptor_id == descriptor_id) return policy;
    }
    return NULL;
}

static PokemonRuleConditionKind weather_rule_kind(PokemonWeatherKind weather) {
    switch (weather) {
    case POKEMON_WEATHER_SANDSTORM: return POKEMON_RULE_CONDITION_SANDSTORM;
    case POKEMON_WEATHER_HAIL: return POKEMON_RULE_CONDITION_HAIL;
    case POKEMON_WEATHER_RAIN: return POKEMON_RULE_CONDITION_RAIN;
    case POKEMON_WEATHER_SUN: return POKEMON_RULE_CONDITION_SUN;
    case POKEMON_WEATHER_NONE: break;
    }
    return 0;
}

static int valid_condition_duration(PokemonConditionDuration duration) {
    switch (duration.kind) {
    case POKEMON_CONDITION_DURATION_NONE:
        return duration.minimum == 0 && duration.maximum == 0;
    case POKEMON_CONDITION_DURATION_FIXED:
        return duration.minimum != 0 && duration.minimum == duration.maximum;
    case POKEMON_CONDITION_DURATION_UNIFORM:
        return duration.minimum != 0 && duration.minimum < duration.maximum;
    }
    return 0;
}

int pokemon_move_choice_set_check_invariants(const PokemonMoveChoiceSet *set) {
    if (set == NULL || set->slot_count == 0 ||
        set->slot_count > POKEMON_MOVE_CAPACITY) return 0;
    uint8_t valid_mask = (uint8_t)((1u << set->slot_count) - 1u);
    if ((set->legal_slot_mask & (uint8_t)~valid_mask) != 0) return 0;
    if (set->kind == POKEMON_MOVE_CHOICE_SET_SELECTABLE) {
        return set->legal_slot_mask != 0 && set->synthetic_move_id == 0;
    }
    if (set->kind == POKEMON_MOVE_CHOICE_SET_HARD_LOCK ||
        set->kind == POKEMON_MOVE_CHOICE_SET_FALLBACK) {
        return set->legal_slot_mask == 0 && set->synthetic_move_id != 0;
    }
    return 0;
}

int pokemon_validate_choice_control_policies(
    const PokemonChoiceControlPolicy *policies, size_t count
) {
    if (count != 0 && policies == NULL) return 0;
    for (size_t i = 0; i < count; i++) {
        const PokemonChoiceControlPolicy *policy = &policies[i];
        int category_operation =
            policy->request_op == POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY ||
            policy->action_op == POKEMON_CHOICE_ACTION_REJECT_CATEGORY;
        if (policy->owner_descriptor_id == 0 ||
            policy->start_op >
                POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE ||
            policy->start_duration_op >
                POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED ||
            policy->request_op >
                POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC ||
            policy->action_op >
                POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC ||
            policy->residual_op >
                POKEMON_CHOICE_RESIDUAL_END_IF_STORED_MOVE_UNUSABLE ||
            ((policy->request_op != POKEMON_CHOICE_REQUEST_NONE) !=
                (policy->request_handler_id != 0)) ||
            ((policy->start_op != POKEMON_CHOICE_START_NONE) !=
                (policy->start_handler_id != 0)) ||
            ((policy->action_op != POKEMON_CHOICE_ACTION_NONE) !=
                (policy->action_handler_id != 0)) ||
            ((policy->residual_op != POKEMON_CHOICE_RESIDUAL_NONE) !=
                (policy->residual_handler_id != 0)) ||
            category_operation !=
                (policy->category >= POKEMON_CATEGORY_PHYSICAL &&
                 policy->category <= POKEMON_CATEGORY_STATUS) ||
            ((policy->request_op ==
                    POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC ||
              policy->action_op ==
                    POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC) !=
                (policy->synthetic_move_id != 0)) ||
            policy->allows_indefinite_start > 1) {
            return 0;
        }
        for (size_t j = 0; j < i; j++) {
            if (policies[j].owner_descriptor_id ==
                policy->owner_descriptor_id) return 0;
        }
    }
    return 1;
}

int pokemon_prepare_choice_control_start(
    const PokemonChoiceControlPolicy *policy, uint16_t last_move_id,
    PokemonMoveSlotState last_move_slot_state,
    uint8_t last_move_encore_eligible,
    uint8_t target_will_move, uint8_t sampled_duration,
    PokemonChoiceControlStart *start
) {
    if (policy == NULL || start == NULL ||
        (sampled_duration == 0 && !policy->allows_indefinite_start) ||
        policy->start_op == POKEMON_CHOICE_START_NONE ||
        policy->start_op >
            POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE ||
        last_move_slot_state > POKEMON_MOVE_SLOT_PRESENT_WITH_PP ||
        policy->start_duration_op >
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED) {
        return POKEMON_INVALID_ARGUMENT;
    }
    PokemonChoiceControlStart next = {
        .duration = sampled_duration,
        .admitted = last_move_id != 0 &&
            last_move_slot_state != POKEMON_MOVE_SLOT_PRESENT_ZERO_PP,
    };
    if (policy->start_op ==
            POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE &&
        (last_move_slot_state != POKEMON_MOVE_SLOT_PRESENT_WITH_PP ||
         !last_move_encore_eligible)) {
        next.admitted = 0;
    }
    if (next.admitted) next.stored_move_id = last_move_id;
    if (next.admitted && policy->start_duration_op ==
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED &&
        !target_will_move) {
        if (next.duration == UINT8_MAX) return POKEMON_INVALID_CONFIGURATION;
        next.duration++;
    }
    *start = next;
    return POKEMON_OK;
}

static const PokemonChoiceControlPolicy *choice_control_policy(
    const PokemonChoiceControlPolicy *policies, size_t count,
    uint16_t descriptor_id
) {
    for (size_t i = 0; i < count; i++) {
        if (policies[i].owner_descriptor_id == descriptor_id) {
            return &policies[i];
        }
    }
    return NULL;
}

int pokemon_apply_choice_action_stage(
    const PokemonChoiceControlPolicy *policies, size_t policy_count,
    const PokemonVolatileState *volatiles, size_t volatile_count,
    const PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY],
    uint16_t selected_move_id, PokemonChoiceActionStage stage,
    PokemonChoiceActionDecision *decision
) {
    if (!pokemon_validate_choice_control_policies(policies, policy_count) ||
        (volatile_count != 0 && volatiles == NULL) || slots == NULL ||
        selected_move_id == 0 || decision == NULL ||
        (stage != POKEMON_CHOICE_ACTION_STAGE_OVERRIDE &&
         stage != POKEMON_CHOICE_ACTION_STAGE_GUARD)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    size_t order[POKEMON_VOLATILE_CAPACITY];
    size_t count = 0;
    for (size_t i = 0; i < volatile_count; i++) {
        const PokemonChoiceControlPolicy *policy = choice_control_policy(
            policies, policy_count, volatiles[i].descriptor_id);
        if (policy == NULL || policy->action_op == POKEMON_CHOICE_ACTION_NONE) {
            continue;
        }
        order[count++] = i;
    }
    for (size_t i = 1; i < count; i++) {
        size_t value = order[i];
        const PokemonChoiceControlPolicy *value_policy = choice_control_policy(
            policies, policy_count, volatiles[value].descriptor_id);
        size_t j = i;
        while (j != 0) {
            size_t previous = order[j - 1];
            const PokemonChoiceControlPolicy *previous_policy =
                choice_control_policy(
                    policies, policy_count, volatiles[previous].descriptor_id);
            int value_first = value_policy->action_priority >
                    previous_policy->action_priority ||
                (value_policy->action_priority ==
                    previous_policy->action_priority &&
                 volatiles[value].effect_order <
                    volatiles[previous].effect_order);
            if (!value_first) break;
            order[j] = previous;
            j--;
        }
        order[j] = value;
    }
    PokemonChoiceActionDecision next = {
        .executed_move_id = selected_move_id, .allowed = 1,
    };
    for (size_t i = 0; i < count; i++) {
        const PokemonVolatileState *owner = &volatiles[order[i]];
        const PokemonChoiceControlPolicy *policy = choice_control_policy(
            policies, policy_count, owner->descriptor_id);
        uint16_t stored = owner->payload.choice_control.stored_move_id;
        if (stage == POKEMON_CHOICE_ACTION_STAGE_OVERRIDE) {
            if (policy->action_op ==
                POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE) {
                if (stored == 0) return POKEMON_INVALID_CONFIGURATION;
                next.executed_move_id = stored;
            }
            continue;
        }
        if (policy->action_op == POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE) {
            if (stored == 0) return POKEMON_INVALID_CONFIGURATION;
            if (next.executed_move_id == stored) next.allowed = 0;
        } else if (policy->action_op ==
            POKEMON_CHOICE_ACTION_REJECT_CATEGORY) {
            PokemonCategory category = 0;
            for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
                if (slots[slot].move_id == next.executed_move_id) {
                    category = slots[slot].category;
                    break;
                }
            }
            if (category == 0) return POKEMON_INVALID_CONFIGURATION;
            if (category == policy->category) next.allowed = 0;
        } else if (policy->action_op ==
            POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC) {
            if (policy->synthetic_move_id == 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (next.executed_move_id == policy->synthetic_move_id) {
                next.allowed = 0;
            }
        }
        if (!next.allowed) break;
    }
    *decision = next;
    return POKEMON_OK;
}

int pokemon_reduce_move_choices(
    const PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY],
    uint8_t slot_count, uint16_t hard_lock_move_id,
    uint16_t fallback_move_id,
    const PokemonMoveRestriction *restrictions, size_t restriction_count,
    PokemonMoveChoiceSet *result
) {
    if (slots == NULL || result == NULL ||
        (restriction_count != 0 && restrictions == NULL)) {
        return POKEMON_INVALID_ARGUMENT;
    }
    if (slot_count == 0 || slot_count > POKEMON_MOVE_CAPACITY ||
        fallback_move_id == 0) return POKEMON_INVALID_CONFIGURATION;
    for (size_t i = 0; i < slot_count; i++) {
        if (slots[i].move_id == 0) {
            if (slots[i].pp != 0 || slots[i].category != 0) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            continue;
        }
        if (
            slots[i].category < POKEMON_CATEGORY_PHYSICAL ||
            slots[i].category > POKEMON_CATEGORY_STATUS) {
            return POKEMON_INVALID_CONFIGURATION;
        }
    }
    PokemonMoveChoiceSet next = {.slot_count = slot_count};
    if (hard_lock_move_id != 0) {
        next.kind = POKEMON_MOVE_CHOICE_SET_HARD_LOCK;
        next.synthetic_move_id = hard_lock_move_id;
        *result = next;
        return POKEMON_OK;
    }
    for (size_t slot = 0; slot < slot_count; slot++) {
        if (slots[slot].move_id != 0 && slots[slot].pp != 0) {
            next.legal_slot_mask |= (uint8_t)(1u << slot);
        }
    }
    for (size_t i = 0; i < restriction_count; i++) {
        const PokemonMoveRestriction *restriction = &restrictions[i];
        for (size_t slot = 0; slot < slot_count; slot++) {
            uint8_t bit = (uint8_t)(1u << slot);
            if ((next.legal_slot_mask & bit) == 0) continue;
            int disable = 0;
            switch (restriction->kind) {
            case POKEMON_MOVE_RESTRICTION_DISABLE_EQUAL:
            case POKEMON_MOVE_RESTRICTION_DISABLE_UNEQUAL:
                if (restriction->move_id == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                disable = slots[slot].move_id == restriction->move_id;
                if (restriction->kind ==
                    POKEMON_MOVE_RESTRICTION_DISABLE_UNEQUAL) {
                    disable = !disable;
                }
                break;
            case POKEMON_MOVE_RESTRICTION_DISABLE_CATEGORY:
                if (restriction->category < POKEMON_CATEGORY_PHYSICAL ||
                    restriction->category > POKEMON_CATEGORY_STATUS) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                disable = slots[slot].category == restriction->category;
                break;
            case POKEMON_MOVE_RESTRICTION_DISABLE_LAST_NONFALLBACK:
                if (restriction->fallback_move_id == 0) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                disable = restriction->move_id != 0 &&
                    restriction->move_id != restriction->fallback_move_id &&
                    slots[slot].move_id == restriction->move_id;
                break;
            default:
                return POKEMON_INVALID_CONFIGURATION;
            }
            if (disable) next.legal_slot_mask &= (uint8_t)~bit;
        }
    }
    if (next.legal_slot_mask == 0) {
        next.kind = POKEMON_MOVE_CHOICE_SET_FALLBACK;
        next.synthetic_move_id = fallback_move_id;
    } else {
        next.kind = POKEMON_MOVE_CHOICE_SET_SELECTABLE;
    }
    if (!pokemon_move_choice_set_check_invariants(&next)) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *result = next;
    return POKEMON_OK;
}

int pokemon_reduce_switch_choices(
    uint8_t candidate_mask, PokemonSwitchChoiceMode mode,
    const PokemonSwitchRestriction *restrictions, size_t restriction_count,
    uint8_t *legal_mask
) {
    if (legal_mask == NULL ||
        (restriction_count != 0 && restrictions == NULL)) {
        return POKEMON_INVALID_ARGUMENT;
    }
    if (mode != POKEMON_SWITCH_CHOICE_VOLUNTARY &&
        mode != POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT &&
        mode != POKEMON_SWITCH_CHOICE_MOVE_DRIVEN) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint8_t next = candidate_mask;
    if (mode == POKEMON_SWITCH_CHOICE_VOLUNTARY) {
        for (size_t i = 0; i < restriction_count; i++) {
            if (restrictions[i].kind !=
                    POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            next = 0;
        }
    }
    *legal_mask = next;
    return POKEMON_OK;
}

int pokemon_append_switch_restriction(
    PokemonSwitchRestrictionBuffer *buffer,
    PokemonSwitchRestriction restriction
) {
    if (buffer == NULL || (buffer->capacity != 0 && buffer->values == NULL)) {
        return POKEMON_INVALID_ARGUMENT;
    }
    if (restriction.kind != POKEMON_SWITCH_RESTRICTION_DISALLOW_ALL ||
        restriction.hidden > 1) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (buffer->count > buffer->capacity) return POKEMON_INVALID_CONFIGURATION;
    if (buffer->count == buffer->capacity) return POKEMON_CAPACITY_EXCEEDED;
    buffer->values[buffer->count++] = restriction;
    return POKEMON_OK;
}

int pokemon_make_switch_choice_request(
    uint8_t candidate_mask, PokemonSwitchChoiceMode mode,
    const PokemonSwitchRestriction *restrictions, size_t restriction_count,
    PokemonTrapDisclosure disclosure, PokemonSwitchChoiceRequest *request
) {
    if (request == NULL) return POKEMON_INVALID_ARGUMENT;
    if (disclosure != POKEMON_TRAP_DISCLOSURE_NONE &&
        disclosure != POKEMON_TRAP_DISCLOSURE_MAYBE &&
        disclosure != POKEMON_TRAP_DISCLOSURE_KNOWN) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    PokemonSwitchChoiceRequest next = {
        .candidate_mask = candidate_mask,
        .mode = mode,
        .trap_disclosure = disclosure,
    };
    int status = pokemon_reduce_switch_choices(
        candidate_mask, mode, restrictions, restriction_count,
        &next.definitive_mask);
    if (status != POKEMON_OK) return status;
    if (mode != POKEMON_SWITCH_CHOICE_VOLUNTARY &&
        disclosure != POKEMON_TRAP_DISCLOSURE_NONE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    if (next.definitive_mask != candidate_mask &&
        disclosure == POKEMON_TRAP_DISCLOSURE_NONE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *request = next;
    return POKEMON_OK;
}

int pokemon_attempt_choice(
    PokemonChoiceAttemptState *state, PokemonChoice choice,
    PokemonChoiceAttemptOutcome *outcome
) {
    if (state == NULL || outcome == NULL) return POKEMON_INVALID_ARGUMENT;
    PokemonChoiceAttemptState next = *state;
    if (next.has_choice && next.cant_undo) {
        *outcome = POKEMON_CHOICE_ATTEMPT_REJECTED_CANT_UNDO;
        return POKEMON_OK;
    }
    if (choice.kind == POKEMON_CHOICE_MOVE) {
        if (next.request_kind != POKEMON_REQUEST_MOVE ||
            choice.slot >= POKEMON_MOVE_CAPACITY ||
            (next.legal_move_mask & (1u << choice.slot)) == 0) {
            return POKEMON_ILLEGAL_CHOICE;
        }
    } else if (choice.kind == POKEMON_CHOICE_SWITCH) {
        if (choice.slot >= POKEMON_TEAM_CAPACITY) return POKEMON_ILLEGAL_CHOICE;
        uint8_t selected = (uint8_t)(1u << choice.slot);
        uint8_t public_mask = next.switches.trap_disclosure ==
            POKEMON_TRAP_DISCLOSURE_KNOWN ?
            next.switches.definitive_mask : next.switches.candidate_mask;
        if ((public_mask & selected) == 0) return POKEMON_ILLEGAL_CHOICE;
        if ((next.switches.definitive_mask & selected) == 0) {
            if (next.request_kind != POKEMON_REQUEST_MOVE ||
                next.switches.mode != POKEMON_SWITCH_CHOICE_VOLUNTARY ||
                next.switches.trap_disclosure != POKEMON_TRAP_DISCLOSURE_MAYBE) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            next.switches.trap_disclosure = POKEMON_TRAP_DISCLOSURE_KNOWN;
            next.switches.updated = 1;
            *state = next;
            *outcome = POKEMON_CHOICE_ATTEMPT_REJECTED_HIDDEN_TRAP;
            return POKEMON_OK;
        }
        if (next.request_kind != POKEMON_REQUEST_MOVE &&
            next.request_kind != POKEMON_REQUEST_SWITCH) {
            return POKEMON_ILLEGAL_CHOICE;
        }
    } else {
        return POKEMON_ILLEGAL_CHOICE;
    }
    next.choice = choice;
    next.has_choice = 1;
    next.cant_undo = choice.kind == POKEMON_CHOICE_SWITCH &&
        next.switches.mode == POKEMON_SWITCH_CHOICE_VOLUNTARY &&
        next.switches.trap_disclosure == POKEMON_TRAP_DISCLOSURE_MAYBE;
    *state = next;
    *outcome = POKEMON_CHOICE_ATTEMPT_ACCEPTED;
    return POKEMON_OK;
}

static uint8_t condition_duration_maximum(
    const PokemonConditionRule *rule
) {
    return rule->lifecycle_duration.maximum;
}

static int fixed_condition_duration(
    const PokemonConditionRule *rule, uint8_t *duration
) {
    if (rule == NULL || duration == NULL ||
        rule->lifecycle_duration.kind != POKEMON_CONDITION_DURATION_FIXED) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    *duration = rule->lifecycle_duration.minimum;
    return POKEMON_OK;
}

static int valid_generation_rules(const PokemonGeneration *generation) {
    if ((generation->condition_rule_count != 0 &&
         generation->condition_rules == NULL) ||
        generation->condition_descriptor == NULL ||
        !pokemon_validate_choice_control_policies(
            generation->choice_control_policies,
            generation->choice_control_policy_count) ||
        generation->critical_chance == NULL || generation->stages == NULL ||
        generation->resolve_personal_move_profile == NULL ||
        generation->weather_damage_stage <
            POKEMON_WEATHER_DAMAGE_BEFORE_FINAL_BASE_OFFSET ||
        generation->weather_damage_stage >
            POKEMON_WEATHER_DAMAGE_AFTER_FINAL_BASE_OFFSET ||
        generation->stall.initial_denominator == 0 ||
        generation->stall.multiplier < 2 ||
        generation->stall.denominator_cap <
            generation->stall.initial_denominator ||
        generation->stages->minimum != -6 || generation->stages->maximum != 6 ||
        generation->multihit.minimum < 2 ||
        generation->multihit.maximum < generation->multihit.minimum ||
        generation->multihit.outcomes == NULL ||
        generation->multihit.outcome_count == 0 ||
        generation->ohko.base_accuracy == 0 ||
        generation->ohko.base_accuracy > 100 ||
        ((generation->random_damage_formula_count != 0) !=
         (generation->random_damage_formulas != NULL)) ||
        generation->cancel_all_actions_on_faint > 1 ||
        ((generation->shared_turn_speed.numerator == 0) !=
         (generation->shared_turn_speed.denominator == 0)) ||
        ((generation->shared_turn_speed.numerator == 0) !=
         (generation->shared_turn_speed.speed_sentinel == 0)) ||
        generation->shared_turn_speed.numerator >
            generation->shared_turn_speed.denominator ||
        generation->replaced_ability_runs_start > 1 ||
        generation->continue_preselected_switch_after_interception_faint > 1 ||
        generation->fallback_move_id == 0 ||
        generation->self_destruct_defense_divisor == 0) {
        return 0;
    }
    for (size_t i = 0; i < generation->multihit.outcome_count; i++) {
        if (generation->multihit.outcomes[i] < generation->multihit.minimum ||
            generation->multihit.outcomes[i] > generation->multihit.maximum) {
            return 0;
        }
    }
    for (size_t i = 0; i < generation->random_damage_formula_count; i++) {
        const PokemonDamageFormulaRandomPolicy *policy =
            &generation->random_damage_formulas[i];
        if (policy->formula != POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT ||
            policy->minimum >= policy->maximum_exclusive) return 0;
        for (size_t j = 0; j < i; j++) {
            if (generation->random_damage_formulas[j].formula ==
                policy->formula) return 0;
        }
    }
    for (size_t i = 0; i < 13; i++) {
        if (generation->stages->ordinary[i].numerator == 0 ||
            generation->stages->ordinary[i].denominator == 0 ||
            generation->stages->accuracy[i].numerator == 0 ||
            generation->stages->accuracy[i].denominator == 0) return 0;
    }
    for (size_t i = 0; i < generation->condition_rule_count; i++) {
        const PokemonConditionRule *rule = &generation->condition_rules[i];
        if (rule->kind == 0 ||
            rule->kind > POKEMON_RULE_CONDITION_BOUNDED_COUNTER ||
            (generation->capabilities & POKEMON_CAP_CONDITION(rule->kind)) == 0 ||
            rule->descriptor_id == 0 ||
            rule->has_residual > 1 || rule->has_order > 1 ||
            rule->speed_tied > 1 || rule->no_copy > 1 ||
            (rule->flags & ~(POKEMON_CONDITION_RULE_STALLING_GUARD |
				POKEMON_CONDITION_RULE_REPEATABLE_FAMILY)) != 0 ||
            rule->remove_with_status > POKEMON_STATUS_FREEZE ||
			rule->source_linked_kind > POKEMON_VOLATILE_TRAPPER ||
            (!rule->has_residual && (rule->has_order || rule->residual_order ||
                rule->residual_sub_order || rule->speed_tied)) ||
            (rule->has_order && rule->residual_order == 0) ||
            (!rule->has_order && rule->residual_order != 0) ||
            !valid_condition_duration(rule->lifecycle_duration) ||
            ((rule->flags & POKEMON_CONDITION_RULE_STALLING_GUARD) &&
             (rule->lifecycle_duration.kind !=
                  POKEMON_CONDITION_DURATION_FIXED ||
              rule->lifecycle_duration.minimum != 1 ||
              rule->lifecycle_duration.maximum != 1)) ||
            ((rule->lifecycle_duration.kind ==
                POKEMON_CONDITION_DURATION_UNIFORM) !=
                (rule->duration_draw_label != 0)) ||
            rule->duration_draw_label > POKEMON_DRAW_UPROAR_DURATION ||
            (rule->kind <= POKEMON_RULE_CONDITION_MUST_RECHARGE &&
             rule->kind != POKEMON_RULE_CONDITION_CONFUSION &&
             rule->kind != POKEMON_RULE_CONDITION_FOCUS_ENERGY &&
             rule->kind != POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED &&
             rule->kind != POKEMON_RULE_CONDITION_TORMENT &&
             rule->kind != POKEMON_RULE_CONDITION_SPIKES &&
             rule->kind != POKEMON_RULE_CONDITION_NIGHTMARE &&
            ((rule->kind == POKEMON_RULE_CONDITION_TOXIC ||
              rule->kind == POKEMON_RULE_CONDITION_BURN ||
              rule->kind == POKEMON_RULE_CONDITION_POISON ||
              rule->kind == POKEMON_RULE_CONDITION_CONFUSION) !=
              (rule->lifecycle_duration.kind ==
                POKEMON_CONDITION_DURATION_NONE)))) return 0;
        for (size_t j = 0; j < i; j++) {
            if (generation->condition_rules[j].descriptor_id ==
				rule->descriptor_id) return 0;
        }
    }
    for (PokemonRuleConditionKind required = POKEMON_RULE_CONDITION_TOXIC;
         required <= POKEMON_RULE_CONDITION_BOUNDED_COUNTER; required++) {
        if ((generation->capabilities & POKEMON_CAP_CONDITION(required)) == 0) {
            continue;
        }
        uint8_t found = 0;
        for (size_t i = 0; i < generation->condition_rule_count; i++) {
            found |= generation->condition_rules[i].kind == required;
        }
        if (!found) return 0;
    }
    return 1;
}

static const PokemonItemData *find_item(
    const PokemonBattle *battle, uint16_t id
) {
    for (size_t i = 0; i < battle->data->item_count; i++) {
        if (battle->data->items[i].id == id) return &battle->data->items[i];
    }
    return NULL;
}
#line 17 "pokemon.c"
