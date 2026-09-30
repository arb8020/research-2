#include "pokemon_admission.h"
#include "pokemon_acquisition.h"
#include "pokemon.h"

#include <string.h>

static int canonical_id(const char *id) {
    if (id == NULL || id[0] == '\0') return 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))) return 0;
    }
    return 1;
}

static int identity_kind_mask(uint8_t mask) {
    const uint8_t all = (UINT8_C(1) << POKEMON_ADMISSION_IDENTITY_KIND_COUNT) - 1;
    return mask != 0 && (mask & (uint8_t)~all) == 0;
}

static int one_bit(uint8_t value) {
    return value != 0 && (value & (uint8_t)(value - 1)) == 0;
}

/* Returns -1 for malformed UTF-8, 0 for more than 18 JavaScript UTF-16 code
 * units, and 1 for a bounded string. */
static int nickname_utf8_units(const char *name, size_t *units) {
    size_t total = 0;
    if (name == NULL) {
        *units = 0;
        return 1;
    }
    const unsigned char *p = (const unsigned char *)name;
    while (*p) {
        uint32_t value;
        size_t width;
        if (*p < 0x80) {
            value = *p;
            width = 1;
        } else if ((*p & 0xe0) == 0xc0) {
            value = *p & 0x1f;
            width = 2;
            if (value < 2) return -1;
        } else if ((*p & 0xf0) == 0xe0) {
            value = *p & 0x0f;
            width = 3;
        } else if ((*p & 0xf8) == 0xf0) {
            value = *p & 0x07;
            width = 4;
        } else {
            return -1;
        }
        for (size_t i = 1; i < width; i++) {
            if ((p[i] & 0xc0) != 0x80) return -1;
            value = (value << 6) | (p[i] & 0x3f);
        }
        if ((width == 3 && value < 0x800) || (width == 4 && value < 0x10000) ||
            value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) return -1;
        total += value > 0xffff ? 2 : 1;
        if (total > 18) return 0;
        p += width;
    }
    *units = total;
    return 1;
}

static void normalize_nickname(
    const char *input,
    char output[POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES + 1]
) {
    uint32_t codepoints[18];
    size_t count = 0;
    int pending_space = 0;
    const unsigned char *p = (const unsigned char *)input;
    while (*p) {
        uint32_t value;
        size_t width;
        if (*p < 0x80) { value = *p; width = 1; }
        else if ((*p & 0xe0) == 0xc0) { value = *p & 0x1f; width = 2; }
        else if ((*p & 0xf0) == 0xe0) { value = *p & 0x0f; width = 3; }
        else { value = *p & 0x07; width = 4; }
        for (size_t i = 1; i < width; i++) value = (value << 6) | (p[i] & 0x3f);
        p += width;
        int whitespace = (value >= 0x09 && value <= 0x0d) || value == 0x20 ||
            value == 0xa0 || value == 0x1680 ||
            (value >= 0x2000 && value <= 0x200a) || value == 0x2028 ||
            value == 0x2029 || value == 0x202f || value == 0x205f ||
            value == 0x3000 || value == 0xfeff;
        int separator = whitespace || value == '|' || value == '[' ||
            value == ']' || value == ',' || value == 0x202e;
        if (separator) {
            if (count != 0) pending_space = 1;
            continue;
        }
        if (pending_space) codepoints[count++] = 0x20;
        pending_space = 0;
        codepoints[count++] = value;
    }

    size_t compacted = 0;
    for (size_t i = 0; i < count;) {
        uint32_t value = codepoints[i];
        int combining = (value >= 0x0300 && value <= 0x036f) ||
            (value >= 0x0483 && value <= 0x0489) ||
            (value >= 0x0610 && value <= 0x0615) ||
            (value >= 0x064b && value <= 0x065f) || value == 0x0670 ||
            (value >= 0x06d6 && value <= 0x06dc) ||
            (value >= 0x06df && value <= 0x06ed) || value == 0x0e31 ||
            (value >= 0x0e34 && value <= 0x0e3a) ||
            (value >= 0x0e47 && value <= 0x0e4e);
        if (combining) {
            size_t end = i + 1;
            while (end < count) {
                uint32_t next = codepoints[end];
                int next_combining = (next >= 0x0300 && next <= 0x036f) ||
                    (next >= 0x0483 && next <= 0x0489) ||
                    (next >= 0x0610 && next <= 0x0615) ||
                    (next >= 0x064b && next <= 0x065f) || next == 0x0670 ||
                    (next >= 0x06d6 && next <= 0x06dc) ||
                    (next >= 0x06df && next <= 0x06ed) || next == 0x0e31 ||
                    (next >= 0x0e34 && next <= 0x0e3a) ||
                    (next >= 0x0e47 && next <= 0x0e4e);
                if (!next_combining) break;
                end++;
            }
            if (end - i >= 3) { i = end; continue; }
        }
        if (value < 0x239b || value > 0x23b9) codepoints[compacted++] = value;
        i++;
    }

    size_t written = 0;
    for (size_t i = 0; i < compacted; i++) {
        uint32_t value = codepoints[i];
        if (value < 0x80) output[written++] = (char)value;
        else if (value < 0x800) {
            output[written++] = (char)(0xc0 | (value >> 6));
            output[written++] = (char)(0x80 | (value & 0x3f));
        } else if (value < 0x10000) {
            output[written++] = (char)(0xe0 | (value >> 12));
            output[written++] = (char)(0x80 | ((value >> 6) & 0x3f));
            output[written++] = (char)(0x80 | (value & 0x3f));
        } else {
            output[written++] = (char)(0xf0 | (value >> 18));
            output[written++] = (char)(0x80 | ((value >> 12) & 0x3f));
            output[written++] = (char)(0x80 | ((value >> 6) & 0x3f));
            output[written++] = (char)(0x80 | (value & 0x3f));
        }
    }
    output[written] = '\0';
}

static int display_name_equal(const char *left, const char *right) {
    if (left == NULL || right == NULL) return 0;
    while (*left && *right) {
        unsigned char a = (unsigned char)*left++;
        unsigned char b = (unsigned char)*right++;
        if (a >= 'A' && a <= 'Z') a = (unsigned char)(a + ('a' - 'A'));
        if (b >= 'A' && b <= 'Z') b = (unsigned char)(b + ('a' - 'A'));
        if (a != b) return 0;
    }
    return *left == *right;
}

static uint16_t lookup(
    const PokemonAdmissionUniverse *universe,
    PokemonAdmissionIdentityKind kind,
    const char *id
) {
    const PokemonAdmissionIdentitySpan *span = &universe->identities[kind];
    size_t lo = 0, hi = span->count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        int order = strcmp(id, span->values[mid].id);
        if (order == 0) return (uint16_t)(mid + 1);
        if (order < 0) hi = mid;
        else lo = mid + 1;
    }
    return 0;
}

static int runtime_matches(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime
) {
    if (runtime == NULL || runtime->rules == NULL || runtime->data == NULL ||
        runtime->runtime_format == NULL || runtime->policy == NULL ||
        runtime->manifest == NULL || runtime->manifest->id == NULL ||
        runtime->policy->manifest != runtime->manifest) return 0;
#define COMPONENT_MATCHES(component) \
    ((component)->plugin_fingerprint == runtime->plugin_fingerprint && \
     (component)->generation == runtime->generation && \
     (component)->capability_version == runtime->capability_version && \
     (component)->capabilities == runtime->capabilities)
    int coherent = COMPONENT_MATCHES(runtime->rules) &&
        COMPONENT_MATCHES(runtime->data) &&
        COMPONENT_MATCHES(runtime->runtime_format) &&
        COMPONENT_MATCHES(runtime->policy) &&
        COMPONENT_MATCHES(runtime->manifest);
#undef COMPONENT_MATCHES
    return coherent && bundle->runtime_plugin_fingerprint == runtime->plugin_fingerprint &&
        bundle->generation == runtime->generation &&
        strcmp(bundle->format_id, runtime->manifest->id) == 0;
}

static int valid_requirement(
    const PokemonAdmissionUniverse *universe,
    const PokemonAdmissionPredicateRequirement *required
) {
    if (!one_bit(required->predicate) ||
        !identity_kind_mask(required->identity_kind_mask)) return 0;
    for (int kind = 0; kind < POKEMON_ADMISSION_IDENTITY_KIND_COUNT; kind++) {
        if (!(required->identity_kind_mask & (UINT8_C(1) << kind))) continue;
        const PokemonAdmissionIdentitySpan *span = &universe->identities[kind];
        for (uint16_t i = 0; i < span->count; i++) {
            if (span->values[i].predicates & required->predicate) return 1;
        }
    }
    return 0;
}

int pokemon_admission_validate_bundle(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime
) {
    if (bundle == NULL || bundle->abi_version != POKEMON_ADMISSION_ABI_VERSION ||
        bundle->plugin_fingerprint == 0 || bundle->universe == NULL ||
        bundle->program == NULL || bundle->runtime_plugin_fingerprint == 0 ||
        bundle->generation == 0 || !canonical_id(bundle->format_id) ||
        bundle->format_policy == NULL ||
        !canonical_id(bundle->format_policy->format_id) ||
        strcmp(bundle->format_policy->format_id, bundle->format_id) != 0 ||
        bundle->format_policy->level_up_policy >
            POKEMON_ACQUISITION_LEVEL_UP_GEN3_POMEG ||
        (bundle->format_policy->level_up_policy ==
            POKEMON_ACQUISITION_LEVEL_UP_GEN3_POMEG &&
            bundle->format_policy->pomeg_minimum_level < 5) ||
        bundle->oracle_revision == NULL || strlen(bundle->oracle_revision) != 40 ||
        bundle->universe->plugin_fingerprint != bundle->plugin_fingerprint ||
        bundle->program->plugin_fingerprint != bundle->plugin_fingerprint ||
        bundle->program->rules == NULL || bundle->program->rule_count == 0 ||
        !runtime_matches(bundle, runtime) ||
        !pokemon_acquisition_validate(bundle->universe->acquisition,
            bundle->universe)) return 0;

    for (int kind = 0; kind < POKEMON_ADMISSION_IDENTITY_KIND_COUNT; kind++) {
        const PokemonAdmissionIdentitySpan *span = &bundle->universe->identities[kind];
        if (span->values == NULL || span->count == 0) return 0;
        for (uint16_t i = 0; i < span->count; i++) {
            const char *id = span->values[i].id;
            const uint8_t known_tags = POKEMON_ADMISSION_TAG_UBER |
                POKEMON_ADMISSION_TAG_UNOBTAINABLE |
                POKEMON_ADMISSION_TAG_NONEXISTENT;
            const uint8_t known_predicates = POKEMON_ADMISSION_PREDICATE_OHKO |
                POKEMON_ADMISSION_PREDICATE_GUARANTEED_ACCURACY_DROP |
                POKEMON_ADMISSION_PREDICATE_TRAPPING |
                POKEMON_ADMISSION_PREDICATE_BATON_PASS |
                POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE |
                POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE;
            if (!canonical_id(id) || (span->values[i].tags & (uint8_t)~known_tags) ||
                (span->values[i].predicates & (uint8_t)~known_predicates) ||
                (kind == POKEMON_ADMISSION_SPECIES && span->values[i].predicates != 0) ||
                (kind == POKEMON_ADMISSION_ITEM &&
                    (span->values[i].predicates & (uint8_t)~(
                        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE |
                        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE))) ||
                (kind == POKEMON_ADMISSION_ABILITY &&
                    (span->values[i].predicates & (uint8_t)~(
                        POKEMON_ADMISSION_PREDICATE_TRAPPING |
                        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE |
                        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE))) ||
                ((span->values[i].tags & POKEMON_ADMISSION_TAG_UNOBTAINABLE) &&
                    (span->values[i].tags & POKEMON_ADMISSION_TAG_NONEXISTENT)) ||
                (i && strcmp(span->values[i - 1].id, id) >= 0)) return 0;
        }
    }
    const PokemonAdmissionIdentitySpan *species_span =
        &bundle->universe->identities[POKEMON_ADMISSION_SPECIES];
    if (bundle->universe->species_metadata == NULL) return 0;
    for (uint16_t i = 0; i < species_span->count; i++) {
        const PokemonAdmissionSpeciesMetadata *metadata =
            &bundle->universe->species_metadata[i];
        if (metadata->display_name == NULL || metadata->display_name[0] == '\0' ||
            strlen(metadata->display_name) > POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES ||
            metadata->base_species_id == 0 ||
            metadata->base_species_id > species_span->count ||
            bundle->universe->species_metadata[metadata->base_species_id - 1]
                .base_species_id != metadata->base_species_id) return 0;
    }
    if ((bundle->universe->relation_count == 0) !=
        (bundle->universe->relations == NULL)) return 0;
    for (uint16_t relation_index = 0;
         relation_index < bundle->universe->relation_count; relation_index++) {
        const PokemonAdmissionAllowedRelation *relation =
            &bundle->universe->relations[relation_index];
        if (relation->owner_kind >= POKEMON_ADMISSION_IDENTITY_KIND_COUNT ||
            relation->member_kind >= POKEMON_ADMISSION_IDENTITY_KIND_COUNT ||
            relation->owner_kind == POKEMON_ADMISSION_MOVE ||
            relation->member_kind == POKEMON_ADMISSION_MOVE ||
            relation->owner_kind == relation->member_kind ||
            !canonical_id(relation->canonical_id) || relation->row_offsets == NULL ||
            relation->row_offset_count !=
                (uint16_t)(bundle->universe->identities[relation->owner_kind].count + 1) ||
            relation->row_offsets[0] != 0 ||
            relation->row_offsets[relation->row_offset_count - 1] != relation->member_count ||
            (relation->member_count != 0 && relation->members == NULL)) return 0;
        for (uint16_t prior = 0; prior < relation_index; prior++) {
            if (strcmp(bundle->universe->relations[prior].canonical_id,
                relation->canonical_id) == 0) return 0;
        }
        uint16_t member_limit = bundle->universe->identities[relation->member_kind].count;
        for (uint16_t row = 1; row < relation->row_offset_count; row++) {
            uint16_t begin = relation->row_offsets[row - 1];
            uint16_t end = relation->row_offsets[row];
            if (begin > end || end > relation->member_count) return 0;
            for (uint16_t member = begin; member < end; member++) {
                if (relation->members[member] == 0 || relation->members[member] > member_limit ||
                    (member > begin && relation->members[member - 1] >=
                        relation->members[member])) return 0;
            }
        }
    }
    int saw_species_rewrite_rule = 0;
    int saw_nickname_clause_rule = 0;
    int saw_unique_moves_rule = 0;
    int saw_obtainable_moves_rule = 0;
    int saw_set_fields_rule = 0;
    for (uint16_t i = 0; i < bundle->program->rule_count; i++) {
        const PokemonAdmissionRule *rule = &bundle->program->rules[i];
        if (!canonical_id(rule->source_rule_id) ||
            (rule->scope != POKEMON_ADMISSION_SCOPE_SET &&
                rule->scope != POKEMON_ADMISSION_SCOPE_TEAM)) return 0;
        if (rule->kind == POKEMON_ADMISSION_ATOMIC_BAN) {
            if (rule->scope != POKEMON_ADMISSION_SCOPE_SET) return 0;
            const PokemonAdmissionOperand *operand = &rule->value.atomic_ban;
            if (operand->kind >= POKEMON_ADMISSION_IDENTITY_KIND_COUNT ||
                !canonical_id(operand->canonical_id)) return 0;
            uint16_t resolved = lookup(bundle->universe, operand->kind, operand->canonical_id);
            if (operand->disposition == POKEMON_ADMISSION_OPERAND_MATCHABLE) {
                if (operand->identity_id == 0 || operand->identity_id != resolved) return 0;
            } else if (operand->disposition == POKEMON_ADMISSION_OPERAND_STATICALLY_UNMATCHABLE) {
                if (operand->identity_id != 0 || resolved != 0) return 0;
            } else {
                return 0;
            }
        } else if (rule->kind == POKEMON_ADMISSION_TAG_BAN) {
            if (rule->scope != POKEMON_ADMISSION_SCOPE_SET) return 0;
            const PokemonAdmissionTagBan *tag = &rule->value.tag_ban;
            if (tag->tag != POKEMON_ADMISSION_TAG_UBER &&
                tag->tag != POKEMON_ADMISSION_TAG_UNOBTAINABLE &&
                tag->tag != POKEMON_ADMISSION_TAG_NONEXISTENT) return 0;
            if (!identity_kind_mask(tag->identity_kind_mask) ||
                !canonical_id(tag->canonical_id)) return 0;
            if ((tag->tag == POKEMON_ADMISSION_TAG_UBER && strcmp(tag->canonical_id, "uber")) ||
                (tag->tag == POKEMON_ADMISSION_TAG_UNOBTAINABLE &&
                    strcmp(tag->canonical_id, "unobtainable")) ||
                (tag->tag == POKEMON_ADMISSION_TAG_NONEXISTENT &&
                    strcmp(tag->canonical_id, "nonexistent"))) return 0;
        } else if (rule->kind == POKEMON_ADMISSION_ALL_OF_BAN) {
            const PokemonAdmissionAllOfBan *all = &rule->value.all_of_ban;
            if (!canonical_id(all->canonical_id) || all->requirement_count == 0 ||
                all->requirement_count > 2) return 0;
            for (size_t unused = all->requirement_count; unused < 2; unused++) {
                if (all->requirements[unused].predicate != 0 ||
                    all->requirements[unused].identity_kind_mask != 0) return 0;
            }
            for (size_t requirement = 0; requirement < all->requirement_count; requirement++) {
                const PokemonAdmissionPredicateRequirement *required =
                    &all->requirements[requirement];
                if (!valid_requirement(bundle->universe, required)) return 0;
                for (size_t prior = 0; prior < requirement; prior++) {
                    const PokemonAdmissionPredicateRequirement *seen = &all->requirements[prior];
                    if (seen->predicate == required->predicate &&
                        seen->identity_kind_mask == required->identity_kind_mask) return 0;
                }
            }
        } else if (rule->kind == POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN) {
            const PokemonAdmissionAnchoredCardinalityBan *cardinality =
                &rule->value.anchored_cardinality_ban;
            if (rule->scope != POKEMON_ADMISSION_SCOPE_TEAM ||
                !canonical_id(cardinality->canonical_id) ||
                cardinality->max_sources_per_set == 0 ||
                cardinality->max_matching_sets == 0) return 0;
            const PokemonAdmissionPredicateRequirement requirements[] = {
                cardinality->anchor, cardinality->counted,
            };
            for (size_t requirement = 0; requirement < 2; requirement++) {
                const PokemonAdmissionPredicateRequirement *required = &requirements[requirement];
                if (!valid_requirement(bundle->universe, required)) return 0;
            }
            if (cardinality->anchor.predicate == cardinality->counted.predicate &&
                cardinality->anchor.identity_kind_mask ==
                    cardinality->counted.identity_kind_mask) return 0;
        } else if (rule->kind == POKEMON_ADMISSION_STAT_VECTOR_RULE) {
            const PokemonAdmissionStatVectorRule *stat = &rule->value.stat_vector_rule;
            if (rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                !canonical_id(stat->canonical_id) ||
                stat->component_min < 0 || stat->component_min > stat->component_max ||
                stat->reject_zero_above_level > runtime->manifest->max_level ||
                !runtime->manifest->ev_limit_enabled ||
                stat->expected_total_limit != runtime->manifest->ev_limit ||
                stat->expected_total_limit >
                    (uint32_t)POKEMON_ADMISSION_STAT_COUNT * (uint16_t)stat->component_max) return 0;
        } else if (rule->kind == POKEMON_ADMISSION_SPECIES_REWRITE_RULE) {
            const PokemonAdmissionSpeciesRewriteRule *rewrite_rule =
                &rule->value.species_rewrite_rule;
            uint16_t species_count =
                bundle->universe->identities[POKEMON_ADMISSION_SPECIES].count;
            uint16_t ability_count =
                bundle->universe->identities[POKEMON_ADMISSION_ABILITY].count;
            if (saw_species_rewrite_rule || rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                rewrite_rule->rewrites == NULL || rewrite_rule->rewrite_count == 0 ||
                !canonical_id(rewrite_rule->canonical_id)) return 0;
            saw_species_rewrite_rule = 1;
            for (uint16_t rewrite_index = 0;
                 rewrite_index < rewrite_rule->rewrite_count; rewrite_index++) {
                const PokemonAdmissionGuardedSpeciesRewrite *rewrite =
                    &rewrite_rule->rewrites[rewrite_index];
                if (rewrite->input_species_id == 0 ||
                    rewrite->input_species_id > species_count ||
                    rewrite->output_species_id == 0 ||
                    rewrite->output_species_id > species_count ||
                    rewrite->required_ability_id == 0 ||
                    rewrite->required_ability_id > ability_count ||
                    rewrite->input_species_id == rewrite->output_species_id) return 0;
                for (uint16_t other_index = 0;
                     other_index < rewrite_rule->rewrite_count; other_index++) {
                    const PokemonAdmissionGuardedSpeciesRewrite *candidate =
                        &rewrite_rule->rewrites[other_index];
                    if (other_index != rewrite_index &&
                        candidate->input_species_id == rewrite->input_species_id) return 0;
                    if (candidate->input_species_id == rewrite->output_species_id) return 0;
                }
            }
        } else if (rule->kind == POKEMON_ADMISSION_ALLOWED_RELATION_RULE) {
            if (rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                rule->value.allowed_relation_rule.relation_id == 0 ||
                rule->value.allowed_relation_rule.relation_id >
                    bundle->universe->relation_count) return 0;
        } else if (rule->kind == POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE) {
            if (saw_nickname_clause_rule || rule->scope != POKEMON_ADMISSION_SCOPE_TEAM ||
                strcmp(rule->source_rule_id, "nicknameclause") != 0) return 0;
            saw_nickname_clause_rule = 1;
        } else if (rule->kind == POKEMON_ADMISSION_UNIQUE_MOVES_RULE) {
            if (saw_unique_moves_rule || rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                strcmp(rule->source_rule_id, "obtainablemisc") != 0) return 0;
            saw_unique_moves_rule = 1;
        } else if (rule->kind == POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE) {
            if (saw_obtainable_moves_rule || rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                strcmp(rule->source_rule_id, "obtainablemoves") != 0) return 0;
            saw_obtainable_moves_rule = 1;
        } else if (rule->kind == POKEMON_ADMISSION_SET_FIELDS_RULE) {
            if (saw_set_fields_rule || rule->scope != POKEMON_ADMISSION_SCOPE_SET ||
                strcmp(rule->source_rule_id, "obtainablemisc") != 0) return 0;
            saw_set_fields_rule = 1;
        } else {
            return 0;
        }
    }
    return saw_nickname_clause_rule && saw_unique_moves_rule &&
        saw_obtainable_moves_rule && saw_set_fields_rule;
}

typedef struct {
    int found;
    PokemonAdmissionIdentityKind kind;
    uint8_t input_index;
} PokemonAdmissionPredicateMatch;

static PokemonAdmissionPredicateMatch find_predicate(
    const PokemonAdmissionBundle *bundle,
    const PokemonAdmissionSetInput *input,
    uint16_t species,
    uint16_t ability,
    uint16_t item,
    const uint16_t moves[POKEMON_ADMISSION_MAX_MOVES],
    PokemonAdmissionPredicate predicate,
    uint8_t kind_mask
) {
#define IDENTITY_MATCHES(kind, identity) \
    ((kind_mask & (UINT8_C(1) << (kind))) && (identity) && \
     (bundle->universe->identities[(kind)].values[(identity) - 1].predicates & predicate))
    if (IDENTITY_MATCHES(POKEMON_ADMISSION_SPECIES, species)) {
        PokemonAdmissionPredicateMatch match = {1, POKEMON_ADMISSION_SPECIES, 0};
        return match;
    }
    for (uint8_t i = 0; i < input->move_count; i++) {
        if (IDENTITY_MATCHES(POKEMON_ADMISSION_MOVE, moves[i])) {
            PokemonAdmissionPredicateMatch match = {1, POKEMON_ADMISSION_MOVE, i};
            return match;
        }
    }
    if (IDENTITY_MATCHES(POKEMON_ADMISSION_ABILITY, ability)) {
        PokemonAdmissionPredicateMatch match = {1, POKEMON_ADMISSION_ABILITY, 0};
        return match;
    }
    if (IDENTITY_MATCHES(POKEMON_ADMISSION_ITEM, item)) {
        PokemonAdmissionPredicateMatch match = {1, POKEMON_ADMISSION_ITEM, 0};
        return match;
    }
#undef IDENTITY_MATCHES
    PokemonAdmissionPredicateMatch none = {0, POKEMON_ADMISSION_SPECIES, 0};
    return none;
}

static size_t count_normalized_predicate(
    const PokemonAdmissionBundle *bundle,
    const PokemonAdmissionNormalizedSet *set,
    PokemonAdmissionPredicate predicate,
    uint8_t kind_mask,
    PokemonAdmissionPredicateMatch *last_match
) {
    size_t count = 0;
#define COUNT_IDENTITY(identity_kind, id, index) do { \
    if ((kind_mask & (UINT8_C(1) << (identity_kind))) && (id) != NULL && (id)[0] != '\0') { \
        uint16_t identity = lookup(bundle->universe, (identity_kind), (id)); \
        if (identity && (bundle->universe->identities[(identity_kind)].values[identity - 1].predicates & predicate)) { \
            count++; \
            if (last_match != NULL) { \
                last_match->found = 1; \
                last_match->kind = (identity_kind); \
                last_match->input_index = (index); \
            } \
        } \
    } \
} while (0)
    COUNT_IDENTITY(POKEMON_ADMISSION_SPECIES, set->species_id, 0);
    for (uint8_t i = 0; i < set->move_count; i++) {
        COUNT_IDENTITY(POKEMON_ADMISSION_MOVE, set->move_ids[i], i);
    }
    COUNT_IDENTITY(POKEMON_ADMISSION_ABILITY, set->ability_id, 0);
    COUNT_IDENTITY(POKEMON_ADMISSION_ITEM, set->item_id, 0);
#undef COUNT_IDENTITY
    return count;
}

static PokemonAdmissionDecision decision(
    PokemonAdmissionResult result,
    PokemonAdmissionIdentityKind kind,
    uint8_t input_index,
    uint16_t rule_index
) {
    PokemonAdmissionDecision value = {result, 0, kind, input_index, rule_index};
    return value;
}

static uint16_t scalar_identity(
    PokemonAdmissionIdentityKind kind,
    uint16_t species,
    uint16_t ability,
    uint16_t item
) {
    if (kind == POKEMON_ADMISSION_SPECIES) return species;
    if (kind == POKEMON_ADMISSION_ABILITY) return ability;
    if (kind == POKEMON_ADMISSION_ITEM) return item;
    return 0;
}

PokemonAdmissionDecision pokemon_admission_check_set_normalized(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionSetInput *input,
    PokemonAdmissionNormalizedSet *output
) {
    if (!pokemon_admission_validate_bundle(bundle, runtime)) {
        return decision(POKEMON_ADMISSION_RESULT_INVALID_BUNDLE, POKEMON_ADMISSION_SPECIES, 0, 0);
    }
    if (input == NULL || !canonical_id(input->species_id) ||
        !canonical_id(input->ability_id) || input->move_count == 0 ||
        input->move_count > POKEMON_ADMISSION_MAX_MOVES ||
        input->level < runtime->manifest->min_level ||
        input->level > runtime->manifest->max_level || input->has_evs > 1 ||
        input->gender > POKEMON_ACQUISITION_GENDER_NEUTER || input->shiny > 1 ||
        input->has_ivs > 1 ||
        (input->item_id != NULL && input->item_id[0] != '\0' && !canonical_id(input->item_id)) ||
        (input->nature_id != NULL && input->nature_id[0] != '\0' &&
            (!canonical_id(input->nature_id) ||
                strlen(input->nature_id) > POKEMON_ADMISSION_MAX_CANONICAL_FIELD_BYTES)) ||
        (input->hidden_power_type_id != NULL && input->hidden_power_type_id[0] != '\0' &&
            (!canonical_id(input->hidden_power_type_id) || strlen(input->hidden_power_type_id) >
                POKEMON_ADMISSION_MAX_CANONICAL_FIELD_BYTES)) ||
        (input->nickname != NULL &&
            strlen(input->nickname) > POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES)) {
        return decision(POKEMON_ADMISSION_RESULT_MALFORMED, POKEMON_ADMISSION_SPECIES, 0, 0);
    }
    for (uint8_t i = 0; i < input->move_count; i++) {
        if (!canonical_id(input->move_ids[i])) {
            return decision(POKEMON_ADMISSION_RESULT_MALFORMED, POKEMON_ADMISSION_MOVE, i, 0);
        }
    }
    for (uint8_t i = input->move_count; i < POKEMON_ADMISSION_MAX_MOVES; i++) {
        if (input->move_ids[i] != NULL) {
            return decision(POKEMON_ADMISSION_RESULT_MALFORMED, POKEMON_ADMISSION_MOVE, i, 0);
        }
    }
    if (!input->has_evs) {
        for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
            if (input->evs[stat] != 0) {
                return decision(POKEMON_ADMISSION_RESULT_MALFORMED,
                    POKEMON_ADMISSION_SPECIES, (uint8_t)stat, 0);
            }
        }
    }
    for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
        if ((input->has_ivs && input->ivs[stat] > 31) ||
            (!input->has_ivs && input->ivs[stat] != 0)) {
            return decision(POKEMON_ADMISSION_RESULT_MALFORMED,
                POKEMON_ADMISSION_SPECIES, (uint8_t)stat, 0);
        }
    }

    uint16_t species = lookup(bundle->universe, POKEMON_ADMISSION_SPECIES, input->species_id);
    uint16_t ability = lookup(bundle->universe, POKEMON_ADMISSION_ABILITY, input->ability_id);
    uint16_t item = 0;
    if (input->item_id != NULL && input->item_id[0] != '\0') {
        item = lookup(bundle->universe, POKEMON_ADMISSION_ITEM, input->item_id);
    }
    if (!species) return decision(POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY, POKEMON_ADMISSION_SPECIES, 0, 0);
    if (!ability) return decision(POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY, POKEMON_ADMISSION_ABILITY, 0, 0);
    if (input->item_id != NULL && input->item_id[0] != '\0' && !item) {
        return decision(POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY, POKEMON_ADMISSION_ITEM, 0, 0);
    }
    uint16_t moves[POKEMON_ADMISSION_MAX_MOVES] = {0};
    for (uint8_t i = 0; i < input->move_count; i++) {
        moves[i] = lookup(bundle->universe, POKEMON_ADMISSION_MOVE, input->move_ids[i]);
        if (!moves[i]) return decision(POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY, POKEMON_ADMISSION_MOVE, i, 0);
    }

    for (uint16_t i = 0; i < bundle->program->rule_count; i++) {
        const PokemonAdmissionRule *rule = &bundle->program->rules[i];
        if (rule->kind != POKEMON_ADMISSION_SPECIES_REWRITE_RULE) continue;
        const PokemonAdmissionSpeciesRewriteRule *rewrite_rule =
            &rule->value.species_rewrite_rule;
        for (uint16_t rewrite_index = 0;
             rewrite_index < rewrite_rule->rewrite_count; rewrite_index++) {
            const PokemonAdmissionGuardedSpeciesRewrite *rewrite =
                &rewrite_rule->rewrites[rewrite_index];
            if (rewrite->input_species_id != species) continue;
            if (rewrite->required_ability_id != ability) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_ABILITY, 0, (uint16_t)(i + 1));
            }
            species = rewrite->output_species_id;
        }
    }

    uint16_t nickname_rule_index = 0;
    for (uint16_t i = 0; i < bundle->program->rule_count; i++) {
        if (bundle->program->rules[i].kind == POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE) {
            nickname_rule_index = (uint16_t)(i + 1);
            break;
        }
    }
    const PokemonAdmissionSpeciesMetadata *species_metadata =
        &bundle->universe->species_metadata[species - 1];
    const PokemonAdmissionSpeciesMetadata *base_metadata =
        &bundle->universe->species_metadata[species_metadata->base_species_id - 1];
    char normalized_nickname[POKEMON_ADMISSION_MAX_NICKNAME_UTF8_BYTES + 1];
    const char *raw_nickname = input->nickname != NULL ? input->nickname : "";
    if (raw_nickname[0] == '\0') {
        strcpy(normalized_nickname, base_metadata->display_name);
    } else {
        size_t nickname_units = 0;
        int nickname_shape = nickname_utf8_units(raw_nickname, &nickname_units);
        if (nickname_shape < 0) {
            return decision(POKEMON_ADMISSION_RESULT_MALFORMED,
                POKEMON_ADMISSION_SPECIES, 0, 0);
        }
        if (nickname_shape == 0) {
            if (strcmp(raw_nickname, species_metadata->display_name) != 0) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_SPECIES, 0, nickname_rule_index);
            }
            strcpy(normalized_nickname, base_metadata->display_name);
        } else {
            normalize_nickname(raw_nickname, normalized_nickname);
            if (normalized_nickname[0] == '\0') {
                strcpy(normalized_nickname, base_metadata->display_name);
            }
        }
    }
    for (uint16_t candidate = 0;
         candidate < bundle->universe->identities[POKEMON_ADMISSION_SPECIES].count;
         candidate++) {
        const PokemonAdmissionSpeciesMetadata *named =
            &bundle->universe->species_metadata[candidate];
        if (!display_name_equal(named->display_name, normalized_nickname)) continue;
        if (named->base_species_id == species_metadata->base_species_id) {
            strcpy(normalized_nickname, base_metadata->display_name);
        } else {
            return decision(POKEMON_ADMISSION_RESULT_BANNED,
                POKEMON_ADMISSION_SPECIES, 0, nickname_rule_index);
        }
        break;
    }

    uint16_t set_fields_rule_index = 0;
    for (uint16_t i = 0; i < bundle->program->rule_count; i++) {
        if (bundle->program->rules[i].kind == POKEMON_ADMISSION_SET_FIELDS_RULE) {
            set_fields_rule_index = (uint16_t)(i + 1);
            break;
        }
    }
    const PokemonAcquisitionData *acquisition_data = bundle->universe->acquisition;
    const char *nature_id = input->nature_id && input->nature_id[0] ?
        input->nature_id : "serious";
    int known_nature = 0;
    for (uint8_t i = 0; i < acquisition_data->nature_count; i++) {
        known_nature |= strcmp(nature_id, acquisition_data->nature_ids[i]) == 0;
    }
    if (!known_nature) return decision(POKEMON_ADMISSION_RESULT_BANNED,
        POKEMON_ADMISSION_SPECIES, 0, set_fields_rule_index);
    uint8_t normalized_ivs[POKEMON_ADMISSION_STAT_COUNT];
    int all_max_ivs = 1;
    for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
        normalized_ivs[stat] = input->has_ivs ? input->ivs[stat] : 31;
        all_max_ivs &= normalized_ivs[stat] == 31;
    }
    uint8_t hidden_power_type = 0;
    if (input->hidden_power_type_id && input->hidden_power_type_id[0]) {
        for (uint8_t type = 0; type < acquisition_data->hidden_power_type_count; type++) {
            if (strcmp(input->hidden_power_type_id,
                    acquisition_data->hidden_power_type_ids[type]) == 0) {
                hidden_power_type = (uint8_t)(type + 1);
                break;
            }
        }
        if (!hidden_power_type) return decision(POKEMON_ADMISSION_RESULT_BANNED,
            POKEMON_ADMISSION_SPECIES, 0, set_fields_rule_index);
    }
    int has_hidden_power_move = 0;
    for (uint8_t move = 0; move < input->move_count; move++) {
        uint8_t move_type = acquisition_data->move_hidden_power_type[moves[move] - 1];
        has_hidden_power_move |= acquisition_data->move_source_ids[moves[move] - 1] ==
            acquisition_data->hidden_power_move_id;
        if (move_type && hidden_power_type && move_type != hidden_power_type) {
            return decision(POKEMON_ADMISSION_RESULT_BANNED,
                POKEMON_ADMISSION_MOVE, move, set_fields_rule_index);
        }
        if (move_type && !hidden_power_type) hidden_power_type = move_type;
    }
    if (hidden_power_type && all_max_ivs) {
        memcpy(normalized_ivs, acquisition_data->hidden_power_ivs[hidden_power_type - 1],
            sizeof normalized_ivs);
    }
    if (!hidden_power_type && has_hidden_power_move) {
        hidden_power_type = pokemon_acquisition_hidden_power_type(
            acquisition_data, normalized_ivs);
    }
    if (hidden_power_type && pokemon_acquisition_hidden_power_type(
            acquisition_data, normalized_ivs) != hidden_power_type) {
        return decision(POKEMON_ADMISSION_RESULT_BANNED,
            POKEMON_ADMISSION_SPECIES, 0, set_fields_rule_index);
    }
    PokemonAcquisitionGender normalized_gender = input->gender;
    if (normalized_gender == POKEMON_ACQUISITION_GENDER_NEUTER) {
        normalized_gender = POKEMON_ACQUISITION_GENDER_UNSPECIFIED;
    }
    if (acquisition_data->species[species - 1].fixed_gender) {
        normalized_gender = (PokemonAcquisitionGender)
            acquisition_data->species[species - 1].fixed_gender;
    }
    PokemonAdmissionSetInput normalized_input = *input;
    normalized_input.gender = normalized_gender;
    normalized_input.nature_id = nature_id;
    normalized_input.has_ivs = 1;
    memcpy(normalized_input.ivs, normalized_ivs, sizeof normalized_ivs);
    normalized_input.hidden_power_type_id = hidden_power_type ?
        acquisition_data->hidden_power_type_ids[hidden_power_type - 1] : NULL;

    uint16_t acquisition_event_id = 0;
    for (uint16_t i = 0; i < bundle->program->rule_count; i++) {
        const PokemonAdmissionRule *rule = &bundle->program->rules[i];
        if (rule->scope != POKEMON_ADMISSION_SCOPE_SET) continue;
        if (rule->kind == POKEMON_ADMISSION_SPECIES_REWRITE_RULE) continue;
        if (rule->kind == POKEMON_ADMISSION_TAG_BAN) {
            const PokemonAdmissionTagBan *tag = &rule->value.tag_ban;
#define TAG_MATCHES(kind, identity) \
    ((tag->identity_kind_mask & (UINT8_C(1) << (kind))) && \
     (bundle->universe->identities[(kind)].values[(identity) - 1].tags & tag->tag))
            if (TAG_MATCHES(POKEMON_ADMISSION_SPECIES, species)) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_SPECIES, 0, (uint16_t)(i + 1));
            }
            if (TAG_MATCHES(POKEMON_ADMISSION_ABILITY, ability)) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_ABILITY, 0, (uint16_t)(i + 1));
            }
            if (item && TAG_MATCHES(POKEMON_ADMISSION_ITEM, item)) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_ITEM, 0, (uint16_t)(i + 1));
            }
            for (uint8_t j = 0; j < input->move_count; j++) {
                if (TAG_MATCHES(POKEMON_ADMISSION_MOVE, moves[j])) {
                    return decision(POKEMON_ADMISSION_RESULT_BANNED,
                        POKEMON_ADMISSION_MOVE, j, (uint16_t)(i + 1));
                }
            }
#undef TAG_MATCHES
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_ALL_OF_BAN) {
            const PokemonAdmissionAllOfBan *all = &rule->value.all_of_ban;
            PokemonAdmissionPredicateMatch matches[2];
            int complete = 1;
            for (size_t requirement = 0; requirement < all->requirement_count; requirement++) {
                matches[requirement] = find_predicate(
                    bundle, input, species, ability, item, moves,
                    all->requirements[requirement].predicate,
                    all->requirements[requirement].identity_kind_mask
                );
                complete &= matches[requirement].found;
            }
            if (complete) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    matches[0].kind, matches[0].input_index, (uint16_t)(i + 1));
            }
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_STAT_VECTOR_RULE) {
            const PokemonAdmissionStatVectorRule *stat_rule = &rule->value.stat_vector_rule;
            uint32_t total = 0;
            for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
                int16_t value = input->has_evs ? input->evs[stat] : 0;
                if (value < stat_rule->component_min || value > stat_rule->component_max) {
                    return decision(POKEMON_ADMISSION_RESULT_BANNED,
                        POKEMON_ADMISSION_SPECIES, (uint8_t)stat, (uint16_t)(i + 1));
                }
                total += (uint16_t)value;
            }
            if ((input->level > stat_rule->reject_zero_above_level && total == 0) ||
                total > runtime->manifest->ev_limit) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    POKEMON_ADMISSION_SPECIES, 0, (uint16_t)(i + 1));
            }
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_ALLOWED_RELATION_RULE) {
            const PokemonAdmissionAllowedRelation *relation = &bundle->universe->relations[
                rule->value.allowed_relation_rule.relation_id - 1];
            uint16_t owner = scalar_identity(
                relation->owner_kind, species, ability, item);
            uint16_t member = scalar_identity(
                relation->member_kind, species, ability, item);
            int allowed = 0;
            if (owner != 0 && member != 0) {
                uint16_t begin = relation->row_offsets[owner - 1];
                uint16_t end = relation->row_offsets[owner];
                for (uint16_t relation_member = begin; relation_member < end;
                     relation_member++) {
                    if (relation->members[relation_member] == member) {
                        allowed = 1;
                        break;
                    }
                }
            }
            if (!allowed) return decision(POKEMON_ADMISSION_RESULT_BANNED,
                relation->member_kind, 0, (uint16_t)(i + 1));
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_UNIQUE_MOVES_RULE) {
            for (uint8_t move = 0; move < input->move_count; move++) {
                for (uint8_t prior = 0; prior < move; prior++) {
                    if (moves[move] == moves[prior]) {
                        return decision(POKEMON_ADMISSION_RESULT_BANNED,
                            POKEMON_ADMISSION_MOVE, move, (uint16_t)(i + 1));
                    }
                }
            }
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE) {
            PokemonAcquisitionDecision acquisition = pokemon_acquisition_check(
                bundle->universe->acquisition, bundle->universe,
                bundle->format_policy,
                species, moves, &normalized_input);
            if (!acquisition.obtainable) {
                return decision(POKEMON_ADMISSION_RESULT_BANNED,
                    acquisition.set_field_failure ? POKEMON_ADMISSION_SPECIES : POKEMON_ADMISSION_MOVE,
                    acquisition.set_field_failure ? 0 : acquisition.failing_move_index,
                    acquisition.set_field_failure ? set_fields_rule_index : (uint16_t)(i + 1));
            }
            acquisition_event_id = acquisition.event_id;
            continue;
        }
        if (rule->kind == POKEMON_ADMISSION_SET_FIELDS_RULE) continue;
        const PokemonAdmissionOperand *operand = &rule->value.atomic_ban;
        if (operand->disposition != POKEMON_ADMISSION_OPERAND_MATCHABLE) continue;
        int matches = 0;
        if (operand->kind == POKEMON_ADMISSION_SPECIES) matches = species == operand->identity_id;
        else if (operand->kind == POKEMON_ADMISSION_ABILITY) matches = ability == operand->identity_id;
        else if (operand->kind == POKEMON_ADMISSION_ITEM) matches = item == operand->identity_id;
        else for (uint8_t j = 0; j < input->move_count; j++) {
            if (moves[j] == operand->identity_id) {
                matches = 1;
                return decision(POKEMON_ADMISSION_RESULT_BANNED, operand->kind, j, (uint16_t)(i + 1));
            }
        }
        if (matches) return decision(POKEMON_ADMISSION_RESULT_BANNED, operand->kind, 0, (uint16_t)(i + 1));
    }
    if (output != NULL) {
        PokemonAdmissionNormalizedSet normalized = {
            .species_id = bundle->universe->identities[POKEMON_ADMISSION_SPECIES]
                .values[species - 1].id,
            .ability_id = bundle->universe->identities[POKEMON_ADMISSION_ABILITY]
                .values[ability - 1].id,
            .item_id = item ? bundle->universe->identities[POKEMON_ADMISSION_ITEM]
                .values[item - 1].id : "",
            .move_count = input->move_count,
            .level = input->level,
        };
        strcpy(normalized.nickname, normalized_nickname);
        normalized.gender = normalized_gender;
        if (acquisition_event_id) {
            const PokemonAcquisitionEvent *event =
                &acquisition_data->events[acquisition_event_id - 1];
            if (event->gender) normalized.gender = (PokemonAcquisitionGender)event->gender;
        }
        strcpy(normalized.nature_id, nature_id);
        normalized.shiny = input->shiny;
        memcpy(normalized.ivs, normalized_ivs, sizeof normalized.ivs);
        if (hidden_power_type) strcpy(normalized.hidden_power_type_id,
            acquisition_data->hidden_power_type_ids[hidden_power_type - 1]);
        for (uint8_t i = 0; i < input->move_count; i++) {
            normalized.move_ids[i] = bundle->universe->identities[POKEMON_ADMISSION_MOVE]
                .values[moves[i] - 1].id;
        }
        for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
            normalized.evs[stat] = input->has_evs ? input->evs[stat] : 0;
        }
        *output = normalized;
    }
    return decision(POKEMON_ADMISSION_RESULT_INCOMPLETE, POKEMON_ADMISSION_SPECIES, 0, 0);
}

PokemonAdmissionDecision pokemon_admission_check_set(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionSetInput *input
) {
    return pokemon_admission_check_set_normalized(bundle, runtime, input, NULL);
}

PokemonAdmissionDecision pokemon_admission_check_team_normalized(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionTeamInput *input,
    PokemonAdmissionNormalizedTeam *output
) {
    if (!pokemon_admission_validate_bundle(bundle, runtime)) {
        return decision(POKEMON_ADMISSION_RESULT_INVALID_BUNDLE,
            POKEMON_ADMISSION_SPECIES, 0, 0);
    }
    if (input == NULL || input->set_count == 0 ||
        input->set_count > POKEMON_ADMISSION_MAX_TEAM_SIZE) {
        return decision(POKEMON_ADMISSION_RESULT_MALFORMED,
            POKEMON_ADMISSION_SPECIES, 0, 0);
    }
    PokemonAdmissionNormalizedTeam normalized = {.set_count = input->set_count};
    for (uint8_t set_index = 0; set_index < input->set_count; set_index++) {
        PokemonAdmissionDecision set_decision = pokemon_admission_check_set_normalized(
            bundle, runtime, &input->sets[set_index], &normalized.sets[set_index]
        );
        set_decision.team_index = set_index;
        if (set_decision.result != POKEMON_ADMISSION_RESULT_INCOMPLETE) return set_decision;
    }

    for (uint16_t rule_index = 0; rule_index < bundle->program->rule_count; rule_index++) {
        const PokemonAdmissionRule *rule = &bundle->program->rules[rule_index];
        if (rule->scope != POKEMON_ADMISSION_SCOPE_TEAM) continue;
        if (rule->kind == POKEMON_ADMISSION_ALL_OF_BAN) {
            const PokemonAdmissionAllOfBan *all = &rule->value.all_of_ban;
            for (uint8_t set_index = 0; set_index < input->set_count; set_index++) {
                PokemonAdmissionPredicateMatch first = {0, POKEMON_ADMISSION_SPECIES, 0};
                int complete = 1;
                for (size_t requirement = 0; requirement < all->requirement_count; requirement++) {
                    PokemonAdmissionPredicateMatch match = {0, POKEMON_ADMISSION_SPECIES, 0};
                    complete &= count_normalized_predicate(
                        bundle, &normalized.sets[set_index],
                        all->requirements[requirement].predicate,
                        all->requirements[requirement].identity_kind_mask, &match
                    ) > 0;
                    if (requirement == 0) first = match;
                }
                if (complete) {
                    PokemonAdmissionDecision result = decision(
                        POKEMON_ADMISSION_RESULT_BANNED, first.kind, first.input_index,
                        (uint16_t)(rule_index + 1)
                    );
                    result.team_index = set_index;
                    return result;
                }
            }
        } else if (rule->kind == POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN) {
            const PokemonAdmissionAnchoredCardinalityBan *cardinality =
                &rule->value.anchored_cardinality_ban;
            size_t matching_sets = 0;
            for (uint8_t set_index = 0; set_index < input->set_count; set_index++) {
                const PokemonAdmissionNormalizedSet *set = &normalized.sets[set_index];
                if (count_normalized_predicate(bundle, set, cardinality->anchor.predicate,
                    cardinality->anchor.identity_kind_mask, NULL) == 0) continue;
                PokemonAdmissionPredicateMatch source = {0, POKEMON_ADMISSION_SPECIES, 0};
                size_t source_count = count_normalized_predicate(
                    bundle, set, cardinality->counted.predicate,
                    cardinality->counted.identity_kind_mask, &source
                );
                if (source_count > cardinality->max_sources_per_set) {
                    PokemonAdmissionDecision result = decision(
                        POKEMON_ADMISSION_RESULT_BANNED, source.kind, source.input_index,
                        (uint16_t)(rule_index + 1)
                    );
                    result.team_index = set_index;
                    return result;
                }
                if (source_count == cardinality->max_sources_per_set) matching_sets++;
                if (matching_sets > cardinality->max_matching_sets) {
                    PokemonAdmissionDecision result = decision(
                        POKEMON_ADMISSION_RESULT_BANNED, source.kind, source.input_index,
                        (uint16_t)(rule_index + 1)
                    );
                    result.team_index = set_index;
                    return result;
                }
            }
        } else if (rule->kind == POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE) {
            for (uint8_t set_index = 0; set_index < input->set_count; set_index++) {
                const PokemonAdmissionNormalizedSet *set = &normalized.sets[set_index];
                uint16_t species = lookup(bundle->universe,
                    POKEMON_ADMISSION_SPECIES, set->species_id);
                const PokemonAdmissionSpeciesMetadata *metadata =
                    &bundle->universe->species_metadata[species - 1];
                const char *base_name = bundle->universe->species_metadata[
                    metadata->base_species_id - 1].display_name;
                if (strcmp(set->nickname, base_name) == 0) continue;
                for (uint8_t prior = 0; prior < set_index; prior++) {
                    const PokemonAdmissionNormalizedSet *seen = &normalized.sets[prior];
                    uint16_t seen_species = lookup(bundle->universe,
                        POKEMON_ADMISSION_SPECIES, seen->species_id);
                    const PokemonAdmissionSpeciesMetadata *seen_metadata =
                        &bundle->universe->species_metadata[seen_species - 1];
                    const char *seen_base = bundle->universe->species_metadata[
                        seen_metadata->base_species_id - 1].display_name;
                    if (strcmp(seen->nickname, seen_base) != 0 &&
                        strcmp(seen->nickname, set->nickname) == 0) {
                        PokemonAdmissionDecision result = decision(
                            POKEMON_ADMISSION_RESULT_BANNED,
                            POKEMON_ADMISSION_SPECIES, 0,
                            (uint16_t)(rule_index + 1));
                        result.team_index = set_index;
                        return result;
                    }
                }
            }
        }
    }
    if (output != NULL) *output = normalized;
    return decision(POKEMON_ADMISSION_RESULT_INCOMPLETE, POKEMON_ADMISSION_SPECIES, 0, 0);
}

PokemonAdmissionDecision pokemon_admission_check_team(
    const PokemonAdmissionBundle *bundle,
    const PokemonResolvedBundle *runtime,
    const PokemonAdmissionTeamInput *input
) {
    return pokemon_admission_check_team_normalized(bundle, runtime, input, NULL);
}
