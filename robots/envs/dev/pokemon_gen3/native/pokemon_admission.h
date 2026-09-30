#ifndef POKEMON_ADMISSION_H
#define POKEMON_ADMISSION_H

#include <stddef.h>
#include <stdint.h>

#define POKEMON_ADMISSION_ABI_VERSION UINT32_C(13)
#define POKEMON_ADMISSION_MAX_MOVES 4
#define POKEMON_ADMISSION_MAX_TEAM_SIZE 6
#define POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES 72
#define POKEMON_ADMISSION_MAX_CANONICAL_FIELD_BYTES 16

typedef struct PokemonResolvedBundle PokemonResolvedBundle;
typedef struct PokemonAcquisitionData PokemonAcquisitionData;

typedef enum {
    POKEMON_ADMISSION_SPECIES = 0,
    POKEMON_ADMISSION_MOVE,
    POKEMON_ADMISSION_ABILITY,
    POKEMON_ADMISSION_ITEM,
    POKEMON_ADMISSION_IDENTITY_KIND_COUNT,
} PokemonAdmissionIdentityKind;

typedef struct {
    const char *id;
    uint8_t tags;
    uint8_t predicates;
} PokemonAdmissionIdentity;

typedef enum {
    POKEMON_ADMISSION_TAG_UBER = UINT8_C(1) << 0,
    POKEMON_ADMISSION_TAG_UNOBTAINABLE = UINT8_C(1) << 1,
    POKEMON_ADMISSION_TAG_NONEXISTENT = UINT8_C(1) << 2,
} PokemonAdmissionTag;

typedef enum {
    POKEMON_ADMISSION_PREDICATE_OHKO = UINT8_C(1) << 0,
    POKEMON_ADMISSION_PREDICATE_GUARANTEED_ACCURACY_DROP = UINT8_C(1) << 1,
    POKEMON_ADMISSION_PREDICATE_TRAPPING = UINT8_C(1) << 2,
    POKEMON_ADMISSION_PREDICATE_BATON_PASS = UINT8_C(1) << 3,
    POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE = UINT8_C(1) << 4,
    POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE = UINT8_C(1) << 5,
} PokemonAdmissionPredicate;

typedef struct {
    const PokemonAdmissionIdentity *values;
    uint16_t count;
} PokemonAdmissionIdentitySpan;

typedef struct {
    const char *display_name;
    uint16_t base_species_id;
} PokemonAdmissionSpeciesMetadata;

/* Compressed-row relation over one-based IDs in two identity spans. */
typedef struct {
    PokemonAdmissionIdentityKind owner_kind;
    PokemonAdmissionIdentityKind member_kind;
    const uint16_t *row_offsets;
    uint16_t row_offset_count;
    const uint16_t *members;
    uint16_t member_count;
    const char *canonical_id;
} PokemonAdmissionAllowedRelation;

typedef struct {
    uint64_t plugin_fingerprint;
    PokemonAdmissionIdentitySpan identities[POKEMON_ADMISSION_IDENTITY_KIND_COUNT];
    const PokemonAdmissionSpeciesMetadata *species_metadata;
    const PokemonAcquisitionData *acquisition;
    const PokemonAdmissionAllowedRelation *relations;
    uint16_t relation_count;
} PokemonAdmissionUniverse;

typedef enum {
    POKEMON_ADMISSION_ATOMIC_BAN = 1,
    POKEMON_ADMISSION_TAG_BAN,
    POKEMON_ADMISSION_ALL_OF_BAN,
    POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN,
    POKEMON_ADMISSION_STAT_VECTOR_RULE,
    POKEMON_ADMISSION_SPECIES_REWRITE_RULE,
    POKEMON_ADMISSION_ALLOWED_RELATION_RULE,
    POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE,
    POKEMON_ADMISSION_UNIQUE_MOVES_RULE,
    POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE,
    POKEMON_ADMISSION_SET_FIELDS_RULE,
} PokemonAdmissionRuleKind;

typedef enum {
    POKEMON_ADMISSION_SCOPE_SET = 1,
    POKEMON_ADMISSION_SCOPE_TEAM,
} PokemonAdmissionRuleScope;

typedef enum {
    POKEMON_ADMISSION_OPERAND_MATCHABLE = 0,
    POKEMON_ADMISSION_OPERAND_STATICALLY_UNMATCHABLE,
} PokemonAdmissionOperandDisposition;

/* identity_id is one-based in the corresponding universe span.  A statically
 * unmatchable operand deliberately has identity_id zero and retains its
 * canonical Showdown ID as provenance. */
typedef struct {
    PokemonAdmissionIdentityKind kind;
    uint16_t identity_id;
    const char *canonical_id;
    PokemonAdmissionOperandDisposition disposition;
} PokemonAdmissionOperand;

typedef struct {
    PokemonAdmissionTag tag;
    uint8_t identity_kind_mask;
    const char *canonical_id;
} PokemonAdmissionTagBan;

typedef struct {
    PokemonAdmissionPredicate predicate;
    uint8_t identity_kind_mask;
} PokemonAdmissionPredicateRequirement;

typedef struct {
    PokemonAdmissionPredicateRequirement requirements[2];
    uint8_t requirement_count;
    const char *canonical_id;
} PokemonAdmissionAllOfBan;

typedef struct {
    PokemonAdmissionPredicateRequirement anchor;
    PokemonAdmissionPredicateRequirement counted;
    uint8_t max_sources_per_set;
    uint8_t max_matching_sets;
    const char *canonical_id;
} PokemonAdmissionAnchoredCardinalityBan;

typedef enum {
    POKEMON_ADMISSION_STAT_HP = 0,
    POKEMON_ADMISSION_STAT_ATK,
    POKEMON_ADMISSION_STAT_DEF,
    POKEMON_ADMISSION_STAT_SPA,
    POKEMON_ADMISSION_STAT_SPD,
    POKEMON_ADMISSION_STAT_SPE,
    POKEMON_ADMISSION_STAT_COUNT,
} PokemonAdmissionStat;

typedef struct {
    int16_t component_min;
    int16_t component_max;
    uint16_t expected_total_limit;
    uint8_t reject_zero_above_level;
    const char *canonical_id;
} PokemonAdmissionStatVectorRule;

typedef struct {
    uint16_t relation_id;
} PokemonAdmissionAllowedRelationRule;

typedef struct {
    uint16_t input_species_id;
    uint16_t output_species_id;
    uint16_t required_ability_id;
} PokemonAdmissionGuardedSpeciesRewrite;

typedef struct {
    const PokemonAdmissionGuardedSpeciesRewrite *rewrites;
    uint16_t rewrite_count;
    const char *canonical_id;
} PokemonAdmissionSpeciesRewriteRule;

typedef struct {
    PokemonAdmissionRuleKind kind;
    PokemonAdmissionRuleScope scope;
    /* Canonical ID of the resolved RuleTable entry which introduced this
     * flattened rule, or the selected format for a direct ban. */
    const char *source_rule_id;
    union {
        PokemonAdmissionOperand atomic_ban;
        PokemonAdmissionTagBan tag_ban;
        PokemonAdmissionAllOfBan all_of_ban;
        PokemonAdmissionAnchoredCardinalityBan anchored_cardinality_ban;
        PokemonAdmissionStatVectorRule stat_vector_rule;
        PokemonAdmissionSpeciesRewriteRule species_rewrite_rule;
        PokemonAdmissionAllowedRelationRule allowed_relation_rule;
    } value;
} PokemonAdmissionRule;

typedef struct {
    uint64_t plugin_fingerprint;
    const PokemonAdmissionRule *rules;
    uint16_t rule_count;
} PokemonAdmissionProgram;

typedef enum {
    POKEMON_ACQUISITION_LEVEL_UP_STANDARD = 0,
    POKEMON_ACQUISITION_LEVEL_UP_GEN3_POMEG = 1,
} PokemonAcquisitionLevelUpPolicy;

/* Cold-path acquisition semantics selected by the resolved format. The ID
 * binds this policy to one admission/runtime format instead of permitting an
 * ambient clause toggle. */
typedef struct {
    const char *format_id;
    PokemonAcquisitionLevelUpPolicy level_up_policy;
    uint8_t pomeg_minimum_level;
} PokemonAdmissionFormatPolicy;

typedef struct {
    uint64_t plugin_fingerprint;
    uint64_t runtime_plugin_fingerprint;
    uint32_t abi_version;
    uint8_t generation;
    const char *format_id;
    const char *oracle_revision;
    const PokemonAdmissionUniverse *universe;
    const PokemonAdmissionProgram *program;
    const PokemonAdmissionFormatPolicy *format_policy;
} PokemonAdmissionBundle;

typedef enum {
    POKEMON_ACQUISITION_GENDER_UNSPECIFIED = 0,
    POKEMON_ACQUISITION_GENDER_MALE,
    POKEMON_ACQUISITION_GENDER_FEMALE,
    POKEMON_ACQUISITION_GENDER_NEUTER,
} PokemonAcquisitionGender;

/* External names are normalized at this cold admission boundary. */
typedef struct {
    const char *species_id;
    const char *ability_id;
    const char *item_id; /* NULL or "" means no item. */
    const char *move_ids[POKEMON_ADMISSION_MAX_MOVES];
    uint8_t move_count;
    uint8_t level;
    uint8_t has_evs;
    int16_t evs[POKEMON_ADMISSION_STAT_COUNT];
    const char *nickname; /* NULL or "" means the species' base name. */
    PokemonAcquisitionGender gender;
    const char *nature_id; /* NULL or "" means Serious. */
    uint8_t shiny;
    uint8_t has_ivs;
    uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT];
    const char *hidden_power_type_id;
} PokemonAdmissionSetInput;

typedef struct {
    PokemonAdmissionSetInput sets[POKEMON_ADMISSION_MAX_TEAM_SIZE];
    uint8_t set_count;
} PokemonAdmissionTeamInput;

/* Fully canonical product published only after successful normalization and
 * all currently implemented admission checks. Strings are bundle-owned. */
typedef struct {
    const char *species_id;
    const char *ability_id;
    const char *item_id;
    const char *move_ids[POKEMON_ADMISSION_MAX_MOVES];
    uint8_t move_count;
    uint8_t level;
    int16_t evs[POKEMON_ADMISSION_STAT_COUNT];
    char nickname[POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES + 1];
    PokemonAcquisitionGender gender;
    char nature_id[POKEMON_ADMISSION_MAX_CANONICAL_FIELD_BYTES + 1];
    uint8_t shiny;
    uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT];
    char hidden_power_type_id[POKEMON_ADMISSION_MAX_CANONICAL_FIELD_BYTES + 1];
} PokemonAdmissionNormalizedSet;

typedef struct {
    PokemonAdmissionNormalizedSet sets[POKEMON_ADMISSION_MAX_TEAM_SIZE];
    uint8_t set_count;
} PokemonAdmissionNormalizedTeam;

typedef enum {
    POKEMON_ADMISSION_RESULT_INVALID_BUNDLE = 1,
    POKEMON_ADMISSION_RESULT_MALFORMED,
    POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY,
    POKEMON_ADMISSION_RESULT_BANNED,
    /* Identity and atomic-ban checks passed, but the complete Gen 3 OU
     * admission program has intentionally not yet been implemented. */
    POKEMON_ADMISSION_RESULT_INCOMPLETE,
} PokemonAdmissionResult;

typedef struct {
    PokemonAdmissionResult result;
    uint8_t team_index;
    PokemonAdmissionIdentityKind identity_kind;
    uint8_t input_index;
    uint16_t rule_index;
} PokemonAdmissionDecision;

int pokemon_admission_validate_bundle(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime
);
PokemonAdmissionDecision pokemon_admission_check_set(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionSetInput *input
);
PokemonAdmissionDecision pokemon_admission_check_set_normalized(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionSetInput *input,
    PokemonAdmissionNormalizedSet *output
);
PokemonAdmissionDecision pokemon_admission_check_team(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionTeamInput *input
);
PokemonAdmissionDecision pokemon_admission_check_team_normalized(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionTeamInput *input,
    PokemonAdmissionNormalizedTeam *output
);

#endif
