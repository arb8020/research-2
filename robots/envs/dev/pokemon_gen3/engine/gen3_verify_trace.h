#pragma once

#include "gen3_abi.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define GEN3_TRACE_ABI_VERSION 2u

typedef enum {
    GEN3_TRACE_CHECKPOINT = 1,
    GEN3_TRACE_PHASE = 2,
    GEN3_TRACE_REQUEST = 3,
    GEN3_TRACE_PRNG = 4,
    GEN3_TRACE_PROTOCOL = 5,
    GEN3_TRACE_TERMINAL = 6,
    GEN3_TRACE_QUEUE_BEGIN = 7,
    GEN3_TRACE_QUEUE_ITEM = 8,
    GEN3_TRACE_QUEUE_END = 9,
    GEN3_TRACE_HANDLER_GROUP_BEGIN = 10,
    GEN3_TRACE_HANDLER_DISCOVERED = 11,
    GEN3_TRACE_HANDLER_BEGIN = 12,
    GEN3_TRACE_HANDLER_END = 13,
    GEN3_TRACE_HANDLER_GROUP_END = 14,
} Gen3TraceKind;

typedef enum {
    /* An action receives one stable ID at COMPILE or INSERT. SUSPEND and
     * RESUME preserve that ID so interrupted work is distinguishable from
     * reconstruction. queue_count is the post-operation live count. */
    GEN3_TRACE_QUEUE_COMPILE = 1,
    GEN3_TRACE_QUEUE_INSERT = 2,
    GEN3_TRACE_QUEUE_SORT = 3,
    GEN3_TRACE_QUEUE_POP = 4,
    GEN3_TRACE_QUEUE_CANCEL = 5,
    GEN3_TRACE_QUEUE_SUSPEND = 6,
    GEN3_TRACE_QUEUE_RESUME = 7,
} Gen3TraceQueueOperation;

typedef enum {
    GEN3_TRACE_POINT_INSTALL = 1,
    GEN3_TRACE_POINT_DECISION_BEGIN = 2,
    GEN3_TRACE_POINT_DECISION_END = 3,
    GEN3_TRACE_POINT_REQUEST = 4,
    GEN3_TRACE_POINT_TERMINAL = 5,
} Gen3TracePoint;

typedef struct {
    uint8_t kind;
    uint8_t required_side_mask;
    uint8_t forced_first_side;
    uint8_t continuation;
} Gen3TracePhaseValue;

typedef enum {
    GEN3_TRACE_PRNG_RAW = 1,
    GEN3_TRACE_PRNG_BELOW = 2,
    GEN3_TRACE_PRNG_CHANCE = 3,
    GEN3_TRACE_PRNG_RANGE = 4,
} Gen3TracePrngOperation;

typedef enum {
    GEN3_TRACE_PRNG_UNKNOWN = 0,
    GEN3_TRACE_PRNG_QUEUE_TIE_SHUFFLE = 1,
    GEN3_TRACE_PRNG_QUEUE_TIE_INSERT = 2,
    GEN3_TRACE_PRNG_ACCURACY = 3,
    GEN3_TRACE_PRNG_CRITICAL = 4,
    GEN3_TRACE_PRNG_DAMAGE_ROLL = 5,
    GEN3_TRACE_PRNG_SECONDARY = 6,
    GEN3_TRACE_PRNG_PROTECT = 7,
    GEN3_TRACE_PRNG_QUICK_CLAW = 8,
    GEN3_TRACE_PRNG_RANDOM_TARGET = 9,
    GEN3_TRACE_PRNG_FORCED_SWITCH_TARGET = 10,
    GEN3_TRACE_PRNG_SLEEP_DURATION = 11,
    GEN3_TRACE_PRNG_CONFUSION_DURATION = 12,
    GEN3_TRACE_PRNG_MULTIHIT_COUNT = 13,
} Gen3TracePrngLabel;

typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    uint64_t sequence;
    uint32_t boundary;
    uint16_t kind;
    uint16_t semantic_point;
    union {
        struct { Gen3TracePhaseValue before; Gen3TracePhaseValue after; } phase;
        struct {
            Gen3TracePhaseValue phase;
            uint16_t legal_mask[GEN3_SIDE_COUNT];
        } request;
        struct {
            uint16_t label;
            uint16_t operation;
            uint16_t seed_before[4];
            uint16_t seed_after[4];
            uint32_t argument0;
            uint32_t argument1;
            uint32_t raw_output;
            uint32_t result;
        } prng;
        Gen3BattleEvent protocol;
        struct { uint8_t done; int8_t winner_side; } terminal;
        struct {
            uint32_t stable_id;
            uint16_t operation;
            uint16_t index;
            uint8_t action_kind;
            uint8_t side;
            uint8_t queue_count;
            uint8_t reserved;
        } queue;
        struct { uint32_t stable_id; uint16_t event_id; uint16_t effect_id; } handler;
    } value;
} Gen3TraceRecord;

typedef void (*Gen3TraceEmitFn)(void *context, const Gen3Battle *battle,
    const Gen3TraceRecord *record);

typedef struct {
    uint32_t abi_version;
    uint32_t struct_size;
    void *context;
    Gen3TraceEmitFn emit;
} Gen3TraceSink;

#ifdef GEN3_VERIFY_TRACE
/* Synchronous and non-owning. The callback may call the read-only snapshot
 * and legal-action queries, but must not mutate or re-enter execution. Passing
 * NULL disables observation. Streaming means the engine cannot truncate. */
int gen3_battle_set_trace_sink(Gen3Battle *battle, const Gen3TraceSink *sink);
#endif

#ifdef __cplusplus
}
#endif
