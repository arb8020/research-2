#include "../../native/gen3_admission_data.h"
#include "../../native/singles2.h"

#include <stdio.h>
#include <string.h>

#include "cases.generated.h"

static const char *kind_name(PokemonAdmissionIdentityKind kind) {
    static const char *names[] = {"species", "move", "ability", "item"};
    return kind < POKEMON_ADMISSION_IDENTITY_KIND_COUNT ? names[kind] : "invalid";
}

int main(void) {
    for (size_t i = 0; i < POKEMON_ADMISSION_CASE_COUNT; i++) {
        const PokemonAdmissionCase *test_case = &POKEMON_ADMISSION_CASES[i];
        PokemonAdmissionTeamInput team = {.set_count = test_case->member_count};
        for (uint8_t member = 0; member < team.set_count; member++) {
            const PokemonAdmissionCaseMember *source = &test_case->members[member];
            PokemonAdmissionSetInput *input = &team.sets[member];
            input->species_id = source->species_id;
            input->ability_id = source->ability_id;
            input->item_id = source->item_id;
            input->move_count = source->move_count;
            input->level = source->level;
            input->has_evs = source->has_evs;
            input->nickname = source->name;
            input->gender = source->gender;
            input->nature_id = source->nature_id;
            input->shiny = source->shiny;
            input->has_ivs = source->has_ivs;
            memcpy(input->ivs, source->ivs, sizeof input->ivs);
            input->hidden_power_type_id = source->hidden_power_type_id;
            for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
                input->evs[stat] = source->evs[stat];
            }
            for (uint8_t move = 0; move < input->move_count; move++) {
                input->move_ids[move] = source->move_ids[move];
            }
        }
        PokemonAdmissionNormalizedTeam normalized = {0};
        PokemonAdmissionDecision decision;
        const PokemonAdmissionBundle *admission =
            test_case->format == POKEMON_ADMISSION_FORMAT_GEN3OU_POMEG ?
                &POKEMON_GEN3_OU_POMEG_ADMISSION : &POKEMON_GEN3_OU_ADMISSION;
        const PokemonResolvedBundle *runtime =
            test_case->format == POKEMON_ADMISSION_FORMAT_GEN3OU_POMEG ?
                &POKEMON_GEN3_OU_POMEG_BUNDLE : &POKEMON_GEN3_OU_BUNDLE;
        if (test_case->scope == POKEMON_ADMISSION_CASE_SET) {
            normalized.set_count = 1;
            decision = pokemon_admission_check_set_normalized(
                admission, runtime,
                &team.sets[0], &normalized.sets[0]);
        } else {
            decision = pokemon_admission_check_team_normalized(
                admission, runtime, &team, &normalized);
        }
        if (decision.result == POKEMON_ADMISSION_RESULT_BANNED) {
            if (decision.rule_index == 0 ||
                decision.rule_index > admission->program->rule_count) return 2;
            const PokemonAdmissionRule *matched =
                &admission->program->rules[decision.rule_index - 1];
            char rule[96];
            int length;
            if (matched->kind == POKEMON_ADMISSION_ATOMIC_BAN) {
                const PokemonAdmissionOperand *operand = &matched->value.atomic_ban;
                length = snprintf(rule, sizeof rule, "-%s:%s",
                    kind_name(operand->kind), operand->canonical_id);
            } else if (matched->kind == POKEMON_ADMISSION_ALL_OF_BAN) {
                length = snprintf(rule, sizeof rule, "%s",
                    matched->value.all_of_ban.canonical_id);
            } else if (matched->kind == POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN) {
                length = snprintf(rule, sizeof rule, "%s",
                    matched->value.anchored_cardinality_ban.canonical_id);
            } else if (matched->kind == POKEMON_ADMISSION_STAT_VECTOR_RULE) {
                length = snprintf(rule, sizeof rule, "%s",
                    matched->value.stat_vector_rule.canonical_id);
            } else if (matched->kind == POKEMON_ADMISSION_ALLOWED_RELATION_RULE) {
                length = snprintf(rule, sizeof rule, "%s", matched->source_rule_id);
            } else if (matched->kind == POKEMON_ADMISSION_SPECIES_REWRITE_RULE) {
                length = snprintf(rule, sizeof rule, "%s",
                    matched->value.species_rewrite_rule.canonical_id);
            } else if (matched->kind == POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE) {
                length = snprintf(rule, sizeof rule, "%s", matched->source_rule_id);
            } else if (matched->kind == POKEMON_ADMISSION_UNIQUE_MOVES_RULE) {
                length = snprintf(rule, sizeof rule, "%s", matched->source_rule_id);
            } else if (matched->kind == POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE) {
                length = snprintf(rule, sizeof rule, "%s", matched->source_rule_id);
            } else if (matched->kind == POKEMON_ADMISSION_SET_FIELDS_RULE) {
                length = snprintf(rule, sizeof rule, "%s", matched->source_rule_id);
            } else if (matched->value.tag_ban.tag == POKEMON_ADMISSION_TAG_NONEXISTENT) {
                length = snprintf(rule, sizeof rule, "-nonexistent");
            } else {
                length = snprintf(rule, sizeof rule, "-pokemontag:%s",
                    matched->value.tag_ban.canonical_id);
            }
            if (length < 0 || (size_t)length >= sizeof rule ||
                test_case->expected_rule == NULL ||
                strcmp(rule, test_case->expected_rule) != 0) {
                fprintf(stderr, "%s: expected rule %s, got %s\n", test_case->id,
                    test_case->expected_rule ? test_case->expected_rule : "(none)", rule);
                return 4;
            }
            if (decision.team_index != test_case->expected_member_index) return 6;
            printf("{\"id\":\"%s\",\"rejected\":true,\"normalized_species\":null,\"normalized_names\":null,\"normalized_fields\":null}\n",
                test_case->id);
        } else if (decision.result == POKEMON_ADMISSION_RESULT_INCOMPLETE) {
            if (test_case->expected_rule != NULL) return 5;
            printf("{\"id\":\"%s\",\"rejected\":false,\"normalized_species\":[",
                test_case->id);
            for (uint8_t member = 0; member < normalized.set_count; member++) {
                printf("%s\"%s\"", member ? "," : "", normalized.sets[member].species_id);
            }
            printf("],\"normalized_names\":[");
            for (uint8_t member = 0; member < normalized.set_count; member++) {
                printf("%s\"%s\"", member ? "," : "", normalized.sets[member].nickname);
            }
            printf("],\"normalized_fields\":[");
            for (uint8_t member = 0; member < normalized.set_count; member++) {
                const PokemonAdmissionNormalizedSet *set = &normalized.sets[member];
                const char gender = set->gender == POKEMON_ACQUISITION_GENDER_MALE ? 'M' :
                    set->gender == POKEMON_ACQUISITION_GENDER_FEMALE ? 'F' :
                    set->gender == POKEMON_ACQUISITION_GENDER_NEUTER ? 'N' : '-';
                printf("%s{\"gender\":\"%c\",\"nature\":\"%s\",\"shiny\":%s,\"ivs\":[",
                    member ? "," : "", gender, set->nature_id,
                    set->shiny ? "true" : "false");
                for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
                    printf("%s%u", stat ? "," : "", set->ivs[stat]);
                }
                printf("],\"hp_type\":\"%s\"}", set->hidden_power_type_id);
            }
            puts("]}");
        } else {
            fprintf(stderr, "%s: unexpected admission result %d\n", test_case->id, decision.result);
            return 3;
        }
    }
    return 0;
}
