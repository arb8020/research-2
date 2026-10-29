#include "gen3_move_preflight.h"
#include "gen3_abi.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

static int supports_declarative_op(
    void *context, const Gen3MoveProgramOp *operation
) {
    (void)context;
    return operation->opcode == GEN3_PROGRAM_OP_STATUS ||
        operation->opcode == GEN3_PROGRAM_OP_BOOST;
}

static Gen3OrdinaryMovePreflight request_for(const Gen3MoveData *move) {
    return (Gen3OrdinaryMovePreflight){
        .move = move,
        .programs = GEN3_MOVE_PROGRAMS,
        .program_count = GEN3_MOVE_PROGRAM_COUNT,
        .operations = GEN3_MOVE_PROGRAM_OPS,
        .operation_count = GEN3_MOVE_PROGRAM_OP_COUNT,
        .supports_program_op = supports_declarative_op,
    };
}

static const Gen3EffectDescriptor *effect(uint8_t kind, uint16_t id) {
    for (size_t index = 0; index < GEN3_EFFECT_DESCRIPTOR_COUNT; index++) {
        if (GEN3_EFFECT_DESCRIPTORS[index].kind == kind &&
            GEN3_EFFECT_DESCRIPTORS[index].effect_id == id) {
            return &GEN3_EFFECT_DESCRIPTORS[index];
        }
    }
    return NULL;
}

static void test_accepts_only_represented_ordinary_descriptors(void) {
    Gen3OrdinaryMovePreflight request =
        request_for(&GEN3_MOVES[GEN3_MOVE_EARTHQUAKE]);
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_SUPPORTED);

    request = request_for(&GEN3_MOVES[GEN3_MOVE_ICE_BEAM]);
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_SUPPORTED);

    const Gen3EffectDescriptor *levitate =
        effect(GEN3_EFFECT_ABILITY, GEN3_ABILITY_LEVITATE);
    assert(levitate != NULL && levitate->handler_count == 0);
    request.active_effects = &levitate;
    request.active_effect_count = 1;
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_SUPPORTED);
}

static void test_rejects_exceptional_descriptors_and_ambient_hooks(void) {
    Gen3OrdinaryMovePreflight request =
        request_for(&GEN3_MOVES[GEN3_MOVE_DOUBLE_SLAP]);
    assert(request.move->native_execution_required != 0);
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_NATIVE_EXECUTION);

    Gen3MoveData self_target = GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    self_target.target = GEN3_MOVE_TARGET_SELF;
    request = request_for(&self_target);
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_UNSUPPORTED_TARGET);

    request = request_for(&GEN3_MOVES[GEN3_MOVE_EARTHQUAKE]);
    const Gen3EffectDescriptor *torrent =
        effect(GEN3_EFFECT_ABILITY, GEN3_ABILITY_TORRENT);
    assert(torrent != NULL && torrent->handler_count != 0);
    request.active_effects = &torrent;
    request.active_effect_count = 1;
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_ACTIVE_EFFECT);

    request.active_effect_count = 0;
    request.accuracy_stage = 1;
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_ACCURACY_EVASION);
    request.accuracy_stage = 0;
    request.modifier_hook_count = 1;
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_MODIFIER_HOOK);
}

static void test_unsupported_preflight_is_atomic(void) {
    Gen3BattleInit init = {0};
    init.abi_version = GEN3_ABI_VERSION;
    init.struct_size = sizeof(init);
    memcpy(init.seed, (uint16_t[]){1, 65535, 42, 900}, sizeof(init.seed));
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        init.teams[side].abi_version = GEN3_ABI_VERSION;
        init.teams[side].struct_size = sizeof(init.teams[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            Gen3PokemonSet *set = &init.teams[side].pokemon[slot];
            set->abi_version = GEN3_ABI_VERSION;
            set->struct_size = sizeof(*set);
            set->species_id = (uint16_t)(1 + side * GEN3_TEAM_SIZE + slot);
            set->ability_id = GEN3_ABILITY_LEVITATE;
            set->level = 100;
            set->gender = 1;
            set->happiness = 255;
            set->move_ids[0] = GEN3_MOVE_DOUBLE_SLAP;
            set->max_pp[0] = 16;
            for (size_t stat = 0; stat < 6; stat++) set->stats[stat] = 200;
        }
    }
    Gen3Battle *battle = NULL;
    assert(gen3_battle_create(&init, &battle, NULL, 0) == GEN3_OK);
    Gen3BattleSnapshot before;
    Gen3BattleSnapshot after;
    assert(gen3_battle_snapshot(battle, &before) == GEN3_OK);

    Gen3OrdinaryMovePreflight request =
        request_for(&GEN3_MOVES[GEN3_MOVE_DOUBLE_SLAP]);
    assert(gen3_preflight_ordinary_move(&request) ==
        GEN3_ORDINARY_MOVE_NATIVE_EXECUTION);
    assert(gen3_battle_snapshot(battle, &after) == GEN3_OK);
    assert(memcmp(&before, &after, sizeof(before)) == 0);
    assert(memcmp(before.seed, after.seed, sizeof(before.seed)) == 0);
    gen3_battle_destroy(battle);
}

int main(void) {
    test_accepts_only_represented_ordinary_descriptors();
    test_rejects_exceptional_descriptors_and_ambient_hooks();
    test_unsupported_preflight_is_atomic();
    puts("move preflight tests passed");
    return 0;
}
