#include "gen3_move_hit.h"

#include <stddef.h>
#include <string.h>

static int random_value(
    const Gen3MoveHitContext *context, const char *label, uint32_t *out
) {
    if (context->random.next == NULL) return GEN3_INVALID_ARGUMENT;
    return context->random.next(context->random.context, label, out);
}

static uint32_t random_below(uint32_t value, uint32_t limit) {
    return (uint32_t)(((uint64_t)value * limit) >> 32);
}

static uint32_t modify(uint32_t value, uint32_t numerator, uint32_t denominator) {
    const uint32_t modifier = (uint32_t)(((uint64_t)numerator * 4096u) / denominator);
    return (uint32_t)(((uint64_t)value * modifier + 2047u) / 4096u);
}

static uint32_t apply_modifier(uint32_t value, Gen3HitModifier modifier) {
    if (modifier.denominator == 0) return value;
    return modify(value, modifier.numerator, modifier.denominator);
}

static uint32_t staged_stat(uint32_t value, int8_t stage) {
    if (stage > 6) stage = 6;
    if (stage < -6) stage = -6;
    if (stage >= 0) return value * (uint32_t)(2 + stage) / 2u;
    return value * 2u / (uint32_t)(2 - stage);
}

static int ability_has_capability(uint16_t ability_id, uint32_t capability) {
    for (size_t i = 0; i < GEN3_EFFECT_DESCRIPTOR_COUNT; i++) {
        const Gen3EffectDescriptor *effect = &GEN3_EFFECT_DESCRIPTORS[i];
        if (effect->kind == GEN3_EFFECT_ABILITY && effect->effect_id == ability_id) {
            return (effect->capability_bits & capability) != 0;
        }
    }
    return 0;
}

int gen3_generated_ability_immunity(
    const Gen3HitCombatant *target, const Gen3MoveData *move
) {
    if (target == NULL || move == NULL || move->ignore_immunity) return 0;
    return move->type == GEN3_TYPE_GROUND &&
        ability_has_capability(target->ability_id, GEN3_EFFECT_CAP_GROUND_IMMUNE);
}

static int type_is_immune(
    const Gen3HitCombatant *target, const Gen3MoveData *move
) {
    if (move->ignore_immunity) return 0;
    const Gen3SpeciesData *species = &GEN3_SPECIES[target->set->species_id];
    for (uint8_t i = 0; i < species->type_count; i++) {
        if (GEN3_TYPE_EFFECTIVENESS[move->type][species->types[i]] == 0) return 1;
    }
    return 0;
}

static uint32_t apply_type_effectiveness(
    uint32_t damage, const Gen3HitCombatant *target, const Gen3MoveData *move
) {
    const Gen3SpeciesData *species = &GEN3_SPECIES[target->set->species_id];
    for (uint8_t i = 0; i < species->type_count; i++) {
        const uint8_t multiplier =
            GEN3_TYPE_EFFECTIVENESS[move->type][species->types[i]];
        if (multiplier == 4) {
            damage *= 2u;
        } else if (multiplier == 1) {
            damage /= 2u;
        }
        /* Immunity is staged before accuracy.  If a move explicitly ignores
         * immunity, the immune type contributes a neutral multiplier. */
    }
    return damage;
}

static int validate_context(const Gen3MoveHitContext *context) {
    if (context == NULL || context->attacker.set == NULL ||
        context->target.set == NULL || context->move == NULL) {
        return 0;
    }
    const Gen3PokemonSet *attacker = context->attacker.set;
    const Gen3PokemonSet *target = context->target.set;
    const Gen3MoveData *move = context->move;
    if (attacker->species_id == 0 || attacker->species_id > GEN3_SPECIES_MAX_ID ||
        target->species_id == 0 || target->species_id > GEN3_SPECIES_MAX_ID ||
        GEN3_SPECIES[attacker->species_id].national_dex == 0 ||
        GEN3_SPECIES[target->species_id].national_dex == 0 ||
        attacker->level == 0 || move->type >= GEN3_TYPE_COUNT ||
        move->base_power == 0 || (move->category != 1 && move->category != 2)) {
        return 0;
    }
    const size_t attack_index = move->category == 1 ? 1u : 3u;
    const size_t defense_index = move->category == 1 ? 2u : 4u;
    if ((context->burn.denominator == 0 && context->burn.numerator != 0) ||
        (context->phase1.denominator == 0 && context->phase1.numerator != 0) ||
        (context->weather.denominator == 0 && context->weather.numerator != 0))
        return 0;
    return attacker->stats[attack_index] != 0 && target->stats[defense_index] != 0;
}

int gen3_resolve_move_hit(
    const Gen3MoveHitContext *context, Gen3HitOutcome *outcome
) {
    if (outcome == NULL || !validate_context(context)) return GEN3_INVALID_ARGUMENT;
    memset(outcome, 0, sizeof(*outcome));

    const Gen3MoveData *move = context->move;
    const int natural_immunity = type_is_immune(&context->target, move) ||
        (context->natural_immunity != NULL &&
         context->natural_immunity(&context->target, move));

    int accuracy_passed = 1;
    if (move->accuracy != 0) {
        uint32_t random = 0;
        const int result = random_value(context, "move.accuracy", &random);
        if (result != GEN3_OK) return result;
        accuracy_passed = random_below(random, 100u) < move->accuracy;
    }

    if (accuracy_passed && context->try_hit != NULL &&
        context->try_hit(
            context->try_hit_context, &context->target, move
        ) != GEN3_TRY_HIT_PASS) {
        outcome->kind = GEN3_HIT_FAILED;
        return GEN3_OK;
    }
    if (natural_immunity) {
        outcome->kind = GEN3_HIT_IMMUNE;
        return GEN3_OK;
    }
    if (!accuracy_passed) {
        outcome->kind = GEN3_HIT_MISSED;
        return GEN3_OK;
    }

    uint8_t critical = 0;
    uint8_t crit_ratio = move->crit_ratio;
    if (crit_ratio > 5) crit_ratio = 5;
    if (crit_ratio != 0) {
        static const uint8_t denominators[] = {0, 16, 8, 4, 3, 2};
        uint32_t random = 0;
        const int result = random_value(context, "move.critical_hit", &random);
        if (result != GEN3_OK) return result;
        critical = random_below(random, denominators[crit_ratio]) == 0;
    }

    uint32_t roll_random = 0;
    const int roll_result = random_value(
        context, "move.damage_roll", &roll_random
    );
    if (roll_result != GEN3_OK) return roll_result;
    const uint8_t damage_roll = (uint8_t)random_below(roll_random, 16u);

    const Gen3PokemonSet *attacker = context->attacker.set;
    const Gen3PokemonSet *target = context->target.set;
    const size_t attack_index = move->category == 1 ? 1u : 3u;
    const size_t defense_index = move->category == 1 ? 2u : 4u;
    const size_t attack_stage_index = move->category == 1 ? 0u : 2u;
    const size_t defense_stage_index = move->category == 1 ? 1u : 3u;
    int8_t attack_stage = context->attacker.stat_stages[attack_stage_index];
    int8_t defense_stage = context->target.stat_stages[defense_stage_index];
    /* Gen 3 critical hits ignore only detrimental offensive stages and
     * beneficial defensive stages.  Favorable stages still apply. */
    if (critical && attack_stage < 0) attack_stage = 0;
    if (critical && defense_stage > 0) defense_stage = 0;
    const uint32_t attack = staged_stat(attacker->stats[attack_index], attack_stage);
    uint32_t defense = staged_stat(target->stats[defense_index], defense_stage);
    if (defense == 0) defense = 1;
    uint64_t damage = (2u * attacker->level) / 5u + 2u;
    damage = damage * move->base_power * attack;
    damage /= defense;
    damage /= 50u;

    damage = apply_modifier((uint32_t)damage, context->burn);
    damage = apply_modifier((uint32_t)damage, context->phase1);
    damage = apply_modifier((uint32_t)damage, context->weather);

    damage += 2u;

    if (critical) damage = modify((uint32_t)damage, 2u, 1u);

    const Gen3SpeciesData *attacker_species =
        &GEN3_SPECIES[attacker->species_id];
    for (uint8_t i = 0; i < attacker_species->type_count; i++) {
        if (attacker_species->types[i] == move->type) {
            damage = modify((uint32_t)damage, 3u, 2u);
            break;
        }
    }
    damage = apply_type_effectiveness(
        (uint32_t)damage, &context->target, move
    );
    damage = (damage * (100u - damage_roll)) / 100u;
    if (damage == 0) damage = 1;

    outcome->kind = GEN3_HIT_CONNECTED;
    outcome->value.connected.critical = critical;
    outcome->value.connected.damage_roll = damage_roll;
    outcome->value.connected.damage = (uint32_t)damage;
    return GEN3_OK;
}
