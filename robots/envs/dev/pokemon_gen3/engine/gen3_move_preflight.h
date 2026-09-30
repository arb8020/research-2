#pragma once

#include <stddef.h>
#include <stdint.h>

#include "data_gen3.h"
#include "gen3_move_program.h"

typedef enum {
    GEN3_ORDINARY_MOVE_SUPPORTED = 0,
    GEN3_ORDINARY_MOVE_INVALID,
    GEN3_ORDINARY_MOVE_UNSUPPORTED_SHAPE,
    GEN3_ORDINARY_MOVE_UNSUPPORTED_TARGET,
    GEN3_ORDINARY_MOVE_NATIVE_EXECUTION,
    GEN3_ORDINARY_MOVE_UNSUPPORTED_PROGRAM,
    GEN3_ORDINARY_MOVE_ACTIVE_EFFECT,
    GEN3_ORDINARY_MOVE_ACCURACY_EVASION,
    GEN3_ORDINARY_MOVE_MODIFIER_HOOK,
} Gen3OrdinaryMovePreflightResult;

typedef struct {
    const Gen3MoveData *move;
    const Gen3MoveProgram *programs;
    size_t program_count;
    const Gen3MoveProgramOp *operations;
    size_t operation_count;
    const Gen3EffectDescriptor *const *active_effects;
    size_t active_effect_count;
    int8_t accuracy_stage;
    int8_t evasion_stage;
    size_t modifier_hook_count;
    Gen3ProgramSupports supports_program_op;
    void *program_context;
} Gen3OrdinaryMovePreflight;

/* Pure, closed-world admission check for the generic move pipeline. It owns no
 * battle state and must run before PP, protocol, or PRNG mutation. */
Gen3OrdinaryMovePreflightResult gen3_preflight_ordinary_move(
    const Gen3OrdinaryMovePreflight *request
);
