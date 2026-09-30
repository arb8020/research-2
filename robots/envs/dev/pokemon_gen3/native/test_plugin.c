#include "test_plugin.h"

#include "gen3_rules.h"
#include "gen3_slice_data.h"
#include "singles2.h"

#include <assert.h>
#include <string.h>

static uint16_t proof_base_damage(const PokemonDamageInput *input) {
    assert(input != NULL);
    /* A conspicuous alternate rounding rule: ceiling division at each stage. */
    uint32_t value = (2u * input->attacker->level + 4u) / 5u + 2u;
    value = (value * input->move->power * input->attack +
        input->defense - 1u) / input->defense;
    value = (value + 49u) / 50u;
    return value > UINT16_MAX ? UINT16_MAX : (uint16_t)value;
}

static uint16_t proof_fraction(
    uint16_t basis, uint8_t numerator, uint8_t denominator
) {
    assert(denominator != 0);
    return (uint16_t)(((uint32_t)basis * numerator + denominator - 1u) /
        denominator);
}

static void proof_critical(
    uint32_t stage, uint8_t *numerator, uint8_t *denominator
) {
    (void)stage;
    *numerator = 1;
    *denominator = 1;
}

void pokemon_test_plugin_rebind(PokemonBattleInit *init) {
    enum { TEST_CONDITION_RULE_CAPACITY = 64 };
    static PokemonGeneration rules;
    static PokemonConditionRule condition_rules[TEST_CONDITION_RULE_CAPACITY];
    static const uint8_t multihit_outcomes[] = {4};
    static PokemonData data;
    static PokemonFormat format;
    static PokemonFormatPolicy policy;
    static PokemonFormatManifest manifest;
    static PokemonResolvedBundle bundle;
    const uint64_t proof_capabilities =
        POKEMON_CAP_GEN3 &
        ~POKEMON_CAP_CONDITION(POKEMON_RULE_CONDITION_FOCUS_ENERGY) &
        ~POKEMON_CAP_CONDITION(POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED);

    assert(init != NULL);
    rules = POKEMON_GEN3_RULES;
    size_t condition_count = 0;
    for (size_t i = 0; i < rules.condition_rule_count; i++) {
        if (rules.condition_rules[i].kind ==
                POKEMON_RULE_CONDITION_FOCUS_ENERGY ||
            rules.condition_rules[i].kind ==
                POKEMON_RULE_CONDITION_PARTIALLY_TRAPPED) continue;
        assert(condition_count < sizeof(condition_rules) /
            sizeof(condition_rules[0]));
        condition_rules[condition_count++] = rules.condition_rules[i];
    }
    condition_rules[POKEMON_RULE_CONDITION_REFLECT - 1].lifecycle_duration =
        (PokemonConditionDuration){POKEMON_CONDITION_DURATION_FIXED, 7, 7};
    rules.plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT;
    rules.capabilities = proof_capabilities;
    rules.generation = 99;
    rules.base_damage = proof_base_damage;
    rules.fraction = proof_fraction;
    rules.critical_chance = proof_critical;
    rules.condition_rules = condition_rules;
    rules.condition_rule_count = condition_count;
    rules.multihit.outcomes = multihit_outcomes;
    rules.multihit.outcome_count = 1;

    data = POKEMON_GEN3_SLICE_DATA;
    data.plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT;
    data.capabilities = proof_capabilities;
    data.generation = 99;
    format = POKEMON_SINGLES_6_FORMAT;
    format.plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT;
    format.capabilities = proof_capabilities;
    format.generation = 99;
    manifest = POKEMON_GEN3_OU_FORMAT;
    manifest.plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT;
    manifest.capabilities = proof_capabilities;
    manifest.generation = 99;
    manifest.id = "kernel-proof";
    manifest.name = "Kernel proof plugin";
    policy = POKEMON_GEN3_OU_POLICY;
    policy.plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT;
    policy.capabilities = proof_capabilities;
    policy.generation = 99;
    policy.manifest = &manifest;
    bundle = (PokemonResolvedBundle){
        .plugin_fingerprint = POKEMON_TEST_PLUGIN_FINGERPRINT,
        .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
        .capabilities = proof_capabilities,
        .generation = 99,
        .rules = &rules,
        .data = &data,
        .runtime_format = &format,
        .policy = &policy,
        .manifest = &manifest,
    };
    init->bundle = &bundle;
}
