#include "gen3_move_preflight.h"

static Gen3OrdinaryMovePreflightResult preflight_program(
    const Gen3OrdinaryMovePreflight *request, size_t program_index
) {
    if (program_index >= request->program_count) {
        return GEN3_ORDINARY_MOVE_INVALID;
    }
    const Gen3MoveProgram *program = &request->programs[program_index];
    if ((program->flags & GEN3_MOVE_PROGRAM_NATIVE_REQUIRED) != 0) {
        return GEN3_ORDINARY_MOVE_NATIVE_EXECUTION;
    }
    if ((program->flags & ~GEN3_MOVE_PROGRAM_NATIVE_REQUIRED) != 0 ||
        program->first_op > request->operation_count ||
        program->op_count > request->operation_count - program->first_op) {
        return GEN3_ORDINARY_MOVE_INVALID;
    }
    for (size_t offset = 0; offset < program->op_count; offset++) {
        const Gen3MoveProgramOp *operation =
            &request->operations[program->first_op + offset];
        if (request->supports_program_op == NULL ||
            !request->supports_program_op(request->program_context, operation)) {
            return GEN3_ORDINARY_MOVE_UNSUPPORTED_PROGRAM;
        }
    }
    return GEN3_ORDINARY_MOVE_SUPPORTED;
}

Gen3OrdinaryMovePreflightResult gen3_preflight_ordinary_move(
    const Gen3OrdinaryMovePreflight *request
) {
    if (request == NULL || request->move == NULL || request->programs == NULL ||
        request->operations == NULL ||
        (request->active_effect_count != 0 && request->active_effects == NULL)) {
        return GEN3_ORDINARY_MOVE_INVALID;
    }
    const Gen3MoveData *move = request->move;
    if (move->id == 0 || move->base_power == 0 ||
        (move->category != 1 && move->category != 2)) {
        return GEN3_ORDINARY_MOVE_UNSUPPORTED_SHAPE;
    }
    /* In singles these three target denotations all resolve to the one foe.
     * Their spread distinctions become observable only with multiple active
     * slots, which this ABI cannot construct. */
    if (move->target != GEN3_MOVE_TARGET_NORMAL &&
        move->target != GEN3_MOVE_TARGET_ALL_ADJACENT &&
        move->target != GEN3_MOVE_TARGET_ALL_ADJACENT_FOES) {
        return GEN3_ORDINARY_MOVE_UNSUPPORTED_TARGET;
    }
    if (move->native_execution_required != 0) {
        return GEN3_ORDINARY_MOVE_NATIVE_EXECUTION;
    }
    if (request->accuracy_stage != 0 || request->evasion_stage != 0) {
        return GEN3_ORDINARY_MOVE_ACCURACY_EVASION;
    }
    if (request->modifier_hook_count != 0) {
        return GEN3_ORDINARY_MOVE_MODIFIER_HOOK;
    }
    for (size_t index = 0; index < request->active_effect_count; index++) {
        const Gen3EffectDescriptor *effect = request->active_effects[index];
        if (effect == NULL || effect->handler_count != 0) {
            return GEN3_ORDINARY_MOVE_ACTIVE_EFFECT;
        }
    }

    if (move->primary_program != 0) {
        Gen3OrdinaryMovePreflightResult result =
            preflight_program(request, move->primary_program);
        if (result != GEN3_ORDINARY_MOVE_SUPPORTED) return result;
    }
    if (move->first_secondary_program > request->program_count ||
        move->secondary_program_count >
            request->program_count - move->first_secondary_program) {
        return GEN3_ORDINARY_MOVE_INVALID;
    }
    for (size_t offset = 0; offset < move->secondary_program_count; offset++) {
        Gen3OrdinaryMovePreflightResult result = preflight_program(
            request, move->first_secondary_program + offset
        );
        if (result != GEN3_ORDINARY_MOVE_SUPPORTED) return result;
    }
    return GEN3_ORDINARY_MOVE_SUPPORTED;
}
