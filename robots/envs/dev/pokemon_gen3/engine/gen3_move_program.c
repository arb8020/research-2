#include "gen3_move_program.h"

static int well_formed(const Gen3MoveProgramOp *op) {
    if (op->target > GEN3_PROGRAM_TARGET_SELF) return 0;
    if (op->opcode == GEN3_PROGRAM_OP_STATUS) {
        return op->argument < GEN3_PROGRAM_STATUS_COUNT && op->amount == 0;
    }
    if (op->opcode == GEN3_PROGRAM_OP_BOOST) {
        return op->argument < GEN3_PROGRAM_STAT_COUNT && op->amount != 0;
    }
    return 0;
}

Gen3ProgramResult gen3_execute_move_program(
    const Gen3MoveProgram *programs,
    size_t program_count,
    const Gen3MoveProgramOp *operations,
    size_t operation_count,
    size_t program_index,
    const Gen3ProgramRuntime *runtime,
    int *applied
) {
    if (applied != NULL) *applied = 0;
    if (programs == NULL || operations == NULL || runtime == NULL ||
        applied == NULL || program_index >= program_count) return GEN3_PROGRAM_INVALID;
    const Gen3MoveProgram *program = &programs[program_index];
    if (program->flags & GEN3_MOVE_PROGRAM_NATIVE_REQUIRED) return GEN3_PROGRAM_NATIVE;
    if (program->flags != 0 || program->chance > 100 ||
        program->first_op > operation_count ||
        program->op_count > operation_count - program->first_op) {
        return GEN3_PROGRAM_INVALID;
    }
    for (size_t i = 0; i < program->op_count; i++) {
        const Gen3MoveProgramOp *op = &operations[program->first_op + i];
        if (!well_formed(op)) return GEN3_PROGRAM_INVALID;
        if (runtime->supports == NULL || runtime->apply == NULL ||
            !runtime->supports(runtime->context, op)) return GEN3_PROGRAM_NATIVE;
    }
    if (program->chance != 0) {
        uint32_t random = 0;
        if (runtime->random == NULL ||
            runtime->random(runtime->context, "move.secondary_effect", &random) != 0) {
            return GEN3_PROGRAM_RANDOM_ERROR;
        }
        if ((uint32_t)(((uint64_t)random * 100u) >> 32) >= program->chance) {
            return GEN3_PROGRAM_OK;
        }
    }
    for (size_t i = 0; i < program->op_count; i++) {
        const Gen3MoveProgramOp *op = &operations[program->first_op + i];
        if (runtime->apply(runtime->context, op)) (*applied)++;
    }
    if (program->chance == 0 && *applied == 0) return GEN3_PROGRAM_REJECTED;
    return GEN3_PROGRAM_OK;
}
