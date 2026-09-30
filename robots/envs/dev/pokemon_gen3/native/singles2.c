#include "singles2.h"
#include "gen3_rules.h"
#include "gen3_slice_data.h"

static const PokemonTargetRule SINGLES_TARGET_RULES[] = {
    {POKEMON_TARGET_ADJACENT_ALLY, POKEMON_RESOLVED_TARGET_NONE,
        POKEMON_TARGET_SUPPORTED, 0},
    {POKEMON_TARGET_ALL, POKEMON_RESOLVED_TARGET_FIELD,
        POKEMON_TARGET_SUPPORTED, 0},
    {POKEMON_TARGET_ALL_ADJACENT, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    {POKEMON_TARGET_ALL_ADJACENT_FOES, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    {POKEMON_TARGET_ALLY_SIDE, POKEMON_RESOLVED_TARGET_USER_SIDE,
        POKEMON_TARGET_SUPPORTED, 0},
    {POKEMON_TARGET_ALLY_TEAM, POKEMON_RESOLVED_TARGET_USER_TEAM,
        POKEMON_TARGET_SUPPORTED, 0},
    {POKEMON_TARGET_ANY, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    {POKEMON_TARGET_FOE_SIDE, POKEMON_RESOLVED_TARGET_FOE_SIDE,
        POKEMON_TARGET_SUPPORTED, 0},
    {POKEMON_TARGET_NORMAL, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    {POKEMON_TARGET_RANDOM_NORMAL, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    /* With one active per side, Showdown's scripted retaliation target is
     * already the sole foe; RedirectTarget is only dispatched in multi-active
     * formats. */
    {POKEMON_TARGET_SCRIPTED, POKEMON_RESOLVED_TARGET_FOE,
        POKEMON_TARGET_SUPPORTED, 1},
    {POKEMON_TARGET_SELF, POKEMON_RESOLVED_TARGET_USER,
        POKEMON_TARGET_SUPPORTED, -1},
};

#define SINGLES_TARGET_RULE_COUNT \
    ((uint8_t)(sizeof(SINGLES_TARGET_RULES) / sizeof(SINGLES_TARGET_RULES[0])))

const PokemonFormat POKEMON_SINGLES_1_FORMAT = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .team_size = 1,
    .active_per_side = 1,
    .target_rules = SINGLES_TARGET_RULES,
    .target_rule_count = SINGLES_TARGET_RULE_COUNT,
};

const PokemonFormat POKEMON_SINGLES_2_FORMAT = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .team_size = 2,
    .active_per_side = 1,
    .target_rules = SINGLES_TARGET_RULES,
    .target_rule_count = SINGLES_TARGET_RULE_COUNT,
};

const PokemonFormat POKEMON_SINGLES_3_FORMAT = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .team_size = 3,
    .active_per_side = 1,
    .target_rules = SINGLES_TARGET_RULES,
    .target_rule_count = SINGLES_TARGET_RULE_COUNT,
};

const PokemonFormat POKEMON_SINGLES_6_FORMAT = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .team_size = 6,
    .active_per_side = 1,
    .target_rules = SINGLES_TARGET_RULES,
    .target_rule_count = SINGLES_TARGET_RULE_COUNT,
};

static const PokemonStatusClausePolicy GEN3_OU_STATUS_CLAUSES[] = {
    {
        .status = POKEMON_STATUS_SLEEP,
        .handler_id = POKEMON_GEN3_HANDLER_SLEEP_CLAUSE_SET_STATUS,
        .requires_opposing_source = 1,
        .block_living_opponent_caused = 1,
    },
    {
        .status = POKEMON_STATUS_FREEZE,
        .handler_id = POKEMON_GEN3_HANDLER_FREEZE_CLAUSE_SET_STATUS,
        .requires_opposing_source = 1,
        .block_any_existing = 1,
    },
};

const PokemonFormatPolicy POKEMON_GEN3_OU_POLICY = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .manifest = &POKEMON_GEN3_OU_FORMAT,
    .status_clauses = GEN3_OU_STATUS_CLAUSES,
    .status_clause_count = sizeof(GEN3_OU_STATUS_CLAUSES) /
        sizeof(GEN3_OU_STATUS_CLAUSES[0]),
    .voluntary_switch_order = POKEMON_VOLUNTARY_SWITCH_ORDER_SPEED,
    .protocol = {
        .report_hp_percentages = 1,
        .allow_uncommitted_choice_cancel = 1,
        .hide_beat_up_party_identity = 1,
    },
    .terminal = {
        .endless_minimum_turn = 100,
        .turn_limit = 1000,
        .endless_battle_clause = 1,
    },
};

static const PokemonFormatPolicy POKEMON_GEN3_OU_POMEG_POLICY = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .manifest = &POKEMON_GEN3_OU_POMEG_FORMAT,
    .status_clauses = GEN3_OU_STATUS_CLAUSES,
    .status_clause_count = sizeof(GEN3_OU_STATUS_CLAUSES) /
        sizeof(GEN3_OU_STATUS_CLAUSES[0]),
    .voluntary_switch_order = POKEMON_VOLUNTARY_SWITCH_ORDER_SPEED,
    .protocol = {
        .report_hp_percentages = 1,
        .allow_uncommitted_choice_cancel = 1,
        .hide_beat_up_party_identity = 1,
    },
    .terminal = {
        .endless_minimum_turn = 100,
        .turn_limit = 1000,
        .endless_battle_clause = 1,
    },
};

const PokemonResolvedBundle POKEMON_GEN3_OU_BUNDLE = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .rules = &POKEMON_GEN3_RULES,
    .data = &POKEMON_GEN3_SLICE_DATA,
    .runtime_format = &POKEMON_SINGLES_6_FORMAT,
    .policy = &POKEMON_GEN3_OU_POLICY,
    .manifest = &POKEMON_GEN3_OU_FORMAT,
};

const PokemonResolvedBundle POKEMON_GEN3_OU_POMEG_BUNDLE = {
    .plugin_fingerprint = POKEMON_GEN3_PLUGIN_FINGERPRINT,
    .capability_version = POKEMON_KERNEL_PLUGIN_ABI_VERSION,
    .capabilities = POKEMON_CAP_GEN3,
    .generation = 3,
    .rules = &POKEMON_GEN3_RULES,
    .data = &POKEMON_GEN3_SLICE_DATA,
    .runtime_format = &POKEMON_SINGLES_6_FORMAT,
    .policy = &POKEMON_GEN3_OU_POMEG_POLICY,
    .manifest = &POKEMON_GEN3_OU_POMEG_FORMAT,
};
