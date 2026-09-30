#include "gen3_rules.h"

#include <assert.h>
#include <stdint.h>

static uint16_t gen3_base_damage(const PokemonDamageInput *input) {
    assert(input != NULL);
    const PokemonSet *attacker = input->attacker;
    const PokemonSet *defender = input->defender;
    const PokemonMoveData *move = input->move;
    uint32_t attack = input->attack;
    uint32_t defense = input->defense;
    (void)attacker;
    (void)defender;
    uint32_t damage = (2u * attacker->level) / 5u + 2u;
    damage = damage * move->power * attack;
    damage /= defense;
    damage /= 50u;
    return damage > UINT16_MAX ? UINT16_MAX : (uint16_t)damage;
}

static void gen3_resolve_damage_formula(
    const PokemonDamageFormulaInput *input, PokemonDamageFormulaOutput *output
) {
    assert(input != NULL && output != NULL);
    *output = (PokemonDamageFormulaOutput){0};
    if (input->formula == POKEMON_DAMAGE_FIXED_LEVEL) {
        output->fixed_damage = input->level;
        return;
    }
    if (input->formula == POKEMON_DAMAGE_FIXED_LITERAL) {
        assert(input->parameter != 0);
        output->fixed_damage = input->parameter;
        return;
    }
    if (input->formula == POKEMON_DAMAGE_TARGET_HP_FRACTION) {
        assert(input->parameter != 0 && input->target_hp != 0);
        output->fixed_damage = input->target_hp / input->parameter;
        if (output->fixed_damage == 0) output->fixed_damage = 1;
        return;
    }
    if (input->formula == POKEMON_DAMAGE_TARGET_SOURCE_HP_DIFFERENCE) {
        assert(input->target_hp > input->hp);
        output->fixed_damage = input->target_hp - input->hp;
        return;
    }
    if (input->formula == POKEMON_DAMAGE_TARGET_CURRENT_HP) {
        assert(input->target_hp != 0);
        output->fixed_damage = input->target_hp;
        return;
    }
    if (input->formula == POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT) {
        assert(input->random_value >= 50 && input->random_value < 151);
        output->fixed_damage = (uint16_t)(
            (uint32_t)input->random_value * input->level / 100u);
        if (output->fixed_damage == 0) output->fixed_damage = 1;
        return;
    }
    assert(input->formula == POKEMON_DAMAGE_HP_BRACKET);
    assert(input->max_hp != 0 && input->hp != 0 && input->hp <= input->max_hp);
    uint32_t ratio = (uint32_t)input->hp * 48u / input->max_hp;
    if (ratio == 0) ratio = 1;
    output->ratio = (uint8_t)ratio;
    if (ratio < 2) { output->bracket = 0; output->resolved_power = 200; }
    else if (ratio < 5) { output->bracket = 1; output->resolved_power = 150; }
    else if (ratio < 10) { output->bracket = 2; output->resolved_power = 100; }
    else if (ratio < 17) { output->bracket = 3; output->resolved_power = 80; }
    else if (ratio < 33) { output->bracket = 4; output->resolved_power = 40; }
    else { output->bracket = 5; output->resolved_power = 20; }
}

static uint16_t gen3_residual_damage(
    PokemonResidualFormula formula, uint16_t max_hp, uint8_t stage
) {
    assert(max_hp != 0);
    uint32_t denominator =
        (formula == POKEMON_RESIDUAL_FORMULA_BURN ||
         formula == POKEMON_RESIDUAL_FORMULA_POISON) ? 8u : 16u;
    assert(formula >= POKEMON_RESIDUAL_FORMULA_SAND &&
        formula <= POKEMON_RESIDUAL_FORMULA_TOXIC);
    uint32_t unit = max_hp / denominator;
    if (unit == 0) unit = 1;
    uint32_t damage = formula == POKEMON_RESIDUAL_FORMULA_TOXIC ?
        unit * stage : unit;
    return damage > UINT16_MAX ? UINT16_MAX : (uint16_t)damage;
}

static uint16_t gen3_fraction(
    uint16_t basis, uint8_t numerator, uint8_t denominator
) {
    assert(denominator != 0);
    return (uint16_t)((uint32_t)basis * numerator / denominator);
}

static uint16_t gen3_condition_descriptor(
    PokemonOwnerKind owner_kind, uint16_t semantic_kind
) {
    if (owner_kind == POKEMON_OWNER_STATUS) {
        switch ((PokemonStatus)semantic_kind) {
        case POKEMON_STATUS_NONE: return 0;
        case POKEMON_STATUS_BURN: return POKEMON_GEN3_CONDITION_STATUS_BRN;
        case POKEMON_STATUS_TOXIC: return POKEMON_GEN3_CONDITION_STATUS_TOX;
        case POKEMON_STATUS_PARALYSIS: return POKEMON_GEN3_CONDITION_STATUS_PAR;
        case POKEMON_STATUS_POISON: return POKEMON_GEN3_CONDITION_STATUS_PSN;
        case POKEMON_STATUS_SLEEP: return POKEMON_GEN3_CONDITION_STATUS_SLP;
        case POKEMON_STATUS_FREEZE: return POKEMON_GEN3_CONDITION_STATUS_FRZ;
        }
    } else if (owner_kind == POKEMON_OWNER_VOLATILE) {
        switch ((PokemonVolatileKind)semantic_kind) {
        case POKEMON_VOLATILE_NONE: return 0;
        case POKEMON_VOLATILE_PROTECT: return POKEMON_GEN3_CONDITION_VOLATILE_PROTECT;
        case POKEMON_VOLATILE_STALL: return POKEMON_GEN3_CONDITION_VOLATILE_STALL;
        case POKEMON_VOLATILE_SUBSTITUTE: return POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTE;
        case POKEMON_VOLATILE_SUBSTITUTE_BROKEN: return POKEMON_GEN3_CONDITION_VOLATILE_SUBSTITUTEBROKEN;
        case POKEMON_VOLATILE_PARTIALLY_TRAPPED: return POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED;
        case POKEMON_VOLATILE_MAGIC_COAT: return POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT;
        case POKEMON_VOLATILE_SNATCH: return POKEMON_GEN3_CONDITION_VOLATILE_SNATCH;
        case POKEMON_VOLATILE_CONFUSION: return POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION;
        case POKEMON_VOLATILE_LOCKED_MOVE: return POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE;
        case POKEMON_VOLATILE_TWO_TURN_MOVE: return POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE;
        case POKEMON_VOLATILE_TWO_TURN_MARKER: return 0;
        case POKEMON_VOLATILE_FLINCH: return POKEMON_GEN3_CONDITION_VOLATILE_FLINCH;
        case POKEMON_VOLATILE_FOCUS_ENERGY: return POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY;
        case POKEMON_VOLATILE_TAUNT: return POKEMON_GEN3_CONDITION_VOLATILE_TAUNT;
        case POKEMON_VOLATILE_TORMENT: return POKEMON_GEN3_CONDITION_VOLATILE_TORMENT;
        case POKEMON_VOLATILE_DISABLE: return POKEMON_GEN3_CONDITION_VOLATILE_DISABLE;
        case POKEMON_VOLATILE_ENCORE: return POKEMON_GEN3_CONDITION_VOLATILE_ENCORE;
        case POKEMON_VOLATILE_YAWN: return POKEMON_GEN3_CONDITION_VOLATILE_YAWN;
        case POKEMON_VOLATILE_MUST_RECHARGE:
            return POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE;
        case POKEMON_VOLATILE_NIGHTMARE:
            return POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE;
        case POKEMON_VOLATILE_ATTRACT:
            return POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT;
        case POKEMON_VOLATILE_CHOICE_LOCK:
            return POKEMON_GEN3_CONDITION_VOLATILE_CHOICELOCK;
		case POKEMON_VOLATILE_TRAPPED:
			return POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED;
		case POKEMON_VOLATILE_TRAPPER:
			return POKEMON_GEN3_CONDITION_SIMULATOR_TRAPPER;
		case POKEMON_VOLATILE_MUD_SPORT:
			return POKEMON_GEN3_CONDITION_VOLATILE_MUDSPORT;
        case POKEMON_VOLATILE_WATER_SPORT:
            return POKEMON_GEN3_CONDITION_VOLATILE_WATERSPORT;
        case POKEMON_VOLATILE_ENDURE:
            return POKEMON_GEN3_CONDITION_VOLATILE_ENDURE;
        case POKEMON_VOLATILE_LOCK_ON:
            return POKEMON_GEN3_CONDITION_VOLATILE_LOCKON;
        case POKEMON_VOLATILE_PREPARED_RETALIATION:
            /* Counter and Mirror Coat share one runtime payload shape but
             * retain distinct flattened descriptors, so callers must select
             * the descriptor explicitly rather than through semantic kind. */
            return 0;
        case POKEMON_VOLATILE_INGRAIN:
            return POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN;
        case POKEMON_VOLATILE_QUEUED_MOVE_INTERCEPT:
            return POKEMON_GEN3_CONDITION_VOLATILE_PURSUIT;
        case POKEMON_VOLATILE_CHARGE:
            return POKEMON_GEN3_CONDITION_VOLATILE_CHARGE;
        case POKEMON_VOLATILE_LEECH_SEED:
            return POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED;
        case POKEMON_VOLATILE_FLASH_FIRE:
            return POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE;
        case POKEMON_VOLATILE_COUNTDOWN_FAINT:
            return POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG;
        case POKEMON_VOLATILE_FORESIGHT:
            return POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT;
        case POKEMON_VOLATILE_STORED_DAMAGE:
            return POKEMON_GEN3_CONDITION_VOLATILE_BIDE;
        case POKEMON_VOLATILE_FURY_CUTTER:
            return POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER;
		case POKEMON_VOLATILE_ROLLOUT:
			return POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT;
		case POKEMON_VOLATILE_ICE_BALL:
			return POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL;
        case POKEMON_VOLATILE_DEFENSE_CURL:
			return POKEMON_GEN3_CONDITION_VOLATILE_DEFENSECURL;
		case POKEMON_VOLATILE_STOCKPILE:
			return POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE;
		case POKEMON_VOLATILE_RAGE:
			return POKEMON_GEN3_CONDITION_VOLATILE_RAGE;
		case POKEMON_VOLATILE_MINIMIZE:
			return POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE;
		case POKEMON_VOLATILE_PREPARED_ACTION:
			return POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH;
		case POKEMON_VOLATILE_SOURCE_FAINT_RESPONSE:
			return POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND;
		case POKEMON_VOLATILE_SOURCE_PP_ZERO_RESPONSE:
			return POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE;
		case POKEMON_VOLATILE_UPROAR:
			return POKEMON_GEN3_CONDITION_VOLATILE_UPROAR;
		case POKEMON_VOLATILE_IMPRISON:
			return POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON;
		case POKEMON_VOLATILE_CURSE:
			return POKEMON_GEN3_CONDITION_VOLATILE_CURSE;
		case POKEMON_VOLATILE_PARTY_HIT:
			return POKEMON_GEN3_CONDITION_VOLATILE_BEATUP;
		case POKEMON_VOLATILE_KIND_COUNT:
			return 0;
        }
    } else if (owner_kind == POKEMON_OWNER_SIDE) {
        switch ((PokemonSideConditionKind)semantic_kind) {
        case POKEMON_SIDE_CONDITION_NONE: return 0;
        case POKEMON_SIDE_CONDITION_PHYSICAL_SCREEN:
            return POKEMON_GEN3_CONDITION_SIDE_REFLECT;
        case POKEMON_SIDE_CONDITION_SPECIAL_SCREEN:
            return POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN;
        case POKEMON_SIDE_CONDITION_MIST:
            return POKEMON_GEN3_CONDITION_SIDE_MIST;
        case POKEMON_SIDE_CONDITION_SAFEGUARD:
            return POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD;
        case POKEMON_SIDE_CONDITION_SPIKES:
            return POKEMON_GEN3_CONDITION_SIDE_SPIKES;
        }
    } else if (owner_kind == POKEMON_OWNER_FIELD) {
        switch ((PokemonWeatherKind)semantic_kind) {
        case POKEMON_WEATHER_NONE: return 0;
        case POKEMON_WEATHER_SANDSTORM: return POKEMON_GEN3_CONDITION_WEATHER_SANDSTORM;
        case POKEMON_WEATHER_HAIL: return POKEMON_GEN3_CONDITION_WEATHER_HAIL;
        case POKEMON_WEATHER_RAIN: return POKEMON_GEN3_CONDITION_WEATHER_RAINDANCE;
        case POKEMON_WEATHER_SUN: return POKEMON_GEN3_CONDITION_WEATHER_SUNNYDAY;
        }
    }
    return 0;
}

#define DURATION_NONE {POKEMON_CONDITION_DURATION_NONE, 0, 0}
#define DURATION_FIXED(turns) \
    {POKEMON_CONDITION_DURATION_FIXED, (turns), (turns)}
#define DURATION_UNIFORM(minimum, maximum) \
    {POKEMON_CONDITION_DURATION_UNIFORM, (minimum), (maximum)}

static const PokemonConditionRule GEN3_CONDITION_RULES[] = {
    {POKEMON_RULE_CONDITION_TOXIC, POKEMON_GEN3_CONDITION_STATUS_TOX, DURATION_NONE, 1, 1, 10, 6, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_BURN, POKEMON_GEN3_CONDITION_STATUS_BRN, DURATION_NONE, 1, 1, 10, 6, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_POISON, POKEMON_GEN3_CONDITION_STATUS_PSN, DURATION_NONE, 1, 1, 10, 6, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_PROTECT, POKEMON_GEN3_CONDITION_VOLATILE_PROTECT, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 1},
    {POKEMON_RULE_CONDITION_STALL, POKEMON_GEN3_CONDITION_VOLATILE_STALL, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_REFLECT, POKEMON_GEN3_CONDITION_SIDE_REFLECT, DURATION_FIXED(5), 1, 1, 1, 4, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_SANDSTORM, POKEMON_GEN3_CONDITION_WEATHER_SANDSTORM, DURATION_FIXED(5), 1, 1, 8, 5, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_MAGIC_COAT, POKEMON_GEN3_CONDITION_VOLATILE_MAGICCOAT, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_SNATCH, POKEMON_GEN3_CONDITION_VOLATILE_SNATCH, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_HAIL, POKEMON_GEN3_CONDITION_WEATHER_HAIL, DURATION_FIXED(5), 1, 1, 8, 5, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_RAIN, POKEMON_GEN3_CONDITION_WEATHER_RAINDANCE, DURATION_FIXED(5), 1, 1, 8, 5, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_SUN, POKEMON_GEN3_CONDITION_WEATHER_SUNNYDAY, DURATION_FIXED(5), 1, 1, 8, 5, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_CONFUSION, POKEMON_GEN3_CONDITION_VOLATILE_CONFUSION, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_LOCKED_MOVE, POKEMON_GEN3_CONDITION_VOLATILE_LOCKEDMOVE, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_TWO_TURN_MOVE, POKEMON_GEN3_CONDITION_VOLATILE_TWOTURNMOVE, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_FLINCH, POKEMON_GEN3_CONDITION_VOLATILE_FLINCH, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_FOCUS_ENERGY, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSENERGY, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_LIGHT_SCREEN, POKEMON_GEN3_CONDITION_SIDE_LIGHTSCREEN, DURATION_FIXED(5), 1, 1, 2, 4, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED, POKEMON_GEN3_CONDITION_VOLATILE_PARTIALLYTRAPPED, DURATION_UNIFORM(3, 6), 1, 1, 10, 9, 1, POKEMON_DRAW_PARTIALLY_TRAPPED_DURATION, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_TAUNT, POKEMON_GEN3_CONDITION_VOLATILE_TAUNT, DURATION_FIXED(2), 1, 1, 10, 15, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_TORMENT, POKEMON_GEN3_CONDITION_VOLATILE_TORMENT, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_DISABLE, POKEMON_GEN3_CONDITION_VOLATILE_DISABLE, DURATION_UNIFORM(2, 5), 1, 0, 0, 2, 1, POKEMON_DRAW_DISABLE_DURATION, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_ENCORE, POKEMON_GEN3_CONDITION_VOLATILE_ENCORE, DURATION_UNIFORM(3, 6), 1, 1, 10, 14, 1, POKEMON_DRAW_ENCORE_DURATION, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_MIST, POKEMON_GEN3_CONDITION_SIDE_MIST, DURATION_FIXED(5), 1, 1, 3, 4, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_SAFEGUARD, POKEMON_GEN3_CONDITION_SIDE_SAFEGUARD, DURATION_FIXED(5), 1, 1, 4, 4, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_YAWN, POKEMON_GEN3_CONDITION_VOLATILE_YAWN, DURATION_FIXED(2), 1, 1, 10, 19, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_SPIKES, POKEMON_GEN3_CONDITION_SIDE_SPIKES, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_MUST_RECHARGE, POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_NIGHTMARE, POKEMON_GEN3_CONDITION_VOLATILE_NIGHTMARE, DURATION_NONE, 1, 1, 10, 7, 1, 0, 1, POKEMON_STATUS_SLEEP, 0, 0},
    {POKEMON_RULE_CONDITION_ATTRACT, POKEMON_GEN3_CONDITION_VOLATILE_ATTRACT, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_TRAPPED, POKEMON_GEN3_CONDITION_VOLATILE_TRAPPED, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, POKEMON_VOLATILE_TRAPPER, 0},
    {POKEMON_RULE_CONDITION_TRAPPER, POKEMON_GEN3_CONDITION_SIMULATOR_TRAPPER, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, POKEMON_VOLATILE_NONE, 0},
    {POKEMON_RULE_CONDITION_CHOICE_LOCK, POKEMON_GEN3_CONDITION_VOLATILE_CHOICELOCK, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_MUD_SPORT, POKEMON_GEN3_CONDITION_VOLATILE_MUDSPORT, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_WATER_SPORT, POKEMON_GEN3_CONDITION_VOLATILE_WATERSPORT, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_ENDURE, POKEMON_GEN3_CONDITION_VOLATILE_ENDURE, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 1},
    {POKEMON_RULE_CONDITION_LOCK_ON, POKEMON_GEN3_CONDITION_VOLATILE_LOCKON, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_RETALIATION_PHYSICAL, POKEMON_GEN3_CONDITION_VOLATILE_COUNTER, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_RETALIATION_SPECIAL, POKEMON_GEN3_CONDITION_VOLATILE_MIRRORCOAT, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_INGRAIN, POKEMON_GEN3_CONDITION_VOLATILE_INGRAIN, DURATION_NONE, 1, 1, 10, 1, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_QUEUED_MOVE_INTERCEPT, POKEMON_GEN3_CONDITION_VOLATILE_PURSUIT, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_CHARGE, POKEMON_GEN3_CONDITION_VOLATILE_CHARGE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_LEECH_SEED, POKEMON_GEN3_CONDITION_VOLATILE_LEECHSEED, DURATION_NONE, 1, 1, 10, 5, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_FLASH_FIRE, POKEMON_GEN3_CONDITION_VOLATILE_FLASHFIRE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_COUNTDOWN_FAINT, POKEMON_GEN3_CONDITION_VOLATILE_PERISHSONG, DURATION_FIXED(4), 1, 1, 12, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_FORESIGHT, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_STORED_DAMAGE, POKEMON_GEN3_CONDITION_VOLATILE_BIDE, DURATION_FIXED(3), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
    {POKEMON_RULE_CONDITION_RAMPING_POWER, POKEMON_GEN3_CONDITION_VOLATILE_FURYCUTTER, DURATION_FIXED(2), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, POKEMON_CONDITION_RULE_REPEATABLE_FAMILY},
	{POKEMON_RULE_CONDITION_RAMPING_POWER, POKEMON_GEN3_CONDITION_VOLATILE_ROLLOUT, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, POKEMON_CONDITION_RULE_REPEATABLE_FAMILY},
	{POKEMON_RULE_CONDITION_RAMPING_POWER, POKEMON_GEN3_CONDITION_VOLATILE_ICEBALL, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, POKEMON_CONDITION_RULE_REPEATABLE_FAMILY},
	{POKEMON_RULE_CONDITION_RAMPING_POWER, POKEMON_GEN3_CONDITION_VOLATILE_DEFENSECURL, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, POKEMON_CONDITION_RULE_REPEATABLE_FAMILY},
	{POKEMON_RULE_CONDITION_BOUNDED_COUNTER, POKEMON_GEN3_CONDITION_VOLATILE_STOCKPILE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, POKEMON_CONDITION_RULE_REPEATABLE_FAMILY},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_RAGE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_MINIMIZE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_FOCUSPUNCH, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_DESTINYBOND, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_GRUDGE, DURATION_NONE, 0, 0, 0, 0, 0, 0, 0, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_UPROAR, DURATION_UNIFORM(2, 5), 1, 1, 10, 11, 1, POKEMON_DRAW_UPROAR_DURATION, 0, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_IMPRISON, DURATION_NONE, 0, 0, 0, 0, 0, 0, 1, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_CURSE, DURATION_NONE, 1, 1, 10, 8, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
	{POKEMON_RULE_CONDITION_PERSISTENT_HANDLER_DRIVEN, POKEMON_GEN3_CONDITION_VOLATILE_BEATUP, DURATION_FIXED(1), 1, 0, 0, 2, 1, 0, 0, POKEMON_STATUS_NONE, 0, 0},
};

#undef DURATION_UNIFORM
#undef DURATION_FIXED
#undef DURATION_NONE

static const PokemonStagePolicy GEN3_STAGE_POLICY = {
    .minimum = -6,
    .maximum = 6,
    .ordinary = {
        {2, 8},
    {2, 7},
    {2, 6},
    {2, 5},
    {2, 4},
    {2, 3},
    {2, 2},
        {3, 2},
    {4, 2},
    {5, 2},
    {6, 2},
    {7, 2},
    {8, 2},
    },
    .accuracy = {
        {3, 9},
    {3, 8},
    {3, 7},
    {3, 6},
    {3, 5},
    {3, 4},
    {3, 3},
        {4, 3},
    {5, 3},
    {6, 3},
    {7, 3},
    {8, 3},
    {9, 3},
    },
};

static const uint8_t GEN3_MULTIHIT_OUTCOMES[] = {2, 2, 2, 3, 3, 3, 4, 5};
static const PokemonDamageFormulaRandomPolicy GEN3_RANDOM_DAMAGE_FORMULAS[] = {
    {POKEMON_DAMAGE_RANDOM_LEVEL_PERCENT, 50, 151},
};

static const PokemonChoiceControlPolicy GEN3_CHOICE_CONTROL_POLICIES[] = {
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_UPROAR,
        .request_op = POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC,
        .synthetic_move_id = POKEMON_GEN3_MOVE_UPROAR,
        .request_handler_id = 1017,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_BIDE,
        .request_op = POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC,
        .synthetic_move_id = POKEMON_GEN3_MOVE_BIDE,
        .request_handler_id = 1016,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_MUSTRECHARGE,
        .request_op = POKEMON_CHOICE_REQUEST_HARD_LOCK_SYNTHETIC,
        .action_op = POKEMON_CHOICE_ACTION_CONSUME_AND_PREVENT_SYNTHETIC,
        .synthetic_move_id = POKEMON_GEN3_MOVE_RECHARGE,
        .action_priority = 11,
        .request_handler_id = 1012,
        .action_handler_id = 1013,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_TAUNT,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_CATEGORY,
        .action_op = POKEMON_CHOICE_ACTION_REJECT_CATEGORY,
        .category = POKEMON_CATEGORY_STATUS,
        .request_handler_id = 1001,
        .action_handler_id = 1002,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_TORMENT,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_LAST_MOVE,
        .request_handler_id = 1003,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_DISABLE,
        .start_op = POKEMON_CHOICE_START_CAPTURE_LAST_USABLE_MOVE,
        .start_duration_op =
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_STORED_MOVE,
        .action_op = POKEMON_CHOICE_ACTION_REJECT_STORED_MOVE,
        .request_priority = 0,
        .action_priority = 7,
        .start_handler_id = 1004,
        .request_handler_id = 1005,
        .action_handler_id = 1006,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_ENCORE,
        .start_op = POKEMON_CHOICE_START_CAPTURE_LAST_ENCORE_ELIGIBLE_MOVE,
        .start_duration_op =
            POKEMON_CHOICE_START_DURATION_INCREMENT_IF_ALREADY_MOVED,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_EXCEPT_STORED_MOVE,
        .action_op = POKEMON_CHOICE_ACTION_OVERRIDE_WITH_STORED_MOVE,
        .residual_op =
            POKEMON_CHOICE_RESIDUAL_END_IF_STORED_MOVE_UNUSABLE,
        .start_handler_id = 1008,
        .request_handler_id = 1009,
        .action_handler_id = 1010,
        .residual_handler_id = 1011,
    },
    {
        .owner_descriptor_id = POKEMON_GEN3_CONDITION_VOLATILE_CHOICELOCK,
        .start_op = POKEMON_CHOICE_START_CAPTURE_LAST_USABLE_MOVE,
        .request_op = POKEMON_CHOICE_REQUEST_DISABLE_EXCEPT_STORED_MOVE,
        .required_held_item_id = POKEMON_GEN3_ITEM_CHOICEBAND,
        .allows_indefinite_start = 1,
        .start_handler_id = 1014,
        .request_handler_id = 1015,
    },
};

static void gen3_critical_chance(
    uint32_t stage, uint8_t *numerator, uint8_t *denominator
) {
    static const uint8_t denominators[] = {0, 16, 8, 4, 3, 2};
    assert(numerator != NULL && denominator != NULL);
    if (stage > 5) stage = 5;
    *numerator = stage == 0 ? 0 : 1;
    *denominator = denominators[stage];
}

enum { GEN3_PERSONAL_MOVE_HIDDEN_POWER = 1 };

static int gen3_resolve_personal_move_profile(
    uint16_t kind, const uint8_t ivs[6], PokemonPersonalMoveProfile *output
) {
    static const uint8_t hidden_power_types[16] = {
        POKEMON_GEN3_TYPE_FIGHTING, POKEMON_GEN3_TYPE_FLYING,
        POKEMON_GEN3_TYPE_POISON, POKEMON_GEN3_TYPE_GROUND,
        POKEMON_GEN3_TYPE_ROCK, POKEMON_GEN3_TYPE_BUG,
        POKEMON_GEN3_TYPE_GHOST, POKEMON_GEN3_TYPE_STEEL,
        POKEMON_GEN3_TYPE_FIRE, POKEMON_GEN3_TYPE_WATER,
        POKEMON_GEN3_TYPE_GRASS, POKEMON_GEN3_TYPE_ELECTRIC,
        POKEMON_GEN3_TYPE_PSYCHIC, POKEMON_GEN3_TYPE_ICE,
        POKEMON_GEN3_TYPE_DRAGON, POKEMON_GEN3_TYPE_DARK,
    };
    /* Native stat order is HP, Atk, Def, SpA, SpD, Spe.  The cartridge
     * formula weights Speed before the two special stats. */
    static const uint8_t formula_order[6] = {0, 1, 2, 5, 3, 4};
    if (kind != GEN3_PERSONAL_MOVE_HIDDEN_POWER || ivs == NULL ||
        output == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint8_t type_bits = 0;
    uint8_t power_bits = 0;
    for (size_t bit = 0; bit < 6; bit++) {
        uint8_t iv = ivs[formula_order[bit]];
        if (iv > 31) return POKEMON_INVALID_CONFIGURATION;
        type_bits |= (uint8_t)((iv & 1u) << bit);
        power_bits |= (uint8_t)(((iv >> 1) & 1u) << bit);
    }
    uint8_t type = hidden_power_types[(uint8_t)(type_bits * 15u / 63u)];
    uint8_t special = type == POKEMON_GEN3_TYPE_FIRE ||
        type == POKEMON_GEN3_TYPE_WATER || type == POKEMON_GEN3_TYPE_GRASS ||
        type == POKEMON_GEN3_TYPE_ICE || type == POKEMON_GEN3_TYPE_ELECTRIC ||
        type == POKEMON_GEN3_TYPE_PSYCHIC || type == POKEMON_GEN3_TYPE_DRAGON ||
        type == POKEMON_GEN3_TYPE_DARK;
    *output = (PokemonPersonalMoveProfile){
        .kind = kind,
        .type = type,
        .category = special ? POKEMON_CATEGORY_SPECIAL : POKEMON_CATEGORY_PHYSICAL,
        .power = (uint8_t)(power_bits * 40u / 63u + 30u),
    };
    return POKEMON_OK;
}

static int gen3_recalculate_species_stat(
    uint16_t original_stat, uint8_t original_base, uint8_t replacement_base,
    uint8_t iv, uint8_t level, uint8_t nature, uint16_t *output
) {
    if (original_stat == 0 || original_base == 0 || replacement_base == 0 ||
        iv > 31 || level == 0 || output == NULL) {
        return POKEMON_INVALID_CONFIGURATION;
    }
    uint8_t numerator = 10;
    if (nature == POKEMON_NATURE_TIMID || nature == POKEMON_NATURE_HASTY ||
        nature == POKEMON_NATURE_JOLLY || nature == POKEMON_NATURE_NAIVE) {
        numerator = 11;
    } else if (nature == POKEMON_NATURE_BRAVE ||
        nature == POKEMON_NATURE_RELAXED ||
        nature == POKEMON_NATURE_QUIET ||
        nature == POKEMON_NATURE_SASSY) {
        numerator = 9;
    }
    uint16_t resolved = 0;
    for (uint16_t effort_quarter = 0; effort_quarter <= 63; effort_quarter++) {
        uint32_t original =
            ((2u * original_base + iv + effort_quarter) * level) / 100u + 5u;
        original = original * numerator / 10u;
        if (original != original_stat) continue;
        uint32_t replacement =
            ((2u * replacement_base + iv + effort_quarter) * level) / 100u + 5u;
        replacement = replacement * numerator / 10u;
        if (replacement == 0 || replacement > UINT16_MAX ||
            (resolved != 0 && resolved != replacement)) {
            return POKEMON_INVALID_CONFIGURATION;
        }
        resolved = (uint16_t)replacement;
    }
    if (resolved == 0) return POKEMON_INVALID_CONFIGURATION;
    *output = resolved;
    return POKEMON_OK;
}

const PokemonGeneration POKEMON_GEN3_RULES = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .critical_multiplier = 2,
    .shared_turn_speed = {
        .numerator = 1, .denominator = 5, .speed_sentinel = UINT16_MAX,
    },
    .toxic_stage_cap = 15,
    .paralysis_speed_numerator = 1,
    .paralysis_speed_denominator = 4,
    .confusion_duration_min = 2,
    .confusion_duration_max = 5,
    .confusion_action_denominator = 2,
    .locked_move_duration_min = 2,
    .locked_move_duration_max = 3,
    .has_separate_modify_type_phase = 0,
    .hit_staging =
        POKEMON_HIT_STAGING_DEFER_IMMUNITY_AFTER_ACCURACY_AND_TRY_HIT,
    .weather_damage_stage = POKEMON_WEATHER_DAMAGE_BEFORE_FINAL_BASE_OFFSET,
    .base_damage = gen3_base_damage,
    .resolve_damage_formula = gen3_resolve_damage_formula,
    .residual_damage = gen3_residual_damage,
    .fraction = gen3_fraction,
    .condition_descriptor = gen3_condition_descriptor,
    .critical_chance = gen3_critical_chance,
    .resolve_personal_move_profile = gen3_resolve_personal_move_profile,
    .recalculate_species_stat = gen3_recalculate_species_stat,
    .condition_rules = GEN3_CONDITION_RULES,
    .condition_rule_count = sizeof(GEN3_CONDITION_RULES) /
        sizeof(GEN3_CONDITION_RULES[0]),
    .stall = {2, 2, 8},
    .stages = &GEN3_STAGE_POLICY,
    .multihit = {
        .minimum = 2,
        .maximum = 5,
        .outcomes = GEN3_MULTIHIT_OUTCOMES,
        .outcome_count = sizeof(GEN3_MULTIHIT_OUTCOMES) /
            sizeof(GEN3_MULTIHIT_OUTCOMES[0]),
    },
    .ohko = {.base_accuracy = 30},
    .random_damage_formulas = GEN3_RANDOM_DAMAGE_FORMULAS,
    .random_damage_formula_count = sizeof(GEN3_RANDOM_DAMAGE_FORMULAS) /
        sizeof(GEN3_RANDOM_DAMAGE_FORMULAS[0]),
    .substitute_cost_denominator = 4,
    .substitute_reject_max_hp_one = 1,
    .knock_off_locks_item_slot = 1,
    .cancel_all_actions_on_faint = 1,
    .self_destruct_defense_divisor = 2,
    .replaced_ability_runs_start = 0,
    .continue_preselected_switch_after_interception_faint = 1,
    .fallback_move_id = POKEMON_GEN3_MOVE_STRUGGLE,
    .choice_control_policies = GEN3_CHOICE_CONTROL_POLICIES,
    .choice_control_policy_count = sizeof(GEN3_CHOICE_CONTROL_POLICIES) /
        sizeof(GEN3_CHOICE_CONTROL_POLICIES[0]),
};
