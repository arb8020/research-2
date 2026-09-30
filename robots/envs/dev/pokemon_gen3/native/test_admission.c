#include "gen3_admission_data.h"
#include "singles2.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static PokemonAdmissionSetInput valid_set(void) {
    PokemonAdmissionSetInput input = {
        .species_id = "pikachu",
        .ability_id = "static",
        .item_id = "leftovers",
        .move_ids = {"thunderbolt"},
        .move_count = 1,
        .level = 100,
        .has_evs = 1,
        .evs = {[POKEMON_ADMISSION_STAT_HP] = 1},
    };
    return input;
}

static PokemonAdmissionDecision check(const PokemonAdmissionSetInput *input) {
    return pokemon_admission_check_set(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, input
    );
}

static void expect(PokemonAdmissionSetInput *input, PokemonAdmissionResult result) {
    PokemonAdmissionDecision actual = check(input);
    assert(actual.result == result);
}

static void test_bundle_and_universe(void) {
    assert(pokemon_admission_validate_bundle(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE
    ));
    assert(POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_SPECIES].count == 393);
    assert(POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_MOVE].count == 374);
    assert(POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_ABILITY].count == 80);
    assert(POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_ITEM].count == 129);
    assert(POKEMON_GEN3_OU_ADMISSION.program->rule_count == POKEMON_GEN3_ADMISSION_RULE_COUNT);
    assert(POKEMON_GEN3_ADMISSION_UNRELEASED_MATCH_COUNT == 0);
    assert(POKEMON_GEN3_ADMISSION_UNMATCHABLE_COMPLEX_RULE_COUNT == 2);

    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    PokemonAdmissionUniverse foreign = *mixed.universe;
    foreign.plugin_fingerprint++;
    mixed.universe = &foreign;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    PokemonAdmissionSetInput input = valid_set();
    assert(pokemon_admission_check_set(
        &mixed, &POKEMON_GEN3_OU_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_INVALID_BUNDLE);

    PokemonResolvedBundle wrong_runtime = POKEMON_GEN3_OU_BUNDLE;
    wrong_runtime.plugin_fingerprint++;
    assert(!pokemon_admission_validate_bundle(&POKEMON_GEN3_OU_ADMISSION, &wrong_runtime));
    PokemonFormatManifest wrong_manifest = *POKEMON_GEN3_OU_BUNDLE.manifest;
    PokemonFormatPolicy wrong_policy = *POKEMON_GEN3_OU_BUNDLE.policy;
    wrong_manifest.id = "gen3uu";
    wrong_policy.manifest = &wrong_manifest;
    wrong_runtime = POKEMON_GEN3_OU_BUNDLE;
    wrong_runtime.manifest = &wrong_manifest;
    wrong_runtime.policy = &wrong_policy;
    assert(!pokemon_admission_validate_bundle(&POKEMON_GEN3_OU_ADMISSION, &wrong_runtime));

    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.abi_version++;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.plugin_fingerprint = 0;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.format_id = "Gen 3 OU";
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.oracle_revision = "short";
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.program = NULL;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));

    PokemonAdmissionIdentity copied_species[POKEMON_GEN3_ADMISSION_SPECIES_COUNT];
    memcpy(copied_species,
        POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_SPECIES].values,
        sizeof copied_species);
    PokemonAdmissionUniverse malformed_universe = *POKEMON_GEN3_OU_ADMISSION.universe;
    malformed_universe.identities[POKEMON_ADMISSION_SPECIES].values = copied_species;
    copied_species[0].tags = UINT8_C(0x80);
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.universe = &malformed_universe;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));

    memcpy(copied_species,
        POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_SPECIES].values,
        sizeof copied_species);
    copied_species[0].predicates = POKEMON_ADMISSION_PREDICATE_OHKO;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    copied_rules[9].value.tag_ban.canonical_id = "unobtainable";
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.program = &malformed_program;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_malformed_and_unknown(void) {
    PokemonAdmissionSetInput input = valid_set();
    input.species_id = "Mr. Mime";
    expect(&input, POKEMON_ADMISSION_RESULT_MALFORMED);
    input = valid_set(); input.move_count = 0;
    expect(&input, POKEMON_ADMISSION_RESULT_MALFORMED);
    input = valid_set(); input.move_ids[0] = NULL;
    expect(&input, POKEMON_ADMISSION_RESULT_MALFORMED);
    input = valid_set(); input.move_count = POKEMON_ADMISSION_MAX_MOVES + 1;
    expect(&input, POKEMON_ADMISSION_RESULT_MALFORMED);
    input = valid_set(); input.move_ids[1] = "surf";
    PokemonAdmissionDecision malformed = check(&input);
    assert(malformed.result == POKEMON_ADMISSION_RESULT_MALFORMED);
    assert(malformed.identity_kind == POKEMON_ADMISSION_MOVE && malformed.input_index == 1);
    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, NULL
    ).result == POKEMON_ADMISSION_RESULT_MALFORMED);

    input = valid_set(); input.species_id = "terapagos";
    expect(&input, POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY);
    input = valid_set(); input.ability_id = "protosynthesis";
    expect(&input, POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY);
    input = valid_set(); input.item_id = "choicescarf";
    expect(&input, POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY);
    input = valid_set();
    input.move_ids[0] = "surf"; input.move_ids[1] = "scratch";
    input.move_ids[2] = "closecombat"; input.move_count = 3;
    PokemonAdmissionDecision unknown = check(&input);
    assert(unknown.result == POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY);
    assert(unknown.identity_kind == POKEMON_ADMISSION_MOVE && unknown.input_index == 2);
}

static void test_atomic_bans(void) {
    static const struct {
        PokemonAdmissionIdentityKind kind;
        const char *id;
        uint16_t rule_index;
    } bans[] = {
        {POKEMON_ADMISSION_ABILITY, "sandveil", 1},
        {POKEMON_ADMISSION_ABILITY, "soundproof", 2},
        {POKEMON_ADMISSION_ITEM, "brightpowder", 3},
        {POKEMON_ADMISSION_ITEM, "laxincense", 4},
        {POKEMON_ADMISSION_MOVE, "acupressure", 5},
        {POKEMON_ADMISSION_MOVE, "assist", 6},
        {POKEMON_ADMISSION_MOVE, "doubleteam", 7},
        {POKEMON_ADMISSION_MOVE, "minimize", 8},
        {POKEMON_ADMISSION_MOVE, "swagger", 9},
    };
    PokemonAdmissionSetInput input;
    for (size_t i = 0; i < sizeof bans / sizeof *bans; i++) {
        input = valid_set();
        uint8_t expected_input_index = 0;
        if (bans[i].kind == POKEMON_ADMISSION_ABILITY) input.ability_id = bans[i].id;
        else if (bans[i].kind == POKEMON_ADMISSION_ITEM) input.item_id = bans[i].id;
        else {
            input.move_ids[0] = "surf";
            input.move_ids[1] = "scratch";
            input.move_ids[2] = bans[i].id;
            input.move_count = 3;
            expected_input_index = 2;
        }
        PokemonAdmissionDecision actual = check(&input);
        assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
        assert(actual.identity_kind == bans[i].kind);
        assert(actual.input_index == expected_input_index);
        assert(actual.rule_index == bans[i].rule_index);
    }

    input = valid_set(); input.ability_id = "sandveil";
    input.item_id = "brightpowder"; input.move_ids[0] = "doubleteam";
    PokemonAdmissionDecision recombined = check(&input);
    assert(recombined.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(recombined.identity_kind == POKEMON_ADMISSION_ABILITY);
    assert(recombined.rule_index == 1);
}

static void test_rule_source_provenance(void) {
    static const char *sources[] = {
        "gen3ou", "gen3ou",
        "evasionitemsclause", "evasionitemsclause",
        "evasionmovesclause", "gen3ou", "evasionmovesclause",
        "evasionmovesclause", "gen3ou",
    };
    assert(sizeof sources / sizeof *sources == POKEMON_GEN3_ADMISSION_ATOMIC_BAN_COUNT);
    for (size_t i = 0; i < sizeof sources / sizeof *sources; i++) {
        assert(strcmp(POKEMON_GEN3_OU_ADMISSION.program->rules[i].source_rule_id,
            sources[i]) == 0);
    }
}

static size_t count_tag(PokemonAdmissionIdentityKind kind, PokemonAdmissionTag tag) {
    const PokemonAdmissionIdentitySpan *span =
        &POKEMON_GEN3_OU_ADMISSION.universe->identities[kind];
    size_t count = 0;
    for (uint16_t i = 0; i < span->count; i++) count += !!(span->values[i].tags & tag);
    return count;
}

static size_t count_predicate(
    PokemonAdmissionIdentityKind kind, PokemonAdmissionPredicate predicate
) {
    const PokemonAdmissionIdentitySpan *span =
        &POKEMON_GEN3_OU_ADMISSION.universe->identities[kind];
    size_t count = 0;
    for (uint16_t i = 0; i < span->count; i++) {
        count += !!(span->values[i].predicates & predicate);
    }
    return count;
}

static int identity_has_predicate(
    PokemonAdmissionIdentityKind kind, const char *id, PokemonAdmissionPredicate predicate
) {
    const PokemonAdmissionIdentitySpan *span =
        &POKEMON_GEN3_OU_ADMISSION.universe->identities[kind];
    for (uint16_t i = 0; i < span->count; i++) {
        if (strcmp(span->values[i].id, id) == 0) {
            return !!(span->values[i].predicates & predicate);
        }
    }
    return 0;
}

static void test_generated_ohko_predicate(void) {
    assert(POKEMON_GEN3_ADMISSION_ALL_OF_BAN_COUNT == 3);
    assert(count_predicate(POKEMON_ADMISSION_SPECIES, POKEMON_ADMISSION_PREDICATE_OHKO) == 0);
    assert(count_predicate(POKEMON_ADMISSION_MOVE, POKEMON_ADMISSION_PREDICATE_OHKO) == 4);
    assert(count_predicate(POKEMON_ADMISSION_ABILITY, POKEMON_ADMISSION_PREDICATE_OHKO) == 0);
    assert(count_predicate(POKEMON_ADMISSION_ITEM, POKEMON_ADMISSION_PREDICATE_OHKO) == 0);

    static const char *ohko_moves[] = {"fissure", "guillotine", "horndrill", "sheercold"};
    for (size_t i = 0; i < sizeof ohko_moves / sizeof *ohko_moves; i++) {
        PokemonAdmissionSetInput input = valid_set();
        input.move_ids[0] = "surf";
        input.move_ids[1] = "scratch";
        input.move_ids[2] = "protect";
        input.move_ids[3] = ohko_moves[i];
        input.move_count = 4;
        PokemonAdmissionDecision actual = check(&input);
        assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
        assert(actual.identity_kind == POKEMON_ADMISSION_MOVE && actual.input_index == 3);
        assert(actual.rule_index == 13);
    }

    PokemonAdmissionSetInput input = valid_set();
    input.species_id = "clefable";
    input.ability_id = "cutecharm";
    input.move_ids[0] = "metronome";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.species_id = "donphan";
    input.ability_id = "sturdy";
    input.move_ids[0] = "earthquake";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    mixed.program = &malformed_program;
    copied_rules[12].value.all_of_ban.requirements[0].identity_kind_mask =
        UINT8_C(1) << POKEMON_ADMISSION_SPECIES;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    copied_rules[12].value.all_of_ban.requirement_count = 0;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_generated_accuracy_trap_conjunction(void) {
    static const char *accuracy_moves[] = {
        "flash", "kinesis", "mudslap", "sandattack", "smokescreen",
    };
    static const char *trapping_moves[] = {"block", "meanlook", "spiderweb"};
    static const char *trapping_abilities[] = {"arenatrap", "magnetpull", "shadowtag"};
    assert(count_predicate(POKEMON_ADMISSION_MOVE,
        POKEMON_ADMISSION_PREDICATE_GUARANTEED_ACCURACY_DROP) == 5);
    assert(count_predicate(POKEMON_ADMISSION_MOVE,
        POKEMON_ADMISSION_PREDICATE_TRAPPING) == 3);
    assert(count_predicate(POKEMON_ADMISSION_ABILITY,
        POKEMON_ADMISSION_PREDICATE_TRAPPING) == 3);
    assert(count_predicate(POKEMON_ADMISSION_SPECIES,
        POKEMON_ADMISSION_PREDICATE_TRAPPING) == 0);
    assert(count_predicate(POKEMON_ADMISSION_ITEM,
        POKEMON_ADMISSION_PREDICATE_TRAPPING) == 0);
    for (size_t i = 0; i < sizeof accuracy_moves / sizeof *accuracy_moves; i++) {
        assert(identity_has_predicate(POKEMON_ADMISSION_MOVE, accuracy_moves[i],
            POKEMON_ADMISSION_PREDICATE_GUARANTEED_ACCURACY_DROP));
    }
    for (size_t i = 0; i < sizeof trapping_moves / sizeof *trapping_moves; i++) {
        assert(identity_has_predicate(POKEMON_ADMISSION_MOVE, trapping_moves[i],
            POKEMON_ADMISSION_PREDICATE_TRAPPING));
    }
    for (size_t i = 0; i < sizeof trapping_abilities / sizeof *trapping_abilities; i++) {
        assert(identity_has_predicate(POKEMON_ADMISSION_ABILITY, trapping_abilities[i],
            POKEMON_ADMISSION_PREDICATE_TRAPPING));
    }
    assert(!identity_has_predicate(POKEMON_ADMISSION_MOVE, "muddywater",
        POKEMON_ADMISSION_PREDICATE_GUARANTEED_ACCURACY_DROP));
    assert(!identity_has_predicate(POKEMON_ADMISSION_MOVE, "bind",
        POKEMON_ADMISSION_PREDICATE_TRAPPING));

    PokemonAdmissionSetInput input = valid_set();
    input.species_id = "dugtrio"; input.ability_id = "arenatrap";
    input.move_ids[0] = "earthquake"; input.move_ids[1] = "sandattack"; input.move_count = 2;
    PokemonAdmissionDecision actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.rule_index == 14 && actual.identity_kind == POKEMON_ADMISSION_MOVE &&
        actual.input_index == 1);

    input = valid_set(); input.move_ids[0] = "flash"; input.move_ids[1] = "meanlook";
    input.move_count = 2;
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 14);

    input = valid_set(); input.move_ids[0] = "flash";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input = valid_set(); input.species_id = "dugtrio"; input.ability_id = "arenatrap";
    input.move_ids[0] = "earthquake";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input = valid_set(); input.species_id = "smeargle"; input.ability_id = "owntempo";
    input.move_ids[0] = "muddywater"; input.move_ids[1] = "meanlook";
    input.move_count = 2;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION; mixed.program = &malformed_program;
    copied_rules[13].value.all_of_ban.requirements[1] =
        copied_rules[13].value.all_of_ban.requirements[0];
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    copied_rules[13].value.all_of_ban.requirement_count = 1;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_generated_tag_bans(void) {
    assert(count_tag(POKEMON_ADMISSION_SPECIES, POKEMON_ADMISSION_TAG_UBER) == 15);
    assert(count_tag(POKEMON_ADMISSION_MOVE, POKEMON_ADMISSION_TAG_UBER) == 0);
    assert(count_tag(POKEMON_ADMISSION_ITEM, POKEMON_ADMISSION_TAG_UNOBTAINABLE) == 10);
    assert(count_tag(POKEMON_ADMISSION_SPECIES, POKEMON_ADMISSION_TAG_UNOBTAINABLE) == 0);
    assert(count_tag(POKEMON_ADMISSION_SPECIES, POKEMON_ADMISSION_TAG_NONEXISTENT) == 1);
    /* The three Gen 3 CAP moves plus explicit rule operand Acupressure. */
    assert(count_tag(POKEMON_ADMISSION_MOVE, POKEMON_ADMISSION_TAG_NONEXISTENT) == 4);
    assert(count_tag(POKEMON_ADMISSION_ABILITY, POKEMON_ADMISSION_TAG_NONEXISTENT) == 4);
    assert(count_tag(POKEMON_ADMISSION_ITEM, POKEMON_ADMISSION_TAG_NONEXISTENT) == 13);

    PokemonAdmissionSetInput input = valid_set(); input.species_id = "mewtwo";
    PokemonAdmissionDecision actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_SPECIES && actual.rule_index == 10);

    input = valid_set(); input.item_id = "berryjuice";
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_ITEM && actual.rule_index == 11);

    input = valid_set(); input.species_id = "missingno";
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_SPECIES && actual.rule_index == 12);

    input = valid_set(); input.ability_id = "rebound";
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_ABILITY && actual.rule_index == 12);

    input = valid_set(); input.move_ids[0] = "surf";
    input.move_ids[1] = "scratch"; input.move_ids[2] = "paleowave";
    input.move_count = 3;
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_MOVE && actual.input_index == 2 &&
        actual.rule_index == 12);

    input = valid_set(); input.item_id = "berry";
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(actual.identity_kind == POKEMON_ADMISSION_ITEM && actual.rule_index == 12);

    input = valid_set(); input.species_id = "articuno";
    input.ability_id = "pressure"; input.move_ids[0] = "icebeam";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input = valid_set(); input.item_id = "liechiberry";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
}

static void test_allowed_is_never_accepted(void) {
    PokemonAdmissionSetInput input = valid_set();
    expect(&input, POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.species_id = "starmie";
    input.ability_id = "naturalcure";
    input.item_id = NULL;
    input.move_ids[1] = "surf";
    input.move_count = 2;
    expect(&input, POKEMON_ADMISSION_RESULT_INCOMPLETE);
}

static void test_team_admission(void) {
    assert(POKEMON_GEN3_ADMISSION_ANCHORED_CARDINALITY_BAN_COUNT == 1);
    assert(POKEMON_GEN3_OU_ADMISSION.program->rules[14].kind ==
        POKEMON_ADMISSION_ANCHORED_CARDINALITY_BAN);
    assert(POKEMON_GEN3_OU_ADMISSION.program->rules[14].scope == POKEMON_ADMISSION_SCOPE_TEAM);
    assert(strcmp(POKEMON_GEN3_OU_ADMISSION.program->rules[14].value
        .anchored_cardinality_ban.canonical_id, "oneboostpasserclause") == 0);
    assert(POKEMON_GEN3_OU_ADMISSION.program->rules[15].kind == POKEMON_ADMISSION_ALL_OF_BAN);
    assert(POKEMON_GEN3_OU_ADMISSION.program->rules[15].scope == POKEMON_ADMISSION_SCOPE_TEAM);
    assert(count_predicate(POKEMON_ADMISSION_MOVE,
        POKEMON_ADMISSION_PREDICATE_BATON_PASS) == 1);
    assert(count_predicate(POKEMON_ADMISSION_MOVE,
        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE) == 20);
    assert(count_predicate(POKEMON_ADMISSION_ITEM,
        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE) == 6);
    assert(count_predicate(POKEMON_ADMISSION_ABILITY,
        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE) == 1);
    assert(count_predicate(POKEMON_ADMISSION_MOVE,
        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE) == 4);
    assert(count_predicate(POKEMON_ADMISSION_ITEM,
        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE) == 2);
    assert(count_predicate(POKEMON_ADMISSION_ABILITY,
        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE) == 1);
    assert(identity_has_predicate(POKEMON_ADMISSION_MOVE, "ancientpower",
        POKEMON_ADMISSION_PREDICATE_SPEED_BOOST_SOURCE));
    assert(!identity_has_predicate(POKEMON_ADMISSION_MOVE, "ancientpower",
        POKEMON_ADMISSION_PREDICATE_BOOST_SOURCE));

    PokemonAdmissionTeamInput team = {.sets = {valid_set()}, .set_count = 1};
    team.sets[0].species_id = "vaporeon"; team.sets[0].ability_id = "waterabsorb";
    team.sets[0].move_ids[0] = "batonpass"; team.sets[0].move_ids[1] = "acidarmor";
    team.sets[0].move_count = 2;
    assert(pokemon_admission_check_set(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team.sets[0]).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    assert(pokemon_admission_check_team(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    team.sets[0].item_id = "liechiberry";
    PokemonAdmissionDecision actual = pokemon_admission_check_team(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 15);
    assert(actual.team_index == 0 && actual.identity_kind == POKEMON_ADMISSION_ITEM);

    team.sets[0].item_id = "leftovers";
    team.sets[1] = valid_set(); team.set_count = 2;
    team.sets[1].species_id = "espeon"; team.sets[1].ability_id = "synchronize";
    team.sets[1].move_ids[0] = "batonpass"; team.sets[1].move_ids[1] = "calmmind";
    team.sets[1].move_count = 2;
    actual = pokemon_admission_check_team(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 15);
    assert(actual.team_index == 1 && actual.identity_kind == POKEMON_ADMISSION_MOVE &&
        actual.input_index == 1);

    team = (PokemonAdmissionTeamInput){.sets = {valid_set()}, .set_count = 1};
    team.sets[0].species_id = "jolteon"; team.sets[0].ability_id = "voltabsorb";
    team.sets[0].move_ids[0] = "batonpass"; team.sets[0].move_ids[1] = "agility";
    team.sets[0].move_count = 2;
    actual = pokemon_admission_check_team(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 16);

    team.sets[0].move_ids[0] = "thunderbolt";
    assert(pokemon_admission_check_team(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    team.sets[0].move_ids[0] = "batonpass"; team.sets[0].move_ids[1] = "swagger";
    actual = pokemon_admission_check_team(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 9);

    team = (PokemonAdmissionTeamInput){.sets = {valid_set()}, .set_count = 2};
    team.sets[1] = valid_set(); team.sets[1].species_id = "terapagos";
    actual = pokemon_admission_check_team(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY && actual.team_index == 1);
    team.set_count = 0;
    assert(pokemon_admission_check_team(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team).result == POKEMON_ADMISSION_RESULT_MALFORMED);
    team.set_count = POKEMON_ADMISSION_MAX_TEAM_SIZE + 1;
    assert(pokemon_admission_check_team(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team).result == POKEMON_ADMISSION_RESULT_MALFORMED);

    team = (PokemonAdmissionTeamInput){.set_count = POKEMON_ADMISSION_MAX_TEAM_SIZE};
    for (uint8_t i = 0; i < team.set_count; i++) team.sets[i] = valid_set();
    assert(pokemon_admission_check_team(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION; mixed.program = &malformed_program;
    copied_rules[14].value.anchored_cardinality_ban.max_sources_per_set = 0;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    copied_rules[14].scope = POKEMON_ADMISSION_SCOPE_SET;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    copied_rules[14].value.anchored_cardinality_ban.counted =
        copied_rules[14].value.anchored_cardinality_ban.anchor;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_ev_stat_vector_policy(void) {
    assert(POKEMON_GEN3_ADMISSION_STAT_VECTOR_RULE_COUNT == 1);
    assert(POKEMON_GEN3_OU_BUNDLE.manifest->ev_limit_enabled);
    assert(POKEMON_GEN3_OU_BUNDLE.manifest->ev_limit == 510);
    const PokemonAdmissionRule *rule = &POKEMON_GEN3_OU_ADMISSION.program->rules[16];
    assert(rule->kind == POKEMON_ADMISSION_STAT_VECTOR_RULE);
    assert(rule->scope == POKEMON_ADMISSION_SCOPE_SET);
    assert(strcmp(rule->source_rule_id, "obtainable") == 0);
    assert(strcmp(rule->value.stat_vector_rule.canonical_id, "evlimit") == 0);

    PokemonAdmissionSetInput input = valid_set();
    memset(input.evs, 0, sizeof input.evs);
    input.evs[POKEMON_ADMISSION_STAT_HP] = 255;
    input.evs[POKEMON_ADMISSION_STAT_ATK] = 255;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.evs[POKEMON_ADMISSION_STAT_DEF] = 1;
    PokemonAdmissionDecision actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 17);

    input = valid_set(); memset(input.evs, 0, sizeof input.evs);
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_BANNED);
    input.level = 1;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.level = 100; input.evs[POKEMON_ADMISSION_STAT_HP] = 256;
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.input_index == POKEMON_ADMISSION_STAT_HP);
    input.evs[POKEMON_ADMISSION_STAT_HP] = -1;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_BANNED);

    input = valid_set(); input.has_evs = 0; memset(input.evs, 0, sizeof input.evs);
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_BANNED);
    input.evs[POKEMON_ADMISSION_STAT_HP] = 1;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_MALFORMED);
    input = valid_set(); input.has_evs = 2;
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_MALFORMED);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION; mixed.program = &malformed_program;
    copied_rules[16].value.stat_vector_rule.expected_total_limit = 509;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    copied_rules[16].value.stat_vector_rule.component_max = -1;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_species_ability_relation(void) {
    assert(POKEMON_GEN3_ADMISSION_ALLOWED_RELATION_COUNT == 1);
    assert(POKEMON_GEN3_ADMISSION_SPECIES_ABILITY_PAIR_COUNT == 517);
    const PokemonAdmissionAllowedRelation *relation =
        &POKEMON_GEN3_OU_ADMISSION.universe->relations[0];
    assert(relation->owner_kind == POKEMON_ADMISSION_SPECIES);
    assert(relation->member_kind == POKEMON_ADMISSION_ABILITY);
    assert(relation->row_offset_count == POKEMON_GEN3_ADMISSION_SPECIES_COUNT + 1);
    assert(relation->member_count == POKEMON_GEN3_ADMISSION_SPECIES_ABILITY_PAIR_COUNT);
    assert(strcmp(relation->canonical_id, "speciesabilities") == 0);
    const PokemonAdmissionRule *rule = &POKEMON_GEN3_OU_ADMISSION.program->rules[18];
    assert(rule->kind == POKEMON_ADMISSION_ALLOWED_RELATION_RULE);
    assert(rule->value.allowed_relation_rule.relation_id == 1);
    assert(strcmp(rule->source_rule_id, "obtainableabilities") == 0);

    PokemonAdmissionSetInput input = valid_set();
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.species_id = "starmie"; input.ability_id = "naturalcure";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.species_id = "rattata"; input.ability_id = "runaway";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.ability_id = "guts";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    input.species_id = "pikachu"; input.ability_id = "lightningrod";
    PokemonAdmissionDecision actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.identity_kind == POKEMON_ADMISSION_ABILITY && actual.rule_index == 19);
    input.species_id = "blissey"; input.ability_id = "levitate";
    assert(check(&input).rule_index == 19);
    input.species_id = "cacturne"; input.ability_id = "sandveil";
    actual = check(&input);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index != 19);
    input = valid_set(); input.ability_id = "protosynthesis";
    assert(check(&input).result == POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    mixed.program = &malformed_program;
    copied_rules[18].value.allowed_relation_rule.relation_id = 0;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));

    PokemonAdmissionAllowedRelation copied_relation = *relation;
    PokemonAdmissionUniverse malformed_universe = *POKEMON_GEN3_OU_ADMISSION.universe;
    malformed_universe.relations = &copied_relation;
    mixed = POKEMON_GEN3_OU_ADMISSION; mixed.universe = &malformed_universe;
    copied_relation.owner_kind = POKEMON_ADMISSION_MOVE;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    copied_relation = *relation; copied_relation.row_offset_count--;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    copied_relation = *relation;
    uint16_t copied_members[POKEMON_GEN3_ADMISSION_SPECIES_ABILITY_PAIR_COUNT];
    memcpy(copied_members, relation->members, sizeof copied_members);
    copied_relation.members = copied_members; copied_members[0] = 0;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_species_rewrite_normalization(void) {
    assert(POKEMON_GEN3_ADMISSION_SPECIES_REWRITE_COUNT == 3);
    const PokemonAdmissionRule *rule = &POKEMON_GEN3_OU_ADMISSION.program->rules[17];
    assert(rule->kind == POKEMON_ADMISSION_SPECIES_REWRITE_RULE);
    assert(strcmp(rule->source_rule_id, "obtainableformes") == 0);
    assert(strcmp(rule->value.species_rewrite_rule.canonical_id,
        "obtainableformes") == 0);
    assert(rule->value.species_rewrite_rule.rewrite_count == 3);
    const char *expected[] = {"castformrainy", "castformsnowy", "castformsunny"};
    for (size_t i = 0; i < 3; i++) {
        const PokemonAdmissionGuardedSpeciesRewrite *rewrite =
            &rule->value.species_rewrite_rule.rewrites[i];
        const PokemonAdmissionIdentitySpan *species =
            &POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_SPECIES];
        const PokemonAdmissionIdentitySpan *abilities =
            &POKEMON_GEN3_OU_ADMISSION.universe->identities[POKEMON_ADMISSION_ABILITY];
        assert(strcmp(species->values[rewrite->input_species_id - 1].id, expected[i]) == 0);
        assert(strcmp(species->values[rewrite->output_species_id - 1].id, "castform") == 0);
        assert(strcmp(abilities->values[rewrite->required_ability_id - 1].id, "forecast") == 0);
    }

    PokemonAdmissionSetInput input = valid_set();
    input.species_id = "castform"; input.ability_id = "forecast";
    PokemonAdmissionNormalizedSet normalized = {.species_id = "sentinel", .level = 77};
    assert(pokemon_admission_check_set_normalized(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &input, &normalized).result ==
        POKEMON_ADMISSION_RESULT_INCOMPLETE);
    assert(strcmp(normalized.species_id, "castform") == 0 &&
        strcmp(normalized.ability_id, "forecast") == 0 && normalized.level == 100 &&
        normalized.move_count == 1 && normalized.evs[POKEMON_ADMISSION_STAT_HP] == 1);

    for (size_t i = 0; i < 3; i++) {
        input.species_id = expected[i];
        normalized = (PokemonAdmissionNormalizedSet){.species_id = "sentinel", .level = 77};
        assert(pokemon_admission_check_set_normalized(&POKEMON_GEN3_OU_ADMISSION,
            &POKEMON_GEN3_OU_BUNDLE, &input, &normalized).result ==
            POKEMON_ADMISSION_RESULT_INCOMPLETE);
        assert(strcmp(normalized.species_id, "castform") == 0 &&
            strcmp(normalized.ability_id, "forecast") == 0);
    }

    input.species_id = "castformsunny"; input.ability_id = "intimidate";
    normalized = (PokemonAdmissionNormalizedSet){.species_id = "sentinel", .level = 77};
    PokemonAdmissionDecision actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &normalized);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.rule_index == 18 &&
        strcmp(normalized.species_id, "sentinel") == 0 && normalized.level == 77);
    input = valid_set(); input.species_id = "unknownforme";
    actual = pokemon_admission_check_set_normalized(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &input, &normalized);
    assert(actual.result == POKEMON_ADMISSION_RESULT_UNKNOWN_IDENTITY &&
        strcmp(normalized.species_id, "sentinel") == 0);

    PokemonAdmissionTeamInput team = {.set_count = 2};
    team.sets[0] = valid_set(); team.sets[1] = valid_set();
    team.sets[1].species_id = "castformrainy"; team.sets[1].ability_id = "forecast";
    PokemonAdmissionNormalizedTeam normalized_team = {.set_count = 99};
    assert(pokemon_admission_check_team_normalized(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team, &normalized_team).result ==
        POKEMON_ADMISSION_RESULT_INCOMPLETE);
    assert(normalized_team.set_count == 2 &&
        strcmp(normalized_team.sets[1].species_id, "castform") == 0);
    team.sets[1].ability_id = "intimidate";
    normalized_team = (PokemonAdmissionNormalizedTeam){.set_count = 99};
    actual = pokemon_admission_check_team_normalized(&POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &team, &normalized_team);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED && actual.team_index == 1 &&
        normalized_team.set_count == 99);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    mixed.program = &malformed_program;
    PokemonAdmissionGuardedSpeciesRewrite copied_rewrites[3];
    memcpy(copied_rewrites, rule->value.species_rewrite_rule.rewrites,
        sizeof copied_rewrites);
    copied_rules[17].value.species_rewrite_rule.rewrites = copied_rewrites;
    copied_rewrites[0].output_species_id = copied_rewrites[0].input_species_id;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rewrites, rule->value.species_rewrite_rule.rewrites,
        sizeof copied_rewrites);
    copied_rewrites[1].input_species_id = copied_rewrites[0].input_species_id;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
    memcpy(copied_rewrites, rule->value.species_rewrite_rule.rewrites,
        sizeof copied_rewrites);
    copied_rewrites[0].output_species_id = copied_rewrites[1].input_species_id;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_nickname_clause_transaction(void) {
    uint16_t nickname_rule = 0;
    for (uint16_t i = 0; i < POKEMON_GEN3_OU_ADMISSION.program->rule_count; i++) {
        if (POKEMON_GEN3_OU_ADMISSION.program->rules[i].kind ==
            POKEMON_ADMISSION_NICKNAME_CLAUSE_RULE) nickname_rule = (uint16_t)(i + 1);
    }
    assert(nickname_rule != 0);

    PokemonAdmissionTeamInput team = {.set_count = 2};
    team.sets[0] = valid_set();
    team.sets[0].nickname = "  Sparky  ";
    team.sets[1] = valid_set();
    team.sets[1].species_id = "raichu";
    team.sets[1].nickname = "Voltage";
    PokemonAdmissionNormalizedTeam normalized = {.set_count = 99};
    PokemonAdmissionDecision actual = pokemon_admission_check_team_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team, &normalized);
    assert(actual.result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    assert(normalized.set_count == 2 &&
        strcmp(normalized.sets[0].nickname, "Sparky") == 0 &&
        strcmp(normalized.sets[1].nickname, "Voltage") == 0);

    team.sets[0].nickname = "Sparky";
    team.sets[1].nickname = "Sparky";
    normalized = (PokemonAdmissionNormalizedTeam){.set_count = 99};
    actual = pokemon_admission_check_team_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team, &normalized);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.rule_index == nickname_rule && actual.team_index == 1 &&
        normalized.set_count == 99);

    team.sets[1].nickname = "sparky";
    actual = pokemon_admission_check_team_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &team, &normalized);
    assert(actual.result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    PokemonAdmissionSetInput input = valid_set();
    input.nickname = "Raichu";
    PokemonAdmissionNormalizedSet normalized_set = {.species_id = "sentinel", .level = 77};
    actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &normalized_set);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.rule_index == nickname_rule &&
        strcmp(normalized_set.species_id, "sentinel") == 0 && normalized_set.level == 77);

    input = valid_set();
    input.nickname = "1234567890123456789";
    actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &normalized_set);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.rule_index == nickname_rule &&
        strcmp(normalized_set.species_id, "sentinel") == 0 && normalized_set.level == 77);

    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    PokemonAdmissionUniverse malformed_universe = *mixed.universe;
    malformed_universe.species_metadata = NULL;
    mixed.universe = &malformed_universe;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    copied_rules[nickname_rule - 1].scope = POKEMON_ADMISSION_SCOPE_SET;
    mixed = POKEMON_GEN3_OU_ADMISSION;
    mixed.program = &malformed_program;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_unique_move_admission(void) {
    uint16_t rule_index = 0;
    for (uint16_t i = 0; i < POKEMON_GEN3_OU_ADMISSION.program->rule_count; i++) {
        if (POKEMON_GEN3_OU_ADMISSION.program->rules[i].kind ==
            POKEMON_ADMISSION_UNIQUE_MOVES_RULE) rule_index = (uint16_t)(i + 1);
    }
    assert(rule_index != 0);
    PokemonAdmissionSetInput input = valid_set();
    input.move_ids[1] = "thunderbolt";
    input.move_count = 2;
    PokemonAdmissionNormalizedSet output = {.species_id = "sentinel", .level = 77};
    PokemonAdmissionDecision actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &output);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        actual.identity_kind == POKEMON_ADMISSION_MOVE && actual.input_index == 1 &&
        actual.rule_index == rule_index && strcmp(output.species_id, "sentinel") == 0 &&
        output.level == 77);

    input.move_ids[1] = "quickattack";
    actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &output);
    assert(actual.result == POKEMON_ADMISSION_RESULT_INCOMPLETE &&
        output.move_count == 2 && strcmp(output.move_ids[1], "quickattack") == 0);

    PokemonAdmissionRule copied_rules[POKEMON_GEN3_ADMISSION_RULE_COUNT];
    memcpy(copied_rules, POKEMON_GEN3_OU_ADMISSION.program->rules, sizeof copied_rules);
    PokemonAdmissionProgram malformed_program = *POKEMON_GEN3_OU_ADMISSION.program;
    malformed_program.rules = copied_rules;
    copied_rules[rule_index - 1].scope = POKEMON_ADMISSION_SCOPE_TEAM;
    PokemonAdmissionBundle mixed = POKEMON_GEN3_OU_ADMISSION;
    mixed.program = &malformed_program;
    assert(!pokemon_admission_validate_bundle(&mixed, &POKEMON_GEN3_OU_BUNDLE));
}

static void test_acquisition_boundary(void) {
    const PokemonAdmissionUniverse *universe = POKEMON_GEN3_OU_ADMISSION.universe;
    assert(pokemon_acquisition_validate(universe->acquisition, universe));

    PokemonAcquisitionData malformed = *universe->acquisition;
    malformed.plugin_fingerprint++;
    assert(!pokemon_acquisition_validate(&malformed, universe));

    PokemonAcquisitionSpecies copied_species[POKEMON_GEN3_ADMISSION_SPECIES_COUNT];
    memcpy(copied_species, universe->acquisition->species, sizeof copied_species);
    malformed = *universe->acquisition;
    malformed.species = copied_species;
    copied_species[0].parent_species_id = 1;
    assert(!pokemon_acquisition_validate(&malformed, universe));
    memcpy(copied_species, universe->acquisition->species, sizeof copied_species);
    copied_species[0].ability_ids[0] =
        (uint16_t)(universe->identities[POKEMON_ADMISSION_ABILITY].count + 1);
    assert(!pokemon_acquisition_validate(&malformed, universe));

    uint16_t copied_event_only_refs[POKEMON_GEN3_ACQUISITION_EVENT_ONLY_REF_COUNT];
    memcpy(copied_event_only_refs, universe->acquisition->event_only_refs,
        sizeof copied_event_only_refs);
    malformed = *universe->acquisition;
    malformed.event_only_refs = copied_event_only_refs;
    copied_event_only_refs[0] = 0;
    assert(!pokemon_acquisition_validate(&malformed, universe));

    PokemonAdmissionSetInput input = valid_set();
    input.species_id = "persian";
    input.ability_id = "limber";
    input.move_ids[0] = "hiddenpowerice";
    input.hidden_power_type_id = "ice";
    PokemonAdmissionNormalizedSet output = {.species_id = "sentinel", .level = 77};
    PokemonAdmissionDecision actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &output);
    assert(actual.result == POKEMON_ADMISSION_RESULT_INCOMPLETE);
    const uint8_t ice_ivs[POKEMON_ADMISSION_STAT_COUNT] = {31, 30, 30, 31, 31, 31};
    assert(memcmp(output.ivs, ice_ivs, sizeof ice_ivs) == 0 &&
        strcmp(output.hidden_power_type_id, "ice") == 0);

    input.has_ivs = 1;
    memset(input.ivs, 30, sizeof input.ivs);
    output = (PokemonAdmissionNormalizedSet){.species_id = "sentinel", .level = 77};
    actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &output);
    assert(actual.result == POKEMON_ADMISSION_RESULT_BANNED &&
        strcmp(output.species_id, "sentinel") == 0 && output.level == 77);

    input = valid_set();
    input.species_id = "electabuzz";
    input.ability_id = "static";
    input.move_ids[0] = "quickattack";
    input.move_ids[1] = "leer";
    input.move_ids[2] = "thunderpunch";
    input.move_count = 3;
    input.level = 10;
    actual = pokemon_admission_check_set_normalized(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input, &output);
    assert(actual.result == POKEMON_ADMISSION_RESULT_INCOMPLETE &&
        output.gender == POKEMON_ACQUISITION_GENDER_MALE);
}

static void test_pomeg_glitch_format_policy(void) {
    PokemonAdmissionSetInput input = {
        .species_id = "zigzagoon",
        .ability_id = "pickup",
        .item_id = "leftovers",
        .move_ids = {"bellydrum", "extremespeed"},
        .move_count = 2,
        .level = 5,
        .has_evs = 1,
        .evs = {[POKEMON_ADMISSION_STAT_HP] = 1},
    };
    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_ADMISSION, &POKEMON_GEN3_OU_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_BANNED);
    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_POMEG_ADMISSION,
        &POKEMON_GEN3_OU_POMEG_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_INCOMPLETE);

    input.level = 4;
    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_POMEG_ADMISSION,
        &POKEMON_GEN3_OU_POMEG_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_BANNED);

    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_ADMISSION,
        &POKEMON_GEN3_OU_POMEG_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_INVALID_BUNDLE);
    assert(pokemon_admission_check_set(
        &POKEMON_GEN3_OU_POMEG_ADMISSION,
        &POKEMON_GEN3_OU_BUNDLE, &input
    ).result == POKEMON_ADMISSION_RESULT_INVALID_BUNDLE);

    PokemonAdmissionBundle malformed = POKEMON_GEN3_OU_POMEG_ADMISSION;
    PokemonAdmissionFormatPolicy wrong = *malformed.format_policy;
    wrong.pomeg_minimum_level = 4;
    malformed.format_policy = &wrong;
    assert(!pokemon_admission_validate_bundle(
        &malformed, &POKEMON_GEN3_OU_POMEG_BUNDLE));
}

int main(void) {
    test_bundle_and_universe();
    test_malformed_and_unknown();
    test_atomic_bans();
    test_rule_source_provenance();
    test_generated_tag_bans();
    test_generated_ohko_predicate();
    test_generated_accuracy_trap_conjunction();
    test_allowed_is_never_accepted();
    test_team_admission();
    test_ev_stat_vector_policy();
    test_species_ability_relation();
    test_species_rewrite_normalization();
    test_nickname_clause_transaction();
    test_unique_move_admission();
    test_acquisition_boundary();
    test_pomeg_glitch_format_policy();
    puts("pokemon admission tests passed");
    return 0;
}
