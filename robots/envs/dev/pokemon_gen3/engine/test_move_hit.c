#include "gen3_move_hit.h"

#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint32_t values[3];
    const char *labels[3];
    size_t count;
    size_t used;
} ScriptedRandom;

static int scripted_next(void *opaque, const char *label, uint32_t *out) {
    ScriptedRandom *random = opaque;
    assert(random->used < random->count);
    assert(strcmp(label, random->labels[random->used]) == 0);
    *out = random->values[random->used++];
    return GEN3_OK;
}

typedef struct {
    uint16_t seed[4];
    const char *labels[3];
    size_t used;
} SeedRandom;

static int seed_next(void *opaque, const char *label, uint32_t *out) {
    SeedRandom *random = opaque;
    assert(random->used < 3);
    assert(strcmp(label, random->labels[random->used++]) == 0);
    uint64_t state = ((uint64_t)random->seed[0] << 48) |
        ((uint64_t)random->seed[1] << 32) |
        ((uint64_t)random->seed[2] << 16) | random->seed[3];
    state = state * UINT64_C(0x5D588B656C078965) + UINT64_C(0x269EC3);
    random->seed[0] = (uint16_t)(state >> 48);
    random->seed[1] = (uint16_t)(state >> 32);
    random->seed[2] = (uint16_t)(state >> 16);
    random->seed[3] = (uint16_t)state;
    *out = (uint32_t)(state >> 32);
    return GEN3_OK;
}

static Gen3PokemonSet pokemon(
    uint16_t species, uint16_t ability,
    uint16_t attack, uint16_t defense,
    uint16_t special_attack, uint16_t special_defense
) {
    Gen3PokemonSet set = {0};
    set.species_id = species;
    set.ability_id = ability;
    set.level = 100;
    set.stats[0] = 300;
    set.stats[1] = attack;
    set.stats[2] = defense;
    set.stats[3] = special_attack;
    set.stats[4] = special_defense;
    set.stats[5] = 200;
    return set;
}

static Gen3MoveHitContext context(
    const Gen3PokemonSet *attacker, const Gen3PokemonSet *target,
    const Gen3MoveData *move, ScriptedRandom *random
) {
    Gen3MoveHitContext result = {
        .attacker = {.set = attacker, .ability_id = attacker->ability_id},
        .target = {.set = target, .ability_id = target->ability_id},
        .move = move,
        .random = {scripted_next, random},
        .natural_immunity = gen3_generated_ability_immunity,
    };
    return result;
}

typedef struct {
    size_t calls;
    Gen3TryHitResult result;
    const ScriptedRandom *random;
} TryHitProbe;

static Gen3TryHitResult probe_try_hit(
    void *opaque, const Gen3HitCombatant *target, const Gen3MoveData *move
) {
    TryHitProbe *probe = opaque;
    assert(target != NULL && move != NULL);
    assert(probe->random == NULL || probe->random->used == 1);
    probe->calls++;
    return probe->result;
}

static void test_type_immunity_stages_only_accuracy(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200); /* Swampert */
    Gen3PokemonSet target = pokemon(227, 51, 200, 300, 200, 200); /* Skarmory */
    ScriptedRandom random = {{0}, {"move.accuracy"}, 1, 0};
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE], &random
    );
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_IMMUNE);
    assert(random.used == 1);
}

static void test_ability_immunity_is_a_handler(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200);
    /* Gengar's types do not resist Ground.  Its generated ability handler does. */
    Gen3PokemonSet target = pokemon(94, GEN3_ABILITY_LEVITATE, 200, 200, 200, 200);
    ScriptedRandom random = {{UINT32_MAX}, {"move.accuracy"}, 1, 0};
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE], &random
    );
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_IMMUNE);
    assert(random.used == 1);

    hit.natural_immunity = NULL;
    random.used = 0;
    random.count = 3;
    random.values[0] = 0;
    random.values[1] = UINT32_MAX;
    random.values[2] = UINT32_MAX;
    random.labels[1] = "move.critical_hit";
    random.labels[2] = "move.damage_roll";
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_CONNECTED);

    /* Battle-current ability, not immutable team data, owns immunity. */
    hit.natural_immunity = gen3_generated_ability_immunity;
    hit.target.ability_id = 30;
    random.used = 0;
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_CONNECTED);
}

static void test_try_hit_runs_only_after_accuracy(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200);
    Gen3PokemonSet target = pokemon(227, 51, 200, 300, 200, 200);
    Gen3MoveData move = GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    ScriptedRandom random = {{0}, {"move.accuracy"}, 1, 0};
    TryHitProbe probe = {0, GEN3_TRY_HIT_PASS, &random};
    Gen3MoveHitContext hit = context(&attacker, &target, &move, &random);
    hit.try_hit = probe_try_hit;
    hit.try_hit_context = &probe;
    Gen3HitOutcome outcome = {0};

    /* Successful accuracy reaches TryHit even after natural immunity. */
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_IMMUNE);
    assert(probe.calls == 1);

    /* TryHit failure is not laundered into immunity. */
    target = pokemon(242, 30, 200, 200, 200, 200);
    random.used = 0;
    probe.calls = 0;
    probe.result = GEN3_TRY_HIT_FAILED;
    hit = context(&attacker, &target, &move, &random);
    hit.try_hit = probe_try_hit;
    hit.try_hit_context = &probe;
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_FAILED);
    assert(probe.calls == 1);

    /* A miss stops before TryHit; precomputed Levitate still reports immune. */
    target = pokemon(94, GEN3_ABILITY_LEVITATE, 200, 200, 200, 200);
    move.accuracy = 50;
    random.values[0] = UINT32_MAX;
    random.used = 0;
    probe.calls = 0;
    probe.result = GEN3_TRY_HIT_PASS;
    hit = context(&attacker, &target, &move, &random);
    hit.try_hit = probe_try_hit;
    hit.try_hit_context = &probe;
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_IMMUNE);
    assert(probe.calls == 0);
}

static void test_miss_stops_before_critical(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200);
    Gen3PokemonSet target = pokemon(242, 30, 200, 200, 200, 200); /* Blissey */
    ScriptedRandom random = {{UINT32_MAX}, {"move.accuracy"}, 1, 0};
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_THUNDER], &random
    );
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_MISSED);
    assert(random.used == 1);
}

static void test_always_hit_skips_accuracy(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200);
    Gen3PokemonSet target = pokemon(242, 30, 200, 200, 200, 200);
    ScriptedRandom random = {
        {UINT32_MAX, UINT32_MAX},
        {"move.critical_hit", "move.damage_roll"}, 2, 0
    };
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_SWIFT], &random
    );
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_CONNECTED);
    assert(!outcome.value.connected.critical);
    assert(outcome.value.connected.damage_roll == 15);
    assert(random.used == 2);
}

static void test_critical_precedes_resistance_floor(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 1, 1, 1, 1); /* Ground STAB */
    Gen3PokemonSet target = pokemon(251, 30, 1, 1, 1, 1); /* Celebi resists Ground */
    ScriptedRandom random = {
        {0, 0, 0},
        {"move.accuracy", "move.critical_hit", "move.damage_roll"}, 3, 0
    };
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE], &random
    );
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_CONNECTED);
    assert(outcome.value.connected.critical);
    assert(outcome.value.connected.damage_roll == 0);
    assert(outcome.value.connected.damage == 129);
}

static void test_exact_seed_staging(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 256, 200, 200, 200);
    Gen3PokemonSet target = pokemon(242, 30, 200, 200, 200, 200);
    SeedRandom random = {
        {1, 2, 3, 4},
        {"move.accuracy", "move.critical_hit", "move.damage_roll"}, 0
    };
    Gen3MoveHitContext hit = {
        .attacker = {.set = &attacker, .ability_id = attacker.ability_id},
        .target = {.set = &target, .ability_id = target.ability_id},
        .move = &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE],
        .random = {seed_next, &random},
        .natural_immunity = gen3_generated_ability_immunity,
    };
    Gen3HitOutcome outcome = {0};
    assert(gen3_resolve_move_hit(&hit, &outcome) == GEN3_OK);
    assert(outcome.kind == GEN3_HIT_CONNECTED);
    assert(!outcome.value.connected.critical);
    assert(outcome.value.connected.damage_roll == 10);
    assert(outcome.value.connected.damage == 146);
    assert(random.used == 3);
    assert(random.seed[0] == 43514 && random.seed[1] == 9542);
    assert(random.seed[2] == 40559 && random.seed[3] == 8561);
}

static void test_current_stages_and_critical_stage_rules(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 200, 200, 200, 200);
    Gen3PokemonSet target = pokemon(242, 30, 200, 200, 200, 200);
    ScriptedRandom random = {
        {0, UINT32_MAX, 0},
        {"move.accuracy", "move.critical_hit", "move.damage_roll"}, 3, 0
    };
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE], &random
    );
    hit.attacker.stat_stages[0] = 2;
    hit.target.stat_stages[1] = -2;
    Gen3HitOutcome boosted = {0};
    assert(gen3_resolve_move_hit(&hit, &boosted) == GEN3_OK);
    assert(boosted.kind == GEN3_HIT_CONNECTED);

    random.used = 0;
    hit.attacker.stat_stages[0] = 0;
    hit.target.stat_stages[1] = 0;
    Gen3HitOutcome neutral = {0};
    assert(gen3_resolve_move_hit(&hit, &neutral) == GEN3_OK);
    assert(boosted.value.connected.damage > neutral.value.connected.damage);

    /* A critical ignores an attack penalty and a defense boost. */
    random.used = 0;
    random.values[1] = 0;
    hit.attacker.stat_stages[0] = -6;
    hit.target.stat_stages[1] = 6;
    Gen3HitOutcome critical = {0};
    assert(gen3_resolve_move_hit(&hit, &critical) == GEN3_OK);
    assert(critical.value.connected.critical);

    random.used = 0;
    hit.attacker.stat_stages[0] = 0;
    hit.target.stat_stages[1] = 0;
    Gen3HitOutcome critical_neutral = {0};
    assert(gen3_resolve_move_hit(&hit, &critical_neutral) == GEN3_OK);
    assert(critical.value.connected.damage ==
        critical_neutral.value.connected.damage);
}

static void test_phase1_modifier_precedes_additive_and_critical(void) {
    Gen3PokemonSet attacker = pokemon(260, 67, 200, 200, 200, 200);
    Gen3PokemonSet target = pokemon(242, 30, 200, 200, 200, 200);
    ScriptedRandom random = {
        {0, 0, 0},
        {"move.accuracy", "move.critical_hit", "move.damage_roll"}, 3, 0
    };
    Gen3MoveHitContext hit = context(
        &attacker, &target, &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE], &random
    );
    hit.phase1 = (Gen3HitModifier){1, 2};
    Gen3HitOutcome halved = {0};
    assert(gen3_resolve_move_hit(&hit, &halved) == GEN3_OK);
    assert(halved.value.connected.critical);
    /* floor(42*100*200/200/50)=84; phase1=42; +2; crit=88;
     * STAB=132; neutral effectiveness and roll 0 leave 132. Applying the
     * modifier after +2 would incorrectly produce 129. */
    assert(halved.value.connected.damage == 132);
}

int main(void) {
    test_type_immunity_stages_only_accuracy();
    test_ability_immunity_is_a_handler();
    test_try_hit_runs_only_after_accuracy();
    test_miss_stops_before_critical();
    test_always_hit_skips_accuracy();
    test_critical_precedes_resistance_floor();
    test_exact_seed_staging();
    test_current_stages_and_critical_stage_rules();
    test_phase1_modifier_precedes_additive_and_critical();
    puts("move-hit tests passed");
    return 0;
}
