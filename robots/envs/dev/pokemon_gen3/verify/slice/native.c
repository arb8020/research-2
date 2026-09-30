#include <stdio.h>
#include <stdlib.h>

#include <string.h>

#include "gen3_rules.h"
#include "gen3_slice_data.h"
#include "singles2.h"
#include "generated_cases.h"


static const VerifyCase *output_case;

static const char *species_name(uint16_t id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.species_catalog_count; i++) {
        const PokemonSpeciesIdentity *identity =
            &POKEMON_GEN3_SLICE_DATA.species_catalog[i];
        if (identity->executable_id == id) return identity->id;
    }
    abort();
}

static const char *move_name(uint16_t id) {
	if (id == POKEMON_GEN3_RULES.fallback_move_id) return "struggle";
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_catalog_count; i++) {
        const PokemonMoveIdentity *identity =
            &POKEMON_GEN3_SLICE_DATA.move_catalog[i];
        if (identity->executable_id == id) return identity->id;
    }
    abort();
}

static const char *type_name(uint8_t id) {
    switch (id) {
    case POKEMON_GEN3_TYPE_NORMAL: return "normal";
    case POKEMON_GEN3_TYPE_GHOST: return "ghost";
    case POKEMON_GEN3_TYPE_PSYCHIC: return "psychic";
    case POKEMON_GEN3_TYPE_FIGHTING: return "fighting";
    case POKEMON_GEN3_TYPE_DARK: return "dark";
    case POKEMON_GEN3_TYPE_GRASS: return "grass";
    case POKEMON_GEN3_TYPE_POISON: return "poison";
    case POKEMON_GEN3_TYPE_FIRE: return "fire";
    case POKEMON_GEN3_TYPE_FLYING: return "flying";
    case POKEMON_GEN3_TYPE_GROUND: return "ground";
    case POKEMON_GEN3_TYPE_WATER: return "water";
    case POKEMON_GEN3_TYPE_ROCK: return "rock";
    case POKEMON_GEN3_TYPE_STEEL: return "steel";
    case POKEMON_GEN3_TYPE_BUG: return "bug";
    case POKEMON_GEN3_TYPE_ICE: return "ice";
    case POKEMON_GEN3_TYPE_ELECTRIC: return "electric";
    case POKEMON_GEN3_TYPE_DRAGON: return "dragon";
    case POKEMON_GEN3_TYPE_TYPELESS: return "???";
    default: abort();
    }
}

static const char *ability_name(uint16_t id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.ability_catalog_count; i++) {
        const PokemonNamedIdentity *identity =
            &POKEMON_GEN3_SLICE_DATA.ability_catalog[i];
        if (identity->executable_id == id) return identity->id;
    }
    abort();
}

static const char *item_name(uint16_t id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.item_catalog_count; i++) {
        const PokemonNamedIdentity *identity =
            &POKEMON_GEN3_SLICE_DATA.item_catalog[i];
        if (identity->executable_id == id) return identity->id;
    }
    abort();
}

static const char *condition_id_name(PokemonConditionScope scope, uint16_t id);

static const char *handler_condition_name(uint16_t id) {
    const PokemonConditionIdentity *identity = pokemon_condition_identity(
        &POKEMON_GEN3_SLICE_DATA, id);
    if (identity == NULL) abort();
    return identity->id;
}

static const char *side_condition_name(PokemonSideConditionKind kind) {
    return condition_id_name(POKEMON_CONDITION_SCOPE_SIDE, kind);
}

static const char *source_name(PokemonHandlerSourceKind kind, uint16_t id) {
    switch (kind) {
    case POKEMON_HANDLER_SOURCE_ABILITY: return ability_name(id);
    case POKEMON_HANDLER_SOURCE_ITEM: return item_name(id);
    case POKEMON_HANDLER_SOURCE_CONDITION: return handler_condition_name(id);
    case POKEMON_HANDLER_SOURCE_MOVE: return move_name(id);
    }
    abort();
}

static const char *source_kind_name(PokemonHandlerSourceKind kind) {
    switch (kind) {
    case POKEMON_HANDLER_SOURCE_ABILITY: return "ability";
    case POKEMON_HANDLER_SOURCE_ITEM: return "item";
    case POKEMON_HANDLER_SOURCE_CONDITION: return "condition";
    case POKEMON_HANDLER_SOURCE_MOVE: return "move";
    }
    abort();
}

static const char *request_name(PokemonRequestKind kind) {
    switch (kind) {
    case POKEMON_REQUEST_MOVE: return "move";
    case POKEMON_REQUEST_SWITCH: return "switch";
    case POKEMON_REQUEST_WAIT: return "wait";
    case POKEMON_REQUEST_TERMINAL: return "terminal";
    }
    abort();
}

static const char *stat_name(uint16_t stat) {
    static const char *const names[POKEMON_STAT_COUNT] = {
        "atk", "def", "spa", "spd", "spe", "accuracy", "evasion",
    };
    if (stat >= POKEMON_STAT_COUNT) abort();
    return names[stat];
}

static const char *status_name(uint16_t status) {
    switch (status) {
    case POKEMON_STATUS_NONE: return NULL;
    case POKEMON_STATUS_BURN: return "brn";
    case POKEMON_STATUS_PARALYSIS: return "par";
    case POKEMON_STATUS_POISON: return "psn";
    case POKEMON_STATUS_SLEEP: return "slp";
    case POKEMON_STATUS_FREEZE: return "frz";
    case POKEMON_STATUS_TOXIC: return "tox";
    default: abort();
    }
}

static const char *draw_name(PokemonDrawLabel label) {
    switch (label) {
    case POKEMON_DRAW_TEAM_GENDER: return "team.gender";
    case POKEMON_DRAW_QUEUE_TIE: return "queue.tie";
    case POKEMON_DRAW_ACCURACY: return "move.accuracy";
    case POKEMON_DRAW_CRITICAL: return "move.critical";
    case POKEMON_DRAW_DAMAGE_ROLL: return "move.damage_roll";
    case POKEMON_DRAW_SECONDARY: return "move.secondary";
    case POKEMON_DRAW_MULTIHIT_COUNT: return "move.multihit_count";
    case POKEMON_DRAW_END_TURN: return "turn.quick_claw";
    case POKEMON_DRAW_STALL_SUCCESS: return "stall.success";
    case POKEMON_DRAW_SET_STATUS_HANDLER_ORDER: return "event.setstatus.handler_order";
    case POKEMON_DRAW_SET_STATUS_HANDLER_ORDER_OFFSET_ONE: return "event.setstatus.handler_order";
    case POKEMON_DRAW_RESIDUAL_HANDLER_ORDER: return "field_event.residual.handler_order";
    case POKEMON_DRAW_EVENT_HANDLER_ORDER: return "event.handler_order";
    case POKEMON_DRAW_SLEEP_DURATION: return "status.sleep.duration";
    case POKEMON_DRAW_PARALYSIS: return "status.paralysis.before_move";
    case POKEMON_DRAW_FREEZE_THAW: return "status.freeze.before_move";
    case POKEMON_DRAW_EACH_EVENT_BEFORE_TURN_ACTIVE_ORDER:
        return "each_event.beforeturn.active_order";
    case POKEMON_DRAW_EACH_EVENT_UPDATE_ACTIVE_ORDER:
        return "each_event.update.active_order";
    case POKEMON_DRAW_EACH_EVENT_WEATHER_ACTIVE_ORDER:
        return "each_event.weather.active_order";
    case POKEMON_DRAW_EACH_EVENT_WEATHER_CHANGE_ACTIVE_ORDER:
        return "each_event.weatherchange.active_order";
    case POKEMON_DRAW_CONFUSION_DURATION: return "condition.confusion.duration";
    case POKEMON_DRAW_CONFUSION_ACTION: return "condition.confusion.action";
    case POKEMON_DRAW_LOCKED_MOVE_DURATION: return "condition.lockedmove.duration";
    case POKEMON_DRAW_PARTIALLY_TRAPPED_DURATION: return "condition.partiallytrapped.duration";
    case POKEMON_DRAW_DISABLE_DURATION: return "condition.disable.duration";
    case POKEMON_DRAW_ENCORE_DURATION: return "condition.encore.duration";
    case POKEMON_DRAW_UPROAR_DURATION: return "condition.uproar.duration";
    case POKEMON_DRAW_DAMAGE_FORMULA: return "move.damage_formula";
    case POKEMON_DRAW_CONTACT_RESPONSE: return "ability.contact_response.activation";
    case POKEMON_DRAW_CONTACT_STATUS_SELECTION: return "ability.contact_response.status";
    case POKEMON_DRAW_RESIDUAL_STATUS_CURE: return "ability.residual_status_cure";
    case POKEMON_DRAW_ABILITY_TARGET: return "ability.trace.target";
    case POKEMON_DRAW_ATTRACTION_ACTION: return "condition.attract.action";
    case POKEMON_DRAW_ITEM_RANDOM_STAT: return "item.starfberry.stat";
    case POKEMON_DRAW_MOVE_POWER_DISTRIBUTION: return "move.power_variant";
    case POKEMON_DRAW_MOVE_RESOLUTION_DISTRIBUTION:
        return "move.resolution_variant";
	case POKEMON_DRAW_FOCUS_BAND: return "item.focus_band";
    case POKEMON_DRAW_FORCED_SWITCH_TARGET: return "drag.switch_candidate";
    case POKEMON_DRAW_MOVE_DELEGATION_SELECTION:
        return "move.delegation.selection";
    case POKEMON_DRAW_TYPE_RESPONSE_SELECTION:
        return "move.type_response.selection";
    case POKEMON_DRAW_MOVE_PP_REDUCTION: return "move.pp_reduction";
    case POKEMON_DRAW_MOVE_TYPE_SELECTION: return "move.type_selection";
    case POKEMON_DRAW_MOVE_STATUS_SELECTION: return "move.status_selection";
    case POKEMON_DRAW_LABEL_COUNT: break;
    }
    abort();
}

static void write_request(const PokemonBattleView *view, size_t side) {
    PokemonRequestKind kind = view->request.kind[side];
    printf("{\"kind\":\"%s\",\"legal\":[", request_name(kind));
    int comma = 0;
    for (size_t slot = 0; slot < view->team_sizes[side]; slot++) {
        if (view->request.legal_switches[side] & (1u << slot)) {
            printf("%s\"switch %zu\"", comma ? "," : "", slot + 1);
            comma = 1;
        }
    }
    for (size_t slot = 0; slot < POKEMON_MOVE_CAPACITY; slot++) {
        if (view->request.legal_moves[side] & (1u << slot)) {
            printf("%s\"move %zu\"", comma ? "," : "", slot + 1);
            comma = 1;
        }
    }
    fputs("]}", stdout);
}

static const char *volatile_name(const PokemonVolatileState *state) {
    PokemonVolatileKind kind = state->kind;
    if (kind == POKEMON_VOLATILE_PREPARED_RETALIATION ||
        kind == POKEMON_VOLATILE_STORED_DAMAGE ||
        kind == POKEMON_VOLATILE_FURY_CUTTER ||
        kind == POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT) {
        const PokemonConditionIdentity *identity = pokemon_condition_identity(
            &POKEMON_GEN3_SLICE_DATA, state->descriptor_id);
        if (identity == NULL ||
            identity->domain != POKEMON_CONDITION_DOMAIN_VOLATILE) abort();
        return identity->id;
    }
    return kind == POKEMON_VOLATILE_PROTECT ? "protect" :
        kind == POKEMON_VOLATILE_STALL ? "stall" :
        kind == POKEMON_VOLATILE_MAGIC_COAT ? "magiccoat" :
        kind == POKEMON_VOLATILE_CONFUSION ? "confusion" :
        kind == POKEMON_VOLATILE_FOCUS_ENERGY ? "focusenergy" :
        kind == POKEMON_VOLATILE_LOCKED_MOVE ? "lockedmove" :
        kind == POKEMON_VOLATILE_TWO_TURN_MOVE ? "twoturnmove" :
        kind == POKEMON_VOLATILE_TWO_TURN_MARKER ?
            move_name(state->payload.two_turn.move_id) :
        kind == POKEMON_VOLATILE_SUBSTITUTE ? "substitute" :
        kind == POKEMON_VOLATILE_SUBSTITUTE_BROKEN ? "substitutebroken" :
        kind == POKEMON_VOLATILE_TAUNT ? "taunt" :
        kind == POKEMON_VOLATILE_TORMENT ? "torment" :
        kind == POKEMON_VOLATILE_DISABLE ? "disable" :
        kind == POKEMON_VOLATILE_ENCORE ? "encore" :
        kind == POKEMON_VOLATILE_YAWN ? "yawn" :
        kind == POKEMON_VOLATILE_MUST_RECHARGE ? "mustrecharge" :
        kind == POKEMON_VOLATILE_NIGHTMARE ? "nightmare" :
        kind == POKEMON_VOLATILE_ATTRACT ? "attract" :
        kind == POKEMON_VOLATILE_CHOICE_LOCK ? "choicelock" :
		kind == POKEMON_VOLATILE_TRAPPED ? "trapped" :
        kind == POKEMON_VOLATILE_MUD_SPORT ? "mudsport" :
        kind == POKEMON_VOLATILE_WATER_SPORT ? "watersport" :
        kind == POKEMON_VOLATILE_CHARGE ? "charge" :
        kind == POKEMON_VOLATILE_LEECH_SEED ? "leechseed" :
        kind == POKEMON_VOLATILE_FLASH_FIRE ? "flashfire" :
        kind == POKEMON_VOLATILE_COUNTDOWN_FAINT ? "perishsong" :
        kind == POKEMON_VOLATILE_FORESIGHT ? "foresight" :
        kind == POKEMON_VOLATILE_LOCK_ON ? "lockon" :
        kind == POKEMON_VOLATILE_INGRAIN ? "ingrain" :
		kind == POKEMON_VOLATILE_FURY_CUTTER ? "furycutter" :
		kind == POKEMON_VOLATILE_ROLLOUT ? "rollout" :
		kind == POKEMON_VOLATILE_ICE_BALL ? "iceball" :
		kind == POKEMON_VOLATILE_DEFENSE_CURL ? "defensecurl" :
		kind == POKEMON_VOLATILE_STOCKPILE ? "stockpile" :
		kind == POKEMON_VOLATILE_RAGE ? "rage" :
		kind == POKEMON_VOLATILE_MINIMIZE ? "minimize" :
		kind == POKEMON_VOLATILE_PREPARED_ACTION ? "focuspunch" :
		kind == POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE ? "destinybond" :
		kind == POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE ? "grudge" :
		kind == POKEMON_VOLATILE_UPROAR ? "uproar" :
		kind == POKEMON_VOLATILE_IMPRISON ? "imprison" :
        kind == POKEMON_VOLATILE_CURSE ? "curse" :
        "partiallytrapped";
}

static void write_pokemon(const PokemonBattleView *view, size_t side, size_t slot) {
    const PokemonSet *set = &view->sides[side].sets[slot];
    const PokemonMutable *state = &view->sides[side].state[slot];
    const char *gender = set->gender == POKEMON_GENDER_MALE ? "M" :
        set->gender == POKEMON_GENDER_FEMALE ? "F" : "N";
    printf("{\"species\":\"%s\",\"level\":%u,\"gender\":\"%s\",\"stats\":[",
        species_name(set->species_id), set->level, gender);
    for (size_t stat = 0; stat < 6; stat++) {
        printf("%s%u", stat ? "," : "", set->stats[stat]);
    }
    printf("],\"hp\":%u,\"max_hp\":%u,\"ability\":\"%s\","
        "\"effective_types\":[", state->hp, set->stats[0],
        ability_name(state->ability_id));
    for (size_t i = 0; i < state->effective_type_count; i++) {
        printf("%s\"%s\"", i ? "," : "", type_name(state->effective_types[i]));
    }
    fputs("],\"moves\":[", stdout);
    int comma = 0;
    for (size_t move_slot = 0; move_slot < POKEMON_MOVE_CAPACITY; move_slot++) {
        uint16_t id = state->move_ids[move_slot];
        if (id == 0) continue;
        printf("%s{\"id\":\"%s\",\"pp\":%u,\"max_pp\":%u}",
            comma ? "," : "", move_name(id), state->pp[move_slot],
            state->max_pp[move_slot]);
        comma = 1;
    }
    fputs("],\"boosts\":{", stdout);
    for (size_t stat = 0; stat < POKEMON_STAT_COUNT; stat++) {
        printf("%s\"%s\":%d", stat ? "," : "", stat_name(stat),
            state->boosts[stat]);
    }
    fputs("},\"status\":", stdout);
    if (state->status.kind == POKEMON_STATUS_NONE ||
        (state->fainted && view->phase == POKEMON_PHASE_FORCED_REPLACEMENT &&
         view->sides[side].active == slot)) fputs("null", stdout);
    else {
        const char *name = status_name(state->status.kind);
        if (name == NULL) abort();
        printf("\"%s\"", name);
    }
    fputs(",\"status_state\":", stdout);
    if (state->status.kind == POKEMON_STATUS_NONE &&
        !(state->fainted && view->phase == POKEMON_PHASE_FORCED_REPLACEMENT &&
          view->sides[side].active == slot)) fputs("null", stdout);
    else {
        printf("{\"stage\":%u,\"duration\":%u",
            state->status.kind == POKEMON_STATUS_TOXIC ?
                state->status.state.toxic.stage : 0,
            state->status.kind == POKEMON_STATUS_SLEEP ?
                state->status.state.sleep.time : 0);
        if (state->status.kind == POKEMON_STATUS_SLEEP) {
            printf(",\"skipped_time\":%u",
                state->status.state.sleep.skipped_time);
        }
        putchar('}');
    }
    fputs(",\"volatiles\":[", stdout);
    uint8_t volatile_order[POKEMON_VOLATILE_CAPACITY];
    for (size_t i = 0; i < state->volatile_count; i++) {
        size_t at = i;
        while (at != 0 && strcmp(volatile_name(&state->volatiles[i]),
            volatile_name(&state->volatiles[volatile_order[at - 1]])) < 0) {
            volatile_order[at] = volatile_order[at - 1];
            at--;
        }
        volatile_order[at] = (uint8_t)i;
    }
    for (size_t i = 0; i < state->volatile_count; i++) {
        if (i) putchar(',');
        const PokemonVolatileState *volatile_state =
            &state->volatiles[volatile_order[i]];
        const char *id = volatile_name(volatile_state);
        printf("{\"id\":\"%s\",\"duration\":%u,\"counter\":%u",
            id, volatile_state->kind == POKEMON_VOLATILE_CONFUSION ?
                volatile_state->payload.confusion.time : volatile_state->duration,
            volatile_state->counter);
        if (volatile_state->kind == POKEMON_VOLATILE_SUBSTITUTE) {
            printf(",\"hp\":%u", volatile_state->payload.substitute.hp);
        } else if (volatile_state->kind == POKEMON_VOLATILE_SUBSTITUTE_BROKEN) {
            printf(",\"breaking_move\":\"%s\"", move_name(
                volatile_state->payload.substitute_broken.breaking_move_id));
        } else if (volatile_state->kind == POKEMON_VOLATILE_LOCKED_MOVE) {
            printf(",\"move\":\"%s\",\"true_duration\":%u", move_name(
                volatile_state->payload.locked_move.move_id),
                volatile_state->payload.locked_move.true_duration);
        } else if (volatile_state->kind == POKEMON_VOLATILE_DISABLE ||
            volatile_state->kind == POKEMON_VOLATILE_ENCORE) {
            printf(",\"move\":\"%s\"", move_name(
                volatile_state->payload.choice_control.stored_move_id));
        } else if (volatile_state->kind == POKEMON_VOLATILE_ATTRACT ||
			volatile_state->kind == POKEMON_VOLATILE_TRAPPED ||
            volatile_state->kind == POKEMON_VOLATILE_LOCK_ON) {
            printf(",\"source_side\":%u,\"source_slot\":%u,"
                "\"source_effect\":{\"kind\":\"%s\",\"id\":\"%s\"}",
                volatile_state->source.side, volatile_state->source.slot,
                volatile_state->source_effect.kind == POKEMON_SOURCE_EFFECT_ABILITY ?
                    "ability" : "move",
                volatile_state->source_effect.kind == POKEMON_SOURCE_EFFECT_ABILITY ?
                    ability_name(volatile_state->source_effect.id) :
                    move_name(volatile_state->source_effect.id));
        } else if (volatile_state->kind == POKEMON_VOLATILE_STORED_DAMAGE) {
            printf(",\"total_damage\":%u,\"last_source\":",
                volatile_state->payload.stored_damage.value);
            if (!volatile_state->payload.stored_damage.captured) {
                fputs("null", stdout);
            } else {
                printf("{\"side\":%u,\"slot\":%u}",
                    volatile_state->payload.stored_damage.last_source.side,
                    volatile_state->payload.stored_damage.last_source.slot);
            }
        }
        putchar('}');
    }
    fputs("],\"last_move\":", stdout);
    if (state->last_move_id == 0) fputs("null", stdout);
    else printf("\"%s\"", move_name(state->last_move_id));
	fputs(",\"last_move_used\":", stdout);
	if (!state->last_move_used.present) {
		fputs("null", stdout);
	} else {
		printf("{\"move\":\"%s\",\"resolved_type\":\"%s\"}",
			move_name(state->last_move_used.move_id),
			type_name(state->last_move_used.resolved_type));
	}
    fputs(",\"attacked_by\":", stdout);
    if (!state->last_attacked_by.present) {
        fputs("null", stdout);
    } else {
        printf("{\"source_side\":%u,\"source_slot\":%u,\"move\":\"%s\","
            "\"damage\":%u,\"damage_was_number\":%s,\"this_turn\":%s}",
            state->last_attacked_by.source.side,
            state->last_attacked_by.source.slot,
            move_name(state->last_attacked_by.move_id),
            state->last_attacked_by.damage,
            state->last_attacked_by.damage_was_number ? "true" : "false",
            state->last_attacked_by.this_turn ? "true" : "false");
    }
    fputs(",\"item\":", stdout);
    if (state->item_id == 0) fputs("null", stdout);
    else printf("\"%s\"", item_name(state->item_id));
    fputs(",\"last_item\":", stdout);
    if (state->last_item_id == 0) fputs("null", stdout);
    else printf("\"%s\"", item_name(state->last_item_id));
    static const char *const staleness_names[] = {
        "null", "\"internal\"", "\"external\"",
    };
    printf(",\"staleness\":%s,\"pending_staleness\":%s,"
        "\"volatile_staleness\":%s",
        staleness_names[state->staleness],
        staleness_names[state->pending_staleness],
        staleness_names[state->volatile_staleness]);
    printf(",\"used_item_this_turn\":%s,\"ate_berry\":%s,\"item_knocked_off\":%s,\"fainted\":%s}",
        state->used_item_this_turn ? "true" : "false",
        state->ate_berry ? "true" : "false",
        state->item_knocked_off ? "true" : "false",
        state->fainted ? "true" : "false");
}

static const char *weather_name(PokemonWeatherKind kind) {
    switch (kind) {
    case POKEMON_WEATHER_NONE: return "";
    case POKEMON_WEATHER_SANDSTORM: return "sandstorm";
    case POKEMON_WEATHER_HAIL: return "hail";
    case POKEMON_WEATHER_RAIN: return "raindance";
    case POKEMON_WEATHER_SUN: return "sunnyday";
    }
    abort();
}

static const char *resolved_condition_name(
    PokemonConditionScope scope, uint16_t semantic_kind, uint16_t descriptor_id
);

static void write_state(const PokemonBattleView *view) {
    printf("{\"turn\":%u,\"terminal\":%s,\"winner\":",
        view->turn, view->terminal ? "true" : "false");
    if (view->terminal && view->winner >= 0) printf("%d", view->winner);
    else fputs("null", stdout);
    fputs(",\"field\":{\"weather\":", stdout);
    if (view->field.weather.kind == POKEMON_WEATHER_NONE) fputs("null", stdout);
    else printf("\"%s\"", weather_name(view->field.weather.kind));
    fputs(",\"weather_state\":", stdout);
    if (view->field.weather.kind == POKEMON_WEATHER_NONE) fputs("null", stdout);
    else printf("{\"id\":\"%s\",\"duration\":%u}",
        weather_name(view->field.weather.kind), view->field.weather.duration);
    fputs(",\"terrain\":null},\"sides\":[", stdout);
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        printf("%s{\"active\":%u,\"side_conditions\":[", side ? "," : "", view->sides[side].active);
        const PokemonSideConditionState *conditions[
            POKEMON_SIDE_CONDITION_CAPACITY];
        for (size_t i = 0; i < view->sides[side].condition_count; i++) {
            conditions[i] = &view->sides[side].conditions[i];
        }
        for (size_t i = 1; i < view->sides[side].condition_count; i++) {
            const PokemonSideConditionState *condition = conditions[i];
            size_t position = i;
            while (position > 0 && strcmp(
                    side_condition_name(conditions[position - 1]->kind),
                    side_condition_name(condition->kind)) > 0) {
                conditions[position] = conditions[position - 1];
                position--;
            }
            conditions[position] = condition;
        }
        for (size_t i = 0; i < view->sides[side].condition_count; i++) {
            if (i) putchar(',');
            printf("{\"id\":\"%s\",",
                side_condition_name(conditions[i]->kind));
            if (conditions[i]->counter != 0) {
                printf("\"layers\":%u}",
                    conditions[i]->counter);
            } else {
                printf("\"duration\":%u}",
                    conditions[i]->duration);
            }
        }
        fputs("],\"slot_conditions\":[", stdout);
        size_t slot_written = 0;
        for (size_t position = 0;
             position < POKEMON_ACTIVE_POSITION_CAPACITY; position++) {
            const PokemonSlotConditionState *slots[
                POKEMON_SLOT_CONDITION_CAPACITY];
            size_t count = view->sides[side].slot_condition_count[position];
            for (size_t i = 0; i < count; i++) {
                slots[i] = &view->sides[side].slot_conditions[position][i];
            }
            for (size_t i = 1; i < count; i++) {
                const PokemonSlotConditionState *condition = slots[i];
                size_t at = i;
                while (at > 0 && strcmp(
                        resolved_condition_name(
                            POKEMON_CONDITION_SCOPE_SLOT,
                            slots[at - 1]->semantic_kind,
                            slots[at - 1]->descriptor_id),
                        resolved_condition_name(
                            POKEMON_CONDITION_SCOPE_SLOT,
                            condition->semantic_kind,
                            condition->descriptor_id)) > 0) {
                    slots[at] = slots[at - 1];
                    at--;
                }
                slots[at] = condition;
            }
            for (size_t i = 0; i < count; i++) {
                const PokemonSlotConditionState *condition = slots[i];
                if (slot_written++) putchar(',');
                printf("{\"position\":%zu,\"id\":\"%s\",\"duration\":%u,"
                    "\"source_side\":%u,\"source_slot\":%u,"
                    "\"source_effect\":",
                    position, resolved_condition_name(
                        POKEMON_CONDITION_SCOPE_SLOT,
                        condition->semantic_kind, condition->descriptor_id),
                    condition->duration, condition->source.side,
                    condition->source.slot);
                if (condition->semantic_kind ==
                        POKEMON_SLOT_CONDITION_FUTURE_MOVE) {
                    printf("{\"kind\":\"move\",\"id\":\"%s\"},"
                        "\"payload\":{\"kind\":\"delayed-move\",\"move\":\"%s\","
                        "\"fixed_damage\":%u}}",
                        move_name(condition->source_effect.id),
                        move_name(condition->payload.delayed_move.move_id),
                        condition->payload.delayed_move.fixed_damage);
                } else {
                    fputs("{\"kind\":\"condition\"},"
                        "\"payload\":{\"kind\":\"wish\"}}", stdout);
                }
            }
        }
        fputs("],\"pokemon\":[", stdout);
        for (size_t slot = 0; slot < view->team_sizes[side]; slot++) {
            if (slot) putchar(',');
            write_pokemon(view, side, slot);
        }
        fputs("]}", stdout);
    }
    fputs("]}", stdout);
}

static void write_event(const PokemonEvent *event) {
    switch (event->kind) {
    case POKEMON_EVENT_SWITCH:
        printf("{\"kind\":\"%s\",\"side\":%u,\"species\":\"%s\",\"hp\":%u,\"max_hp\":%u}",
            event->switch_cause == POKEMON_SWITCH_CAUSE_DRAG ? "drag" : "switch",
            event->side, species_name(event->species_id), event->hp,
            output_case->init.teams[event->side].members[event->slot].stats[0]);
        break;
    case POKEMON_EVENT_MOVE:
        printf("{\"kind\":\"move\",\"side\":%u,\"move\":\"%s\",\"target_side\":",
            event->side, move_name(event->move_id));
        if (event->target_side == UINT8_MAX) fputs("null}", stdout);
        else printf("%u}", event->target_side);
        break;
    case POKEMON_EVENT_MISS:
        printf("{\"kind\":\"miss\",\"side\":%u}", event->side);
        break;
    case POKEMON_EVENT_IMMUNE:
        printf("{\"kind\":\"immune\",\"side\":%u}", event->side);
        break;
    case POKEMON_EVENT_DAMAGE:
        printf("{\"kind\":\"damage\",\"side\":%u,\"species\":\"%s\",\"amount\":%u,\"hp\":%u}",
            event->side, species_name(event->species_id), event->amount, event->hp);
        break;
    case POKEMON_EVENT_HEAL:
        printf("{\"kind\":\"heal\",\"side\":%u,\"species\":\"%s\",\"amount\":%u,\"hp\":%u}",
            event->side, species_name(event->species_id), event->amount, event->hp);
        break;
    case POKEMON_EVENT_FAINT:
        printf("{\"kind\":\"faint\",\"side\":%u}", event->side);
        break;
    case POKEMON_EVENT_WIN:
        printf("{\"kind\":\"win\",\"side\":%u}", event->side);
        break;
    case POKEMON_EVENT_TIE:
        fputs("{\"kind\":\"tie\"}", stdout);
        break;
    case POKEMON_EVENT_STATUS:
    case POKEMON_EVENT_CONDITION:
    case POKEMON_EVENT_BLOCK:
        abort();
    }
}

static int protocol_event(PokemonEventKind kind) {
    return (kind >= POKEMON_EVENT_SWITCH && kind <= POKEMON_EVENT_WIN) ||
        kind == POKEMON_EVENT_HEAL || kind == POKEMON_EVENT_TIE;
}

static void write_seed(const uint16_t seed[4]) {
    printf("[%u,%u,%u,%u]", seed[0], seed[1], seed[2], seed[3]);
}

static const char *choice_name(PokemonChoiceKind kind) {
    switch (kind) {
    case POKEMON_CHOICE_NONE: return "none";
    case POKEMON_CHOICE_MOVE: return "move";
    case POKEMON_CHOICE_SWITCH: return "switch";
    }
    abort();
}

static const char *action_name(PokemonActionKind kind) {
    switch (kind) {
    case POKEMON_ACTION_MOVE: return "move";
    case POKEMON_ACTION_SWITCH: return "switch";
    case POKEMON_ACTION_RUN_SWITCH: return "run-switch";
    case POKEMON_ACTION_BEFORE_TURN_MOVE: return "before-turn-move";
    }
    abort();
}

static void write_transition(
    const PokemonChoice choices[POKEMON_SIDES], const PokemonQueue *queue
) {
    fputs(",\"choices\":[", stdout);
    if (choices != NULL) {
        for (size_t side = 0; side < POKEMON_SIDES; side++) {
            if (side) putchar(',');
            printf("{\"kind\":\"%s\",\"slot\":", choice_name(choices[side].kind));
            if (choices[side].kind == POKEMON_CHOICE_NONE) fputs("null", stdout);
            else printf("%u", choices[side].slot);
            putchar('}');
        }
    }
    fputs("],\"queue\":[", stdout);
    if (queue != NULL) {
        for (size_t i = 0; i < queue->count; i++) {
            const PokemonAction *action = &queue->values[i];
            if (i) putchar(',');
            printf("{\"kind\":\"%s\",\"side\":%u,\"slot\":%d,\"order\":%d",
                action_name(action->kind), action->side,
                action->kind == POKEMON_ACTION_MOVE &&
                    (action->move_choice_kind == POKEMON_MOVE_CHOICE_FALLBACK ||
                     action->slot >= POKEMON_MOVE_CAPACITY ||
                     action->selected_move_id == POKEMON_GEN3_MOVE_RECHARGE) ?
                    -1 : (int)action->slot,
                action->order);
            if (action->kind == POKEMON_ACTION_MOVE) {
                printf(",\"priority\":%d", action->priority);
            }
            printf(",\"speed\":%u}", action->speed);
        }
    }
    putchar(']');
}

static void write_handlers(const PokemonBattleView *view) {
    fputs(",\"handlers\":[", stdout);
    size_t written = 0;
    for (uint32_t sequence = 1; sequence <= view->semantic_sequence; sequence++) {
        const PokemonHandlerRef *handler = NULL;
        const char *event = NULL;
        for (size_t i = 0; i < view->handler_count; i++) {
            if (view->handlers[i].semantic_sequence == sequence) {
                handler = &view->handlers[i].handler;
                event = handler->descriptor.event == POKEMON_HANDLER_EVENT_AFTER_SET_STATUS ?
                        "after-set-status" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_AFTER_SUB_DAMAGE ?
                        "after-sub-damage" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_AFTER_MOVE ?
                        "after-move" :
                    handler->descriptor.event ==
                            POKEMON_HANDLER_EVENT_AFTER_MOVE_SECONDARY_SELF ?
                        "after-move-secondary-self" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_SET_STATUS ?
                    "set-status" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_DAMAGE ?
                    "damage" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_HIT ?
                        "try-hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_BOOST ?
                        "try-boost" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_PREPARE_HIT ?
                        "prepare-hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_PRIMARY_HIT ?
                        "try-primary-hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_ADD_VOLATILE ?
                        "try-add-volatile" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_IMMUNITY ?
                        "immunity" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_HIT ?
                        "hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MOVE_HIT_CALLBACK ?
                        "hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MOVE_HIT_FIELD_CALLBACK ?
                        "hit-field" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_START ?
                        "start" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_END ?
                        "end" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_BEFORE_MOVE ?
                        "before-move" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_DISABLE_MOVE ?
                        "disable-move" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_OVERRIDE_ACTION ?
                        "override-action" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY ?
                        "try" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_MOVE ?
                        "try-move" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_HEAL ?
                        "try-heal" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY ?
                        "try-immunity" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_INVULNERABILITY ?
                        "invulnerability" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_DAMAGING_HIT ?
                        "damaging-hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_BASE_POWER ?
                        "base-power" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MOVE_ABORTED ?
                        "move-aborted" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MOVE_FAIL ?
                        "move-fail" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_RESIDUAL ?
                        "residual" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_RESTART ?
                        "restart" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_SWITCH_OUT ?
                        "switch-out" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_BEFORE_SWITCH_OUT ?
                        "before-switch-out" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_SWITCH_IN ?
                        "switch-in" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_DEDUCT_PP ?
                        "deduct-pp" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_TYPE ?
                        "modify-type" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_MOVE ?
                        "modify-move" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_USE_MOVE_MESSAGE ?
                        "use-move-message" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_LOCK_MOVE ?
                        "lock-move" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRAP_POKEMON ?
                        "trap-pokemon" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_ENTRY_HAZARD ?
                        "entry-hazard" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_FAINT ?
                        "faint" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_EAT_ITEM ?
                        "try-eat-item" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_ITEM_EAT ?
                        "eat" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_UPDATE ?
                        "update" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SECONDARIES ?
                        "modify-secondaries" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_ACCURACY ?
                        "accuracy" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ?
                        "modify-accuracy" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_BOOST ?
                        "modify-boost" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_NEGATE_IMMUNITY ?
                        "negate-immunity" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_DRAG_OUT ?
                        "drag-out" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_CRITICAL_HIT ?
                        "critical-hit" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_WEATHER_CHANGE ?
                        "weather-change" : NULL;
                if (event == NULL) abort();
            }
        }
        for (size_t i = 0; i < view->modifier_count; i++) {
            if (view->modifiers[i].semantic_sequence == sequence) {
                if (view->modifiers[i].handler.descriptor.event ==
                        POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) continue;
                handler = &view->modifiers[i].handler;
                event = handler->descriptor.event == POKEMON_HANDLER_EVENT_BASE_POWER ?
                    "base-power" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_ATK ?
                    "modify-atk" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_DEF ?
                    "modify-def" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPA ?
                        "modify-spa" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPD ?
                        "modify-spd" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPE ?
                        "modify-spe" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ?
                        "modify-accuracy" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO ?
                        "modify-crit-ratio" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE ?
                        "modify-damage" :
                handler->descriptor.event == POKEMON_HANDLER_EVENT_RESIDUAL ?
                        "residual" :
                    handler->descriptor.event == POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE ?
                        "weather-modify-damage" : NULL;
                if (event == NULL) abort();
            }
        }
        if (handler == NULL) continue;
        /* A move's TryImmunity is a direct single-event callback in Showdown,
         * not a discovered event-handler list. Its result is observed through
         * the immunity boundary instead. */
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY_IMMUNITY &&
            handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_MOVE) continue;
        /* Move-owned onPrepareHit is a direct single-event callback. Its
         * mutations remain observable, but it is not part of Showdown's
         * discovered handler list. */
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_PREPARE_HIT &&
            handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_MOVE) continue;
        /* Showdown invokes beforeMoveCallback directly on the selected move;
         * it is generated as a typed native program but is not a discovered
         * event-handler record at the shared observer boundary. */
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_TRY &&
            handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_MOVE &&
            handler->descriptor.raw_hook != NULL &&
            strcmp(handler->descriptor.raw_hook, "beforeMoveCallback") == 0) continue;
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_UPDATE &&
            handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
            strcmp(source_name(handler->descriptor.source_kind,
                handler->descriptor.source_id), "attract") == 0) continue;
        if (handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
            strcmp(source_name(handler->descriptor.source_kind,
                handler->descriptor.source_id), "spikes") == 0 &&
            (handler->descriptor.event == POKEMON_HANDLER_EVENT_START ||
             handler->descriptor.event == POKEMON_HANDLER_EVENT_RESTART)) continue;
        if (handler->descriptor.source_kind == POKEMON_HANDLER_SOURCE_CONDITION &&
            strcmp(source_name(handler->descriptor.source_kind,
                handler->descriptor.source_id), "nightmare") == 0 &&
            handler->descriptor.event == POKEMON_HANDLER_EVENT_START) continue;
        /* The oracle observer deliberately exposes the supported Safeguard
         * condition while keeping format rules and ability callbacks behind
         * the SetStatus boundary. Preserve that projection without changing
         * the kernel's unified handler ordering. */
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_SET_STATUS &&
            handler->owner.kind != POKEMON_OWNER_SIDE) continue;
        if (written++) putchar(',');
        printf("{\"event\":\"%s\",\"source_kind\":\"%s\"," 
            "\"source_id\":\"%s\",\"holder\":", event,
            handler->owner.kind == POKEMON_OWNER_FIELD ? "weather" :
                handler->owner.kind == POKEMON_OWNER_STATUS ? "status" :
                source_kind_name(handler->descriptor.source_kind),
            source_name(handler->descriptor.source_kind, handler->descriptor.source_id));
        if (handler->owner.kind == POKEMON_OWNER_FIELD) fputs("{\"kind\":\"field\"}", stdout);
        else if (handler->owner.kind == POKEMON_OWNER_SIDE)
            printf("{\"kind\":\"side\",\"side\":%u}", handler->holder_side);
        else printf("{\"side\":%u,\"slot\":%u}", handler->holder_side, handler->holder_slot);
        fputs(",\"order\":", stdout);
        if (handler->descriptor.order != 0) {
            printf("%d", handler->descriptor.order);
        } else {
            fputs("null", stdout);
        }
        printf(",\"priority\":%d,\"sub_order\":%d,\"effect_order\":",
            handler->descriptor.priority, handler->descriptor.sub_order);
        if (handler->descriptor.event == POKEMON_HANDLER_EVENT_START ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_RESTART ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_END) {
            /* The native kernel reserves zero as "not installed"; Showdown's
             * effectOrder counter starts at zero.  Normalize that internal
             * representation difference at the observer boundary. */
            printf("%u", handler->effect_order - 1u);
        } else if (handler->descriptor.event ==
            POKEMON_HANDLER_EVENT_SWITCH_IN &&
            (handler->owner.kind == POKEMON_OWNER_ITEM ||
             handler->owner.kind == POKEMON_OWNER_ABILITY)) {
            printf("%u", handler->effect_order - 1u);
        } else if (handler->descriptor.event ==
            POKEMON_HANDLER_EVENT_SWITCH_IN &&
            handler->owner.kind == POKEMON_OWNER_STATUS) {
            printf("%u", handler->effect_order == 0 ? 0 :
                handler->effect_order - 1u);
        } else {
            fputs("null", stdout);
        }
        fputs(",\"speed\":", stdout);
        if (handler->owner.kind == POKEMON_OWNER_FIELD ||
            handler->owner.kind == POKEMON_OWNER_SIDE ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_START ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_RESTART ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_END ||
            handler->descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPE) fputs("null}", stdout);
        else printf("%u}", handler->speed);
    }
    putchar(']');
}

static const char *burn_reason_name(PokemonBurnReason reason) {
    switch (reason) {
    case POKEMON_BURN_NOT_BURNED: return "not-burned";
    case POKEMON_BURN_ZERO_DAMAGE: return "zero-damage";
    case POKEMON_BURN_NOT_PHYSICAL: return "not-physical";
    case POKEMON_BURN_GUTS: return "guts";
    case POKEMON_BURN_APPLIED: return "applied";
    }
    abort();
}

static void write_modifiers(const PokemonBattleView *view) {
    fputs(",\"modifiers\":[", stdout);
    size_t written = 0;
    for (uint32_t sequence = 1; sequence <= view->semantic_sequence; sequence++) {
        for (size_t i = 0; i < view->modifier_count; i++) {
            const PokemonModifierInvocation *entry = &view->modifiers[i];
            if (entry->semantic_sequence != sequence) continue;
            if (!entry->invoked) continue;
            if (entry->handler.descriptor.event ==
                    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) continue;
            if (written++) putchar(',');
            const char *event = entry->handler.descriptor.event ==
                POKEMON_HANDLER_EVENT_BASE_POWER ? "base-power" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_ATK ? "modify-atk" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_DEF ? "modify-def" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPA ?
                    "modify-spa" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPD ?
                    "modify-spd" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_SPE ?
                    "modify-spe" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ?
                    "modify-accuracy" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO ?
                    "modify-crit-ratio" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE ?
                    "modify-damage" :
                entry->handler.descriptor.event == POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE ?
                    "weather-modify-damage" : NULL;
            if (event == NULL) abort();
            printf("{\"kind\":\"relay-handler\",\"event\":\"%s\"," 
                "\"source_kind\":\"%s\",\"source_id\":\"%s\",\"holder\":",
                event, entry->handler.owner.kind == POKEMON_OWNER_FIELD ? "weather" :
                    entry->handler.owner.kind == POKEMON_OWNER_STATUS ? "status" :
                    source_kind_name(entry->handler.descriptor.source_kind),
                source_name(entry->handler.descriptor.source_kind,
                    entry->handler.descriptor.source_id));
            if (entry->handler.owner.kind == POKEMON_OWNER_FIELD) fputs("{\"kind\":\"field\"}", stdout);
            else if (entry->handler.owner.kind == POKEMON_OWNER_SIDE)
                printf("{\"kind\":\"side\",\"side\":%u}", entry->handler.holder_side);
            else printf("{\"side\":%u,\"slot\":%u}", entry->handler.holder_side, entry->handler.holder_slot);
            printf(",\"relay\":%.17g,\"modifier_q12_before\":%u,\"modifier_q12_after\":%u}",
                entry->input,
                entry->modifier_before_q12, entry->modifier_after_q12);
        }
        for (size_t i = 0; i < view->relay_result_count; i++) {
            const PokemonRelayResult *entry = &view->relay_results[i];
            if (entry->semantic_sequence != sequence) continue;
            if (entry->event ==
                    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) continue;
            uint32_t previous_result_sequence = 0;
            for (size_t j = 0; j < view->relay_result_count; j++) {
                const PokemonRelayResult *previous = &view->relay_results[j];
                if (previous->event == entry->event &&
                    previous->semantic_sequence < entry->semantic_sequence &&
                    previous->semantic_sequence > previous_result_sequence) {
                    previous_result_sequence = previous->semantic_sequence;
                }
            }
            int discovered = 0;
            for (size_t j = 0; j < view->modifier_count; j++) {
                discovered |=
                    (view->modifiers[j].invoked ||
                     entry->event == POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE) &&
                    view->modifiers[j].handler.descriptor.event == entry->event &&
                    view->modifiers[j].semantic_sequence > previous_result_sequence &&
                    view->modifiers[j].semantic_sequence < entry->semantic_sequence;
            }
            if (!discovered) continue;
            if (written++) putchar(',');
            const char *event = entry->event == POKEMON_HANDLER_EVENT_BASE_POWER ?
                "base-power" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_ATK ?
                "modify-atk" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_DEF ?
                "modify-def" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_SPA ?
                "modify-spa" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_SPD ?
                "modify-spd" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_SPE ?
                "modify-spe" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_ACCURACY ?
                    "modify-accuracy" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_CRIT_RATIO ?
                    "modify-crit-ratio" : entry->event == POKEMON_HANDLER_EVENT_MODIFY_DAMAGE ?
                    "modify-damage" : entry->event == POKEMON_HANDLER_EVENT_WEATHER_MODIFY_DAMAGE ?
                    "weather-modify-damage" : NULL;
            if (event == NULL) abort();
            printf("{\"kind\":\"relay-result\",\"event\":\"%s\"," 
                "\"relay\":%.17g,\"modifier_q12\":%u,\"result\":%.17g}",
                event, entry->input, entry->modifier_q12, entry->output);
        }
        for (size_t i = 0; i < view->damage_stage_count; i++) {
            const PokemonDamageStageTrace *stage = &view->damage_stages[i];
            if (stage->semantic_sequence != sequence ||
                stage->kind != POKEMON_DAMAGE_STAGE_BURN ||
                stage->reason == POKEMON_BURN_NOT_BURNED) continue;
            if (written++) putchar(',');
            printf("{\"kind\":\"damage-stage\",\"stage\":\"burn\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},\"move\":\"%s\","
                "\"before\":%u,\"after\":%u,\"multiplier_q12\":%u,"
                "\"applied\":%s,\"reason\":\"%s\"}",
                stage->source_side, view->sides[stage->source_side].active,
                stage->target_side, view->sides[stage->target_side].active,
                move_name(stage->move_id), stage->input, stage->output,
                stage->modifier_q12, stage->applied ? "true" : "false",
                burn_reason_name(stage->reason));
        }
    }
    putchar(']');
}

static const char *condition_scope_name(PokemonConditionScope scope) {
    switch (scope) {
    case POKEMON_CONDITION_SCOPE_STATUS: return "status";
    case POKEMON_CONDITION_SCOPE_VOLATILE: return "volatile";
    case POKEMON_CONDITION_SCOPE_SIDE: return "side";
    case POKEMON_CONDITION_SCOPE_FIELD: return "weather";
    case POKEMON_CONDITION_SCOPE_SLOT: return "slot";
    }
    abort();
}

static const char *condition_id_name(PokemonConditionScope scope, uint16_t id) {
    PokemonConditionDomain domain;
    switch (scope) {
    case POKEMON_CONDITION_SCOPE_STATUS: domain = POKEMON_CONDITION_DOMAIN_STATUS; break;
    case POKEMON_CONDITION_SCOPE_VOLATILE: domain = POKEMON_CONDITION_DOMAIN_VOLATILE; break;
    case POKEMON_CONDITION_SCOPE_SIDE: domain = POKEMON_CONDITION_DOMAIN_SIDE; break;
    case POKEMON_CONDITION_SCOPE_FIELD: domain = POKEMON_CONDITION_DOMAIN_WEATHER; break;
    case POKEMON_CONDITION_SCOPE_SLOT: domain = POKEMON_CONDITION_DOMAIN_SLOT; break;
    default: abort();
    }
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.condition_catalog_count; i++) {
        const PokemonConditionIdentity *identity =
            &POKEMON_GEN3_SLICE_DATA.condition_catalog[i];
        if (identity->domain == domain && identity->semantic_kind == id) {
            return identity->id;
        }
    }
    abort();
}

static const char *resolved_condition_name(
    PokemonConditionScope scope, uint16_t semantic_kind, uint16_t descriptor_id
) {
    if (descriptor_id != 0) {
        const PokemonConditionIdentity *identity = pokemon_condition_identity(
            &POKEMON_GEN3_SLICE_DATA, descriptor_id);
        if (identity == NULL) abort();
        return identity->id;
    }
    return condition_id_name(scope, semantic_kind);
}

static uint8_t side_condition_residual_order(uint16_t semantic_kind) {
    uint16_t descriptor = POKEMON_GEN3_RULES.condition_descriptor(
        POKEMON_OWNER_SIDE, semantic_kind);
    for (size_t i = 0; i < POKEMON_GEN3_RULES.condition_rule_count; i++) {
        const PokemonConditionRule *rule = &POKEMON_GEN3_RULES.condition_rules[i];
        if (rule->descriptor_id == descriptor) return rule->residual_order;
    }
    abort();
}

static const PokemonSlotConditionPolicy *slot_condition_policy_by_descriptor(
    uint16_t descriptor_id
) {
    for (size_t i = 0;
         i < POKEMON_GEN3_SLICE_DATA.slot_condition_policy_count; i++) {
        const PokemonSlotConditionPolicy *policy =
            &POKEMON_GEN3_SLICE_DATA.slot_condition_policies[i];
        if (policy->descriptor_id == descriptor_id) return policy;
    }
    abort();
}

static const PokemonConditionRule *volatile_condition_rule(
    uint16_t semantic_kind
) {
    uint16_t descriptor = POKEMON_GEN3_RULES.condition_descriptor(
        POKEMON_OWNER_VOLATILE, semantic_kind);
    for (size_t i = 0; i < POKEMON_GEN3_RULES.condition_rule_count; i++) {
        const PokemonConditionRule *rule = &POKEMON_GEN3_RULES.condition_rules[i];
        if (rule->descriptor_id == descriptor) return rule;
    }
    abort();
}

static const PokemonConditionRule *condition_rule_by_descriptor(
    uint16_t descriptor_id
) {
    for (size_t i = 0; i < POKEMON_GEN3_RULES.condition_rule_count; i++) {
        const PokemonConditionRule *rule = &POKEMON_GEN3_RULES.condition_rules[i];
        if (rule->descriptor_id == descriptor_id) return rule;
    }
    return NULL;
}

static int locked_ramp_descriptor(uint16_t descriptor_id) {
	for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.locked_ramp_policy_count; i++) {
		if (POKEMON_GEN3_SLICE_DATA.locked_ramp_policies[i].condition_descriptor_id ==
				descriptor_id) return 1;
	}
	return 0;
}

static void write_condition_holder(
    PokemonConditionScope scope, uint8_t side, uint8_t slot
) {
    if (scope == POKEMON_CONDITION_SCOPE_FIELD) fputs("{\"kind\":\"field\"}", stdout);
    else if (scope == POKEMON_CONDITION_SCOPE_SIDE) {
        printf("{\"kind\":\"side\",\"side\":%u}", side);
    } else if (scope == POKEMON_CONDITION_SCOPE_SLOT) {
        printf("{\"kind\":\"slot\",\"side\":%u,\"position\":%u}",
            side, slot);
    } else {
        printf("{\"kind\":\"pokemon\",\"side\":%u,\"slot\":%u}", side, slot);
    }
}

static void write_trace_values(const PokemonConditionTrace *trace) {
    fputs(",\"duration_before\":", stdout);
    if (trace->has_duration_before) printf("%u", trace->duration_before); else fputs("null", stdout);
    fputs(",\"duration_after\":", stdout);
    if (trace->has_duration_after) printf("%u", trace->duration_after); else fputs("null", stdout);
    fputs(",\"counter_before\":", stdout);
    if (trace->has_counter_before) printf("%u", trace->counter_before); else fputs("null", stdout);
    fputs(",\"counter_after\":", stdout);
    if (trace->has_counter_after) printf("%u", trace->counter_after); else fputs("null", stdout);
    fputs(",\"stage_before\":", stdout);
    if (trace->has_stage_before) printf("%u", trace->stage_before); else fputs("null", stdout);
    fputs(",\"stage_after\":", stdout);
    if (trace->has_stage_after) printf("%u", trace->stage_after); else fputs("null", stdout);
}

static void write_lifecycle_trace(
    const PokemonConditionTrace *trace, size_t *written
) {
    if ((*written)++) putchar(',');
    const char *phase = trace->operation == POKEMON_CONDITION_ADD ? "add" :
        trace->operation == POKEMON_CONDITION_RESTART ? "restart" :
        trace->operation == POKEMON_CONDITION_REMOVE ? "remove" :
        trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
        trace->condition_id == POKEMON_VOLATILE_STALL &&
        trace->reason == POKEMON_CONDITION_REASON_MOVE ? "restart" : "update";
    printf("{\"kind\":\"lifecycle\",\"phase\":\"%s\","
        "\"scope\":\"%s\",\"id\":\"%s\",\"holder\":",
        phase, condition_scope_name(trace->scope),
        resolved_condition_name(
            trace->scope, trace->condition_id, trace->descriptor_id));
    write_condition_holder(trace->scope, trace->side, trace->slot);
    write_trace_values(trace);
    putchar('}');
}

static int residual_work_is_projected(const PokemonResidualWork *work) {
    if (work->kind == POKEMON_RESIDUAL_OWNER_EVENT) return 0;
    return work->kind != POKEMON_RESIDUAL_VOLATILE ||
        (work->condition_id != POKEMON_VOLATILE_TWO_TURN_MARKER &&
         work->condition_id != POKEMON_VOLATILE_NIGHTMARE &&
         work->condition_id != POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT);
}

static void write_residual_discovery(
    const PokemonResidualWork *work, size_t *written
) {
    PokemonConditionScope scope = work->kind == POKEMON_RESIDUAL_WEATHER ?
        POKEMON_CONDITION_SCOPE_FIELD :
        work->kind == POKEMON_RESIDUAL_STATUS ? POKEMON_CONDITION_SCOPE_STATUS :
        work->kind == POKEMON_RESIDUAL_VOLATILE ? POKEMON_CONDITION_SCOPE_VOLATILE :
        work->kind == POKEMON_RESIDUAL_SLOT_CONDITION ? POKEMON_CONDITION_SCOPE_SLOT :
        POKEMON_CONDITION_SCOPE_SIDE;
    const PokemonConditionRule *persistent_rule =
        scope == POKEMON_CONDITION_SCOPE_VOLATILE && work->duration_before == 0 ?
        condition_rule_by_descriptor(work->descriptor_id) : NULL;
    int stateless_persistent_residual = persistent_rule != NULL &&
        persistent_rule->has_residual;
    if ((*written)++) putchar(',');
    printf("{\"kind\":\"residual\",\"phase\":\"discover\","
        "\"scope\":\"%s\",\"id\":\"%s\",\"holder\":",
        condition_scope_name(scope), resolved_condition_name(
            scope, work->condition_id, work->descriptor_id));
    write_condition_holder(scope, work->side, work->slot);
    fputs(",\"duration_before\":", stdout);
    if (!stateless_persistent_residual &&
        (scope == POKEMON_CONDITION_SCOPE_FIELD ||
         scope == POKEMON_CONDITION_SCOPE_VOLATILE ||
         scope == POKEMON_CONDITION_SCOPE_SIDE ||
         scope == POKEMON_CONDITION_SCOPE_SLOT)) printf("%u", work->duration_before);
    else fputs("null", stdout);
    fputs(",\"duration_after\":", stdout);
    if (!stateless_persistent_residual &&
        (scope == POKEMON_CONDITION_SCOPE_FIELD ||
         scope == POKEMON_CONDITION_SCOPE_VOLATILE ||
         scope == POKEMON_CONDITION_SCOPE_SIDE ||
         scope == POKEMON_CONDITION_SCOPE_SLOT)) printf("%u", work->duration_before);
    else fputs("null", stdout);
    fputs(",\"counter_before\":", stdout);
	if (scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
		(work->counter_before != 0 || locked_ramp_descriptor(work->descriptor_id)))
        printf("%u", work->counter_before);
    else fputs("null", stdout);
    fputs(",\"counter_after\":", stdout);
	if (scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
		(work->counter_before != 0 || locked_ramp_descriptor(work->descriptor_id)))
        printf("%u", work->counter_before);
    else fputs("null", stdout);
    fputs(",\"stage_before\":", stdout);
    if (scope == POKEMON_CONDITION_SCOPE_STATUS &&
        work->condition_id == POKEMON_STATUS_TOXIC) printf("%u", work->counter_before);
    else fputs("null", stdout);
    fputs(",\"stage_after\":", stdout);
    if (scope == POKEMON_CONDITION_SCOPE_STATUS &&
        work->condition_id == POKEMON_STATUS_TOXIC) printf("%u", work->counter_before);
    else fputs("null", stdout);
    if (work->has_order) printf(",\"order\":%u", work->order);
    else fputs(",\"order\":null", stdout);
    printf(",\"priority\":0,\"sub_order\":%u}", work->sub_order);
}

static void write_conditions(const PokemonBattleView *view) {
    fputs(",\"conditions\":[", stdout);
    size_t written = 0;
    int wrote_residual_prefix = 0;
    int wrote_stall_prng = 0;
    int wrote_protect_handler = 0;
    for (uint32_t sequence = 1; sequence <= view->semantic_sequence; sequence++) {
        for (size_t draw = 0; draw < view->draw_count; draw++) {
            if (view->draws[draw].semantic_sequence != sequence) continue;
            if (written++) putchar(',');
            if (view->draws[draw].label == POKEMON_DRAW_STALL_SUCCESS) {
                printf("{\"kind\":\"prng\",\"label\":\"stall.success\","
                    "\"from\":%u,\"to\":null,\"result\":%u}",
                    view->draws[draw].upper_bound,
                    view->draws[draw].result);
                wrote_stall_prng = 1;
            } else if (view->draws[draw].label ==
                    POKEMON_DRAW_SET_STATUS_HANDLER_ORDER_OFFSET_ONE) {
                printf("{\"kind\":\"prng\",\"label\":"
                    "\"event.setstatus.handler_order\",\"from\":1,"
                    "\"to\":3,\"result\":%u}", view->draws[draw].result + 1u);
            } else if (view->draws[draw].label ==
                    POKEMON_DRAW_EVENT_HANDLER_ORDER &&
                    view->draws[draw].context_event_id ==
                        POKEMON_HANDLER_EVENT_SET_STATUS) {
                printf("{\"kind\":\"prng\",\"label\":"
                    "\"event.setstatus.handler_order\",\"from\":%u,"
                    "\"to\":%u,\"result\":%u}",
                    view->draws[draw].lower_bound,
                    view->draws[draw].lower_bound +
                        view->draws[draw].upper_bound,
                    view->draws[draw].lower_bound +
                        view->draws[draw].result);
            } else {
                printf("{\"kind\":\"prng\",\"label\":"
                    "\"event.setstatus.handler_order\",\"from\":0,"
                    "\"to\":2,\"result\":%u}", view->draws[draw].result);
            }
        }
        /* TryHit handlers execute inside the target-admission operation.  In
         * particular, field-target moves can interleave a handler for one
         * active with lifecycle mutation for the next active, so preserve the
         * kernel's semantic sequence instead of appending Protect afterward. */
        for (size_t handler = 0; handler < view->handler_count; handler++) {
            const PokemonHandlerInvocation *invocation =
                &view->handlers[handler];
            if (invocation->semantic_sequence != sequence ||
                invocation->handler.descriptor.id !=
                    POKEMON_GEN3_HANDLER_PROTECT) continue;
            if (written++) putchar(',');
            uint8_t side = invocation->handler.holder_side;
            printf("{\"kind\":\"handler\",\"event\":\"try-hit\","
                "\"id\":\"protect\",\"holder\":{\"kind\":\"pokemon\","
                "\"side\":%u,\"slot\":%u},\"order\":null,"
                "\"priority\":3,\"sub_order\":2}", side,
                invocation->handler.holder_slot);
            wrote_protect_handler = 1;
        }
        for (size_t i = 0; i < view->modifier_count; i++) {
            const PokemonModifierInvocation *entry = &view->modifiers[i];
            if (entry->semantic_sequence != sequence ||
                entry->handler.descriptor.event !=
                    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) continue;
            uint32_t previous_result_sequence = 0;
            uint32_t next_result_sequence = UINT32_MAX;
            for (size_t result = 0; result < view->relay_result_count; result++) {
                const PokemonRelayResult *relay = &view->relay_results[result];
                if (relay->event !=
                        POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) continue;
                if (relay->semantic_sequence < sequence &&
                    relay->semantic_sequence > previous_result_sequence) {
                    previous_result_sequence = relay->semantic_sequence;
                }
                if (relay->semantic_sequence > sequence &&
                    relay->semantic_sequence < next_result_sequence) {
                    next_result_sequence = relay->semantic_sequence;
                }
            }
            uint8_t first_handler = 1;
            for (size_t prior = 0; prior < view->modifier_count; prior++) {
                const PokemonModifierInvocation *candidate =
                    &view->modifiers[prior];
                if (candidate->handler.descriptor.event ==
                        POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1 &&
                    candidate->semantic_sequence > previous_result_sequence &&
                    candidate->semantic_sequence < sequence) first_handler = 0;
            }
            if (first_handler) {
                for (uint32_t handler_sequence = sequence;
                     handler_sequence < next_result_sequence;
                     handler_sequence++) {
                    for (size_t handler = 0;
                         handler < view->modifier_count; handler++) {
                        const PokemonModifierInvocation *candidate =
                            &view->modifiers[handler];
                        if (candidate->semantic_sequence != handler_sequence ||
                            candidate->handler.descriptor.event !=
                                POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) {
                            continue;
                        }
                        if (written++) putchar(',');
                        printf("{\"kind\":\"handler\",\"event\":\"modify-damage-phase1\"," 
                            "\"id\":\"%s\",\"holder\":",
                            source_name(candidate->handler.descriptor.source_kind,
                                candidate->handler.descriptor.source_id));
                        if (candidate->handler.owner.kind == POKEMON_OWNER_SIDE) {
                            printf("{\"kind\":\"side\",\"side\":%u}",
                                candidate->handler.holder_side);
                        } else {
                            printf("{\"kind\":\"pokemon\",\"side\":%u,\"slot\":%u}",
                                candidate->handler.holder_side,
                                candidate->handler.holder_slot);
                        }
                        printf(",\"order\":null,\"priority\":%d,\"sub_order\":%d}",
                            candidate->handler.descriptor.priority,
                            candidate->handler.descriptor.sub_order);
                    }
                }
            }
            if (written++) putchar(',');
            printf("{\"kind\":\"relay-handler\",\"event\":"
                "\"modify-damage-phase1\",\"id\":\"%s\",\"holder\":",
                source_name(entry->handler.descriptor.source_kind,
                    entry->handler.descriptor.source_id));
            if (entry->handler.owner.kind == POKEMON_OWNER_SIDE) {
                printf("{\"kind\":\"side\",\"side\":%u}",
                    entry->handler.holder_side);
            } else {
                printf("{\"kind\":\"pokemon\",\"side\":%u,\"slot\":%u}",
                    entry->handler.holder_side, entry->handler.holder_slot);
            }
            printf(",\"relay\":%u,\"modifier_q12_before\":%u,"
                "\"modifier_q12_after\":%u}", (uint32_t)entry->input,
                entry->modifier_before_q12, entry->modifier_after_q12);
        }
        for (size_t i = 0; i < view->relay_result_count; i++) {
            const PokemonRelayResult *entry = &view->relay_results[i];
            if (entry->semantic_sequence != sequence ||
                entry->event != POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) {
                continue;
            }
            if (written++) putchar(',');
            printf("{\"kind\":\"relay-result\",\"event\":"
                "\"modify-damage-phase1\",\"relay\":%u,\"modifier_q12\":%u,"
                "\"result\":%u}", (uint32_t)entry->input,
                entry->modifier_q12, (uint32_t)entry->output);
        }
        for (size_t i = 0; i < view->residual_count; i++) {
            const PokemonResidualWork *work = &view->residuals[i];
            if (work->semantic_sequence != sequence) continue;
            if (!wrote_residual_prefix) {
                if (!wrote_stall_prng) {
                    for (size_t draw = 0; draw < view->draw_count; draw++) {
                        if (view->draws[draw].label != POKEMON_DRAW_STALL_SUCCESS) continue;
                        if (written++) putchar(',');
                        printf("{\"kind\":\"prng\",\"label\":\"stall.success\","
                            "\"from\":%u,\"to\":null,\"result\":%u}",
                            view->draws[draw].upper_bound, view->draws[draw].result);
                    }
                    wrote_stall_prng = 1;
                }
                for (size_t draw = 0; draw < view->draw_count; draw++) {
                    if (view->draws[draw].label !=
                        POKEMON_DRAW_RESIDUAL_HANDLER_ORDER) continue;
                    if (written++) putchar(',');
                    printf("{\"kind\":\"prng\",\"label\":"
                        "\"field_event.residual.handler_order\",\"from\":%u,"
                        "\"to\":%u,\"result\":%u}",
                        view->draws[draw].lower_bound,
                        view->draws[draw].upper_bound, view->draws[draw].result);
                }
                /* Showdown discovers and orders the complete handler list
                 * before it executes the first residual handler. */
                for (size_t pending = 0; pending < view->residual_count; pending++) {
                    if (residual_work_is_projected(&view->residuals[pending])) {
                        write_residual_discovery(&view->residuals[pending], &written);
                    }
                }
                wrote_residual_prefix = 1;
            }
            if (!residual_work_is_projected(work)) continue;
        }
        /* Showdown discovers and orders the complete Residual handler list
         * before executing its first handler. Stateless persistent handlers
         * have no mutation trace of their own, so project their execution in
         * a second pass rather than interleaving it with discovery. */
        for (size_t i = 0; i < view->residual_count; i++) {
            const PokemonResidualWork *work = &view->residuals[i];
            if (work->semantic_sequence != sequence ||
                !residual_work_is_projected(work) ||
                work->kind != POKEMON_RESIDUAL_VOLATILE ||
                work->duration_before != 0) continue;
            const PokemonConditionRule *persistent_rule =
                condition_rule_by_descriptor(work->descriptor_id);
            if (persistent_rule != NULL && persistent_rule->has_residual) {
                const PokemonConditionScope scope =
                    POKEMON_CONDITION_SCOPE_VOLATILE;
                for (size_t event = 0; event < view->event_count; event++) {
                    const PokemonEvent *damage = &view->events[event];
                    if (damage->kind != POKEMON_EVENT_DAMAGE ||
                        damage->condition_scope != scope ||
                        damage->condition_id != work->condition_id ||
                        damage->side != work->side ||
                        damage->slot != work->slot) continue;
                    putchar(',');
                    printf("{\"kind\":\"damage\",\"scope\":\"volatile\","
                        "\"id\":\"%s\",\"holder\":",
                        resolved_condition_name(scope, work->condition_id,
                            work->descriptor_id));
                    write_condition_holder(scope, work->side, work->slot);
                    printf(",\"amount\":%u}", damage->amount);
                }
                putchar(',');
                printf("{\"kind\":\"residual\",\"phase\":\"execute\"," 
                    "\"scope\":\"volatile\",\"id\":\"%s\",\"holder\":",
                    resolved_condition_name(scope, work->condition_id,
                        work->descriptor_id));
                write_condition_holder(scope, work->side, work->slot);
                printf(",\"duration_before\":null,\"duration_after\":null,"
                    "\"counter_before\":null,\"counter_after\":null,"
                    "\"stage_before\":null,\"stage_after\":null,"
                    "\"order\":%u,\"priority\":0,\"sub_order\":%u}",
                    work->order, work->sub_order);
            }
        }
        for (size_t i = 0; i < view->condition_trace_count; i++) {
            const PokemonConditionTrace *trace = &view->condition_traces[i];
            if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                trace->condition_id ==
                    POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT) continue;
            if (trace->semantic_sequence != sequence) continue;
            /* The pinned observer exposes these payload volatiles in canonical
             * state but does not yet emit generic addVolatile lifecycle rows. */
            if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                (trace->condition_id == POKEMON_VOLATILE_SUBSTITUTE ||
                 trace->condition_id == POKEMON_VOLATILE_SUBSTITUTE_BROKEN ||
                 trace->condition_id == POKEMON_VOLATILE_TWO_TURN_MARKER ||
                 trace->condition_id == POKEMON_VOLATILE_NIGHTMARE ||
                 trace->condition_id == POKEMON_VOLATILE_CHOICE_LOCK)) continue;
            if (!wrote_stall_prng && trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                (trace->reason == POKEMON_CONDITION_REASON_MOVE ||
                 trace->condition_id == POKEMON_VOLATILE_STALL)) {
                for (size_t draw = 0; draw < view->draw_count; draw++) {
                    if (view->draws[draw].label != POKEMON_DRAW_STALL_SUCCESS) continue;
                    if (written++) putchar(',');
                    printf("{\"kind\":\"prng\",\"label\":\"stall.success\","
                        "\"from\":%u,\"to\":null,\"result\":%u}",
                        view->draws[draw].upper_bound, view->draws[draw].result);
                }
                wrote_stall_prng = 1;
            }
            const PokemonResidualWork *matching_residual = NULL;
            for (size_t work_index = 0; work_index < view->residual_count;
                 work_index++) {
                const PokemonResidualWork *work = &view->residuals[work_index];
                if (work->kind == POKEMON_RESIDUAL_VOLATILE &&
                    trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                    work->condition_id == trace->condition_id &&
                    (trace->descriptor_id == 0 ||
                     work->descriptor_id == trace->descriptor_id) &&
                    work->side == trace->side && work->slot == trace->slot) {
                    matching_residual = work;
                    break;
                }
            }
            int handler_removed_during_residual =
                trace->reason == POKEMON_CONDITION_REASON_HANDLER &&
                trace->operation == POKEMON_CONDITION_REMOVE &&
                matching_residual != NULL &&
                (trace->condition_id == POKEMON_VOLATILE_PARTIALLY_TRAPPED ||
                 trace->condition_id == POKEMON_VOLATILE_ENCORE);
            int residual = trace->reason == POKEMON_CONDITION_REASON_RESIDUAL ||
                trace->reason == POKEMON_CONDITION_REASON_EXPIRY ||
                handler_removed_during_residual;
            if (residual) {
                if (handler_removed_during_residual &&
                    trace->condition_id == POKEMON_VOLATILE_ENCORE) {
                    write_lifecycle_trace(trace, &written);
                }
                if (trace->scope == POKEMON_CONDITION_SCOPE_STATUS) {
                    for (size_t event = 0; event < view->event_count; event++) {
                        const PokemonEvent *damage = &view->events[event];
                        if (damage->kind != POKEMON_EVENT_DAMAGE ||
                            damage->condition_scope != POKEMON_CONDITION_SCOPE_STATUS ||
                            damage->condition_id != trace->condition_id ||
                            damage->side != trace->side) continue;
                        putchar(',');
                        printf("{\"kind\":\"damage\",\"scope\":\"status\"," 
                            "\"id\":\"%s\",\"holder\":",
                            condition_id_name(trace->scope, trace->condition_id));
                        write_condition_holder(trace->scope, trace->side, trace->slot);
                        printf(",\"amount\":%u}", damage->amount);
                    }
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_FIELD &&
                    (trace->before_value == 0 || trace->before_value > 1) &&
                    (trace->condition_id == POKEMON_WEATHER_SANDSTORM ||
                     trace->condition_id == POKEMON_WEATHER_HAIL) &&
                    matching_residual == NULL) {
                    const PokemonResidualWork *weather_residual = NULL;
                    for (size_t work_index = 0;
                         work_index < view->residual_count; work_index++) {
                        const PokemonResidualWork *candidate =
                            &view->residuals[work_index];
                        if (candidate->kind == POKEMON_RESIDUAL_WEATHER &&
                            candidate->condition_id == trace->condition_id) {
                            weather_residual = candidate;
                            break;
                        }
                    }
                    if (weather_residual == NULL ||
                        !weather_residual->weather_event_dispatched) goto weather_done;
                    for (size_t offset = 0; offset < POKEMON_SIDES; offset++) {
                        size_t side = weather_residual->weather_order[offset];
                        uint16_t amount = 0;
                        uint8_t slot = (uint8_t)view->sides[side].active;
                        for (size_t event = 0; event < view->event_count; event++) {
                            const PokemonEvent *damage = &view->events[event];
                            if (damage->kind == POKEMON_EVENT_DAMAGE &&
                                damage->condition_scope == POKEMON_CONDITION_SCOPE_FIELD &&
                                damage->condition_id == trace->condition_id &&
                                damage->side == side) {
                                slot = damage->slot;
                                amount = damage->amount;
                                break;
                            }
                        }
                        putchar(',');
                        printf("{\"kind\":\"damage\",\"scope\":\"weather\"," 
                            "\"id\":\"%s\",\"holder\":"
                            "{\"kind\":\"pokemon\",\"side\":%zu,\"slot\":%u},"
                            "\"amount\":%u}",
                            condition_id_name(trace->scope, trace->condition_id),
                            side, slot, amount);
                    }
weather_done:;
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE) {
                    for (size_t event = 0; event < view->event_count; event++) {
                        const PokemonEvent *damage = &view->events[event];
                        if (damage->kind != POKEMON_EVENT_DAMAGE ||
                            damage->condition_scope !=
                                POKEMON_CONDITION_SCOPE_VOLATILE ||
                            damage->condition_id != trace->condition_id ||
                            damage->side != trace->side) continue;
                        putchar(',');
                        printf("{\"kind\":\"damage\",\"scope\":\"volatile\"," 
                            "\"id\":\"%s\",\"holder\":",
                            condition_id_name(trace->scope,
                                trace->condition_id));
                        write_condition_holder(
                            trace->scope, trace->side, trace->slot);
                        printf(",\"amount\":%u}", damage->amount);
                    }
                }
                putchar(',');
                printf("{\"kind\":\"residual\",\"phase\":\"execute\","
                    "\"scope\":\"%s\",\"id\":\"%s\",\"holder\":",
                    condition_scope_name(trace->scope),
                    resolved_condition_name(trace->scope, trace->condition_id,
                        trace->descriptor_id));
                write_condition_holder(trace->scope, trace->side, trace->slot);
                if (trace->operation == POKEMON_CONDITION_REMOVE) {
                    fputs(",\"duration_before\":", stdout);
                    if (handler_removed_during_residual) {
                        printf("%u", matching_residual->duration_before);
                    } else if (trace->value_kind == POKEMON_CONDITION_VALUE_DURATION) printf("%u", trace->before_value);
                    else if (trace->has_duration_before) printf("%u", trace->duration_before);
                    else fputs("null", stdout);
                    fputs(",\"duration_after\":", stdout);
                    if (handler_removed_during_residual) {
                        printf("%u", trace->before_value);
                    } else if (trace->value_kind == POKEMON_CONDITION_VALUE_DURATION) printf("%u", trace->after_value); else fputs("null", stdout);
                    fputs(",\"counter_before\":", stdout);
                    if (trace->has_counter_before) printf("%u", trace->counter_before);
                    else if (matching_residual != NULL &&
                        matching_residual->counter_before != 0)
                        printf("%u", matching_residual->counter_before);
                    else fputs("null", stdout);
                    fputs(",\"counter_after\":", stdout);
                    if (trace->has_counter_before) printf("%u", trace->counter_before);
                    else if (matching_residual != NULL &&
                        matching_residual->counter_before != 0)
                        printf("%u", matching_residual->counter_before);
                    else fputs("null", stdout);
                    fputs(",\"stage_before\":", stdout);
                    if (trace->has_stage_before) printf("%u", trace->stage_before); else fputs("null", stdout);
                    fputs(",\"stage_after\":", stdout);
                    if (trace->has_stage_before) printf("%u", trace->stage_before); else fputs("null", stdout);
                } else {
                    if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE &&
                        matching_residual != NULL &&
                        matching_residual->counter_before != 0) {
                        fputs(",\"duration_before\":", stdout);
                        if (trace->has_duration_before)
                            printf("%u", trace->duration_before);
                        else if (trace->value_kind ==
                            POKEMON_CONDITION_VALUE_DURATION)
                            printf("%u", trace->before_value);
                        else fputs("null", stdout);
                        fputs(",\"duration_after\":", stdout);
                        if (trace->has_duration_after)
                            printf("%u", trace->duration_after);
                        else if (trace->value_kind ==
                            POKEMON_CONDITION_VALUE_DURATION)
                            printf("%u", trace->after_value);
                        else fputs("null", stdout);
                        printf(",\"counter_before\":%u,\"counter_after\":%u,"
                            "\"stage_before\":null,\"stage_after\":null",
                            matching_residual->counter_before,
                            matching_residual->counter_before);
                    } else {
                        write_trace_values(trace);
                    }
                }
                if (trace->scope == POKEMON_CONDITION_SCOPE_FIELD) {
                    fputs(",\"order\":8,\"priority\":0,\"sub_order\":5}", stdout);
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_STATUS) {
                    fputs(",\"order\":10,\"priority\":0,\"sub_order\":6}", stdout);
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_SIDE) {
                    printf(",\"order\":%u,\"priority\":0,\"sub_order\":4}",
                        side_condition_residual_order(trace->condition_id));
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_VOLATILE) {
                    const PokemonConditionRule *rule = trace->descriptor_id != 0 ?
                        condition_rule_by_descriptor(trace->descriptor_id) :
                        volatile_condition_rule(trace->condition_id);
                    if (rule == NULL) abort();
                    if (rule->has_order) printf(",\"order\":%u", rule->residual_order);
                    else fputs(",\"order\":null", stdout);
                    printf(",\"priority\":0,\"sub_order\":%u}",
                        rule->residual_sub_order);
                } else if (trace->scope == POKEMON_CONDITION_SCOPE_SLOT) {
                    const PokemonSlotConditionPolicy *policy =
                        slot_condition_policy_by_descriptor(trace->descriptor_id);
                    printf(",\"order\":%u,\"priority\":0,\"sub_order\":%u}",
                        policy->residual_order, policy->residual_sub_order);
                } else {
                    fputs(",\"order\":null,\"priority\":0,\"sub_order\":2}", stdout);
                }
                if (trace->operation != POKEMON_CONDITION_REMOVE ||
                    handler_removed_during_residual) continue;
            }
            write_lifecycle_trace(trace, &written);
        }
    }
    if (!wrote_protect_handler) {
        for (size_t handler = 0; handler < view->handler_count; handler++) {
            if (view->handlers[handler].handler.descriptor.id !=
                POKEMON_GEN3_HANDLER_PROTECT) continue;
            if (written++) putchar(',');
            uint8_t side = view->handlers[handler].handler.holder_side;
            printf("{\"kind\":\"handler\",\"event\":\"try-hit\","
                "\"id\":\"protect\",\"holder\":{\"kind\":\"pokemon\","
                "\"side\":%u,\"slot\":%u},\"order\":null,"
                "\"priority\":3,\"sub_order\":2}", side,
                view->sides[side].active);
            break;
        }
    }
    putchar(']');
}

static void write_immunities(const PokemonBattleView *view) {
    fputs(",\"immunity\":[", stdout);
    size_t written = 0;
    for (size_t i = 0; i < view->immunity_count; i++) {
        const PokemonImmunityDecision *decision = &view->immunities[i];
        int superseded_by_ohko_rule = 0;
        for (size_t event_index = 0; event_index < view->event_count;
             event_index++) {
            const PokemonEvent *event = &view->events[event_index];
            if (event->kind == POKEMON_EVENT_IMMUNE &&
                event->immunity_cause == POKEMON_IMMUNITY_OHKO_RULE &&
                event->side == decision->target_side) {
                superseded_by_ohko_rule = 1;
                break;
            }
        }
        /* runImmunity precedes Showdown's Gen 3 OHKO level/type gate.  The
         * observer exposes the gate through the immune event, not the earlier
         * successful natural-immunity probe. */
        if (decision->cause == POKEMON_IMMUNITY_NONE &&
            superseded_by_ohko_rule) continue;
        const char *result = NULL;
        const char *effect = NULL;
        switch (decision->cause) {
        case POKEMON_IMMUNITY_NONE: result = "none"; break;
        case POKEMON_IMMUNITY_NATURAL_TYPE: result = "type"; break;
        case POKEMON_IMMUNITY_LEVITATE:
            result = "ability";
            effect = ability_name(decision->effect_id);
            break;
        case POKEMON_IMMUNITY_HANDLER:
            /* TryHit cancellation is represented by the handler trace. */
            abort();
        case POKEMON_IMMUNITY_OHKO_RULE:
            /* Showdown reports the OHKO level gate only through battle log state. */
            continue;
        }
        if (written++) putchar(',');
        printf("{\"attack_type\":\"%s\",\"target\":{\"side\":%u,\"slot\":%u},"
            "\"result\":\"%s\",\"effect\":",
            type_name(decision->move_type), decision->target_side,
            decision->target_slot, result);
        if (effect == NULL) fputs("null", stdout);
        else printf("\"%s\"", effect);
        putchar('}');
    }
    putchar(']');
}

static uint16_t effect_move_id(
    const PokemonBattleView *view, const PokemonEffectTrace *trace
) {
    (void)view;
    return trace->move_id;
}

static int status_effect_kind(PokemonEffectKind kind) {
    return kind == POKEMON_EFFECT_SET_STATUS ||
        kind == POKEMON_EFFECT_SET_STATUS_FROM_DISTRIBUTION;
}

static int supported_effect_move(uint16_t move_id) {
    for (size_t i = 0; i < POKEMON_GEN3_SLICE_DATA.move_count; i++) {
        const PokemonMoveData *move = &POKEMON_GEN3_SLICE_DATA.moves[i];
        if (move->id != move_id) continue;
        if (move->failure_policy.kind != POKEMON_MOVE_FAILURE_NONE) return 1;
        for (size_t op_index = 0; op_index < move->effect_count; op_index++) {
            const PokemonEffectOp *op =
                &POKEMON_GEN3_SLICE_DATA.effects[move->effect_offset + op_index];
            if (op->kind == POKEMON_EFFECT_BOOST ||
                (status_effect_kind(op->kind) &&
                 op->phase == POKEMON_EFFECT_PHASE_AFTER_HIT) ||
                op->kind == POKEMON_EFFECT_DAMAGE_RELATIVE ||
                op->kind == POKEMON_EFFECT_HEAL_FRACTION ||
                op->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION) return 1;
        }
        for (size_t handler_index = 0;
             handler_index < POKEMON_GEN3_SLICE_DATA.handler_count;
             handler_index++) {
            const PokemonHandlerDescriptor *handler =
                &POKEMON_GEN3_SLICE_DATA.handlers[handler_index];
            if (handler->source_kind != POKEMON_HANDLER_SOURCE_MOVE ||
                handler->source_id != move_id) continue;
            for (size_t program = 0; program < handler->program_count;
                 program++) {
                const PokemonHandlerOp *op =
                    &POKEMON_GEN3_SLICE_DATA.handler_programs[
                        handler->program_offset + program];
                if (op->opcode ==
                    POKEMON_HANDLER_OP_CLEAR_USER_TEAM_MAJOR_STATUS) return 1;
            }
        }
        return 0;
    }
    return 0;
}

static void write_effects(const PokemonBattleView *view) {
    fputs(",\"effects\":[", stdout);
    size_t written = 0;
    for (uint32_t sequence = 1; sequence <= view->semantic_sequence; sequence++) {
      for (size_t i = 0; i < view->effect_trace_count; i++) {
        const PokemonEffectTrace *trace = &view->effect_traces[i];
        if (trace->semantic_sequence != sequence) continue;
        if (trace->kind != POKEMON_EFFECT_BOOST &&
            !status_effect_kind(trace->kind) &&
            trace->kind != POKEMON_EFFECT_CURE_STATUS &&
            trace->kind != POKEMON_EFFECT_DAMAGE_RELATIVE &&
            trace->kind != POKEMON_EFFECT_HEAL_FRACTION &&
            trace->kind != POKEMON_EFFECT_HEAL_WEATHER_FRACTION &&
            trace->kind != POKEMON_EFFECT_CRASH_DAMAGE) continue;
        uint16_t move_id = effect_move_id(view, trace);
        if (trace->kind != POKEMON_EFFECT_CURE_STATUS &&
            !supported_effect_move(move_id)) continue;
        if (written++) putchar(',');
        const char *phase = trace->kind == POKEMON_EFFECT_CRASH_DAMAGE ? "move-fail" :
            trace->kind == POKEMON_EFFECT_DAMAGE_RELATIVE ? "after-damage" :
            trace->phase == POKEMON_EFFECT_PHASE_SELF_DROP ? "primary" :
            trace->phase == POKEMON_EFFECT_PHASE_PRIMARY ? "primary" :
            trace->target == POKEMON_EFFECT_TARGET_USER ? "self-secondary" : "secondary";
        const char *operation = trace->kind == POKEMON_EFFECT_BOOST ? "boost" :
            status_effect_kind(trace->kind) ? "set-status" :
            trace->kind == POKEMON_EFFECT_CURE_STATUS ? "cure-status" :
            trace->kind == POKEMON_EFFECT_CRASH_DAMAGE ? "crash-damage" :
            (trace->kind == POKEMON_EFFECT_HEAL_FRACTION ||
             trace->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION) ? "direct-heal" :
            trace->prevention ? "prevent-recoil" :
            trace->argument == POKEMON_DAMAGE_RELATIVE_RECOIL ? "recoil" : "drain";
        if (operation == NULL) abort();
        printf("{\"kind\":\"effect\",\"phase\":\"%s\",\"operation\":\"%s\"," 
            "\"move\":\"%s\",\"source\":{\"side\":%u,\"slot\":%u},"
            "\"target\":{\"side\":%u,\"slot\":%u},\"applied\":%s",
            phase, operation, move_name(move_id),
            trace->source_side, trace->source_slot, trace->target_side,
            trace->target_slot,
            trace->result == POKEMON_EFFECT_APPLIED ? "true" : "false");
        if (trace->kind == POKEMON_EFFECT_CRASH_DAMAGE) {
            printf(",\"basis\":\"hypothetical-move-damage\","
                "\"damage_basis\":%u,\"critical\":%s,\"damage_roll\":%u,"
                "\"numerator\":%u,\"denominator\":%u,\"minimum\":%u,"
                "\"cap_numerator\":%u,\"cap_denominator\":%u,"
                "\"cap_value\":%u,\"requested\":%u,"
                "\"damage_target\":{\"side\":%u,\"slot\":%u},"
                "\"hp_before\":%d,\"hp_after\":%d,\"amount\":%u}",
                trace->damage_basis, trace->critical ? "true" : "false",
                trace->damage_roll, trace->numerator, trace->denominator,
                trace->minimum, trace->cap_numerator, trace->cap_denominator,
                trace->cap_value, trace->requested,
                trace->damage_target_side, trace->damage_target_slot,
                trace->before, trace->after, trace->value);
        } else if (trace->kind == POKEMON_EFFECT_HEAL_FRACTION ||
            trace->kind == POKEMON_EFFECT_HEAL_WEATHER_FRACTION) {
            printf(",\"basis\":\"base-max-hp\",\"damage_basis\":%u,"
                "\"numerator\":%u,\"denominator\":%u,\"requested\":%u,"
                "\"hp_before\":%d,\"hp_after\":%d,\"amount\":%u}",
                trace->damage_basis, trace->numerator, trace->denominator,
                trace->requested, trace->before, trace->after, trace->value);
        } else if (trace->kind == POKEMON_EFFECT_DAMAGE_RELATIVE) {
            if (trace->prevention) {
                printf(",\"cause\":\"rockhead\",\"requested\":%u,"
                    "\"damage_target\":{\"side\":%u,\"slot\":%u}}",
                    trace->requested, trace->damage_target_side,
                    trace->damage_target_slot);
            } else {
                int amount = strcmp(operation, "drain") == 0 &&
                        trace->after < trace->before ?
                    trace->after - trace->before : trace->value;
                printf(",\"cause\":\"move-%s\",\"damage_target\":{"
                    "\"side\":%u,\"slot\":%u},\"damage_basis\":%u,"
                    "\"numerator\":%u,\"denominator\":%u,\"requested\":%u,"
                    "\"hp_before\":%d,\"hp_after\":%d,\"amount\":%d}",
                    operation, trace->damage_target_side, trace->damage_target_slot,
                    trace->damage_basis, trace->numerator, trace->denominator,
                    trace->requested, trace->before, trace->after, amount);
            }
        } else if (trace->kind == POKEMON_EFFECT_BOOST) {
            printf(",\"stat\":\"%s\",\"delta\":%d,\"before\":%d,\"after\":%d}",
                stat_name(trace->argument), trace->after - trace->before,
                trace->before, trace->after);
        } else {
            const char *status = status_name(trace->argument);
            const char *before = status_name((uint16_t)trace->before);
            const char *after = status_name((uint16_t)trace->after);
            if (status == NULL) abort();
            printf(",\"status\":\"%s\",\"before\":", status);
            if (before == NULL) fputs("null", stdout); else printf("\"%s\"", before);
            fputs(",\"after\":", stdout);
            if (after == NULL) fputs("null", stdout); else printf("\"%s\"", after);
            putchar('}');
        }
      }
      for (size_t i = 0; i < view->damage_formula_trace_count; i++) {
        const PokemonDamageFormulaTrace *trace = &view->damage_formula_traces[i];
        if (trace->semantic_sequence != sequence) continue;
        /* Showdown's observer reports callback/fixed-damage entry points, not
         * a second formula event when a prepared condition supplies damage. */
        if (trace->formula == POKEMON_DAMAGE_OWNER_CONDITION_VALUE ||
            trace->formula == POKEMON_DAMAGE_TARGET_CURRENT_HP) continue;
        if (trace->move_id == POKEMON_GEN3_MOVE_FUTURESIGHT ||
            trace->move_id == POKEMON_GEN3_MOVE_DOOMDESIRE) continue;
        if (written++) putchar(',');
        if (trace->formula == POKEMON_DAMAGE_FIXED_LEVEL ||
            trace->formula == POKEMON_DAMAGE_FIXED_LITERAL ||
            trace->formula == POKEMON_DAMAGE_TARGET_HP_FRACTION ||
            trace->formula == POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE ||
            trace->formula == POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT) {
            printf("{\"kind\":\"effect\",\"phase\":\"damage-formula\","
                "\"operation\":\"fixed-damage\",\"move\":\"%s\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},"
                "\"formula\":\"%s\",\"resolved\":%u}",
                move_name(trace->move_id), trace->source_side, trace->source_slot,
                trace->target_side, trace->target_slot,
                trace->formula == POKEMON_DAMAGE_FIXED_LEVEL ? "level" :
                trace->formula == POKEMON_DAMAGE_FIXED_LITERAL ? "constant" :
                "callback",
                trace->resolved_value);
        } else if (trace->formula == POKEMON_DAMAGE_HP_BRACKET) {
            printf("{\"kind\":\"effect\",\"phase\":\"damage-formula\","
                "\"operation\":\"variable-power\",\"move\":\"%s\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},"
                "\"formula\":\"hp-bracket\",\"ratio\":%u,"
                "\"bracket\":%u,\"resolved\":%u}",
                move_name(trace->move_id), trace->source_side, trace->source_slot,
                trace->target_side, trace->target_slot, trace->ratio,
                trace->bracket, trace->resolved_value);
        } else {
            abort();
        }
      }
      for (size_t i = 0; i < view->hit_trace_count; i++) {
        const PokemonHitTrace *hit = &view->hit_traces[i];
        if (hit->semantic_sequence != sequence) continue;
        if (hit->move_id == POKEMON_GEN3_MOVE_FUTURESIGHT ||
            hit->move_id == POKEMON_GEN3_MOVE_DOOMDESIRE) continue;
        if (hit->requested_hits == 1 && !hit->dynamic_plan) continue;
        /* Only the multi-hit path creates hit traces. A dynamically resolved
         * one-hit plan is still a multi-hit invocation in Showdown. */
        if (written++) putchar(',');
        printf("{\"kind\":\"effect\",\"phase\":\"hit-loop\",\"operation\":");
        if (hit->kind == POKEMON_HIT_PLAN) {
            printf("\"multihit-plan\",\"move\":\"%s\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},\"requested\":%u}",
                move_name(hit->move_id), hit->source_side, hit->source_slot,
                hit->target_side, hit->target_slot, hit->requested_hits);
        } else if (hit->kind == POKEMON_HIT_CONNECTED ||
                   hit->kind == POKEMON_HIT_SUBSTITUTE) {
            printf("\"multihit-hit\",\"move\":\"%s\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},"
                "\"requested\":%u,\"ordinal\":%u,\"critical\":%s,"
                "\"damage_roll\":%u,\"damage\":%u,\"target_hp_after\":%u,"
                "\"source_hp_after\":%u}",
                move_name(hit->move_id), hit->source_side, hit->source_slot,
                hit->target_side, hit->target_slot, hit->requested_hits,
                hit->hit_index, hit->critical ? "true" : "false",
                hit->damage_roll,
                hit->kind == POKEMON_HIT_SUBSTITUTE ? 0 : hit->damage,
                hit->hp_after, hit->source_hp_after);
        } else if (hit->kind == POKEMON_HIT_RESULT) {
            const char *stop_reason =
                hit->stop_reason == POKEMON_HIT_STOP_COMPLETED ? "completed" :
                hit->stop_reason == POKEMON_HIT_STOP_TARGET_FAINTED ? "target-fainted" :
                hit->stop_reason == POKEMON_HIT_STOP_SOURCE_FAINTED ? "source-fainted" :
                hit->stop_reason == POKEMON_HIT_STOP_ACCURACY ? "missed" :
                hit->stop_reason == POKEMON_HIT_STOP_SOURCE_ASLEEP ? "source-asleep" : NULL;
            if (stop_reason == NULL) abort();
            printf("\"multihit-result\",\"move\":\"%s\","
                "\"source\":{\"side\":%u,\"slot\":%u},"
                "\"target\":{\"side\":%u,\"slot\":%u},"
                "\"requested\":%u,\"actual\":%u,\"stop_reason\":\"%s\"}",
                move_name(hit->move_id), hit->source_side, hit->source_slot,
                hit->target_side, hit->target_slot, hit->requested_hits,
                hit->actual_hits, stop_reason);
        } else {
            abort();
        }
      }
    }
    putchar(']');
}

static void write_boundary(
    size_t ordinal, const PokemonBattle *battle,
    const PokemonChoice choices[POKEMON_SIDES], const PokemonQueue *queue
) {
    PokemonBattleView view;
    pokemon_battle_view(battle, &view);
    printf("{\"schema\":\"pokemon-native-slice-boundary-v1\",\"case_id\":\"%s\",\"boundary\":%zu,\"request\":[", output_case->id, ordinal);
    write_request(&view, 0);
    putchar(',');
    write_request(&view, 1);
    putchar(']');
    write_transition(choices, queue);
    write_handlers(&view);
    write_conditions(&view);
    write_immunities(&view);
    write_modifiers(&view);
    write_effects(&view);
    fputs(",\"state\":", stdout);
    write_state(&view);
    fputs(",\"events\":[", stdout);
    size_t written_events = 0;
    size_t written_damage_hits = 0;
    size_t connected_hits = 0;
    int wrote_hit_count = 0;
    uint16_t multihit_move = 0;
    uint8_t multihit_target_side = 0;
    uint8_t actual_hits = 0;
    int has_hit_result = 0;
    PokemonHitTraceKind last_hit_kind = POKEMON_HIT_PLAN;
    for (size_t i = 0; i < view.hit_trace_count; i++) {
        const PokemonHitTrace *hit = &view.hit_traces[i];
        if (hit->requested_hits == 1 && !hit->dynamic_plan) continue;
        multihit_move = hit->move_id;
        multihit_target_side = hit->target_side;
        if (hit->kind == POKEMON_HIT_CONNECTED) connected_hits++;
        if (hit->kind == POKEMON_HIT_CONNECTED ||
            hit->kind == POKEMON_HIT_SUBSTITUTE) {
            last_hit_kind = hit->kind;
        }
        if (hit->kind == POKEMON_HIT_RESULT) {
            actual_hits = hit->actual_hits;
            has_hit_result = 1;
        }
    }
    for (size_t i = 0; i < view.event_count; i++) {
        if (!protocol_event(view.events[i].kind)) continue;
        if (written_events++) putchar(',');
        write_event(&view.events[i]);
        if (view.events[i].kind == POKEMON_EVENT_DAMAGE &&
            view.events[i].move_id == multihit_move) {
            written_damage_hits++;
            if (written_damage_hits == connected_hits &&
                last_hit_kind == POKEMON_HIT_CONNECTED && has_hit_result) {
                printf(",{\"kind\":\"hit-count\",\"side\":%u,\"hits\":%u}",
                    multihit_target_side, actual_hits);
                written_events++;
                wrote_hit_count = 1;
            }
        }
    }
    if (has_hit_result && actual_hits > 0 && !wrote_hit_count) {
        if (written_events++) putchar(',');
        printf("{\"kind\":\"hit-count\",\"side\":%u,\"hits\":%u}",
            multihit_target_side, actual_hits);
    }
    fputs("],\"prng\":[", stdout);
    for (size_t i = 0; i < view.draw_count; i++) {
        const PokemonDraw *draw = &view.draws[i];
        if (i) putchar(',');
        if (draw->label == POKEMON_DRAW_EVENT_HANDLER_ORDER) {
            if (draw->context_event_id == POKEMON_HANDLER_EVENT_SET_STATUS) {
                fputs("{\"label\":\"event.setstatus.handler_order\",\"before\":",
                    stdout);
            } else if (draw->context_event_id ==
                    POKEMON_HANDLER_EVENT_MODIFY_DAMAGE_PHASE1) {
                fputs("{\"label\":\"event.modifydamagephase1.handler_order\",\"before\":",
                    stdout);
            } else {
                printf("{\"label\":\"event.%u.handler_order\",\"before\":",
                    draw->context_event_id);
            }
        } else {
            printf("{\"label\":\"%s\",\"before\":", draw_name(draw->label));
        }
        write_seed(draw->seed_before);
        fputs(",\"after\":", stdout);
        write_seed(draw->seed_after);
        if (draw->label == POKEMON_DRAW_SET_STATUS_HANDLER_ORDER_OFFSET_ONE) {
            printf(",\"from\":1,\"to\":3,\"result\":%u}", draw->result + 1u);
        } else if (draw->label == POKEMON_DRAW_DAMAGE_FORMULA) {
            const PokemonDamageFormulaRandomPolicy *policy =
                &POKEMON_GEN3_RULES.random_damage_formulas[0];
            if (POKEMON_GEN3_RULES.random_damage_formula_count != 1 ||
                policy->formula != POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT ||
                draw->upper_bound !=
                    (uint32_t)(policy->maximum_exclusive - policy->minimum)) {
                abort();
            }
            printf(",\"from\":%u,\"to\":%u,\"result\":%u}",
                policy->minimum, policy->maximum_exclusive,
                policy->minimum + draw->result);
        } else if (draw->label == POKEMON_DRAW_PARTIALLY_TRAPPED_DURATION ||
                   draw->label == POKEMON_DRAW_DISABLE_DURATION ||
                   draw->label == POKEMON_DRAW_ENCORE_DURATION ||
                   draw->label == POKEMON_DRAW_UPROAR_DURATION) {
            printf(",\"from\":%u,\"to\":null,\"result\":%u}",
                draw->upper_bound - draw->lower_bound,
                draw->result - draw->lower_bound);
        } else if (draw->label == POKEMON_DRAW_RESIDUAL_HANDLER_ORDER ||
                   draw->label == POKEMON_DRAW_MOVE_PP_REDUCTION) {
            printf(",\"from\":%u,\"to\":%u,\"result\":%u}",
                draw->lower_bound, draw->upper_bound, draw->result);
        } else if (draw->label == POKEMON_DRAW_EVENT_HANDLER_ORDER &&
                   draw->context_event_id == POKEMON_HANDLER_EVENT_SET_STATUS) {
            printf(",\"from\":%u,\"to\":%u,\"result\":%u}",
                draw->lower_bound, draw->lower_bound + draw->upper_bound,
                draw->lower_bound + draw->result);
        } else if (draw->label == POKEMON_DRAW_SET_STATUS_HANDLER_ORDER ||
            draw->label == POKEMON_DRAW_EVENT_HANDLER_ORDER ||
            draw->label == POKEMON_DRAW_QUEUE_TIE ||
            draw->label == POKEMON_DRAW_EACH_EVENT_BEFORE_TURN_ACTIVE_ORDER ||
            draw->label == POKEMON_DRAW_EACH_EVENT_UPDATE_ACTIVE_ORDER ||
            draw->label == POKEMON_DRAW_EACH_EVENT_WEATHER_ACTIVE_ORDER ||
            draw->label == POKEMON_DRAW_EACH_EVENT_WEATHER_CHANGE_ACTIVE_ORDER) {
            printf(",\"from\":0,\"to\":%u,\"result\":%u}",
                draw->upper_bound, draw->result);
        } else {
            printf(",\"from\":%u,\"to\":null,\"result\":%u}",
                draw->upper_bound, draw->result);
        }
    }
    fputs("]}\n", stdout);
}

static int run_case(const VerifyCase *verify_case) {
    PokemonBattle battle;
    output_case = verify_case;
    /* The oracle applies fixture-only mutable state after Showdown has
     * completed Battle construction and its initial runSwitch lifecycle.
     * Keep that verifier staging out of the runtime initialization contract. */
    PokemonBattleInit startup = verify_case->init;
    memset(startup.initial_hp, 0, sizeof(startup.initial_hp));
    memset(startup.initial_status, 0, sizeof(startup.initial_status));
    memset(startup.initial_sleep_time, 0, sizeof(startup.initial_sleep_time));
    memset(startup.initial_sleep_skipped_time, 0,
        sizeof(startup.initial_sleep_skipped_time));
    memset(startup.initial_toxic_stage, 0,
        sizeof(startup.initial_toxic_stage));
    int result = pokemon_battle_init(&battle, &startup);
    if (result != POKEMON_OK) return result;
    for (size_t side = 0; side < POKEMON_SIDES; side++) {
        for (size_t slot = 0; slot < battle.team_sizes[side]; slot++) {
            PokemonMutable *state = &battle.sides[side].state[slot];
            uint16_t hp = verify_case->init.initial_hp[side][slot];
            if (hp != 0) {
                if (hp > battle.sides[side].sets[slot].stats[0]) {
                    return POKEMON_INVALID_CONFIGURATION;
                }
                state->hp = hp;
                if (slot == battle.sides[side].active) {
                    for (size_t event = 0; event < battle.event_count; event++) {
                        if (battle.events[event].kind == POKEMON_EVENT_SWITCH &&
                            battle.events[event].side == side &&
                            battle.events[event].slot == slot) {
                            battle.events[event].hp = hp;
                        }
                    }
                }
            }
            PokemonStatus status = (PokemonStatus)
                verify_case->init.initial_status[side][slot];
            if (status == POKEMON_STATUS_NONE) continue;
            uint16_t descriptor_id = battle.generation->condition_descriptor(
                POKEMON_OWNER_STATUS, status);
            if (descriptor_id == 0) return POKEMON_INVALID_CONFIGURATION;
            state->status = (PokemonStatusState){
                .kind = status,
                .descriptor_id = descriptor_id,
                .state_generation = 1,
                .effect_order = slot == battle.sides[side].active ?
                    ++battle.next_holder_effect_order : 0,
            };
            if (status == POKEMON_STATUS_SLEEP) {
                state->status.state.sleep.time =
                    verify_case->init.initial_sleep_time[side][slot];
                state->status.state.sleep.skipped_time =
                    verify_case->init.initial_sleep_skipped_time[side][slot];
            } else if (status == POKEMON_STATUS_TOXIC) {
                state->status.state.toxic.stage =
                    verify_case->init.initial_toxic_stage[side][slot];
            }
        }
    }
    if (!pokemon_battle_check_invariants(&battle)) {
        fprintf(stderr, "%s: boundary 0 violated native battle invariants\n",
            verify_case->id);
        return POKEMON_INVALID_CONFIGURATION;
    }
    write_boundary(0, &battle, NULL, NULL);
    for (size_t i = 0; i < verify_case->choice_count; i++) {
        result = pokemon_battle_step(&battle, verify_case->choices[i]);
        if (result != POKEMON_OK) {
            fprintf(stderr, "%s: boundary %zu failed with %d\n",
                verify_case->id, i + 1, result);
            return result;
        }
        if (!pokemon_battle_check_invariants(&battle)) {
            fprintf(stderr, "%s: boundary %zu violated native battle invariants\n",
                verify_case->id, i + 1);
            return POKEMON_INVALID_CONFIGURATION;
        }
        write_boundary(i + 1, &battle, verify_case->choices[i], &battle.last_queue);
    }
    return POKEMON_OK;
}

int main(int argc, char **argv) {
    if (argc > 2) {
        fprintf(stderr, "usage: %s [CASE_ID]\n", argv[0]);
        return EXIT_FAILURE;
    }
    int matched = 0;
    for (size_t i = 0; i < VERIFY_CASE_COUNT; i++) {
        if (argc == 2 && strcmp(argv[1], VERIFY_CASES[i].id) != 0) continue;
        matched = 1;
        int result = run_case(&VERIFY_CASES[i]);
        if (result != POKEMON_OK) {
            fprintf(stderr, "%s: native step failed with %d\n", VERIFY_CASES[i].id, result);
            return EXIT_FAILURE;
        }
    }
    if (!matched) {
        fprintf(stderr, "unknown case: %s\n", argv[1]);
        return EXIT_FAILURE;
    }
    return EXIT_SUCCESS;
}
