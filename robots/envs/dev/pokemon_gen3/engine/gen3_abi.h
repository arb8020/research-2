#pragma once

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GEN3_ABI_VERSION 12u
#define GEN3_TEAM_SIZE 6u
#define GEN3_MOVE_SLOTS 4u
#define GEN3_SIDE_COUNT 2u
#define GEN3_MAX_EVENTS 32u
#define GEN3_STAT_STAGE_COUNT 5u

enum {
    GEN3_EVENT_SWITCH = 1,
    GEN3_EVENT_MOVE = 2,
    GEN3_EVENT_DAMAGE = 3,
    GEN3_EVENT_HEAL = 4,
    GEN3_EVENT_FAIL = 5,
    GEN3_EVENT_FAINT = 6,
    GEN3_EVENT_PROTECT = 7,
    GEN3_EVENT_BLOCK = 8,
    GEN3_EVENT_STATUS = 9,
    GEN3_EVENT_SIDE_START = 10,
    GEN3_EVENT_VOLATILE_START = 11,
    GEN3_EVENT_BOOST = 12,
    GEN3_EVENT_UNBOOST = 13,
};

enum {
    GEN3_STAT_ATK = 1,
    GEN3_STAT_DEF = 2,
    GEN3_STAT_SPA = 3,
    GEN3_STAT_SPD = 4,
    GEN3_STAT_SPE = 5,
};

enum {
    GEN3_STATUS_NONE = 0,
    GEN3_STATUS_BURN = 1,
    GEN3_STATUS_PARALYSIS = 2,
    GEN3_STATUS_POISON = 3,
    GEN3_STATUS_TOXIC = 4,
    GEN3_STATUS_SLEEP = 5,
    GEN3_STATUS_FREEZE = 6,
};

enum {
    GEN3_OK = 0,
    GEN3_INVALID_ARGUMENT = 1,
    GEN3_INVALID_LAYOUT = 2,
    GEN3_INVALID_TEAM = 3,
    GEN3_OUT_OF_MEMORY = 4,
    GEN3_UNSUPPORTED_ACTION = 5,
    GEN3_ILLEGAL_ACTION = 6,
};

/* A complete, already validated and normalized Pokemon set.
 * IDs belong to the generated Gen 3 data tables. Derived battle stats and PP
 * are explicit so initialization does not depend on a second normalization
 * implementation in C. This value is immutable after battle creation. */
typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    uint16_t species_id;
    uint16_t item_id;
    uint16_t ability_id;
    uint16_t move_ids[GEN3_MOVE_SLOTS];
    uint16_t stats[6]; /* hp, atk, def, spa, spd, spe */
    uint16_t max_pp[GEN3_MOVE_SLOTS];
    uint8_t level;
    uint8_t gender; /* 0 genderless, 1 male, 2 female; unresolved is rejected */
    uint8_t happiness;
    uint8_t shiny;
} Gen3PokemonSet;

typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    Gen3PokemonSet pokemon[GEN3_TEAM_SIZE];
} Gen3BattleTeam;

typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    Gen3BattleTeam teams[GEN3_SIDE_COUNT];
    uint16_t seed[4];
} Gen3BattleInit;

typedef struct {
    Gen3PokemonSet set;
    uint16_t hp;
    uint16_t pp[GEN3_MOVE_SLOTS];
    uint8_t status;
    uint8_t protect_counter; /* 0 or next consecutive-use denominator */
    uint8_t toxic_counter;
    uint8_t leech_seeded;
    int8_t stat_stages[GEN3_STAT_STAGE_COUNT]; /* atk, def, spa, spd, spe */
} Gen3PokemonSnapshot;

/* Semantic protocol event. Presentation-only Showdown fields such as
 * timestamps, nicknames, and percentage-only spectator HP are deliberately
 * excluded from the native correctness surface. */
typedef struct {
    uint8_t kind;
    uint8_t side;
    uint8_t status;
    uint8_t amount; /* stat-stage magnitude for boost/unboost events */
    uint16_t species_id;
    uint16_t move_id;
    uint16_t hp;
    uint16_t max_hp;
} Gen3BattleEvent;

typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    Gen3PokemonSnapshot pokemon[GEN3_SIDE_COUNT][GEN3_TEAM_SIZE];
    uint16_t seed[4];
    uint32_t turn;
    uint16_t event_count;
    int8_t force_switch_side; /* -1 at normal decisions; otherwise 0 or 1 */
    uint8_t spikes[GEN3_SIDE_COUNT];
    uint8_t resume_residuals; /* forced replacement resumes an interrupted turn */
    uint8_t done;
    int8_t winner_side; /* -1 while active; otherwise 0 or 1 */
    Gen3BattleEvent events[GEN3_MAX_EVENTS];
} Gen3BattleSnapshot;

typedef struct Gen3Battle Gen3Battle;

uint32_t gen3_abi_version(void);
size_t gen3_sizeof_pokemon_set(void);
size_t gen3_sizeof_battle_team(void);
size_t gen3_sizeof_battle_init(void);
size_t gen3_sizeof_battle_snapshot(void);

/* Advance Showdown's 64-bit Gen 5 compatibility LCG once. The four seed
 * words are big-endian, matching Showdown's public input-log representation.
 * Writes the upper 32 bits of the advanced state to out. */
int gen3_prng_next(uint16_t seed[4], uint32_t *out);

int gen3_battle_create(
    const Gen3BattleInit *init,
    Gen3Battle **out,
    char *error,
    size_t error_capacity
);

void gen3_battle_destroy(Gen3Battle *battle);

/* Bits 0..3 are active move slots. Bits 4..8 are request-order slots 2..6.
 * In singles the active Pokemon is always request-order slot 1. */
int gen3_battle_legal_actions(
    const Gen3Battle *battle,
    uint8_t side,
    uint16_t *out_mask
);

int gen3_battle_switch_slice_supported(
    const Gen3Battle *battle,
    uint8_t *out_supported
);

/* Advance one decision boundary. Unsupported mechanics are rejected before
 * observable state changes; callers may therefore retry or delegate a whole
 * boundary to another implementation without rolling battle state back. */
int gen3_battle_turn(
    Gen3Battle *battle,
    int8_t action_p1,
    int8_t action_p2
);

int gen3_battle_snapshot(
    const Gen3Battle *battle,
    Gen3BattleSnapshot *out
);

#ifdef __cplusplus
}
#endif
