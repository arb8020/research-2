#line 3172 "pokemon.c"
uint32_t pokemon_apply_stage_ratio(
    const PokemonStagePolicy *policy, uint32_t value, int8_t stage,
    uint8_t accuracy
) {
    if (policy == NULL) return 0;
    if (stage < policy->minimum) stage = policy->minimum;
    if (stage > policy->maximum) stage = policy->maximum;
    size_t index = (size_t)(stage - policy->minimum);
    PokemonStageRatio ratio = accuracy ? policy->accuracy[index] :
        policy->ordinary[index];
    if (ratio.denominator == 0) return 0;
    uint64_t product = (uint64_t)value * ratio.numerator;
    uint64_t resolved = product / ratio.denominator;
    return resolved > UINT32_MAX ? UINT32_MAX : (uint32_t)resolved;
}

int pokemon_compare_handler_refs(
    const PokemonHandlerRef *left, const PokemonHandlerRef *right
);

static int draw_below(
    PokemonBattle *battle, PokemonDrawLabel label, uint32_t upper,
    uint32_t *result
) {
    if (upper == 0 || result == NULL) return POKEMON_INVALID_ARGUMENT;
    if (battle->draw_count == POKEMON_DRAW_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    PokemonDraw *draw = &battle->draws[battle->draw_count++];
    memset(draw, 0, sizeof(*draw));
    draw->label = label;
    draw->upper_bound = upper;
    memcpy(draw->seed_before, battle->seed, sizeof(draw->seed_before));
    draw->raw = pokemon_prng_next_u32(battle->seed);
    draw->result = pokemon_prng_project_below(draw->raw, upper);
    memcpy(draw->seed_after, battle->seed, sizeof(draw->seed_after));
    *result = draw->result;
    return POKEMON_OK;
}

static int order_event_handlers(
    PokemonBattle *battle, PokemonEventId event,
    PokemonHandlerRef *handlers, size_t count
) {
    size_t sorted = 0;
    while (sorted + 1 < count) {
        size_t indexes[POKEMON_HANDLER_CAPACITY];
        size_t index_count = 1;
        indexes[0] = sorted;
        for (size_t i = sorted + 1; i < count; i++) {
            int delta = pokemon_compare_handler_refs(
                &handlers[indexes[0]], &handlers[i]);
            if (delta < 0) continue;
            if (delta > 0) {
                index_count = 1;
                indexes[0] = i;
            } else {
                indexes[index_count++] = i;
            }
        }
        for (size_t i = 0; i < index_count; i++) {
            size_t index = indexes[i];
            if (index != sorted + i) {
                PokemonHandlerRef swap = handlers[sorted + i];
                handlers[sorted + i] = handlers[index];
                handlers[index] = swap;
            }
        }
        for (size_t i = 0; i + 1 < index_count; i++) {
            uint32_t offset = 0;
            int status = draw_below(
                battle, POKEMON_DRAW_EVENT_HANDLER_ORDER,
                (uint32_t)(index_count - i), &offset);
            if (status != POKEMON_OK) return status;
            PokemonDraw *draw = &battle->draws[battle->draw_count - 1];
            draw->context_event_id = event;
            if (event == POKEMON_HANDLER_EVENT_SET_STATUS) {
                draw->lower_bound = (uint32_t)(sorted + i);
            }
            size_t other = sorted + i + offset;
            PokemonHandlerRef swap = handlers[sorted + i];
            handlers[sorted + i] = handlers[other];
            handlers[other] = swap;
        }
        sorted += index_count;
    }
    return POKEMON_OK;
}

static size_t event_handler_order_draw_count(
    const PokemonHandlerRef *handlers, size_t count
) {
    PokemonHandlerRef copy[POKEMON_HANDLER_CAPACITY];
    memcpy(copy, handlers, count * sizeof(*copy));
    size_t draws = 0;
    size_t sorted = 0;
    while (sorted + 1 < count) {
        size_t indexes[POKEMON_HANDLER_CAPACITY];
        size_t index_count = 1;
        indexes[0] = sorted;
        for (size_t i = sorted + 1; i < count; i++) {
            int delta = pokemon_compare_handler_refs(&copy[indexes[0]], &copy[i]);
            if (delta < 0) continue;
            if (delta > 0) { index_count = 1; indexes[0] = i; }
            else indexes[index_count++] = i;
        }
        for (size_t i = 0; i < index_count; i++) {
            if (indexes[i] != sorted + i) {
                PokemonHandlerRef swap = copy[sorted + i];
                copy[sorted + i] = copy[indexes[i]];
                copy[indexes[i]] = swap;
            }
        }
        draws += index_count - 1;
        sorted += index_count;
    }
    return draws;
}

/* Showdown's left-to-right event ordering is stable and does not own a tie
 * draw. Singles has one target index, leaving discovery order as the final
 * tie-break after explicit order and priority. */
static void order_left_to_right_handlers(
    PokemonHandlerRef *handlers, size_t count
) {
    for (size_t i = 1; i < count; i++) {
        PokemonHandlerRef value = handlers[i];
        size_t position = i;
        int value_order = value.descriptor.order == 0 ?
            INT_MAX : value.descriptor.order;
        while (position != 0) {
            PokemonHandlerRef *previous = &handlers[position - 1];
            int previous_order = previous->descriptor.order == 0 ?
                INT_MAX : previous->descriptor.order;
            uint8_t before = value_order < previous_order ||
                (value_order == previous_order &&
                 value.descriptor.priority > previous->descriptor.priority);
            if (!before) break;
            handlers[position--] = *previous;
        }
        handlers[position] = value;
    }
}

static uint8_t alive_count(const PokemonBattle *battle, size_t side) {
    uint8_t count = 0;
    for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
        count += battle->sides[side].state[slot].hp != 0;
    }
    return count;
}

static uint16_t locked_move_id(const PokemonBattle *battle, size_t side);

static uint8_t has_lock_move_owner(const PokemonBattle *battle, size_t side) {
	return locked_move_id(battle, side) != 0;
}

static uint16_t locked_move_id(const PokemonBattle *battle, size_t side) {
	size_t slot = battle->sides[side].active;
	const PokemonMutable *state = &battle->sides[side].state[slot];
	int index = volatile_index(state, POKEMON_VOLATILE_TWO_TURN_MOVE);
	if (index >= 0) return state->volatiles[index].payload.two_turn.move_id;
	index = volatile_index(state, POKEMON_VOLATILE_LOCKED_MOVE);
	if (index >= 0) return state->volatiles[index].payload.locked_move.move_id;
	for (size_t i = 0; i < state->volatile_count; i++) {
		const PokemonChoiceControlPolicy *choice = choice_control_policy(
			battle->generation->choice_control_policies,
			battle->generation->choice_control_policy_count,
			state->volatiles[i].descriptor_id);
		if (choice != NULL && choice->request_op ==
				POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC) {
			return choice->synthetic_move_id;
		}
		const PokemonLockedRampPolicy *ramp =
			locked_ramp_policy_for_condition(battle, &state->volatiles[i]);
		if (ramp != NULL) {
			return ramp->move_id;
		}
	}
	return 0;
}

static int query_locked_move(PokemonBattle *battle, size_t side, uint16_t *move_id) {
    *move_id = 0;
    if (!has_lock_move_owner(battle, side)) return POKEMON_OK;
    uint8_t active = battle->sides[side].active;
    PokemonEventFrame frame;
    int status = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_LOCK_MOVE,
        .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, active},
        .target_side = (uint8_t)side, .target_slot = active,
        .relay = {.kind = POKEMON_RELAY_SELECTOR, .value.selector = 0},
    }, &frame);
    if (status != POKEMON_OK) return status;
    *move_id = frame.relay.value.selector;
    return *move_id == 0 ? POKEMON_INVALID_CONFIGURATION : POKEMON_OK;
}

static int build_move_choice_slots(
    const PokemonBattle *battle, size_t side,
    PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY]
) {
    memset(slots, 0, sizeof(PokemonMoveChoiceSlot) * POKEMON_MOVE_CAPACITY);
    uint8_t active = battle->sides[side].active;
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        uint16_t move_id = current_move_id(battle, side, active, slot);
        if (move_id == 0) continue;
        const PokemonMoveData *descriptor = find_move(battle, move_id);
        if (descriptor == NULL) return POKEMON_INVALID_CONFIGURATION;
        slots[slot] = (PokemonMoveChoiceSlot){
            .move_id = move_id,
            .pp = battle->sides[side].state[active].pp[slot],
            .category = descriptor->category,
        };
    }
    return POKEMON_OK;
}

static int has_choice_control_event(
    const PokemonBattle *battle, size_t side, PokemonEventId event
) {
    const PokemonMutable *state = &battle->sides[side].state[
        battle->sides[side].active];
    for (size_t i = 0; i < state->volatile_count; i++) {
        const PokemonChoiceControlPolicy *policy = choice_control_policy(
            battle->generation->choice_control_policies,
            battle->generation->choice_control_policy_count,
            state->volatiles[i].descriptor_id);
        if (policy == NULL) continue;
        if ((event == POKEMON_HANDLER_EVENT_DISABLE_MOVE &&
             policy->request_op != POKEMON_CHOICE_REQUEST_NONE) ||
            (event == POKEMON_HANDLER_EVENT_OVERRIDE_ACTION &&
             policy->action_op ==
                POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE) ||
            (event == POKEMON_HANDLER_EVENT_BEFORE_MOVE &&
             (policy->action_op ==
                POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE ||
              policy->action_op ==
                POKEMON_CHOICE_ACTION_REJECT_CATEGORY ||
              policy->action_op ==
                POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC)) ||
            (event == POKEMON_HANDLER_EVENT_LOCK_MOVE &&
              policy->request_op ==
                POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC)) return 1;
    }
    size_t foe_side = 1u - side;
    const PokemonMutable *foe = &battle->sides[foe_side].state[
        battle->sides[foe_side].active];
    for (size_t volatile_index = 0; volatile_index < foe->volatile_count;
         volatile_index++) {
        uint16_t descriptor_id = foe->volatiles[volatile_index].descriptor_id;
        for (size_t binding = 0;
             binding < battle->data->owner_binding_index_count; binding++) {
            const PokemonOwnerBindingIndex *index =
                &battle->data->owner_binding_index[binding];
            if (index->owner_kind == POKEMON_OWNER_VOLATILE &&
                index->owner_id == descriptor_id && index->event == event &&
                index->scope == POKEMON_HANDLER_SCOPE_FOE &&
                index->route == POKEMON_HANDLER_ROUTE_OWNER) return 1;
        }
    }
    return 0;
}

static int project_request(PokemonBattle *battle) {
    memset(&battle->request, 0, sizeof(battle->request));
    if (battle->terminal) {
        battle->request.kind[0] = POKEMON_REQUEST_TERMINAL;
        battle->request.kind[1] = POKEMON_REQUEST_TERMINAL;
        return POKEMON_OK;
    }
    uint8_t forced_sides = 0;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        uint8_t active = battle->sides[side].active;
        if (battle->sides[side].state[active].hp == 0) {
            forced_sides |= (uint8_t)(1u << side);
        }
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        if (forced_sides != 0 && (forced_sides & (1u << side)) != 0) {
            battle->request.kind[side] = POKEMON_REQUEST_SWITCH;
            battle->request.required_sides |= (uint8_t)(1u << side);
        } else if (forced_sides != 0) {
            battle->request.kind[side] = POKEMON_REQUEST_WAIT;
        } else {
            battle->request.kind[side] = POKEMON_REQUEST_MOVE;
            battle->request.required_sides |= (uint8_t)(1u << side);
            PokemonMoveChoiceSlot slots[POKEMON_MOVE_CAPACITY];
            int status = build_move_choice_slots(battle, side, slots);
            if (status != POKEMON_OK) return status;
            PokemonMoveChoiceSet choice_set;
            PokemonMoveRestriction restrictions[POKEMON_VOLATILE_CAPACITY];
            PokemonMoveRestrictionBuffer restriction_buffer = {
                .values = restrictions,
                .capacity = POKEMON_VOLATILE_CAPACITY,
                .last_move_id = battle->sides[side].state[
                    battle->sides[side].active].last_move_id,
                .fallback_move_id = battle->generation->fallback_move_id,
            };
            if (has_choice_control_event(
                    battle, side, POKEMON_HANDLER_EVENT_DISABLE_MOVE)) {
                PokemonEventFrame disable_move;
                status = run_event_inner(battle, &(PokemonEventInput){
                    .event = POKEMON_HANDLER_EVENT_DISABLE_MOVE,
                    .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side,
                        battle->sides[side].active},
                    .target_side = (uint8_t)side,
                    .target_slot = battle->sides[side].active,
                    .relay = {.kind = POKEMON_RELAY_UNDEFINED},
                    .context_kind = POKEMON_EVENT_CONTEXT_MOVE_RESTRICTIONS,
                    .context.move_restrictions = &restriction_buffer,
                }, &disable_move);
                if (status != POKEMON_OK) return status;
            }
            /* Showdown constructs the ordinary move list (including
             * DisableMove restrictions) before asking LockMove to collapse
             * it to a forced choice. Keep that event order observable: some
             * conditions participate in both stages. */
            uint16_t locked = 0;
            status = query_locked_move(battle, side, &locked);
            if (status != POKEMON_OK) return status;
            status = pokemon_reduce_move_choices(
                slots, POKEMON_MOVE_CAPACITY, locked,
                battle->generation->fallback_move_id,
                restrictions, restriction_buffer.count, &choice_set);
            if (status != POKEMON_OK) return status;
            if (choice_set.kind == POKEMON_MOVE_CHOICE_SET_SELECTABLE) {
                battle->request.legal_moves[side] = choice_set.legal_slot_mask;
            } else {
                battle->request.legal_moves[side] = 1u;
                battle->request.forced_move_id[side] =
                    choice_set.synthetic_move_id;
            }
        }
        if (battle->request.kind[side] != POKEMON_REQUEST_WAIT &&
            locked_move_id(battle, side) == 0) {
            for (size_t slot = 0; slot < battle->team_sizes[side]; slot++) {
                if (slot != battle->sides[side].active &&
                    battle->sides[side].state[slot].hp != 0) {
                    battle->request.legal_switches[side] |= (uint8_t)(1u << slot);
                }
            }
        }
    }
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        uint8_t candidate_switches = battle->request.legal_switches[side];
        if (battle->request.kind[side] == POKEMON_REQUEST_SWITCH) {
            int status = pokemon_make_switch_choice_request(
                candidate_switches, POKEMON_SWITCH_CHOICE_FORCED_REPLACEMENT,
                NULL, 0, POKEMON_TRAP_DISCLOSURE_NONE,
                &battle->request.switch_choices[side]);
            if (status != POKEMON_OK) return status;
            continue;
        }
        if (battle->request.kind[side] != POKEMON_REQUEST_MOVE) continue;
        uint8_t active = battle->sides[side].active;
        PokemonEventInput trap_input = {
            .event = POKEMON_HANDLER_EVENT_TRAP_POKEMON,
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, active},
            .target_side = (uint8_t)side, .target_slot = active,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .context_kind = POKEMON_EVENT_CONTEXT_SWITCH_RESTRICTIONS,
        };
        PokemonHandlerRef trap_handlers[POKEMON_HANDLER_CAPACITY];
        size_t trap_handler_count = 0;
        int status = discover_handlers(
            battle, &trap_input, trap_handlers, &trap_handler_count);
        if (status != POKEMON_OK) return status;
        PokemonSwitchRestriction restrictions[POKEMON_VOLATILE_CAPACITY];
        PokemonSwitchRestrictionBuffer restriction_buffer = {
            .values = restrictions, .capacity = POKEMON_VOLATILE_CAPACITY,
        };
        if (trap_handler_count != 0) {
            trap_input.context.switch_restrictions = &restriction_buffer;
            PokemonEventFrame trap;
            status = run_event_inner(battle, &trap_input, &trap);
            if (status != POKEMON_OK) return status;
        }
        PokemonTrapDisclosure disclosure = POKEMON_TRAP_DISCLOSURE_NONE;
        for (size_t i = 0; i < restriction_buffer.count; i++) {
            if (restrictions[i].hidden) {
                if (disclosure == POKEMON_TRAP_DISCLOSURE_NONE) {
                    disclosure = POKEMON_TRAP_DISCLOSURE_MAYBE;
                }
            } else {
                disclosure = POKEMON_TRAP_DISCLOSURE_KNOWN;
            }
        }
        status = pokemon_make_switch_choice_request(
            candidate_switches, POKEMON_SWITCH_CHOICE_VOLUNTARY,
            restrictions, restriction_buffer.count, disclosure,
            &battle->request.switch_choices[side]);
        if (status != POKEMON_OK) return status;
        battle->request.legal_switches[side] =
            disclosure == POKEMON_TRAP_DISCLOSURE_KNOWN ?
            battle->request.switch_choices[side].definitive_mask :
            battle->request.switch_choices[side].candidate_mask;
    }
    return POKEMON_OK;
}

static int project_move_switch_request(PokemonBattle *battle) {
    const PokemonPendingMoveSwitch *pending = &battle->pending_move_switch;
    if (!pending->active || pending->side >= POKEMON_SIDES ||
        pending->outgoing_slot >= battle->team_sizes[pending->side] ||
        battle->sides[pending->side].active != pending->outgoing_slot ||
        battle->sides[pending->side].state[pending->outgoing_slot].hp == 0 ||
        pending->transfer == POKEMON_SWITCH_TRANSFER_NONE) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    memset(&battle->request, 0, sizeof(battle->request));
    uint8_t candidates = 0;
    for (size_t slot = 0; slot < battle->team_sizes[pending->side]; slot++) {
        if (slot != pending->outgoing_slot &&
            battle->sides[pending->side].state[slot].hp != 0) {
            candidates |= (uint8_t)(1u << slot);
        }
    }
    if (candidates == 0) return POKEMON_INVALID_CONFIGURATION;
    uint8_t other = (uint8_t)(1u - pending->side);
    battle->request.kind[pending->side] = POKEMON_REQUEST_SWITCH;
    battle->request.kind[other] = POKEMON_REQUEST_WAIT;
    battle->request.required_sides = (uint8_t)(1u << pending->side);
    battle->request.legal_switches[pending->side] = candidates;
    return pokemon_make_switch_choice_request(
        candidates, POKEMON_SWITCH_CHOICE_MOVE_DRIVEN, NULL, 0,
        POKEMON_TRAP_DISCLOSURE_NONE,
        &battle->request.switch_choices[pending->side]);
}

static int validate_choice(
    const PokemonBattle *battle, size_t side, PokemonChoice choice
) {
    PokemonRequestKind request = battle->request.kind[side];
    if (request == POKEMON_REQUEST_WAIT) {
        return choice.kind == POKEMON_CHOICE_NONE;
    }
    if (request == POKEMON_REQUEST_TERMINAL) return 0;
    if (choice.kind == POKEMON_CHOICE_MOVE) {
        return request == POKEMON_REQUEST_MOVE &&
            choice.slot < POKEMON_MOVE_CAPACITY &&
            (battle->request.legal_moves[side] & (1u << choice.slot)) != 0;
    }
    if (choice.kind == POKEMON_CHOICE_SWITCH) {
        return choice.slot < battle->team_sizes[side] &&
            (battle->request.legal_switches[side] & (1u << choice.slot)) != 0;
    }
    return 0;
}

int pokemon_resolve_move_target(
    const PokemonFormat *format, PokemonMoveTarget mode,
    PokemonTargetRule *resolved
) {
    if (format == NULL || resolved == NULL || format->target_rules == NULL) return 0;
    for (size_t i = 0; i < format->target_rule_count; i++) {
        if (format->target_rules[i].mode != mode) continue;
        *resolved = format->target_rules[i];
        return resolved->capability == POKEMON_TARGET_SUPPORTED;
    }
    return 0;
}

static int compare_actions(const PokemonAction *left, const PokemonAction *right) {
    if (left->order != right->order) return left->order < right->order ? -1 : 1;
    if (left->priority != right->priority) {
        return left->priority > right->priority ? -1 : 1;
    }
    if (left->speed != right->speed) return left->speed > right->speed ? -1 : 1;
    return 0;
}

static int unsupported_event_applicable(
    const PokemonBattle *battle, PokemonEventId event,
    size_t source_side, size_t source_slot, size_t target_side, size_t target_slot,
    uint8_t *applicable
);
static int run_modify_boost_event(
    PokemonBattle *battle, size_t side, size_t slot,
    PokemonBoostTable *resolved
);

static int resolve_action_speed(
    PokemonBattle *battle, size_t side, size_t slot, uint16_t *speed,
    uint8_t suppress_trace
) {
    PokemonBoostTable boosts;
    int status = run_modify_boost_event(
        battle, side, slot, &boosts);
    if (status != POKEMON_OK || !boosts.present[POKEMON_STAT_SPE]) {
        return status != POKEMON_OK ? status : POKEMON_INVALID_CONFIGURATION;
    }
    uint32_t resolved = pokemon_apply_stage_ratio(
        battle->generation->stages,
        battle->sides[side].state[slot].stored_stats[4],
        boosts.delta[POKEMON_STAT_SPE], 0);
    uint8_t living = battle->sides[side].state[slot].hp != 0;
    uint8_t applicable = 0;
    status = living ? unsupported_event_applicable(
        battle, POKEMON_HANDLER_EVENT_MODIFY_SPE,
        side, slot, side, slot, &applicable) : POKEMON_OK;
    if (status != POKEMON_OK) return status;
    if (applicable) {
        PokemonEventFrame frame;
        status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_MODIFY_SPE,
            .source = {POKEMON_ENTITY_POKEMON, (uint8_t)side, (uint8_t)slot},
            .target_side = (uint8_t)side, .target_slot = (uint8_t)slot,
            .relay = {.kind = POKEMON_RELAY_U32, .value.u32 = resolved},
            .suppress_trace = suppress_trace,
        }, &frame);
        if (status != POKEMON_OK) return status;
        resolved = frame.relay.value.u32;
    }
    const PokemonItemData *item = find_item(
        battle, battle->sides[side].state[slot].item_id);
    if (living && battle->shared_turn_speed_active && item != NULL &&
        (item->flags & POKEMON_ITEM_FLAG_SHARED_TURN_SPEED_SENTINEL) != 0) {
        resolved = battle->generation->shared_turn_speed.speed_sentinel;
    }
    *speed = resolved > UINT16_MAX ? UINT16_MAX : (uint16_t)resolved;
    return POKEMON_OK;
}

static int refresh_active_speeds(PokemonBattle *battle) {
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        size_t slot = battle->sides[side].active;
        int status = resolve_action_speed(
            battle, side, slot,
            &battle->sides[side].state[slot].cached_speed, 1);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int resolve_each_event_active_order(
    PokemonBattle *battle, PokemonDrawLabel label,
    uint8_t order[POKEMON_SIDES]
) {
    if (order == NULL) return POKEMON_INVALID_ARGUMENT;
    order[0] = 0;
    order[1] = 1;
    size_t left_slot = battle->sides[0].active;
    size_t right_slot = battle->sides[1].active;
    PokemonMutable *left = &battle->sides[0].state[left_slot];
    PokemonMutable *right = &battle->sides[1].state[right_slot];
    if (left->hp == 0 || right->hp == 0) return POKEMON_OK;
    if (right->cached_speed > left->cached_speed) {
        order[0] = 1;
        order[1] = 0;
        return POKEMON_OK;
    }
    if (left->cached_speed != right->cached_speed) return POKEMON_OK;
    uint32_t chosen = 0;
    int status = draw_below(battle, label, 2, &chosen);
    if (status == POKEMON_OK && chosen != 0) {
        order[0] = 1;
        order[1] = 0;
    }
    return status;
}

static int each_event_active_order(PokemonBattle *battle, PokemonDrawLabel label) {
    uint8_t ignored[POKEMON_SIDES];
    return resolve_each_event_active_order(battle, label, ignored);
}

static int run_update_each_event_inner(
    PokemonBattle *battle, uint8_t suppress_trace
) {
    uint8_t order[POKEMON_SIDES] = {0, 1};
    PokemonMutable *left = &battle->sides[0].state[battle->sides[0].active];
    PokemonMutable *right = &battle->sides[1].state[battle->sides[1].active];
    if (!left->fainted && !right->fainted) {
        if (right->cached_speed > left->cached_speed) {
            order[0] = 1; order[1] = 0;
        } else if (right->cached_speed == left->cached_speed) {
            uint32_t chosen = 0;
            int status = draw_below(
                battle, POKEMON_DRAW_EACH_EVENT_UPDATE_ACTIVE_ORDER, 2, &chosen);
            if (status != POKEMON_OK) return status;
            if (chosen != 0) { order[0] = 1; order[1] = 0; }
        }
    }
    for (size_t i = 0; i < POKEMON_SIDES; i++) {
        uint8_t side = order[i];
        uint8_t slot = battle->sides[side].active;
        if (battle->sides[side].state[slot].fainted) continue;
        uint8_t applicable = 0;
        int status = unsupported_event_applicable(
            battle, POKEMON_HANDLER_EVENT_UPDATE,
            side, slot, side, slot, &applicable);
        if (status != POKEMON_OK) return status;
        if (!applicable) continue;
        PokemonEventFrame frame;
        status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_UPDATE,
            .source = {POKEMON_ENTITY_NONE, 0, 0},
            .target_side = side, .target_slot = slot,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
            .suppress_trace = suppress_trace,
            .suppress_handler_trace = suppress_trace,
        }, &frame);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int run_update_each_event(PokemonBattle *battle) {
    return run_update_each_event_inner(battle, 0);
}

static int run_weather_change_each_event(PokemonBattle *battle) {
    uint8_t order[POKEMON_SIDES] = {0, 1};
    PokemonMutable *left = &battle->sides[0].state[battle->sides[0].active];
    PokemonMutable *right = &battle->sides[1].state[battle->sides[1].active];
    if (!left->fainted && !right->fainted) {
        if (right->cached_speed > left->cached_speed) {
            order[0] = 1; order[1] = 0;
        } else if (right->cached_speed == left->cached_speed) {
            uint32_t chosen = 0;
            int status = draw_below(
                battle, POKEMON_DRAW_EACH_EVENT_WEATHER_CHANGE_ACTIVE_ORDER,
                2, &chosen);
            if (status != POKEMON_OK) return status;
            if (chosen != 0) { order[0] = 1; order[1] = 0; }
        }
    }
    for (size_t i = 0; i < POKEMON_SIDES; i++) {
        uint8_t side = order[i];
        uint8_t slot = battle->sides[side].active;
        if (battle->sides[side].state[slot].fainted) continue;
        PokemonEventFrame frame;
        int status = run_event_inner(battle, &(PokemonEventInput){
            .event = POKEMON_HANDLER_EVENT_WEATHER_CHANGE,
            .source = {POKEMON_ENTITY_NONE, 0, 0},
            .target_side = side, .target_slot = slot,
            .relay = {.kind = POKEMON_RELAY_UNDEFINED},
        }, &frame);
        if (status != POKEMON_OK) return status;
    }
    return POKEMON_OK;
}

static int queue_sort(PokemonBattle *battle) {
    /* Match Showdown's small-list selection sort.  Collect every action tied
     * for the next position, move that complete group forward, then
     * Fisher-Yates only that group.  The general form matters once a selected
     * move can contribute a separate pre-turn action; it also preserves the
     * existing two-choice draw sequence exactly. */
    size_t sorted = 0;
    while (sorted + 1 < battle->queue.count) {
        size_t next_indexes[POKEMON_QUEUE_CAPACITY];
        size_t next_count = 1;
        next_indexes[0] = sorted;
        for (size_t i = sorted + 1; i < battle->queue.count; i++) {
            int comparison = compare_actions(
                &battle->queue.values[next_indexes[0]],
                &battle->queue.values[i]);
            if (comparison < 0) continue;
            if (comparison > 0) {
                next_count = 1;
                next_indexes[0] = i;
            } else {
                next_indexes[next_count++] = i;
            }
        }
        for (size_t i = 0; i < next_count; i++) {
            size_t index = next_indexes[i];
            if (index == sorted + i) continue;
            PokemonAction temporary = battle->queue.values[sorted + i];
            battle->queue.values[sorted + i] = battle->queue.values[index];
            battle->queue.values[index] = temporary;
        }
        for (size_t i = sorted; i + 1 < sorted + next_count; i++) {
            uint32_t chosen = 0;
            int result = draw_below(
                battle, POKEMON_DRAW_QUEUE_TIE,
                (uint32_t)(sorted + next_count - i), &chosen);
            if (result != POKEMON_OK) return result;
            size_t index = i + chosen;
            if (index == i) continue;
            PokemonAction temporary = battle->queue.values[i];
            battle->queue.values[i] = battle->queue.values[index];
            battle->queue.values[index] = temporary;
        }
        sorted += next_count;
    }
    return POKEMON_OK;
}

static int enqueue_run_switch(PokemonBattle *battle, uint8_t side) {
    if (battle->queue.count == POKEMON_QUEUE_CAPACITY) {
        return POKEMON_CAPACITY_EXCEEDED;
    }
    uint8_t slot = battle->sides[side].active;
    int speed_status = resolve_action_speed(
        battle, side, slot,
        &battle->sides[side].state[slot].cached_speed, 1);
    if (speed_status != POKEMON_OK) return speed_status;
    PokemonAction action = {
        .kind = POKEMON_ACTION_RUN_SWITCH,
        .side = side,
        .slot = slot,
        .order = 101,
        .speed = battle->sides[side].state[slot].cached_speed,
    };
    /* Singles begins with at most two choice actions. A switch is popped
     * before its runSwitch is inserted, so this incremental queue is also at
     * most two elements. Showdown inserts only inside the new action's
     * equal-key interval; it never reshuffles an existing tie group. */
    assert(battle->queue.count <= 1);
    size_t first = 0;
    while (first < battle->queue.count &&
           compare_actions(&action, &battle->queue.values[first]) > 0) first++;
    size_t end = first;
    while (end < battle->queue.count &&
           compare_actions(&action, &battle->queue.values[end]) == 0) end++;
    size_t insertion = first;
    if (end > first) {
        uint32_t chosen = 0;
        int result = draw_below(battle, POKEMON_DRAW_QUEUE_TIE,
            (uint32_t)(end - first + 1), &chosen);
        if (result != POKEMON_OK) return result;
        insertion += chosen;
    }
    for (size_t index = battle->queue.count; index > insertion; index--) {
        battle->queue.values[index] = battle->queue.values[index - 1];
    }
    battle->queue.values[insertion] = action;
    battle->queue.count++;
    return POKEMON_OK;
}

static int compile_choices(
    PokemonBattle *battle, const PokemonChoice choices[POKEMON_SIDES]
) {
    battle->queue.count = 0;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        PokemonChoice choice = choices[side];
        if (choice.kind == POKEMON_CHOICE_NONE) continue;
        if (battle->queue.count == POKEMON_QUEUE_CAPACITY) {
            return POKEMON_CAPACITY_EXCEEDED;
        }
        PokemonAction *action = &battle->queue.values[battle->queue.count++];
        memset(action, 0, sizeof(*action));
        action->side = (uint8_t)side;
        action->slot = choice.slot;
        uint8_t active = battle->sides[side].active;
        int result = POKEMON_OK;
        if (choice.kind == POKEMON_CHOICE_SWITCH) {
            action->kind = POKEMON_ACTION_SWITCH;
            action->switch_cause = battle->phase ==
                POKEMON_PHASE_FORCED_REPLACEMENT ?
                POKEMON_SWITCH_CAUSE_FORCED_REPLACEMENT :
                POKEMON_SWITCH_CAUSE_VOLUNTARY;
            action->order = battle->phase == POKEMON_PHASE_FORCED_REPLACEMENT ? 3 : 103;
            action->speed = battle->sides[side].state[active].cached_speed;
        } else {
            uint16_t locked = 0;
            uint16_t forced = battle->request.forced_move_id[side];
            result = query_locked_move(battle, side, &locked);
            if (result != POKEMON_OK) return result;
            if (locked != 0) {
                action->selected_move_id = locked;
                action->move_choice_kind = POKEMON_MOVE_CHOICE_FORCED;
				action->slot = UINT8_MAX;
				for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
					if (current_move_id(battle, side, active, slot) == locked) {
						action->slot = (uint8_t)slot;
						break;
					}
				}
            } else if (forced != 0) {
                action->selected_move_id = forced;
                action->move_choice_kind = POKEMON_MOVE_CHOICE_FALLBACK;
            } else {
                action->selected_move_id =
                    current_move_id(battle, side, active, choice.slot);
                action->move_choice_kind = POKEMON_MOVE_CHOICE_SELECTED_SLOT;
            }
            result = resolve_action_speed(
                battle, side, active, &action->speed, 0);
            if (result != POKEMON_OK) return result;
            const PokemonMoveData *move = find_move(
                battle, action->selected_move_id);
            assert(move != NULL);
            action->kind = POKEMON_ACTION_MOVE;
            action->order = 200;
            action->priority = move->priority;
            PokemonTargetRule target;
            if (!pokemon_resolve_move_target(&battle->format, move->target, &target)) {
                return POKEMON_INVALID_CONFIGURATION;
            }
            action->target_mode = target.mode;
            action->resolved_target = target.resolved;
            action->target_loc = target.target_loc;
            if (move->pre_turn_condition_descriptor != 0) {
                if (battle->queue.count == POKEMON_QUEUE_CAPACITY) {
                    return POKEMON_CAPACITY_EXCEEDED;
                }
                PokemonAction move_action = *action;
                action->kind = POKEMON_ACTION_BEFORE_TURN_MOVE;
                action->order = 5;
                action->priority = 0;
                action->target_mode = 0;
                action->resolved_target = 0;
                action->target_loc = 0;
                battle->queue.values[battle->queue.count++] = move_action;
            }
        }
    }
    int result = queue_sort(battle);
    if (result != POKEMON_OK) return result;
    battle->last_queue.count = 0;
    for (size_t i = 0; i < battle->queue.count; i++) {
        if (battle->queue.values[i].kind == POKEMON_ACTION_BEFORE_TURN_MOVE) {
            continue;
        }
        battle->last_queue.values[battle->last_queue.count++] =
            battle->queue.values[i];
    }
    battle->phase = POKEMON_PHASE_ACTION_QUEUE;
    return POKEMON_OK;
}

static int compile_move_switch_choice(
    PokemonBattle *battle, const PokemonChoice choices[POKEMON_SIDES]
) {
    PokemonPendingMoveSwitch *pending = &battle->pending_move_switch;
    if (!pending->active || pending->side >= POKEMON_SIDES ||
        choices[pending->side].kind != POKEMON_CHOICE_SWITCH ||
        choices[1u - pending->side].kind != POKEMON_CHOICE_NONE ||
        battle->queue.count == POKEMON_QUEUE_CAPACITY) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    for (size_t index = battle->queue.count; index != 0; index--) {
        battle->queue.values[index] = battle->queue.values[index - 1];
    }
    int speed_status = resolve_action_speed(
        battle, pending->side, pending->outgoing_slot,
        &battle->sides[pending->side].state[
            pending->outgoing_slot].cached_speed, 1);
    if (speed_status != POKEMON_OK) return speed_status;
    battle->queue.values[0] = (PokemonAction){
        .kind = POKEMON_ACTION_SWITCH,
        .side = pending->side,
        .slot = choices[pending->side].slot,
        .order = 3,
        .speed = battle->sides[pending->side].state[
            pending->outgoing_slot].cached_speed,
        .switch_cause = POKEMON_SWITCH_CAUSE_MOVE_DRIVEN,
        .switch_transfer = pending->transfer,
        .skip_before_switch_out = pending->skip_before_switch_out,
    };
    battle->queue.count++;
    battle->last_queue.count = 1;
    battle->last_queue.values[0] = battle->queue.values[0];
    return POKEMON_OK;
}

static PokemonAction queue_pop(PokemonQueue *queue) {
    assert(queue->count != 0);
    PokemonAction result = queue->values[0];
    for (size_t i = 1; i < queue->count; i++) queue->values[i - 1] = queue->values[i];
    queue->count--;
    return result;
}

static void cancel_side_actions(PokemonQueue *queue, size_t side) {
    uint8_t write = 0;
    for (size_t read = 0; read < queue->count; read++) {
        if (queue->values[read].side != side) queue->values[write++] = queue->values[read];
    }
    queue->count = write;
}

static uint8_t living_inactive_slots(
    const PokemonBattle *battle, uint8_t side,
    uint8_t slots[POKEMON_TEAM_CAPACITY]
) {
    uint8_t count = 0;
    for (uint8_t position = 1; position < battle->team_sizes[side];
         position++) {
        uint8_t slot = battle->sides[side].party_order[position];
        const PokemonMutable *candidate = &battle->sides[side].state[slot];
        if (candidate->hp != 0 && !candidate->fainted) slots[count++] = slot;
    }
    return count;
}

static int admit_force_switch_effect(
    PokemonBattle *battle, const PokemonMoveData *move,
    PokemonEntityRef source, PokemonEntityRef target, uint8_t *succeeded
) {
    *succeeded = 1;
    PokemonMutable *source_state = &battle->sides[source.side].state[source.slot];
    PokemonMutable *target_state = &battle->sides[target.side].state[target.slot];
    uint8_t eligible[POKEMON_TEAM_CAPACITY];
    if (source_state->hp == 0 || target_state->hp == 0 ||
        living_inactive_slots(battle, target.side, eligible) == 0) {
        *succeeded = 0;
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_BLOCK,
            .side = target.side, .target_side = source.side,
            .slot = target.slot,
            .species_id = battle->sides[target.side].sets[target.slot].species_id,
            .move_id = move->id,
        });
        return POKEMON_OK;
    }
    PokemonEventFrame drag_out;
    int result = run_event_inner(battle, &(PokemonEventInput){
        .event = POKEMON_HANDLER_EVENT_DRAG_OUT,
        .source = source,
        .target_side = target.side, .target_slot = target.slot,
        .source_effect = {POKEMON_SOURCE_EFFECT_MOVE, move->id},
        .relay = {.kind = POKEMON_RELAY_BOOLEAN, .value.boolean = 1},
        .context_kind = POKEMON_EVENT_CONTEXT_MOVE,
        .context.move = {.move = move},
    }, &drag_out);
    if (result != POKEMON_OK) return result;
    if (drag_out.cancellation != POKEMON_EVENT_CANCEL_NONE ||
        drag_out.relay.kind != POKEMON_RELAY_BOOLEAN ||
        !drag_out.relay.value.boolean) {
        *succeeded = 0;
        append_event(battle, (PokemonEvent){
            .kind = POKEMON_EVENT_BLOCK,
            .side = target.side, .target_side = source.side,
            .slot = target.slot,
            .species_id = battle->sides[target.side].sets[target.slot].species_id,
            .move_id = move->id,
        });
        return POKEMON_OK;
    }
    if (battle->pending_drag.active) return POKEMON_CAPACITY_EXCEEDED;
    battle->pending_drag = (PokemonPendingDrag){
        .active = 1, .target = target,
    };
    return POKEMON_OK;
}
#line 3172 "pokemon.c"
