#include "../../../native/gen3_admission_data.h"
#include "../../../native/singles2.h"

#include <stdio.h>
#include <string.h>

#ifndef POKEMON_ADMISSION_CASES_HEADER
#error "POKEMON_ADMISSION_CASES_HEADER must name the generated fixture header"
#endif
#include POKEMON_ADMISSION_CASES_HEADER

static const char *rule_name(const PokemonAdmissionRule *rule) {
    if (rule->kind == POKEMON_ADMISSION_OBTAINABLE_MOVES_RULE) return rule->source_rule_id;
    return "unexpected-rule";
}

int main(void) {
    for (size_t index = 0; index < POKEMON_ADMISSION_CASE_COUNT; index++) {
        const PokemonAdmissionCase *test_case = &POKEMON_ADMISSION_CASES[index];
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
            memcpy(input->evs, source->evs, sizeof input->evs);
            memcpy(input->move_ids, source->move_ids, sizeof input->move_ids);
        }
        PokemonAdmissionNormalizedTeam normalized = {0};
        PokemonAdmissionDecision decision = pokemon_admission_check_team_normalized(
            &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team, &normalized);
        if (decision.result == POKEMON_ADMISSION_RESULT_BANNED) {
            if (decision.rule_index == 0 ||
                decision.rule_index > POKEMON_GEN3_OU_ADMISSION.program->rule_count) return 2;
            const PokemonAdmissionRule *rule =
                &POKEMON_GEN3_OU_ADMISSION.program->rules[decision.rule_index - 1];
            printf("{\"id\":\"%s\",\"disposition\":\"BANNED\",\"rule\":\"%s\","
                "\"member_index\":%u,\"normalized_species\":null}\n",
                test_case->id, rule_name(rule), decision.team_index);
        } else if (decision.result == POKEMON_ADMISSION_RESULT_INCOMPLETE) {
            printf("{\"id\":\"%s\",\"disposition\":\"INCOMPLETE\",\"rule\":null,"
                "\"member_index\":null,\"normalized_species\":[", test_case->id);
            for (uint8_t member = 0; member < normalized.set_count; member++) {
                printf("%s\"%s\"", member ? "," : "", normalized.sets[member].species_id);
            }
            puts("]}");
        } else {
            fprintf(stderr, "%s: invalid admission decision %d\n",
                test_case->id, decision.result);
            return 3;
        }
    }
    return 0;
}
