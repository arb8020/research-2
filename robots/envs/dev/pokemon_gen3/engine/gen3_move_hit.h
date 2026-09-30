#pragma once

#include <stdint.h>

#include "gen3_abi.h"
#include "data_gen3.h"

typedef struct {
    const Gen3PokemonSet *set;
    /* The current battle ability is mutable even though the normalized set is
     * not.  Keeping it explicit prevents ability suppression/replacement from
     * accidentally consulting immutable team data. */
    uint16_t ability_id;
    /* Current battle stages in atk, def, spa, spd, spe order.  They are
     * deliberately carried with the mutable combatant view rather than the
     * immutable normalized set. */
    int8_t stat_stages[GEN3_STAT_STAGE_COUNT];
} Gen3HitCombatant;

typedef int (*Gen3HitRandomNext)(void *context, const char *label, uint32_t *out);

typedef struct {
    Gen3HitRandomNext next;
    void *context;
} Gen3HitRandom;

typedef enum {
    GEN3_TRY_HIT_PASS = 0,
    GEN3_TRY_HIT_FAILED = 1,
} Gen3TryHitResult;

typedef Gen3TryHitResult (*Gen3TryHit)(
    void *context, const Gen3HitCombatant *target, const Gen3MoveData *move
);

typedef int (*Gen3NaturalAbilityImmunity)(
    const Gen3HitCombatant *target, const Gen3MoveData *move
);

typedef struct {
    uint16_t numerator;
    uint16_t denominator; /* zero denotes identity */
} Gen3HitModifier;

typedef struct {
    Gen3HitCombatant attacker;
    Gen3HitCombatant target;
    const Gen3MoveData *move;
    Gen3HitRandom random;
    Gen3NaturalAbilityImmunity natural_immunity;
    Gen3TryHit try_hit;
    void *try_hit_context;
    /* Gen 3 has distinct pre-+2 rounding boundaries. The caller discovers and
     * composes handlers for each named stage; the kernel applies them in order
     * without rediscovering ambient state. Spread is absent in OU singles. */
    Gen3HitModifier burn;
    Gen3HitModifier phase1;
    Gen3HitModifier weather;
} Gen3MoveHitContext;

typedef enum {
    GEN3_HIT_IMMUNE = 0,
    GEN3_HIT_MISSED = 1,
    GEN3_HIT_FAILED = 2,
    GEN3_HIT_CONNECTED = 3,
} Gen3HitKind;

typedef struct {
    uint8_t critical;
    uint8_t damage_roll; /* Showdown's random(16), in the range 0..15. */
    uint32_t damage;
} Gen3ConnectedHit;

typedef struct {
    Gen3HitKind kind;
    union {
        Gen3ConnectedHit connected;
    } value;
} Gen3HitOutcome;

/* Generated descriptor-backed ability immunity.  Type immunity is owned by
 * gen3_resolve_move_hit and is intentionally not folded into this handler. */
int gen3_generated_ability_immunity(
    const Gen3HitCombatant *target, const Gen3MoveData *move
);

/* Restricted Gen 3 ordinary-hit arithmetic seam.  Callers own mutable stat
 * normalization (accuracy/evasion, burn, screens, weather, and handlers) and all
 * state mutation.  This function only stages immunity, accuracy, TryHit,
 * critical-hit, damage-roll, and base Gen 3 damage arithmetic. */
int gen3_resolve_move_hit(
    const Gen3MoveHitContext *context, Gen3HitOutcome *outcome
);
