#pragma once

#include <stddef.h>
#include <stdint.h>

#include "data_gen3.h"

typedef enum {
    GEN3_PROGRAM_OK = 0,
    GEN3_PROGRAM_INVALID = 1,
    GEN3_PROGRAM_NATIVE = 2,
    GEN3_PROGRAM_REJECTED = 3,
    GEN3_PROGRAM_RANDOM_ERROR = 4,
} Gen3ProgramResult;

typedef int (*Gen3ProgramRandom)(void *context, const char *label, uint32_t *out);
/* supports() answers only whether the runtime implements an opcode. It must
 * not inspect target state or decide whether an otherwise valid effect lands. */
typedef int (*Gen3ProgramSupports)(
    void *context, const Gen3MoveProgramOp *operation
);
/* apply() performs one semantic operation and returns nonzero exactly when it
 * changed state. No-effect is an ordinary semantic result. */
typedef int (*Gen3ProgramApply)(
    void *context, const Gen3MoveProgramOp *operation
);

typedef struct {
    void *context;
    Gen3ProgramRandom random;
    Gen3ProgramSupports supports;
    Gen3ProgramApply apply;
} Gen3ProgramRuntime;

/* Structure and runtime capability are preflighted before effects. A nonzero
 * chance denotes a secondary and owns exactly one draw before target-specific
 * acceptance, matching Showdown's secondaries(). Operations then apply
 * independently in descriptor order; a multi-op primary is not transactional.
 * `applied` receives the number of operations that changed state. */
Gen3ProgramResult gen3_execute_move_program(
    const Gen3MoveProgram *programs,
    size_t program_count,
    const Gen3MoveProgramOp *operations,
    size_t operation_count,
    size_t program_index,
    const Gen3ProgramRuntime *runtime,
    int *applied
);
