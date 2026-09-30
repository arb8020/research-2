#include "gen3_move_program.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t random;
    int random_result;
    int draws;
    int capability_checks;
    int unsupported_opcode;
    int effect_results[4];
    int effects;
    char label[32];
    Gen3MoveProgramOp attempted[4];
} Fixture;

static int next_random(void *opaque, const char *label, uint32_t *out) {
    Fixture *fixture = opaque;
    fixture->draws++;
    snprintf(fixture->label, sizeof(fixture->label), "%s", label);
    *out = fixture->random;
    return fixture->random_result;
}

static int supports(void *opaque, const Gen3MoveProgramOp *operation) {
    Fixture *fixture = opaque;
    fixture->capability_checks++;
    return operation->opcode != fixture->unsupported_opcode;
}

static int apply(void *opaque, const Gen3MoveProgramOp *operation) {
    Fixture *fixture = opaque;
    const int index = fixture->effects;
    fixture->attempted[index] = *operation;
    fixture->effects++;
    return fixture->effect_results[index];
}

static Gen3ProgramRuntime runtime(Fixture *fixture) {
    return (Gen3ProgramRuntime){fixture, next_random, supports, apply};
}

static void test_primary_effects_apply_independently_without_a_draw(void) {
    const Gen3MoveProgram programs[] = {{0, 2, 0, 0}};
    const Gen3MoveProgramOp operations[] = {
        {GEN3_PROGRAM_OP_BOOST, GEN3_PROGRAM_TARGET_SELF,
         GEN3_PROGRAM_STAT_SPECIAL_ATTACK, 1},
        {GEN3_PROGRAM_OP_BOOST, GEN3_PROGRAM_TARGET_SELF,
         GEN3_PROGRAM_STAT_SPECIAL_DEFENSE, 1},
    };
    Fixture fixture = {.unsupported_opcode = -1, .effect_results = {0, 1}};
    Gen3ProgramRuntime callbacks = runtime(&fixture);
    int applied = 0;
    assert(gen3_execute_move_program(
        programs, 1, operations, 2, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_OK);
    assert(applied == 1 && fixture.draws == 0 && fixture.effects == 2);
    assert(memcmp(operations, fixture.attempted, sizeof(operations)) == 0);

    fixture = (Fixture){.unsupported_opcode = -1};
    callbacks = runtime(&fixture);
    assert(gen3_execute_move_program(
        programs, 1, operations, 2, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_REJECTED);
    assert(applied == 0 && fixture.draws == 0 && fixture.effects == 2);
}

static void test_secondary_draw_precedes_semantic_acceptance(void) {
    const Gen3MoveProgram programs[] = {{0, 1, 10, 0}};
    const Gen3MoveProgramOp operation = {
        GEN3_PROGRAM_OP_STATUS, GEN3_PROGRAM_TARGET_TARGET,
        GEN3_PROGRAM_STATUS_FREEZE, 0
    };
    Fixture fixture = {.unsupported_opcode = -1, .random = 0};
    Gen3ProgramRuntime callbacks = runtime(&fixture);
    int applied = 0;
    assert(gen3_execute_move_program(
        programs, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_OK);
    assert(applied == 0 && fixture.draws == 1 && fixture.effects == 1);
    assert(strcmp(fixture.label, "move.secondary_effect") == 0);

    fixture = (Fixture){.unsupported_opcode = -1, .random = UINT32_MAX};
    callbacks = runtime(&fixture);
    assert(gen3_execute_move_program(
        programs, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_OK);
    assert(applied == 0 && fixture.draws == 1 && fixture.effects == 0);

    fixture = (Fixture){.unsupported_opcode = -1, .random_result = 1};
    callbacks = runtime(&fixture);
    assert(gen3_execute_move_program(
        programs, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_RANDOM_ERROR);
    assert(applied == 0 && fixture.draws == 1 && fixture.effects == 0);
}

static void test_structure_and_capability_fail_before_randomness(void) {
    const Gen3MoveProgramOp operation = {
        GEN3_PROGRAM_OP_STATUS, GEN3_PROGRAM_TARGET_TARGET,
        GEN3_PROGRAM_STATUS_POISON, 0
    };
    const Gen3MoveProgram native[] = {{0, 1, 10, GEN3_MOVE_PROGRAM_NATIVE_REQUIRED}};
    const Gen3MoveProgram bad_bounds[] = {{1, 1, 10, 0}};
    const Gen3MoveProgram bad_flags[] = {{0, 1, 10, 2}};
    const Gen3MoveProgram bad_chance[] = {{0, 1, 101, 0}};
    const Gen3MoveProgram ordinary[] = {{0, 1, 10, 0}};
    Fixture fixture = {.unsupported_opcode = GEN3_PROGRAM_OP_STATUS};
    Gen3ProgramRuntime callbacks = runtime(&fixture);
    int applied = 1;
    assert(gen3_execute_move_program(
        native, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_NATIVE);
    assert(gen3_execute_move_program(
        bad_bounds, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_INVALID);
    assert(gen3_execute_move_program(
        bad_flags, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_INVALID);
    assert(gen3_execute_move_program(
        bad_chance, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_INVALID);
    assert(gen3_execute_move_program(
        ordinary, 1, &operation, 1, 0, &callbacks, &applied
    ) == GEN3_PROGRAM_NATIVE);
    assert(fixture.draws == 0 && fixture.effects == 0);
}

static void test_generated_programs_execute_without_move_identity(void) {
    Fixture fixture = {.unsupported_opcode = -1, .effect_results = {1}};
    Gen3ProgramRuntime callbacks = runtime(&fixture);
    int applied = 0;
    assert(gen3_execute_move_program(
        GEN3_MOVE_PROGRAMS, GEN3_MOVE_PROGRAM_COUNT,
        GEN3_MOVE_PROGRAM_OPS, GEN3_MOVE_PROGRAM_OP_COUNT,
        GEN3_MOVES[GEN3_MOVE_TOXIC].primary_program, &callbacks, &applied
    ) == GEN3_PROGRAM_OK);
    assert(applied == 1);
    assert(fixture.attempted[0].argument == GEN3_PROGRAM_STATUS_TOXIC);

    fixture = (Fixture){
        .unsupported_opcode = -1, .random = 0, .effect_results = {1}
    };
    callbacks = runtime(&fixture);
    assert(gen3_execute_move_program(
        GEN3_MOVE_PROGRAMS, GEN3_MOVE_PROGRAM_COUNT,
        GEN3_MOVE_PROGRAM_OPS, GEN3_MOVE_PROGRAM_OP_COUNT,
        GEN3_MOVES[GEN3_MOVE_PSYCHIC].first_secondary_program,
        &callbacks, &applied
    ) == GEN3_PROGRAM_OK);
    assert(applied == 1);
    assert(fixture.attempted[0].opcode == GEN3_PROGRAM_OP_BOOST);
    assert(fixture.attempted[0].argument == GEN3_PROGRAM_STAT_SPECIAL_DEFENSE);
}

int main(void) {
    test_primary_effects_apply_independently_without_a_draw();
    test_secondary_draw_precedes_semantic_acceptance();
    test_structure_and_capability_fail_before_randomness();
    test_generated_programs_execute_without_move_identity();
    puts("gen3 move program tests passed");
    return 0;
}
