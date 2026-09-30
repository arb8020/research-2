#include "gen3_abi.h"
#include "data_gen3.h"
#include "gen3_verify_trace.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
    uint16_t hp;
    uint16_t pp[GEN3_MOVE_SLOTS];
    uint8_t status;
    uint8_t protect_counter;
    uint8_t toxic_counter;
    uint8_t leech_seeded;
    int8_t stat_stages[GEN3_STAT_STAGE_COUNT];
} Gen3PokemonState;

#define GEN3_ACTION_QUEUE_CAP 16u

typedef enum {
    GEN3_CHOICE_NONE = 0,
    GEN3_CHOICE_MOVE,
    GEN3_CHOICE_SWITCH,
} Gen3ChoiceKind;

typedef struct {
    Gen3ChoiceKind kind;
    uint8_t side;
    uint8_t slot;
} Gen3Choice;

typedef enum {
    GEN3_ACTION_SWITCH = 1,
    GEN3_ACTION_INSTASWITCH,
    GEN3_ACTION_RUN_SWITCH,
    GEN3_ACTION_MOVE,
    GEN3_ACTION_BEFORE_TURN,
    GEN3_ACTION_RESIDUAL,
} Gen3ActionKind;

typedef struct {
    uint32_t order; /* zero denotes Showdown's default order, 2^32 */
    int32_t priority;
    int32_t speed;
    int32_t sub_order;
    int32_t effect_order;
} Gen3OrderKey;

typedef struct {
    Gen3OrderKey key;
    uint8_t payload_index;
} Gen3OrderedRecord;

typedef struct {
    Gen3ActionKind kind;
    uint8_t side;
#ifdef GEN3_VERIFY_TRACE
    uint32_t trace_stable_id;
#endif
    Gen3OrderKey key;
    union {
        struct {
            uint8_t target_slot;
        } switch_action;
        struct {
            uint8_t move_slot;
            uint8_t target_side;
            uint16_t move_id;
        } move_action;
    } value;
} Gen3Action;

typedef struct {
    Gen3Action values[GEN3_ACTION_QUEUE_CAP];
    Gen3OrderedRecord order[GEN3_ACTION_QUEUE_CAP];
    uint8_t head;
    uint8_t count;
    uint8_t value_count;
} Gen3ActionQueue;

typedef enum {
    GEN3_PHASE_NORMAL_REQUEST = 0,
    GEN3_PHASE_FORCED_SWITCH_REQUEST,
    GEN3_PHASE_EXECUTING,
    GEN3_PHASE_TERMINAL,
} Gen3PhaseKind;

typedef enum {
    GEN3_CONTINUE_NONE = 0,
    GEN3_CONTINUE_RESIDUAL,
} Gen3Continuation;

typedef struct {
    Gen3PhaseKind kind;
    uint8_t required_side_mask;
    uint8_t forced_first_side;
    Gen3Continuation continuation;
} Gen3Phase;

struct Gen3Battle {
    Gen3BattleTeam teams[GEN3_SIDE_COUNT];
    Gen3PokemonState state[GEN3_SIDE_COUNT][GEN3_TEAM_SIZE];
    uint16_t seed[4];
    uint32_t turn;
    uint16_t event_count;
    int8_t force_switch_side;
    uint8_t resume_residuals;
    uint8_t done;
    int8_t winner_side;
    uint8_t spikes[GEN3_SIDE_COUNT];
    Gen3ActionQueue action_queue;
    Gen3Phase phase;
    Gen3BattleEvent events[GEN3_MAX_EVENTS];
#ifdef GEN3_VERIFY_TRACE
    Gen3TraceSink trace_sink;
    uint64_t trace_sequence;
    uint32_t trace_boundary;
    uint32_t trace_emission_boundary;
    uint32_t trace_next_action_id;
#endif
};

#ifdef GEN3_VERIFY_TRACE
static Gen3TracePhaseValue trace_phase_value(Gen3Phase phase) {
    return (Gen3TracePhaseValue){
        .kind = (uint8_t)phase.kind,
        .required_side_mask = phase.required_side_mask,
        .forced_first_side = phase.forced_first_side,
        .continuation = (uint8_t)phase.continuation,
    };
}

static void trace_emit(Gen3Battle *battle, Gen3TraceRecord record) {
    assert(battle != NULL);
    if (battle->trace_sink.emit == NULL) return;
    assert(battle->trace_sequence != UINT64_MAX);
    record.abi_version = GEN3_TRACE_ABI_VERSION;
    record.struct_size = sizeof(record);
    record.sequence = battle->trace_sequence++;
    record.boundary = battle->trace_emission_boundary;
    battle->trace_sink.emit(battle->trace_sink.context, battle, &record);
}

static void trace_checkpoint(Gen3Battle *battle, uint16_t point) {
    trace_emit(battle, (Gen3TraceRecord){
        .kind = GEN3_TRACE_CHECKPOINT,
        .semantic_point = point,
    });
}

static void trace_request(Gen3Battle *battle) {
    Gen3TraceRecord record = {
        .kind = GEN3_TRACE_REQUEST,
        .semantic_point = GEN3_TRACE_POINT_REQUEST,
        .value.request.phase = trace_phase_value(battle->phase),
    };
    for (uint8_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        assert(gen3_battle_legal_actions(
            battle, side, &record.value.request.legal_mask[side]
        ) == GEN3_OK);
    }
    trace_emit(battle, record);
}

static void trace_phase_transition(
    Gen3Battle *battle, Gen3Phase before, Gen3Phase after
) {
    if (memcmp(&before, &after, sizeof(before)) == 0) return;
    trace_emit(battle, (Gen3TraceRecord){
        .kind = GEN3_TRACE_PHASE,
        .value.phase = {
            .before = trace_phase_value(before),
            .after = trace_phase_value(after),
        },
    });
}

static void trace_protocol(Gen3Battle *battle, Gen3BattleEvent event) {
    trace_emit(battle, (Gen3TraceRecord){
        .kind = GEN3_TRACE_PROTOCOL,
        .value.protocol = event,
    });
}

static void trace_queue_action(
    Gen3Battle *battle, const Gen3Action *action, uint16_t operation,
    uint16_t index
) {
    assert(action != NULL);
    trace_emit(battle, (Gen3TraceRecord){
        .kind = GEN3_TRACE_QUEUE_ITEM,
        .value.queue = {
            .stable_id = action->trace_stable_id,
            .operation = operation,
            .index = index,
            .action_kind = (uint8_t)action->kind,
            .side = action->side,
            .queue_count = battle->action_queue.count,
        },
    });
}
#else
#define trace_protocol(battle, event) ((void)0)
#endif

typedef struct {
    uint8_t kind;
    uint16_t id;
} Gen3EffectRef;

typedef enum {
    GEN3_HOLDER_NONE = 0,
    GEN3_HOLDER_POKEMON,
    GEN3_HOLDER_SIDE,
} Gen3HolderKind;

typedef struct {
    Gen3HolderKind kind;
    uint8_t side;
    uint8_t slot;
} Gen3EffectHolder;

typedef struct {
    uint16_t event_id;
    Gen3EffectRef effect;
    Gen3EffectHolder holder;
    Gen3EffectHolder target;
    Gen3EffectHolder source;
    uint32_t insertion_order;
} Gen3RuntimeEvent;

static uint32_t random_below(uint32_t output, uint32_t limit);
static int compare_ordered_records(
    const Gen3OrderedRecord *left, const Gen3OrderedRecord *right
);
static void sort_ordered_records(
    Gen3Battle *battle, Gen3OrderedRecord *records, size_t count,
    uint16_t trace_label
);

enum {
    GEN3_EFFECT_DISPATCH_UNKNOWN = -1,
    GEN3_EFFECT_DISPATCH_NO_HANDLER = 0,
    GEN3_EFFECT_DISPATCH_HANDLED = 1,
};

static const Gen3EffectDescriptor *find_effect_descriptor(
    Gen3EffectRef effect
) {
    for (size_t index = 0; index < GEN3_EFFECT_DESCRIPTOR_COUNT; index++) {
        const Gen3EffectDescriptor *descriptor = &GEN3_EFFECT_DESCRIPTORS[index];
        if (descriptor->kind == effect.kind &&
            descriptor->effect_id == effect.id) {
            return descriptor;
        }
    }
    return NULL;
}

static const Gen3HandlerDescriptor *find_effect_handler(
    const Gen3EffectDescriptor *effect, uint16_t event_id
) {
    assert(effect != NULL);
    const Gen3HandlerDescriptor *result = NULL;
    for (size_t offset = 0; offset < effect->handler_count; offset++) {
        const Gen3HandlerDescriptor *handler =
            &GEN3_HANDLER_DESCRIPTORS[effect->first_handler + offset];
        if (handler->event_id != event_id) continue;
        assert(result == NULL);
        result = handler;
    }
    return result;
}

typedef enum {
    GEN3_MATERIALIZE_OK = 0,
    GEN3_MATERIALIZE_UNKNOWN_EFFECT,
    GEN3_MATERIALIZE_NO_HANDLER,
    GEN3_MATERIALIZE_CAPACITY,
} Gen3MaterializeResult;

typedef enum {
    GEN3_DISCOVER_OK = 0,
    GEN3_DISCOVER_UNSUPPORTED_EFFECT,
    GEN3_DISCOVER_CAPACITY,
    GEN3_DISCOVER_INVALID,
} Gen3DiscoverResult;

typedef enum {
    GEN3_DISCOVER_ACTIVE_ABILITIES = 1u << 0,
    GEN3_DISCOVER_ACTIVE_ITEMS = 1u << 1,
    GEN3_DISCOVER_SIDE_CONDITIONS = 1u << 2,
} Gen3DiscoveryScope;

typedef enum {
    GEN3_EVENT_ORDER_SPEED = 0,
    GEN3_EVENT_ORDER_LEFT_TO_RIGHT,
} Gen3EventOrderPolicy;

typedef struct {
    uint16_t event_id;
    uint8_t scope;
    Gen3EffectHolder target;
    Gen3EffectHolder source;
} Gen3DiscoveryRequest;

typedef struct {
    Gen3EffectRef effect;
    Gen3EffectHolder holder;
    int32_t speed;
} Gen3AttachedEffect;

enum { GEN3_ATTACHED_EFFECT_CAP = GEN3_SIDE_COUNT * 3 };

/* Showdown deliberately preserves discovery order for these events. They are
 * not ordinary speed-sorted relay events: TryHit walks target-facing effects
 * left-to-right, and EntryHazard walks side conditions left-to-right. */
static Gen3EventOrderPolicy event_order_policy(uint16_t event_id) {
    return event_id == GEN3_EFFECT_EVENT_TRY_HIT ||
        event_id == GEN3_EFFECT_EVENT_ENTRY_HAZARD ?
        GEN3_EVENT_ORDER_LEFT_TO_RIGHT : GEN3_EVENT_ORDER_SPEED;
}

/* Resolve one concrete effect holder into the event and comparator record
 * consumed by the runtime queue. Discovery owns descriptor priority data;
 * callers own applicability and enumerate holders in Showdown discovery
 * order. Insertion order is evidence, not a comparator key unless the caller
 * explicitly supplies effect_order. */
static Gen3MaterializeResult append_materialized_handler(
    Gen3RuntimeEvent *events,
    Gen3OrderedRecord *records,
    size_t capacity,
    size_t *count,
    Gen3RuntimeEvent event,
    int32_t speed,
    int32_t effect_order
) {
    if (events == NULL || records == NULL || count == NULL) {
        return GEN3_MATERIALIZE_CAPACITY;
    }
    if (*count >= capacity || *count >= UINT8_MAX) {
        return GEN3_MATERIALIZE_CAPACITY;
    }
    const Gen3EffectDescriptor *descriptor =
        find_effect_descriptor(event.effect);
    if (descriptor == NULL) return GEN3_MATERIALIZE_UNKNOWN_EFFECT;
    const Gen3HandlerDescriptor *handler =
        find_effect_handler(descriptor, event.event_id);
    if (handler == NULL) return GEN3_MATERIALIZE_NO_HANDLER;

    const size_t index = *count;
    event.insertion_order = (uint32_t)index;
    events[index] = event;
    records[index] = (Gen3OrderedRecord){
        .key = {
            /* compare_ordered_records maps zero to Showdown's default order,
             * sorting it after every explicit positive order. */
            .order = handler->order == GEN3_HANDLER_ORDER_DEFAULT ? 0u :
                (uint32_t)handler->order,
            .priority = handler->priority,
            .speed = speed,
            .sub_order = handler->sub_order,
            .effect_order = effect_order,
        },
        .payload_index = (uint8_t)index,
    };
    *count = index + 1;
    return GEN3_MATERIALIZE_OK;
}

static void attach_effect(
    Gen3AttachedEffect attached[GEN3_ATTACHED_EFFECT_CAP], size_t *count,
    Gen3EffectRef effect, Gen3EffectHolder holder, int32_t speed
) {
    assert(attached != NULL && count != NULL);
    assert(*count < GEN3_ATTACHED_EFFECT_CAP);
    attached[(*count)++] = (Gen3AttachedEffect){effect, holder, speed};
}

/* Discover the currently attached subset that the native descriptor table can
 * represent. Missing descriptors are an unsupported semantic boundary, not
 * evidence that an attached effect is irrelevant: only the descriptor can say
 * that it has no handler for this event.
 *
 * Validation and sizing precede every caller-visible write. A failure leaves
 * events, records, and count byte-for-byte unchanged. */
static Gen3DiscoverResult discover_effect_handlers(
    Gen3Battle *battle,
    Gen3DiscoveryRequest request,
    Gen3RuntimeEvent *events,
    Gen3OrderedRecord *records,
    size_t capacity,
    size_t *count
) {
    if (battle == NULL || count == NULL ||
        (capacity != 0 && (events == NULL || records == NULL)) ||
        request.event_id >= GEN3_EFFECT_EVENT_COUNT ||
        (request.scope & ~(GEN3_DISCOVER_ACTIVE_ABILITIES |
            GEN3_DISCOVER_ACTIVE_ITEMS | GEN3_DISCOVER_SIDE_CONDITIONS)) != 0) {
        return GEN3_DISCOVER_INVALID;
    }

    Gen3AttachedEffect attached[GEN3_ATTACHED_EFFECT_CAP];
    size_t attached_count = 0;
    size_t first_side = 0;
    size_t side_count = GEN3_SIDE_COUNT;
    if (request.event_id == GEN3_EFFECT_EVENT_TRY_HIT ||
        request.event_id == GEN3_EFFECT_EVENT_ENTRY_HAZARD) {
        if (request.target.kind == GEN3_HOLDER_NONE ||
            request.target.side >= GEN3_SIDE_COUNT) {
            return GEN3_DISCOVER_INVALID;
        }
        first_side = request.target.side;
        side_count = 1;
    }

    for (size_t offset = 0; offset < side_count; offset++) {
        size_t side = first_side + offset;
        const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
        int32_t speed = set->stats[5];
        Gen3EffectHolder pokemon = {
            GEN3_HOLDER_POKEMON, (uint8_t)side, 0
        };
        if ((request.scope & GEN3_DISCOVER_ACTIVE_ABILITIES) != 0 &&
            set->ability_id != 0) {
            attach_effect(attached, &attached_count,
                (Gen3EffectRef){GEN3_EFFECT_ABILITY, set->ability_id},
                pokemon, speed);
        }
        if ((request.scope & GEN3_DISCOVER_ACTIVE_ITEMS) != 0 &&
            set->item_id != 0) {
            attach_effect(attached, &attached_count,
                (Gen3EffectRef){GEN3_EFFECT_ITEM, set->item_id},
                pokemon, speed);
        }
        if ((request.scope & GEN3_DISCOVER_SIDE_CONDITIONS) != 0 &&
            battle->spikes[side] != 0) {
            attach_effect(attached, &attached_count,
                (Gen3EffectRef){
                    GEN3_EFFECT_SIDE_CONDITION, GEN3_CONDITION_SPIKES
                },
                (Gen3EffectHolder){GEN3_HOLDER_SIDE, (uint8_t)side, 0},
                speed);
        }
    }

    size_t discovered_count = 0;
    for (size_t index = 0; index < attached_count; index++) {
        const Gen3EffectDescriptor *descriptor =
            find_effect_descriptor(attached[index].effect);
        if (descriptor == NULL) return GEN3_DISCOVER_UNSUPPORTED_EFFECT;
        if (find_effect_handler(descriptor, request.event_id) != NULL) {
            discovered_count++;
        }
    }
    if (discovered_count > capacity || *count > capacity - discovered_count ||
        *count + discovered_count > UINT8_MAX) {
        return GEN3_DISCOVER_CAPACITY;
    }

    size_t committed = *count;
    for (size_t index = 0; index < attached_count; index++) {
        const Gen3EffectDescriptor *descriptor =
            find_effect_descriptor(attached[index].effect);
        if (find_effect_handler(descriptor, request.event_id) == NULL) continue;
        Gen3RuntimeEvent event = {
            .event_id = request.event_id,
            .effect = attached[index].effect,
            .holder = attached[index].holder,
            .target = request.target.kind == GEN3_HOLDER_NONE ?
                attached[index].holder : request.target,
            .source = request.source,
        };
        Gen3MaterializeResult result = append_materialized_handler(
            events, records, capacity, &committed, event,
            attached[index].speed, 0
        );
        assert(result == GEN3_MATERIALIZE_OK);
    }
    assert(committed == *count + discovered_count);
    *count = committed;
    return GEN3_DISCOVER_OK;
}

static void append_protocol_event(Gen3Battle *battle, Gen3BattleEvent event) {
    assert(battle != NULL);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    battle->events[battle->event_count++] = event;
    trace_protocol(battle, event);
}

static void record_switch(Gen3Battle *battle, uint8_t side) {
    assert(battle != NULL);
    assert(side < GEN3_SIDE_COUNT);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
    const Gen3PokemonState *state = &battle->state[side][0];
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_SWITCH,
        .side = side,
        .species_id = set->species_id,
        .hp = state->hp,
        .max_hp = set->stats[0],
    });
}

static void record_move(Gen3Battle *battle, uint8_t side, uint16_t move_id) {
    assert(battle != NULL);
    assert(side < GEN3_SIDE_COUNT);
    assert(move_id > 0 && move_id <= GEN3_MOVE_MAX_ID);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_MOVE,
        .side = side,
        .species_id = battle->teams[side].pokemon[0].species_id,
        .move_id = move_id,
    });
}

static void record_hp_event(Gen3Battle *battle, uint8_t kind, uint8_t side) {
    assert(battle != NULL);
    assert(kind == GEN3_EVENT_DAMAGE || kind == GEN3_EVENT_HEAL);
    assert(side < GEN3_SIDE_COUNT);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = kind,
        .side = side,
        .species_id = set->species_id,
        .hp = battle->state[side][0].hp,
        .max_hp = set->stats[0],
    });
}

static void record_fail(Gen3Battle *battle, uint8_t side, uint16_t move_id) {
    assert(battle != NULL);
    assert(side < GEN3_SIDE_COUNT);
    assert(move_id > 0 && move_id <= GEN3_MOVE_MAX_ID);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_FAIL,
        .side = side,
        .species_id = battle->teams[side].pokemon[0].species_id,
        .move_id = move_id,
    });
}

static void record_faint(Gen3Battle *battle, uint8_t side) {
    assert(battle != NULL);
    assert(side < GEN3_SIDE_COUNT);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_FAINT,
        .side = side,
        .species_id = battle->teams[side].pokemon[0].species_id,
    });
    int has_reserve = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        has_reserve |= battle->state[side][slot].hp > 0;
    }
    if (!has_reserve) {
        battle->done = 1;
        battle->winner_side = (int8_t)(1 - side);
        battle->force_switch_side = -1;
        battle->resume_residuals = 0;
    }
}

static void record_protect_event(Gen3Battle *battle, uint8_t kind, uint8_t side) {
    assert(kind == GEN3_EVENT_PROTECT || kind == GEN3_EVENT_BLOCK);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = kind,
        .side = side,
        .species_id = battle->teams[side].pokemon[0].species_id,
        .move_id = GEN3_MOVE_PROTECT,
    });
}

static void record_status(Gen3Battle *battle, uint8_t side, uint8_t status) {
    assert(status > GEN3_STATUS_NONE && status <= GEN3_STATUS_FREEZE);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_STATUS,
        .side = side,
        .status = status,
        .species_id = battle->teams[side].pokemon[0].species_id,
    });
}

static void record_side_start(Gen3Battle *battle, uint8_t side, uint16_t move_id) {
    assert(side < GEN3_SIDE_COUNT && move_id == GEN3_MOVE_SPIKES);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_SIDE_START,
        .side = side,
        .move_id = move_id,
    });
}

static void record_volatile_start(Gen3Battle *battle, uint8_t side, uint16_t move_id) {
    assert(side < GEN3_SIDE_COUNT && move_id == GEN3_MOVE_LEECH_SEED);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = GEN3_EVENT_VOLATILE_START,
        .side = side,
        .species_id = battle->teams[side].pokemon[0].species_id,
        .move_id = move_id,
    });
}

static void record_stat_change(
    Gen3Battle *battle, uint8_t side, uint8_t stat, uint8_t amount, int lowered
) {
    assert(stat >= GEN3_STAT_ATK && stat <= GEN3_STAT_SPE);
    assert(amount > 0 && amount <= 6);
    assert(battle->event_count < GEN3_MAX_EVENTS);
    append_protocol_event(battle, (Gen3BattleEvent){
        .kind = lowered ? GEN3_EVENT_UNBOOST : GEN3_EVENT_BOOST,
        .side = side,
        .status = stat,
        .amount = amount,
        .species_id = battle->teams[side].pokemon[0].species_id,
    });
}

static int fail(char *error, size_t capacity, int code, const char *message) {
    if (error != NULL && capacity > 0) {
        (void)snprintf(error, capacity, "%s", message);
    }
    return code;
}

static int valid_header(uint32_t version, uint32_t actual, size_t expected) {
    return version == GEN3_ABI_VERSION && actual == expected;
}

static int validate_layout(const Gen3BattleInit *init) {
    if (!valid_header(init->abi_version, init->struct_size, sizeof(*init))) return 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        const Gen3BattleTeam *team = &init->teams[side];
        if (!valid_header(team->abi_version, team->struct_size, sizeof(*team))) return 0;
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            const Gen3PokemonSet *set = &team->pokemon[slot];
            if (!valid_header(set->abi_version, set->struct_size, sizeof(*set))) return 0;
        }
    }
    return 1;
}

static int validate_set(const Gen3PokemonSet *set) {
    if (set->species_id == 0 || set->species_id > GEN3_SPECIES_MAX_ID) return 0;
    if (GEN3_SPECIES[set->species_id].name == NULL) return 0;
    if (set->ability_id == 0 || set->ability_id > GEN3_ABILITY_MAX_ID) return 0;
    if (GEN3_ABILITY_NAMES[set->ability_id] == NULL) return 0;
    if (set->item_id > GEN3_ITEM_MAX_ID) return 0;
    if (set->item_id != 0 && GEN3_ITEM_NAMES[set->item_id] == NULL) return 0;
    if (set->level == 0 || set->level > 100 || set->gender > 2 || set->shiny > 1) return 0;
    for (size_t stat = 0; stat < 6; stat++) {
        if (set->stats[stat] == 0) return 0;
    }
    int moves = 0;
    for (size_t slot = 0; slot < GEN3_MOVE_SLOTS; slot++) {
        if ((set->move_ids[slot] == 0) != (set->max_pp[slot] == 0)) return 0;
        if (set->move_ids[slot] > GEN3_MOVE_MAX_ID) return 0;
        if (set->move_ids[slot] != 0 && GEN3_MOVES[set->move_ids[slot]].id == 0) return 0;
        moves += set->move_ids[slot] != 0;
    }
    return moves > 0;
}

static int validate_init(const Gen3BattleInit *init) {
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        const Gen3BattleTeam *team = &init->teams[side];
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            if (!validate_set(&team->pokemon[slot])) return 0;
        }
    }
    return 1;
}

uint32_t gen3_abi_version(void) { return GEN3_ABI_VERSION; }
size_t gen3_sizeof_pokemon_set(void) { return sizeof(Gen3PokemonSet); }
size_t gen3_sizeof_battle_team(void) { return sizeof(Gen3BattleTeam); }
size_t gen3_sizeof_battle_init(void) { return sizeof(Gen3BattleInit); }
size_t gen3_sizeof_battle_snapshot(void) { return sizeof(Gen3BattleSnapshot); }

int gen3_prng_next(uint16_t seed[4], uint32_t *out) {
    if (seed == NULL || out == NULL) return GEN3_INVALID_ARGUMENT;
    uint64_t state = ((uint64_t)seed[0] << 48) |
        ((uint64_t)seed[1] << 32) |
        ((uint64_t)seed[2] << 16) |
        (uint64_t)seed[3];
    state = state * UINT64_C(0x5D588B656C078965) + UINT64_C(0x269EC3);
    seed[0] = (uint16_t)(state >> 48);
    seed[1] = (uint16_t)(state >> 32);
    seed[2] = (uint16_t)(state >> 16);
    seed[3] = (uint16_t)state;
    *out = (uint32_t)(state >> 32);
    return GEN3_OK;
}

static uint32_t scheduler_prng_below(
    Gen3Battle *battle, uint16_t label, uint32_t limit
) {
    assert(battle != NULL);
    assert(label == GEN3_TRACE_PRNG_QUEUE_TIE_SHUFFLE ||
        label == GEN3_TRACE_PRNG_QUEUE_TIE_INSERT);
    assert(limit > 0);
    uint16_t before[4];
    memcpy(before, battle->seed, sizeof(before));
    uint32_t raw = 0;
    assert(gen3_prng_next(battle->seed, &raw) == GEN3_OK);
    uint32_t result = random_below(raw, limit);
#ifdef GEN3_VERIFY_TRACE
    Gen3TraceRecord record = {
        .kind = GEN3_TRACE_PRNG,
        .value.prng = {
            .label = label,
            .operation = GEN3_TRACE_PRNG_BELOW,
            .argument0 = limit,
            .raw_output = raw,
            .result = result,
        },
    };
    memcpy(record.value.prng.seed_before, before, sizeof(before));
    memcpy(record.value.prng.seed_after, battle->seed, sizeof(battle->seed));
    trace_emit(battle, record);
#else
    (void)before;
#endif
    return result;
}

int gen3_battle_create(
    const Gen3BattleInit *init,
    Gen3Battle **out,
    char *error,
    size_t error_capacity
) {
    if (out == NULL) return fail(error, error_capacity, GEN3_INVALID_ARGUMENT, "out is null");
    *out = NULL;
    if (init == NULL) return fail(error, error_capacity, GEN3_INVALID_ARGUMENT, "init is null");
    if (!validate_layout(init)) {
        return fail(
            error, error_capacity, GEN3_INVALID_LAYOUT,
            "unsupported Gen3BattleInit layout"
        );
    }
    if (!validate_init(init)) {
        return fail(error, error_capacity, GEN3_INVALID_TEAM, "invalid normalized Gen 3 team");
    }

    Gen3Battle *battle = calloc(1, sizeof(*battle));
    if (battle == NULL) return fail(error, error_capacity, GEN3_OUT_OF_MEMORY, "allocation failed");
    memcpy(battle->teams, init->teams, sizeof(battle->teams));
    memcpy(battle->seed, init->seed, sizeof(battle->seed));
    battle->turn = 1;
    battle->force_switch_side = -1;
    battle->winner_side = -1;
    battle->phase = (Gen3Phase){
        .kind = GEN3_PHASE_NORMAL_REQUEST,
        .required_side_mask = (uint8_t)((1u << GEN3_SIDE_COUNT) - 1u),
    };
    /* Showdown resolves the two initial lead placements as tied start actions,
     * consuming one shuffle draw before the first decision request. */
    uint32_t initial_order = 0;
    int rng_result = gen3_prng_next(battle->seed, &initial_order);
    assert(rng_result == GEN3_OK);
    (void)initial_order;
    if (battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5]) {
        /* Equal-speed leads also tie in the remaining ordered start-event
         * queues before Showdown issues its first request. */
        for (size_t frame = 0; frame < 4; frame++) {
            rng_result = gen3_prng_next(battle->seed, &initial_order);
            assert(rng_result == GEN3_OK);
        }
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            const Gen3PokemonSet *set = &battle->teams[side].pokemon[slot];
            battle->state[side][slot].hp = set->stats[0];
            memcpy(battle->state[side][slot].pp, set->max_pp, sizeof(set->max_pp));
        }
    }
    record_switch(battle, 0);
    record_switch(battle, 1);
    *out = battle;
    return GEN3_OK;
}

void gen3_battle_destroy(Gen3Battle *battle) { free(battle); }

#ifdef GEN3_VERIFY_TRACE
int gen3_battle_set_trace_sink(Gen3Battle *battle, const Gen3TraceSink *sink) {
    if (battle == NULL) return GEN3_INVALID_ARGUMENT;
    if (sink == NULL) {
        memset(&battle->trace_sink, 0, sizeof(battle->trace_sink));
        return GEN3_OK;
    }
    if (sink->abi_version != GEN3_TRACE_ABI_VERSION ||
        sink->struct_size != sizeof(*sink) || sink->emit == NULL) {
        return GEN3_INVALID_LAYOUT;
    }
    battle->trace_sink = *sink;
    battle->trace_emission_boundary = battle->trace_boundary;
    trace_checkpoint(battle, GEN3_TRACE_POINT_INSTALL);
    trace_request(battle);
    return GEN3_OK;
}
#endif

static int active_has_no_pp(const Gen3Battle *battle, size_t side) {
    assert(battle != NULL && side < GEN3_SIDE_COUNT);
    for (size_t move = 0; move < GEN3_MOVE_SLOTS; move++) {
        if (battle->state[side][0].pp[move] > 0) return 0;
    }
    return 1;
}

int gen3_battle_legal_actions(
    const Gen3Battle *battle,
    uint8_t side,
    uint16_t *out_mask
) {
    if (battle == NULL || out_mask == NULL || side >= GEN3_SIDE_COUNT) return GEN3_INVALID_ARGUMENT;
    if (battle->done) {
        *out_mask = 0;
        return GEN3_OK;
    }
    uint16_t mask = 0;
    if (battle->force_switch_side != -1) {
        if (battle->force_switch_side >= 0 &&
            side != (uint8_t)battle->force_switch_side) {
            *out_mask = 0;
            return GEN3_OK;
        }
        for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
            if (battle->state[side][slot].hp > 0) mask |= (uint16_t)(1u << (slot + 3));
        }
        *out_mask = mask;
        return GEN3_OK;
    }
    const Gen3PokemonState *active = &battle->state[side][0];
    for (size_t move = 0; move < GEN3_MOVE_SLOTS; move++) {
        if (active->pp[move] > 0) {
            mask |= (uint16_t)(1u << move);
        }
    }
    /* Showdown represents the synthetic Struggle request as move slot 1.
     * The ABI follows that request-level encoding; the turn resolver must
     * interpret action 0 contextually when no real move has PP remaining. */
    if (active_has_no_pp(battle, side)) mask |= 1u;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[side][slot].hp > 0) mask |= (uint16_t)(1u << (slot + 3));
    }
    *out_mask = mask;
    return GEN3_OK;
}

static int switch_slot(int8_t action) {
    if (action < 4 || action > 8) return -1;
    return action - 3;
}

static Gen3Choice decode_choice(uint8_t side, int8_t encoded) {
    assert(side < GEN3_SIDE_COUNT);
    assert(encoded >= -1 && encoded <= 8);
    if (encoded == -1) {
        return (Gen3Choice){.kind = GEN3_CHOICE_NONE, .side = side};
    }
    if (encoded < 4) {
        return (Gen3Choice){
            .kind = GEN3_CHOICE_MOVE,
            .side = side,
            .slot = (uint8_t)encoded,
        };
    }
    return (Gen3Choice){
        .kind = GEN3_CHOICE_SWITCH,
        .side = side,
        .slot = (uint8_t)switch_slot(encoded),
    };
}

static void clear_action_queue(Gen3ActionQueue *queue) {
    assert(queue != NULL);
    queue->head = 0;
    queue->count = 0;
    queue->value_count = 0;
}

#ifdef GEN3_VERIFY_TRACE
static void cancel_action_queue(Gen3Battle *battle) {
    assert(battle != NULL);
    Gen3ActionQueue *queue = &battle->action_queue;
    for (uint16_t index = 0; index < queue->count; index++) {
        const Gen3OrderedRecord *record = &queue->order[queue->head + index];
        trace_queue_action(battle, &queue->values[record->payload_index],
            GEN3_TRACE_QUEUE_CANCEL, index);
    }
    clear_action_queue(&battle->action_queue);
}
#endif

static void append_action(
    Gen3Battle *battle, Gen3Action action, uint16_t trace_operation
) {
    assert(battle != NULL);
    Gen3ActionQueue *queue = &battle->action_queue;
    assert(queue->head + queue->count < GEN3_ACTION_QUEUE_CAP);
    assert(queue->value_count < GEN3_ACTION_QUEUE_CAP);
#ifdef GEN3_VERIFY_TRACE
    assert(battle->trace_next_action_id != UINT32_MAX);
    if (action.trace_stable_id == 0) {
        action.trace_stable_id = ++battle->trace_next_action_id;
    }
#else
    (void)trace_operation;
#endif
    uint8_t payload_index = queue->value_count++;
    queue->values[payload_index] = action;
#ifdef GEN3_VERIFY_TRACE
    uint16_t index = (uint16_t)queue->count;
#endif
    queue->order[queue->head + queue->count++] = (Gen3OrderedRecord){
        .key = action.key,
        .payload_index = payload_index,
    };
#ifdef GEN3_VERIFY_TRACE
    trace_queue_action(battle, &queue->values[payload_index], trace_operation, index);
#endif
}

static void push_action(Gen3Battle *battle, Gen3Action action) {
    append_action(battle, action, GEN3_TRACE_QUEUE_COMPILE);
}

/* Showdown's insertChoice inserts into only the unconsumed queue. Exact ties
 * choose uniformly among every physical insertion position in the tie range. */
static void insert_action(Gen3Battle *battle, Gen3Action action) {
    Gen3ActionQueue *queue = &battle->action_queue;
    assert(queue->head + queue->count < GEN3_ACTION_QUEUE_CAP);
    assert(queue->value_count < GEN3_ACTION_QUEUE_CAP);
    uint8_t payload = queue->value_count++;
#ifdef GEN3_VERIFY_TRACE
    assert(battle->trace_next_action_id != UINT32_MAX);
    action.trace_stable_id = ++battle->trace_next_action_id;
#endif
    queue->values[payload] = action;
    Gen3OrderedRecord record = {.key = action.key, .payload_index = payload};
    size_t begin = queue->head;
    size_t end = begin + queue->count;
    size_t lower = begin;
    while (lower < end && compare_ordered_records(&queue->order[lower], &record) < 0) {
        lower++;
    }
    size_t upper = lower;
    while (upper < end && compare_ordered_records(&queue->order[upper], &record) == 0) {
        upper++;
    }
    size_t insertion = lower;
    if (upper > lower) {
        insertion += scheduler_prng_below(
            battle, GEN3_TRACE_PRNG_QUEUE_TIE_INSERT,
            (uint32_t)(upper - lower + 1)
        );
    }
    memmove(&queue->order[insertion + 1], &queue->order[insertion],
        (end - insertion) * sizeof(queue->order[0]));
    queue->order[insertion] = record;
    queue->count++;
#ifdef GEN3_VERIFY_TRACE
    trace_queue_action(battle, &queue->values[payload],
        GEN3_TRACE_QUEUE_INSERT, (uint16_t)(insertion - begin));
#endif
}

static Gen3Action take_action(Gen3Battle *battle, uint16_t trace_operation) {
    assert(battle != NULL);
    Gen3ActionQueue *queue = &battle->action_queue;
    assert(queue->count > 0);
    Gen3OrderedRecord record = queue->order[queue->head++];
    assert(record.payload_index < GEN3_ACTION_QUEUE_CAP);
    Gen3Action action = queue->values[record.payload_index];
    queue->count--;
#ifdef GEN3_VERIFY_TRACE
    trace_queue_action(battle, &action, trace_operation, 0);
#else
    (void)trace_operation;
#endif
    if (queue->count == 0) clear_action_queue(queue);
    return action;
}

static Gen3Action pop_action(Gen3Battle *battle) {
    return take_action(battle, GEN3_TRACE_QUEUE_POP);
}

static int action_queue_is_residual_continuation(const Gen3ActionQueue *queue) {
    if (queue == NULL || queue->count != 1) return 0;
    const Gen3OrderedRecord *record = &queue->order[queue->head];
    assert(record->payload_index < queue->value_count);
    return queue->values[record->payload_index].kind == GEN3_ACTION_RESIDUAL;
}

/* A forced-switch request suspends execution without discarding the
 * unconsumed queue. Legacy resolvers still communicate that suspension with
 * resume_residuals; normalize it once at the scheduler boundary into the
 * explicit continuation consumed by the action pump. */
static void materialize_legacy_continuation(Gen3Battle *battle) {
    assert(battle != NULL);
    if (battle->done || !battle->resume_residuals ||
        battle->force_switch_side == -1) return;
    if (battle->action_queue.count != 0) {
        assert(action_queue_is_residual_continuation(&battle->action_queue));
        return;
    }
    push_action(battle, (Gen3Action){
        .kind = GEN3_ACTION_RESIDUAL,
        .key = {.order = 300},
    });
}

static void sync_phase_from_legacy_request(Gen3Battle *battle) {
    assert(battle != NULL);
    materialize_legacy_continuation(battle);
#ifdef GEN3_VERIFY_TRACE
    Gen3Phase before = battle->phase;
#endif
    Gen3Phase next;
    if (battle->done) {
        next = (Gen3Phase){.kind = GEN3_PHASE_TERMINAL};
    } else if (battle->force_switch_side >= 0) {
        next = (Gen3Phase){
            .kind = GEN3_PHASE_FORCED_SWITCH_REQUEST,
            .required_side_mask = (uint8_t)(1u << battle->force_switch_side),
            .forced_first_side = (uint8_t)battle->force_switch_side,
            .continuation = action_queue_is_residual_continuation(
                &battle->action_queue) ?
                GEN3_CONTINUE_RESIDUAL : GEN3_CONTINUE_NONE,
        };
    } else if (battle->force_switch_side <= -2) {
        next = (Gen3Phase){
            .kind = GEN3_PHASE_FORCED_SWITCH_REQUEST,
            .required_side_mask = (uint8_t)((1u << GEN3_SIDE_COUNT) - 1u),
            .forced_first_side = (uint8_t)(-2 - battle->force_switch_side),
            .continuation = action_queue_is_residual_continuation(
                &battle->action_queue) ?
                GEN3_CONTINUE_RESIDUAL : GEN3_CONTINUE_NONE,
        };
    } else {
        next = (Gen3Phase){
            .kind = GEN3_PHASE_NORMAL_REQUEST,
            .required_side_mask = (uint8_t)((1u << GEN3_SIDE_COUNT) - 1u),
        };
    }
    battle->phase = next;
#ifdef GEN3_VERIFY_TRACE
    trace_phase_transition(battle, before, next);
#endif
}

/* A forced replacement can suspend an ordinary turn with its residual action
 * still queued.  The replacement itself is not a new turn: the next turn
 * begins only after that saved tail has actually drained and the engine is
 * about to expose a normal move request again.  Keep that transition owned by
 * the scheduler instead of whichever move happened to cause the faint. */
static void finish_resumed_turn(Gen3Battle *battle) {
    assert(battle != NULL);
    assert(battle->action_queue.count == 0);
    assert(battle->force_switch_side == -1);
    assert(battle->resume_residuals == 0);
    sync_phase_from_legacy_request(battle);
    assert(battle->phase.kind == GEN3_PHASE_NORMAL_REQUEST || battle->done);
}

static int switch_only_ability(uint16_t ability) {
    return ability == GEN3_ABILITY_STURDY || ability == GEN3_ABILITY_LEVITATE ||
        ability == GEN3_ABILITY_NATURAL_CURE || ability == GEN3_ABILITY_TORRENT;
}

static int switch_only_team(const Gen3Battle *battle) {
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            const uint16_t ability = battle->teams[side].pokemon[slot].ability_id;
            if (!switch_only_ability(ability)) return 0;
        }
    }
    return 1;
}

static void swap_pokemon(Gen3Battle *battle, size_t side, size_t slot);
static int has_type(const Gen3PokemonSet *set, uint8_t type);

static int simple_items_team(const Gen3Battle *battle) {
    assert(battle != NULL);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            uint16_t item = battle->teams[side].pokemon[slot].item_id;
            if (item != 0 && item != GEN3_ITEM_LEFTOVERS) return 0;
        }
    }
    return 1;
}

static int fixed_damage_slice_supported(
    const Gen3Battle *battle, size_t move_side, size_t move_slot,
    size_t switch_side, size_t switch_target
) {
    assert(battle != NULL);
    assert(move_side < GEN3_SIDE_COUNT && switch_side < GEN3_SIDE_COUNT);
    assert(move_side != switch_side && move_slot < GEN3_MOVE_SLOTS);
    assert(switch_target > 0 && switch_target < GEN3_TEAM_SIZE);
    if (!switch_only_team(battle)) return 0;
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    if (attacker->move_ids[move_slot] != GEN3_MOVE_SEISMIC_TOSS) return 0;
    if (battle->state[move_side][0].pp[move_slot] == 0) return 0;
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3SpeciesData *species = &GEN3_SPECIES[target->species_id];
    for (size_t type = 0; type < species->type_count; type++) {
        if (species->types[type] == GEN3_TYPE_GHOST) return 0;
    }
    return simple_items_team(battle);
}

static void apply_leftovers(Gen3Battle *battle);
static void apply_leftovers_side(Gen3Battle *battle, size_t side);

static uint16_t spikes_damage(
    const Gen3Battle *battle, size_t side, size_t slot
) {
    uint8_t layers = battle->spikes[side];
    if (layers == 0) return 0;
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[slot];
    if (set->ability_id == GEN3_ABILITY_LEVITATE || has_type(set, GEN3_TYPE_FLYING)) {
        return 0;
    }
    uint16_t damage = layers == 1 ? (uint16_t)(set->stats[0] / 8) :
        layers == 2 ? (uint16_t)(set->stats[0] / 6) :
        (uint16_t)(set->stats[0] / 4);
    return damage == 0 ? 1 : damage;
}

static void handle_spikes_entry(
    Gen3Battle *battle, const Gen3RuntimeEvent *event
) {
    assert(battle != NULL && event != NULL);
    assert(event->holder.kind == GEN3_HOLDER_SIDE);
    assert(event->target.kind == GEN3_HOLDER_POKEMON);
    assert(event->holder.side == event->target.side);
    assert(event->target.slot == 0);
    size_t side = event->target.side;
    uint16_t damage = spikes_damage(battle, side, 0);
    if (damage == 0) return;
    battle->state[side][0].hp = battle->state[side][0].hp > damage ?
        (uint16_t)(battle->state[side][0].hp - damage) : 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)side);
    if (battle->state[side][0].hp != 0) return;
    battle->state[side][0].status = GEN3_STATUS_NONE;
    battle->state[side][0].toxic_counter = 0;
    battle->state[side][0].leech_seeded = 0;
    record_faint(battle, (uint8_t)side);
}

static void handle_leftovers_residual(
    Gen3Battle *battle, const Gen3RuntimeEvent *event
) {
    assert(battle != NULL && event != NULL);
    assert(event->holder.kind == GEN3_HOLDER_POKEMON);
    assert(event->target.kind == GEN3_HOLDER_POKEMON);
    assert(event->holder.side == event->target.side);
    assert(event->holder.slot == event->target.slot);
    size_t side = event->target.side;
    size_t slot = event->target.slot;
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[slot];
    Gen3PokemonState *state = &battle->state[side][slot];
    if (state->hp == 0 || state->hp >= set->stats[0]) return;
    uint16_t healing = (uint16_t)(set->stats[0] / 16);
    if (healing == 0) healing = 1;
    uint32_t healed = (uint32_t)state->hp + healing;
    state->hp = (uint16_t)(healed > set->stats[0] ? set->stats[0] : healed);
    assert(slot == 0);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
}

static void handle_natural_cure_switch_out(
    Gen3Battle *battle, const Gen3RuntimeEvent *event
) {
    assert(battle != NULL && event != NULL);
    assert(event->holder.kind == GEN3_HOLDER_POKEMON);
    assert(event->target.kind == GEN3_HOLDER_POKEMON);
    assert(event->holder.side == event->target.side);
    assert(event->holder.slot == event->target.slot);
    Gen3PokemonState *state =
        &battle->state[event->target.side][event->target.slot];
    state->status = GEN3_STATUS_NONE;
    state->toxic_counter = 0;
}

static int dispatch_effect_event(
    Gen3Battle *battle, const Gen3RuntimeEvent *event
) {
    assert(battle != NULL && event != NULL);
    const Gen3EffectDescriptor *effect =
        find_effect_descriptor(event->effect);
    if (effect == NULL) return GEN3_EFFECT_DISPATCH_UNKNOWN;
    const Gen3HandlerDescriptor *handler =
        find_effect_handler(effect, event->event_id);
    if (handler == NULL) return GEN3_EFFECT_DISPATCH_NO_HANDLER;
    switch (handler->native_handler_id) {
    case GEN3_NATIVE_HANDLER_SPIKES_ENTRY:
        handle_spikes_entry(battle, event);
        break;
    case GEN3_NATIVE_HANDLER_LEFTOVERS_RESIDUAL:
        handle_leftovers_residual(battle, event);
        break;
    case GEN3_NATIVE_HANDLER_NATURAL_CURE_SWITCH_OUT:
        handle_natural_cure_switch_out(battle, event);
        break;
    default:
        assert(!"generated handler is not implemented by this runtime slice");
        return GEN3_EFFECT_DISPATCH_UNKNOWN;
    }
    return GEN3_EFFECT_DISPATCH_HANDLED;
}

static void apply_leftovers_side(Gen3Battle *battle, size_t side) {
    assert(battle != NULL && side < GEN3_SIDE_COUNT);
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
    if (set->item_id != GEN3_ITEM_LEFTOVERS) return;
    Gen3RuntimeEvent event = {
        .event_id = GEN3_EFFECT_EVENT_RESIDUAL,
        .effect = {GEN3_EFFECT_ITEM, set->item_id},
        .holder = {GEN3_HOLDER_POKEMON, (uint8_t)side, 0},
        .target = {GEN3_HOLDER_POKEMON, (uint8_t)side, 0},
        .source = {GEN3_HOLDER_NONE, 0, 0},
    };
    assert(dispatch_effect_event(battle, &event) ==
        GEN3_EFFECT_DISPATCH_HANDLED);
}

static void apply_leftovers(Gen3Battle *battle) {
    assert(battle != NULL);
    assert(battle->event_count < GEN3_MAX_EVENTS - GEN3_SIDE_COUNT);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        apply_leftovers_side(battle, side);
    }
}

static int apply_spikes_entry_allow_faint(Gen3Battle *battle, size_t side) {
    assert(battle != NULL && side < GEN3_SIDE_COUNT);
    if (battle->spikes[side] == 0) return 0;
    uint16_t hp_before = battle->state[side][0].hp;
    Gen3RuntimeEvent event = {
        .event_id = GEN3_EFFECT_EVENT_ENTRY_HAZARD,
        .effect = {GEN3_EFFECT_SIDE_CONDITION, GEN3_CONDITION_SPIKES},
        .holder = {GEN3_HOLDER_SIDE, (uint8_t)side, 0},
        .target = {GEN3_HOLDER_POKEMON, (uint8_t)side, 0},
        .source = {GEN3_HOLDER_NONE, 0, 0},
    };
    assert(dispatch_effect_event(battle, &event) ==
        GEN3_EFFECT_DISPATCH_HANDLED);
    return hp_before > 0 && battle->state[side][0].hp == 0;
}

static void apply_spikes_entry(Gen3Battle *battle, size_t side) {
    assert(!apply_spikes_entry_allow_faint(battle, side));
}

static uint32_t random_below(uint32_t output, uint32_t limit);
static void apply_toxic_residual(Gen3Battle *battle, size_t side);
static void apply_burn_residual(Gen3Battle *battle, size_t side);
static void apply_leech_seed_residual(Gen3Battle *battle, size_t seeded_side);
static void consume_rng_frames(Gen3Battle *battle, size_t count);
static int resolve_whirlwind_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
);
static int resolve_leech_seed_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
);
static int resolve_will_o_wisp_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
);

static int resolve_fixed_damage_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    assert(battle != NULL);
    assert((action_p1 < 4) != (action_p2 < 4));
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    int8_t switch_action = switch_side == 0 ? action_p1 : action_p2;
    size_t switch_target = (size_t)switch_slot(switch_action);
    if (!fixed_damage_slice_supported(
        battle, move_side, move_slot, switch_side, switch_target
    )) return GEN3_UNSUPPORTED_ACTION;
    if (battle->state[switch_side][switch_target].hp == 0) return GEN3_ILLEGAL_ACTION;
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    int outgoing_speed_tie =
        battle->teams[switch_side].pokemon[0].stats[5] ==
            battle->teams[move_side].pokemon[0].stats[5];
    uint32_t entry_and_move_damage =
        (uint32_t)entry_damage + battle->teams[move_side].pokemon[0].level;
    if (battle->state[switch_side][switch_target].hp <= entry_and_move_damage &&
        !outgoing_speed_tie) {
        consume_rng_frames(battle, 4);
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        Gen3PokemonState *attacker_state = &battle->state[move_side][0];
        const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
        uint16_t move_id = attacker->move_ids[move_slot];
        attacker_state->pp[move_slot]--;
        attacker_state->protect_counter = 0;
        record_move(battle, (uint8_t)move_side, move_id);
        Gen3PokemonState *target_state = &battle->state[switch_side][0];
        target_state->hp = 0;
        target_state->status = GEN3_STATUS_NONE;
        target_state->toxic_counter = 0;
        target_state->leech_seeded = 0;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)switch_side);
        record_faint(battle, (uint8_t)switch_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)switch_side;
            battle->resume_residuals = 1;
        }
        return GEN3_OK;
    }
    if (battle->state[switch_side][switch_target].hp <= entry_and_move_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    if (outgoing_speed_tie) consume_rng_frames(battle, 2);

    Gen3PokemonState *attacker_state = &battle->state[move_side][0];
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    uint16_t move_id = attacker->move_ids[move_slot];
    attacker_state->pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move_id);

    uint32_t accuracy_roll = 0;
    assert(gen3_prng_next(battle->seed, &accuracy_roll) == GEN3_OK);
    assert((uint32_t)(((uint64_t)accuracy_roll * 100) >> 32) < 100);
    Gen3PokemonState *target_state = &battle->state[switch_side][0];
    uint16_t damage = attacker->level;
    target_state->hp = target_state->hp > damage ? target_state->hp - damage : 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)switch_side);

    uint32_t residual_order = 0;
    size_t residual_first = 0;
    if (battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5]) {
        for (size_t frame = 0; frame < 7; frame++) {
            assert(gen3_prng_next(battle->seed, &residual_order) == GEN3_OK);
            if (frame == 4) residual_first = random_below(residual_order, 2);
        }
    } else {
        assert(gen3_prng_next(battle->seed, &residual_order) == GEN3_OK);
        residual_first = battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1 : 0;
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    return GEN3_OK;
}

static void consume_rng_frames(Gen3Battle *battle, size_t count) {
    assert(battle != NULL);
    assert(count > 0);
    for (size_t frame = 0; frame < count; frame++) {
        uint32_t ignored = 0;
        assert(gen3_prng_next(battle->seed, &ignored) == GEN3_OK);
    }
}

static uint32_t random_below(uint32_t output, uint32_t limit) {
    assert(limit > 0);
    return (uint32_t)(((uint64_t)output * limit) >> 32);
}

static int compare_order_keys(
    const Gen3OrderKey *left, const Gen3OrderKey *right
) {
    assert(left != NULL && right != NULL);
    uint64_t left_order = left->order != 0 ?
        left->order : (UINT64_C(1) << 32);
    uint64_t right_order = right->order != 0 ?
        right->order : (UINT64_C(1) << 32);
    if (left_order != right_order) {
        return left_order < right_order ? -1 : 1;
    }
    if (left->priority != right->priority) {
        return left->priority > right->priority ? -1 : 1;
    }
    if (left->speed != right->speed) {
        return left->speed > right->speed ? -1 : 1;
    }
    if (left->sub_order != right->sub_order) {
        return left->sub_order < right->sub_order ? -1 : 1;
    }
    if (left->effect_order != right->effect_order) {
        return left->effect_order < right->effect_order ? -1 : 1;
    }
    return 0;
}

static int compare_ordered_records(
    const Gen3OrderedRecord *left, const Gen3OrderedRecord *right
) {
    assert(left != NULL && right != NULL);
    return compare_order_keys(&left->key, &right->key);
}

static void sort_ordered_records(
    Gen3Battle *battle, Gen3OrderedRecord *records, size_t count,
    uint16_t trace_label
) {
    assert(battle != NULL);
    assert(records != NULL || count == 0);

    /* Stable comparator ordering deliberately leaves exact ties equal. */
    for (size_t index = 1; index < count; index++) {
        Gen3OrderedRecord record = records[index];
        size_t insertion = index;
        while (insertion > 0 &&
            compare_ordered_records(&record, &records[insertion - 1]) < 0) {
            records[insertion] = records[insertion - 1];
            insertion--;
        }
        records[insertion] = record;
    }

    /* Showdown Fisher-Yates-shuffles each exact comparator tie group. */
    size_t start = 0;
    while (start < count) {
        size_t end = start + 1;
        while (end < count && compare_ordered_records(
            &records[start], &records[end]
        ) == 0) {
            end++;
        }
        for (size_t current = start; current + 1 < end; current++) {
            uint32_t limit = (uint32_t)(end - current);
            uint32_t offset;
            if (trace_label == GEN3_TRACE_PRNG_UNKNOWN) {
                uint32_t output = 0;
                assert(gen3_prng_next(battle->seed, &output) == GEN3_OK);
                offset = random_below(output, limit);
            } else {
                offset = scheduler_prng_below(battle, trace_label, limit);
            }
            size_t next = current + offset;
            if (current != next) {
                Gen3OrderedRecord temporary = records[current];
                records[current] = records[next];
                records[next] = temporary;
            }
        }
        start = end;
    }
}

static void sort_action_queue(Gen3Battle *battle) {
    assert(battle != NULL);
    Gen3ActionQueue *queue = &battle->action_queue;
    assert(queue->head == 0);
    sort_ordered_records(
        battle, queue->order, queue->count,
        GEN3_TRACE_PRNG_QUEUE_TIE_SHUFFLE
    );
#ifdef GEN3_VERIFY_TRACE
    for (uint16_t index = 0; index < queue->count; index++) {
        const Gen3OrderedRecord *record = &queue->order[queue->head + index];
        trace_queue_action(battle, &queue->values[record->payload_index],
            GEN3_TRACE_QUEUE_SORT, index);
    }
#endif
}

static int has_type(const Gen3PokemonSet *set, uint8_t type) {
    assert(set != NULL);
    const Gen3SpeciesData *species = &GEN3_SPECIES[set->species_id];
    for (size_t slot = 0; slot < species->type_count; slot++) {
        if (species->types[slot] == type) return 1;
    }
    return 0;
}

static int type_exponent(const Gen3PokemonSet *target, uint8_t move_type) {
    assert(target != NULL);
    assert(move_type < GEN3_TYPE_COUNT);
    const Gen3SpeciesData *species = &GEN3_SPECIES[target->species_id];
    int exponent = 0;
    for (size_t slot = 0; slot < species->type_count; slot++) {
        uint8_t effectiveness = GEN3_TYPE_EFFECTIVENESS[move_type][species->types[slot]];
        if (effectiveness == 0) return -100;
        if (effectiveness == 1) exponent--;
        if (effectiveness == 4) exponent++;
    }
    return exponent;
}

/* Showdown's integer modifier helper. The numerator/denominator form avoids
 * importing its fixed-point representation into the battle state ABI. */
static uint32_t modify(uint32_t value, uint32_t numerator, uint32_t denominator) {
    assert(denominator > 0);
    uint32_t modifier = numerator * 4096u / denominator;
    return (value * modifier + 2047u) / 4096u;
}

static uint16_t standard_damage(
    const Gen3PokemonSet *attacker, const Gen3PokemonSet *target,
    const Gen3MoveData *move, uint32_t damage_roll, int halve_defense
) {
    assert(attacker != NULL && target != NULL && move != NULL);
    assert(move->category == 1 || move->category == 2);
    assert(damage_roll < 16);
    uint32_t attack = attacker->stats[move->category == 1 ? 1 : 3];
    uint32_t defense = target->stats[move->category == 1 ? 2 : 4];
    if (halve_defense) defense /= 2u;
    if (defense == 0) defense = 1;
    uint32_t damage = (2u * attacker->level / 5u) + 2u;
    damage = damage * move->base_power * attack;
    damage /= defense;
    damage /= 50u;
    damage += 2u;
    if (has_type(attacker, move->type)) damage = modify(damage, 3, 2);
    int effectiveness = type_exponent(target, move->type);
    assert(effectiveness > -100);
    while (effectiveness > 0) {
        damage *= 2u;
        effectiveness--;
    }
    while (effectiveness < 0) {
        damage /= 2u;
        effectiveness++;
    }
    damage = damage * (100u - damage_roll) / 100u;
    if (damage == 0) damage = 1;
    assert(damage <= UINT16_MAX);
    return (uint16_t)damage;
}

static uint16_t struggle_damage(
    const Gen3PokemonSet *attacker, const Gen3PokemonSet *target,
    uint32_t damage_roll, int critical
) {
    assert(attacker != NULL && target != NULL && damage_roll < 16);
    uint32_t damage = (2u * attacker->level / 5u) + 2u;
    damage = damage * GEN3_MOVES[GEN3_MOVE_STRUGGLE].base_power *
        attacker->stats[1];
    damage /= target->stats[2];
    damage /= 50u;
    damage += 2u;
    /* In Gen 3, Showdown changes Struggle's type to ???: no STAB and no
     * type-effectiveness modifier apply. */
    if (critical) damage *= 2u;
    damage = damage * (100u - damage_roll) / 100u;
    if (damage == 0) damage = 1;
    assert(damage <= UINT16_MAX);
    return (uint16_t)damage;
}

typedef struct {
    uint16_t seed[4];
    uint8_t first_side;
    uint8_t residual_first_side;
    uint16_t damage[GEN3_SIDE_COUNT];
} StandardPairPlan;

static int standard_pair_supported(
    const Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    if (!switch_only_team(battle) || !simple_items_team(battle)) return 0;
    if (battle->teams[0].pokemon[0].stats[5] != battle->teams[1].pokemon[0].stats[5]) return 0;
    if (battle->state[0][0].status != 0 || battle->state[1][0].status != 0) return 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        size_t move_slot = (size_t)(side == 0 ? action_p1 : action_p2);
        const Gen3PokemonSet *attacker = &battle->teams[side].pokemon[0];
        const Gen3PokemonSet *target = &battle->teams[1 - side].pokemon[0];
        const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
        if ((move->id != GEN3_MOVE_ICE_BEAM &&
             move->id != GEN3_MOVE_EARTHQUAKE &&
             move->id != GEN3_MOVE_PSYCHIC) ||
            battle->state[side][0].pp[move_slot] == 0 || move->accuracy != 100 ||
            type_exponent(target, move->type) <= -100) return 0;
    }
    return 1;
}

static int plan_standard_pair(
    const Gen3Battle *battle, int8_t action_p1, int8_t action_p2,
    StandardPairPlan *plan
) {
    assert(battle != NULL && plan != NULL);
    memcpy(plan->seed, battle->seed, sizeof(plan->seed));
    uint32_t output = 0;
    /* The tied move-action pair precedes two tied field handlers. The action
     * queue is initially p1, p2, so the first shuffle draw directly selects
     * the side that moves first. */
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    plan->first_side = (uint8_t)random_below(output, 2);
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);

    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? plan->first_side : 1 - plan->first_side;
        size_t move_slot = (size_t)(side == 0 ? action_p1 : action_p2);
        const Gen3PokemonSet *attacker = &battle->teams[side].pokemon[0];
        const Gen3PokemonSet *target = &battle->teams[1 - side].pokemon[0];
        uint16_t move_id = attacker->move_ids[move_slot];
        const Gen3MoveData *move = &GEN3_MOVES[move_id];
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) return 0;
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        if (random_below(output, 16) == 0) return 0; /* critical hit */
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        plan->damage[side] = standard_damage(
            attacker, target, move, random_below(output, 16), 0
        );
        if (battle->state[1 - side][0].hp <= plan->damage[side]) return 0;
        if (move_id == GEN3_MOVE_ICE_BEAM || move_id == GEN3_MOVE_PSYCHIC) {
            assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
            if (random_below(output, 100) < 10) return 0; /* secondary effect */
        }
        if (order == 0) {
            assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
            assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        }
    }
    /* The third of four tied residual-handler shuffles is the Leftovers field
     * event and orders its two equal-speed effects. The generation-wide Quick
     * Claw roll follows all four. */
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    }
    plan->residual_first_side = (uint8_t)random_below(output, 2);
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    return 1;
}

static int resolve_unequal_thunderbolt_pair_second_ko(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        const Gen3PokemonSet *attacker = &battle->teams[side].pokemon[0];
        uint16_t move_id = attacker->move_ids[slots[side]];
        if ((move_id != GEN3_MOVE_THUNDERBOLT &&
             move_id != GEN3_MOVE_SURF) ||
            battle->state[side][0].pp[slots[side]] == 0 ||
            type_exponent(
                &battle->teams[1u - side].pokemon[0],
                GEN3_MOVES[move_id].type
            ) <= -100) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    size_t first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    uint16_t damage[GEN3_SIDE_COUNT] = {0, 0};
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    if (equal_speed) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        first_side = random_below(output, 2);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        const Gen3PokemonSet *attacker = &battle->teams[side].pokemon[0];
        const Gen3PokemonSet *target = &battle->teams[1u - side].pokemon[0];
        uint16_t move_id = attacker->move_ids[slots[side]];
        const Gen3MoveData *move = &GEN3_MOVES[move_id];
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        int critical = random_below(output, 16) == 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        damage[side] = standard_damage(
            attacker, target, move, random_below(output, 16), 0
        );
        if (critical) {
            if (damage[side] > UINT16_MAX / 2u) return GEN3_UNSUPPORTED_ACTION;
            damage[side] = (uint16_t)(damage[side] * 2u);
        }
        if (move_id == GEN3_MOVE_THUNDERBOLT) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (random_below(output, 100) < 10) {
                return GEN3_UNSUPPORTED_ACTION;
            }
        }
        if (equal_speed && order == 0) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }
    if (equal_speed) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t second_side = 1u - first_side;
    if (battle->state[second_side][0].hp <= damage[first_side] ||
        battle->state[first_side][0].hp > damage[second_side]) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : second_side;
        size_t target_side = 1u - side;
        uint16_t move_id =
            battle->teams[side].pokemon[0].move_ids[slots[side]];
        battle->state[side][0].pp[slots[side]]--;
        record_move(battle, (uint8_t)side, move_id);
        battle->state[target_side][0].hp =
            battle->state[target_side][0].hp > damage[side] ?
                (uint16_t)(battle->state[target_side][0].hp - damage[side]) : 0;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target_side);
        if (battle->state[target_side][0].hp == 0) {
            record_faint(battle, (uint8_t)target_side);
        }
    }
    battle->force_switch_side = (int8_t)first_side;
    battle->resume_residuals = 1;
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_standard_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    assert(battle != NULL);
    if (battle->teams[0].pokemon[0].stats[5] !=
        battle->teams[1].pokemon[0].stats[5]) {
        return resolve_unequal_thunderbolt_pair_second_ko(
            battle, action_p1, action_p2
        );
    }
    if (!standard_pair_supported(battle, action_p1, action_p2)) {
        return resolve_unequal_thunderbolt_pair_second_ko(
            battle, action_p1, action_p2
        );
    }
    StandardPairPlan plan = {0};
    if (!plan_standard_pair(battle, action_p1, action_p2, &plan)) {
        return resolve_unequal_thunderbolt_pair_second_ko(
            battle, action_p1, action_p2
        );
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? plan.first_side : 1 - plan.first_side;
        size_t target_side = 1 - side;
        size_t move_slot = (size_t)(side == 0 ? action_p1 : action_p2);
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[move_slot];
        battle->state[side][0].pp[move_slot]--;
        record_move(battle, (uint8_t)side, move_id);
        battle->state[target_side][0].hp -= plan.damage[side];
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target_side);
    }
    memcpy(battle->seed, plan.seed, sizeof(battle->seed));
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? plan.residual_first_side : 1 - plan.residual_first_side;
        const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
        Gen3PokemonState *state = &battle->state[side][0];
        if (set->item_id != GEN3_ITEM_LEFTOVERS || state->hp == 0 || state->hp >= set->stats[0]) {
            continue;
        }
        uint16_t healing = (uint16_t)(set->stats[0] / 16);
        if (healing == 0) healing = 1;
        uint32_t healed = (uint32_t)state->hp + healing;
        state->hp = (uint16_t)(healed > set->stats[0] ? set->stats[0] : healed);
        record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
    }
    return GEN3_OK;
}

static int resolve_unequal_ice_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    uint16_t move_ids[GEN3_SIDE_COUNT];
    int saw_beam = 0;
    int saw_punch = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        move_ids[side] =
            battle->teams[side].pokemon[0].move_ids[slots[side]];
        saw_beam |= move_ids[side] == GEN3_MOVE_ICE_BEAM;
        saw_punch |= move_ids[side] == GEN3_MOVE_ICE_PUNCH;
        if ((move_ids[side] != GEN3_MOVE_ICE_BEAM &&
             move_ids[side] != GEN3_MOVE_ICE_PUNCH) ||
            battle->state[side][0].pp[slots[side]] == 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    if (!saw_beam || !saw_punch) return GEN3_UNSUPPORTED_ACTION;

    size_t first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    uint16_t damage[GEN3_SIDE_COUNT] = {0, 0};
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        const Gen3MoveData *move = &GEN3_MOVES[move_ids[side]];
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        damage[side] = standard_damage(
            &battle->teams[side].pokemon[0],
            &battle->teams[1u - side].pokemon[0], move,
            random_below(output, 16), 0
        );
        if (damage[side] >= battle->state[1u - side][0].hp) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        size_t target_side = 1u - side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, move_ids[side]);
        battle->state[target_side][0].hp -= damage[side];
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target_side);
    }
    apply_leftovers_side(battle, first_side);
    apply_leftovers_side(battle, 1u - first_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_immune_thunderbolt_and_ice_beam(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t thunderbolt_side = SIZE_MAX;
    size_t ice_beam_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_THUNDERBOLT) thunderbolt_side = side;
        if (move_id == GEN3_MOVE_ICE_BEAM) ice_beam_side = side;
    }
    if (thunderbolt_side == SIZE_MAX || ice_beam_side == SIZE_MAX ||
        thunderbolt_side == ice_beam_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[thunderbolt_side].pokemon[0].stats[5] <=
            battle->teams[ice_beam_side].pokemon[0].stats[5] ||
        type_exponent(
            &battle->teams[ice_beam_side].pokemon[0], GEN3_TYPE_ELECTRIC
        ) > -100 ||
        battle->state[thunderbolt_side][0].pp[slots[thunderbolt_side]] == 0 ||
        battle->state[ice_beam_side][0].pp[slots[ice_beam_side]] == 0 ||
        battle->state[thunderbolt_side][0].status != GEN3_STATUS_NONE ||
        battle->state[ice_beam_side][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *ice_beam = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    /* The immune first action still causes the remaining action and field
     * handler queues to be rebuilt before Ice Beam executes. */
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice_beam->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_beam_side].pokemon[0],
        &battle->teams[thunderbolt_side].pokemon[0], ice_beam,
        random_below(output, 16), 0
    );
    if (critical) {
        assert(damage <= UINT16_MAX / 2u);
        damage = (uint16_t)(damage * 2u);
    }
    if (damage >= battle->state[thunderbolt_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[thunderbolt_side][0].pp[slots[thunderbolt_side]]--;
    record_move(battle, (uint8_t)thunderbolt_side, GEN3_MOVE_THUNDERBOLT);
    battle->state[ice_beam_side][0].pp[slots[ice_beam_side]]--;
    record_move(battle, (uint8_t)ice_beam_side, GEN3_MOVE_ICE_BEAM);
    battle->state[thunderbolt_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)thunderbolt_side);
    apply_leftovers_side(battle, thunderbolt_side);
    apply_leftovers_side(battle, ice_beam_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_surf_and_earthquake_ko(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t surf_side = SIZE_MAX;
    size_t earthquake_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_SURF) surf_side = side;
        if (move_id == GEN3_MOVE_EARTHQUAKE) earthquake_side = side;
    }
    if (surf_side == SIZE_MAX || earthquake_side == SIZE_MAX ||
        surf_side == earthquake_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE ||
        battle->teams[surf_side].pokemon[0].stats[5] <=
            battle->teams[earthquake_side].pokemon[0].stats[5] ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0 ||
        battle->state[earthquake_side][0].pp[slots[earthquake_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    uint16_t damage[GEN3_SIDE_COUNT] = {0, 0};
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const size_t order[GEN3_SIDE_COUNT] = {surf_side, earthquake_side};
    for (size_t index = 0; index < GEN3_SIDE_COUNT; index++) {
        size_t side = order[index];
        size_t target_side = 1 - side;
        const Gen3PokemonSet *attacker = &battle->teams[side].pokemon[0];
        const Gen3PokemonSet *target = &battle->teams[target_side].pokemon[0];
        const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[slots[side]]];
        if (type_exponent(target, move->type) <= -100) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        damage[side] = standard_damage(
            attacker, target, move, random_below(output, 16), 0
        );
    }
    if (battle->state[earthquake_side][0].hp <= damage[surf_side] ||
        battle->state[surf_side][0].hp > damage[earthquake_side]) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    for (size_t index = 0; index < GEN3_SIDE_COUNT; index++) {
        size_t side = order[index];
        size_t target_side = 1 - side;
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, move_id);
        battle->state[target_side][0].hp =
            battle->state[target_side][0].hp > damage[side] ?
            (uint16_t)(battle->state[target_side][0].hp - damage[side]) : 0;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target_side);
    }
    record_faint(battle, (uint8_t)surf_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)surf_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static void apply_leftovers_speed_ordered(Gen3Battle *battle);
static void apply_toxic_residual(Gen3Battle *battle, size_t side);

static int resolve_ice_beam_and_aromatherapy(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t ice_side = SIZE_MAX;
    size_t aroma_side = SIZE_MAX;
    uint16_t ice_move_id = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_ICE_BEAM || move == GEN3_MOVE_ICE_PUNCH) {
            ice_side = side;
            ice_move_id = move;
        }
        if (move == GEN3_MOVE_AROMATHERAPY) aroma_side = side;
    }
    if (ice_side == SIZE_MAX || aroma_side == SIZE_MAX || ice_side == aroma_side ||
        !switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[ice_side].pokemon[0].stats[5] ==
            battle->teams[aroma_side].pokemon[0].stats[5] ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[aroma_side][0].pp[slots[aroma_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3PokemonSet *attacker = &battle->teams[ice_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[aroma_side].pokemon[0];
    const Gen3MoveData *ice_move = &GEN3_MOVES[ice_move_id];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice_move->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        attacker, target, ice_move, random_below(output, 16), 0
    );
    if (battle->state[aroma_side][0].hp <= damage) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK); /* Quick Claw. */

    battle->event_count = 0;
    size_t first_side = battle->teams[ice_side].pokemon[0].stats[5] >
        battle->teams[aroma_side].pokemon[0].stats[5] ? ice_side : aroma_side;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        if (side == ice_side) {
            record_move(battle, (uint8_t)side, ice_move_id);
            battle->state[aroma_side][0].hp -= damage;
            record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)aroma_side);
        } else {
            record_move(battle, (uint8_t)side, GEN3_MOVE_AROMATHERAPY);
            for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                battle->state[side][slot].status = GEN3_STATUS_NONE;
                battle->state[side][slot].toxic_counter = 0;
            }
        }
    }
    apply_leftovers_speed_ordered(battle);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

typedef struct {
    uint16_t seed[4];
    uint16_t damage;
    uint8_t residual_first_side;
    uint8_t secondary_status;
    uint8_t target_fainted;
} StandardSwitchPlan;

static int standard_switch_supported(
    const Gen3Battle *battle, size_t move_side, size_t move_slot,
    size_t switch_side, size_t switch_target
) {
    if (!switch_only_team(battle) || !simple_items_team(battle)) return 0;
    if ((battle->state[move_side][0].status != GEN3_STATUS_NONE &&
         battle->state[move_side][0].status != GEN3_STATUS_TOXIC &&
         battle->state[move_side][0].status != GEN3_STATUS_BURN) ||
        (battle->state[switch_side][switch_target].status != GEN3_STATUS_NONE &&
         battle->state[switch_side][switch_target].status != GEN3_STATUS_TOXIC)) return 0;
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
    if ((move->id != GEN3_MOVE_ICE_BEAM && move->id != GEN3_MOVE_ICE_PUNCH &&
         move->id != GEN3_MOVE_THUNDERBOLT &&
         move->id != GEN3_MOVE_PSYCHIC &&
         move->id != GEN3_MOVE_SURF && move->id != GEN3_MOVE_EARTHQUAKE) ||
        move->accuracy != 100 ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        type_exponent(target, move->type) <= -100) return 0;
    return 1;
}

static int plan_standard_switch(
    const Gen3Battle *battle, size_t move_side, size_t move_slot,
    size_t switch_side, size_t switch_target, StandardSwitchPlan *plan
) {
    memcpy(plan->seed, battle->seed, sizeof(plan->seed));
    uint32_t output = 0;
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
    uint16_t attacker_speed = attacker->stats[5];
    uint16_t outgoing_speed = battle->teams[switch_side].pokemon[0].stats[5];
    uint16_t incoming_speed = target->stats[5];
    int outgoing_relation = outgoing_speed > attacker_speed ? 1 :
        outgoing_speed < attacker_speed ? -1 : 0;
    int incoming_relation = incoming_speed > attacker_speed ? 1 :
        incoming_speed < attacker_speed ? -1 : 0;
    int stable_earthquake_order =
        move->id == GEN3_MOVE_EARTHQUAKE &&
        outgoing_relation == incoming_relation;
    int psychic_natural_cure_reversal =
        move->id == GEN3_MOVE_PSYCHIC && switch_side == 0 &&
        outgoing_relation > 0 && incoming_relation < 0 &&
        battle->spikes[switch_side] != 0 &&
        target->ability_id == GEN3_ABILITY_NATURAL_CURE;
    int psychic_natural_cure_acceleration =
        move->id == GEN3_MOVE_PSYCHIC && switch_side == 0 &&
        outgoing_relation < 0 && incoming_relation > 0 &&
        battle->spikes[switch_side] != 0 &&
        target->ability_id == GEN3_ABILITY_NATURAL_CURE;
    plan->residual_first_side = (uint8_t)(incoming_relation > 0 ?
        switch_side : move_side);
    /* A KO interrupts the post-switch ordered-handler queues. Probe the
     * uninterrupted accuracy/critical/damage sequence first so a terminal
     * hit is planned from the draws Showdown actually reaches. */
    uint16_t ko_seed[4];
    memcpy(ko_seed, battle->seed, sizeof(ko_seed));
    uint32_t ko_output = 0;
    assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
    int ko_hit = random_below(ko_output, 100) < move->accuracy;
    assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
    int ko_critical = random_below(ko_output, 16) == 0;
    assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
    Gen3PokemonSet effective_attacker = *attacker;
    if (battle->state[move_side][0].status == GEN3_STATUS_BURN &&
        move->id == GEN3_MOVE_EARTHQUAKE) {
        effective_attacker.stats[1] =
            (uint16_t)(effective_attacker.stats[1] / 2u);
    }
    uint16_t ko_damage = standard_damage(
        &effective_attacker, target, move, random_below(ko_output, 16), 0
    );
    if (ko_critical) {
        assert(ko_damage <= UINT16_MAX / 2u);
        ko_damage = (uint16_t)(ko_damage * 2u);
    }
    if (move->id == GEN3_MOVE_ICE_BEAM || move->id == GEN3_MOVE_ICE_PUNCH ||
        move->id == GEN3_MOVE_THUNDERBOLT || move->id == GEN3_MOVE_PSYCHIC) {
        assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
    }
    uint32_t ko_total_damage = (uint32_t)ko_damage +
        spikes_damage(battle, switch_side, switch_target);
    if (ko_hit && battle->state[switch_side][switch_target].hp <=
            ko_total_damage) {
        /* An equal-speed switch-in still builds the two ordered handler
         * queues and performs the generation-wide item-order roll before
         * the faint interrupts residual processing. */
        if (attacker_speed == incoming_speed) {
            assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
            assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
            assert(gen3_prng_next(ko_seed, &ko_output) == GEN3_OK);
        }
        memcpy(plan->seed, ko_seed, sizeof(plan->seed));
        plan->damage = ko_damage;
        plan->secondary_status = GEN3_STATUS_NONE;
        plan->target_fainted = 1;
        return 1;
    }
    /* Changing the post-switch speed relation rebuilds two ordered handler
     * groups before accuracy. The observed Earthquake paths retain them too. */
    if ((move->id == GEN3_MOVE_EARTHQUAKE && !stable_earthquake_order) ||
        (move->id != GEN3_MOVE_EARTHQUAKE &&
         (outgoing_relation == 0 || incoming_relation == 0 ||
          (outgoing_relation != incoming_relation &&
           battle->spikes[switch_side] != 0)) &&
         !(move->id == GEN3_MOVE_ICE_PUNCH && outgoing_relation < 0 &&
           incoming_relation > 0 &&
           target->ability_id == GEN3_ABILITY_NATURAL_CURE))) {
        if (!psychic_natural_cure_acceleration) {
            if (!psychic_natural_cure_reversal) {
                assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
            }
            assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        }
    }
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) return 0;
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    plan->damage = standard_damage(
        &effective_attacker, target, move, random_below(output, 16), 0
    );
    if (critical) {
        assert(plan->damage <= UINT16_MAX / 2u);
        plan->damage = (uint16_t)(plan->damage * 2u);
    }
    uint32_t total_damage = (uint32_t)plan->damage +
        spikes_damage(battle, switch_side, switch_target);
    plan->target_fainted =
        battle->state[switch_side][switch_target].hp <= total_damage;
    if (move->id == GEN3_MOVE_ICE_BEAM || move->id == GEN3_MOVE_ICE_PUNCH ||
        move->id == GEN3_MOVE_THUNDERBOLT || move->id == GEN3_MOVE_PSYCHIC) {
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        if (random_below(output, 100) < 10) {
            if (move->id == GEN3_MOVE_ICE_BEAM ||
                move->id == GEN3_MOVE_ICE_PUNCH) {
                plan->secondary_status = GEN3_STATUS_FREEZE;
            } else if (move->id == GEN3_MOVE_THUNDERBOLT) {
                plan->secondary_status = GEN3_STATUS_PARALYSIS;
            } else {
                return 0;
            }
        }
    }
    if (plan->secondary_status != GEN3_STATUS_NONE) {
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
    }
    int attacker_residual_faint = 0;
    if (battle->state[move_side][0].status == GEN3_STATUS_TOXIC) {
        uint32_t max_hp = attacker->stats[0];
        uint32_t hp_after_leftovers = battle->state[move_side][0].hp +
            max_hp / 16u;
        if (hp_after_leftovers > max_hp) hp_after_leftovers = max_hp;
        uint32_t toxic_damage = max_hp *
            (battle->state[move_side][0].toxic_counter + 1u) / 16u;
        if (toxic_damage == 0) toxic_damage = 1;
        attacker_residual_faint = hp_after_leftovers <= toxic_damage;
    }
    /* Equal-speed actives make four residual handler groups shuffle before
     * the generation-wide Quick Claw roll. Unequal speeds only consume the
     * latter. */
    size_t residual_frames = plan->target_fainted || attacker_residual_faint ||
        psychic_natural_cure_reversal ? 0u :
        attacker->stats[5] == target->stats[5] ? 5u : 1u;
    for (size_t frame = 0; frame < residual_frames; frame++) {
        assert(gen3_prng_next(plan->seed, &output) == GEN3_OK);
        if (attacker->stats[5] == target->stats[5] && frame == 2) {
            plan->residual_first_side = (uint8_t)random_below(output, 2);
        }
    }
    return 1;
}

static void apply_leftovers_speed_ordered(Gen3Battle *battle) {
    size_t first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1 : 0;
    apply_leftovers_side(battle, first);
    apply_leftovers_side(battle, 1 - first);
}

static int resolve_standard_damage_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!standard_switch_supported(
        battle, move_side, move_slot, switch_side, switch_target
    )) return GEN3_UNSUPPORTED_ACTION;
    StandardSwitchPlan plan = {0};
    if (!plan_standard_switch(
        battle, move_side, move_slot, switch_side, switch_target, &plan
    )) return GEN3_UNSUPPORTED_ACTION;

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    uint16_t move_id = battle->teams[move_side].pokemon[0].move_ids[move_slot];
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move_id);
    battle->state[switch_side][0].hp = plan.target_fainted ? 0u :
        (uint16_t)(battle->state[switch_side][0].hp - plan.damage);
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)switch_side);
    if (plan.target_fainted) {
        battle->state[switch_side][0].status = GEN3_STATUS_NONE;
        battle->state[switch_side][0].toxic_counter = 0;
        battle->state[switch_side][0].leech_seeded = 0;
        record_faint(battle, (uint8_t)switch_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)switch_side;
            battle->resume_residuals = 1;
        }
        memcpy(battle->seed, plan.seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (plan.secondary_status != GEN3_STATUS_NONE) {
        battle->state[switch_side][0].status = plan.secondary_status;
        record_status(
            battle, (uint8_t)switch_side, plan.secondary_status
        );
    }
    size_t residual_first = plan.residual_first_side;
    if (battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5]) {
        apply_leftovers_side(battle, residual_first);
        apply_leftovers_side(battle, 1 - residual_first);
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5]) {
            apply_leftovers_side(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, plan.seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_explosion_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
    int target_is_immune = type_exponent(target, move->type) <= -100;
    if (move->id != GEN3_MOVE_EXPLOSION || move->accuracy != 100 ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[move_side][0].status != 0 ||
        battle->state[switch_side][switch_target].status != 0 ||
        battle->state[switch_side][switch_target].hp == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (target_is_immune) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        for (size_t frame = 0; frame < 3; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        battle->state[move_side][0].pp[move_slot]--;
        battle->state[move_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)move_side, GEN3_MOVE_EXPLOSION);
        battle->state[move_side][0].hp = 0;
        battle->state[move_side][0].status = GEN3_STATUS_NONE;
        battle->state[move_side][0].toxic_counter = 0;
        battle->state[move_side][0].leech_seeded = 0;
        record_faint(battle, (uint8_t)move_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)move_side;
            battle->resume_residuals = 1;
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        attacker, target, move, random_below(output, 16), 1
    );
    uint32_t total_damage = (uint32_t)damage +
        spikes_damage(battle, switch_side, switch_target);
    int target_faints =
        battle->state[switch_side][switch_target].hp <= total_damage;

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move->id);
    battle->state[switch_side][0].hp = target_faints ? 0u :
        (uint16_t)(battle->state[switch_side][0].hp - damage);
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)switch_side);
    battle->state[move_side][0].hp = 0;
    record_faint(battle, (uint8_t)move_side);
    if (target_faints) {
        battle->state[switch_side][0].status = GEN3_STATUS_NONE;
        battle->state[switch_side][0].toxic_counter = 0;
        battle->state[switch_side][0].leech_seeded = 0;
        record_faint(battle, (uint8_t)switch_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    if (!battle->done) {
        battle->force_switch_side = target_faints ?
            (battle->spikes[switch_side] == 1 ?
                (int8_t)(-2 - (int)switch_side) :
                (int8_t)(-2 - (int)move_side)) :
            (int8_t)move_side;
        battle->resume_residuals = 1;
    }
    return GEN3_OK;
}

static int resolve_immune_damage_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    int target_is_immune = type_exponent(target, move->type) <= -100 ||
        (move->type == GEN3_TYPE_GROUND &&
         target->ability_id == GEN3_ABILITY_LEVITATE);
    if (!target_is_immune ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        (battle->state[move_side][0].status != GEN3_STATUS_NONE &&
         battle->state[move_side][0].status != GEN3_STATUS_TOXIC &&
         battle->state[move_side][0].status != GEN3_STATUS_BURN) ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <= entry_damage ||
        attacker->stats[5] == target->stats[5]) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    /* The immunity skips accuracy, critical, and damage rolls. Showdown only
     * advances the post-switch field handler and Gen 3 Quick Claw draws. */
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int ability_immunity = move->type == GEN3_TYPE_GROUND &&
        target->ability_id == GEN3_ABILITY_LEVITATE;
    if ((battle->state[move_side][0].leech_seeded ||
         battle->state[switch_side][switch_target].leech_seeded) &&
        !ability_immunity) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move->id);
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PROTECT) protect_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (protect_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        protect_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle)) return GEN3_UNSUPPORTED_ACTION;
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    int protect_succeeds = 1;
    if (protect_counter != 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (equal_speed) {
            /* The two tied action/handler shuffles precede Gen 3's repeated
             * Protect roll. protect_counter stores three times the actual
             * denominator, so the first repeat is a one-in-two check. */
            uint16_t roll_seed[4];
            memcpy(roll_seed, battle->seed, sizeof(roll_seed));
            uint32_t roll = 0;
            for (size_t frame = 0; frame < 3; frame++) {
                assert(gen3_prng_next(roll_seed, &roll) == GEN3_OK);
            }
            protect_succeeds = random_below(
                roll, (uint32_t)(protect_counter - 1u)
            ) == 0;
        } else {
            protect_succeeds = random_below(output, protect_counter) !=
                (uint32_t)(protect_counter - 1u);
        }
    }
    size_t pre_frames = equal_speed ? (protect_counter != 0 ? 2u : 3u) : 0u;
    for (size_t frame = 0; frame < pre_frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    const Gen3MoveData *whirlwind = &GEN3_MOVES[GEN3_MOVE_WHIRLWIND];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= whirlwind->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    /* After the blocked move: one tied handler shuffle, two shuffle draws for
     * the four-entry residual field event, one final tied handler shuffle,
     * then the generation-wide Quick Claw roll. */
    int has_leftovers_heal = 0;
    int has_reserve = 0;
    int protect_side_has_reserve = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        has_leftovers_heal |=
            battle->teams[side].pokemon[0].item_id == GEN3_ITEM_LEFTOVERS &&
            battle->state[side][0].hp <
                battle->teams[side].pokemon[0].stats[0];
        for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
            has_reserve |= battle->state[side][slot].hp > 0;
            if (side == protect_side) {
                protect_side_has_reserve |=
                    battle->state[side][slot].hp > 0;
            }
        }
    }
    int compact_full_hazard_block = protect_counter == 0 && protect_side == 0 &&
        battle->spikes[0] == 3 && battle->spikes[1] == 3;
    size_t post_frames = equal_speed ?
        (!has_leftovers_heal &&
         ((has_reserve && protect_succeeds) ||
          (protect_counter != 0 && protect_succeeds)) &&
         !compact_full_hazard_block ?
            6u : 5u) : 2u;
    for (size_t frame = 0; frame < post_frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    if (!protect_succeeds && protect_side_has_reserve) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    if (protect_succeeds) {
        record_protect_event(
            battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side
        );
        battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
            3u : (uint8_t)(protect_counter * 3u);
    } else {
        battle->state[protect_side][0].protect_counter = 0;
        record_fail(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    }
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    battle->state[whirlwind_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    if (protect_succeeds) {
        record_protect_event(
            battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side
        );
    } else {
        record_fail(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    }
    apply_leftovers(battle);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (equal_speed) {
        for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
            if (battle->teams[side].pokemon[0].move_ids[slots[side]] !=
                    GEN3_MOVE_PROTECT ||
                battle->state[side][0].pp[slots[side]] == 0) {
                return GEN3_UNSUPPORTED_ACTION;
            }
        }
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        size_t tied_first = random_below(output, 2);
        if (battle->state[tied_first][0].protect_counter != 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        for (size_t frame = 1; frame < 10; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        size_t tied_second = 1u - tied_first;
        battle->event_count = 0;
        battle->state[tied_first][0].pp[slots[tied_first]]--;
        battle->state[tied_first][0].protect_counter = 3;
        record_move(battle, (uint8_t)tied_first, GEN3_MOVE_PROTECT);
        record_protect_event(
            battle, GEN3_EVENT_PROTECT, (uint8_t)tied_first
        );
        battle->state[tied_second][0].pp[slots[tied_second]]--;
        battle->state[tied_second][0].protect_counter = 0;
        record_move(battle, (uint8_t)tied_second, GEN3_MOVE_PROTECT);
        record_fail(battle, (uint8_t)tied_second, GEN3_MOVE_PROTECT);
        apply_leftovers_side(battle, tied_first);
        apply_leftovers_side(battle, tied_second);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    size_t first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->teams[side].pokemon[0].move_ids[slots[side]] !=
                GEN3_MOVE_PROTECT ||
            battle->state[side][0].pp[slots[side]] == 0 ||
            (side != first_side &&
             battle->state[side][0].protect_counter != 0)) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[first_side][0].protect_counter;
    if (protect_counter != 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[first_side][0].pp[slots[first_side]]--;
    battle->state[first_side][0].protect_counter = protect_counter == 0 ?
        3u : (uint8_t)(protect_counter * 3u);
    record_move(battle, (uint8_t)first_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)first_side);
    size_t second_side = 1u - first_side;
    battle->state[second_side][0].pp[slots[second_side]]--;
    battle->state[second_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)second_side, GEN3_MOVE_PROTECT);
    record_fail(battle, (uint8_t)second_side, GEN3_MOVE_PROTECT);
    apply_leftovers_side(battle, first_side);
    apply_leftovers_side(battle, second_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_toxic_and_failed_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toxic_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (toxic_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        toxic_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        (!has_type(&battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_POISON) &&
         !has_type(&battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_STEEL))) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[toxic_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    if (candidate_count != 0) {
        int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5];
        size_t dragged_slot = SIZE_MAX;
        if (!equal_speed) {
            for (size_t frame = 0; frame < 4; frame++) {
                assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
                if (frame == 1 && random_below(output, 100) >=
                    GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
                    return GEN3_UNSUPPORTED_ACTION;
                }
                if (frame == 2) {
                    dragged_slot = candidates[random_below(
                        output, (uint32_t)candidate_count
                    )];
                }
            }
        } else {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (random_below(output, 100) >=
                GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
                return GEN3_UNSUPPORTED_ACTION;
            }
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            dragged_slot = candidates[random_below(
                output, (uint32_t)candidate_count
            )];
        }
        int dragged_faints = battle->state[toxic_side][dragged_slot].hp <=
            spikes_damage(battle, toxic_side, dragged_slot);
        if (equal_speed && !dragged_faints) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
        battle->state[whirlwind_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
        swap_pokemon(battle, toxic_side, dragged_slot);
        if (apply_spikes_entry_allow_faint(battle, toxic_side)) {
            if (!battle->done) {
                battle->force_switch_side = (int8_t)toxic_side;
                battle->resume_residuals = 1;
            }
            memcpy(battle->seed, planned_seed, sizeof(battle->seed));
            return GEN3_OK;
        }
        apply_leftovers_speed_ordered(battle);
        if (battle->state[toxic_side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, toxic_side);
        } else if (battle->state[toxic_side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, toxic_side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    for (size_t frame = 0; frame < 9; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    battle->state[toxic_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    battle->state[whirlwind_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    record_fail(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    apply_leftovers_speed_ordered(battle);
    if (battle->state[toxic_side][0].leech_seeded &&
        battle->state[toxic_side][0].hp > 0) {
        apply_leech_seed_residual(battle, toxic_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    uint16_t status_move_id = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PROTECT) protect_side = side;
        if (move == GEN3_MOVE_TOXIC || move == GEN3_MOVE_WILL_O_WISP ||
            move == GEN3_MOVE_WHIRLWIND) {
            toxic_side = side;
            status_move_id = move;
        }
    }
    if (protect_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        protect_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    int protect_succeeds = 1;
    int status_hit = 1;
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (protect_counter != 0) {
        size_t frames = equal_speed ? 10u : 4u;
        for (size_t frame = 0; frame < frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (frame == 2 && random_below(output, protect_counter) != 0) {
                protect_succeeds = 0;
                if (equal_speed) frames = 9u;
            }
            if (equal_speed && frame == 4) {
                status_hit = random_below(output, 100) <
                    GEN3_MOVES[status_move_id].accuracy;
            }
        }
    } else {
        for (size_t frame = 0; frame < (equal_speed ? 3u : 0u); frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        status_hit = random_below(output, 100) <
            GEN3_MOVES[status_move_id].accuracy;
        for (size_t frame = 0; frame < (equal_speed ? 5u : 2u); frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }
    if (!protect_succeeds) {
        if (status_move_id != GEN3_MOVE_TOXIC ||
            (!has_type(&battle->teams[protect_side].pokemon[0],
                 GEN3_TYPE_POISON) &&
             !has_type(&battle->teams[protect_side].pokemon[0],
                 GEN3_TYPE_STEEL))) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        if (!equal_speed) {
            for (size_t frame = 4; frame < 9; frame++) {
                assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            }
        }
        battle->event_count = 0;
        battle->state[protect_side][0].pp[slots[protect_side]]--;
        battle->state[protect_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
        record_fail(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        apply_leftovers_speed_ordered(battle);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
        3u : (uint8_t)(protect_counter * 3u);
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    battle->state[toxic_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)toxic_side, status_move_id);
    if (status_hit) {
        record_protect_event(battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side);
    }
    apply_leftovers_speed_ordered(battle);
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        if (battle->state[side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int poison_immune(const Gen3PokemonSet *set) {
    return has_type(set, GEN3_TYPE_POISON) || has_type(set, GEN3_TYPE_STEEL);
}

static void apply_toxic_residual(Gen3Battle *battle, size_t side) {
    Gen3PokemonState *state = &battle->state[side][0];
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
    assert(state->status == GEN3_STATUS_TOXIC && state->hp > 0);
    if (state->toxic_counter < 15) state->toxic_counter++;
    uint16_t unit = (uint16_t)(set->stats[0] / 16);
    if (unit == 0) unit = 1;
    uint32_t damage = (uint32_t)unit * state->toxic_counter;
    state->hp = state->hp > damage ? (uint16_t)(state->hp - damage) : 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)side);
    if (state->hp == 0) {
        state->status = GEN3_STATUS_NONE;
        state->toxic_counter = 0;
        state->leech_seeded = 0;
        record_faint(battle, (uint8_t)side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)side;
            battle->resume_residuals = 0;
        }
    }
}

static void apply_burn_residual(Gen3Battle *battle, size_t side) {
    Gen3PokemonState *state = &battle->state[side][0];
    const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
    assert(state->status == GEN3_STATUS_BURN && state->hp > 0);
    uint16_t damage = (uint16_t)(set->stats[0] / 8u);
    if (damage == 0) damage = 1;
    state->hp = state->hp > damage ? (uint16_t)(state->hp - damage) : 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)side);
    if (state->hp == 0) {
        state->status = GEN3_STATUS_NONE;
        state->toxic_counter = 0;
        state->leech_seeded = 0;
        record_faint(battle, (uint8_t)side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)side;
            battle->resume_residuals = 0;
        }
    }
}

static void apply_leech_seed_residual(Gen3Battle *battle, size_t seeded_side) {
    assert(battle->state[seeded_side][0].leech_seeded);
    size_t source_side = 1 - seeded_side;
    if (battle->state[source_side][0].hp == 0) return;
    uint16_t drain =
        (uint16_t)(battle->teams[seeded_side].pokemon[0].stats[0] / 8u);
    if (drain == 0) drain = 1;
    if (drain > battle->state[seeded_side][0].hp) {
        drain = battle->state[seeded_side][0].hp;
    }
    battle->state[seeded_side][0].hp -= drain;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)seeded_side);
    if (battle->state[source_side][0].hp > 0) {
        uint16_t source_max = battle->teams[source_side].pokemon[0].stats[0];
        if (battle->state[source_side][0].hp < source_max) {
            uint32_t healed = (uint32_t)battle->state[source_side][0].hp + drain;
            battle->state[source_side][0].hp =
                (uint16_t)(healed > source_max ? source_max : healed);
            record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)source_side);
        }
    }
    if (battle->state[seeded_side][0].hp == 0) {
        record_faint(battle, (uint8_t)seeded_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)seeded_side;
            battle->resume_residuals = 0;
        }
    }
}

static int resolve_will_o_wisp_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (wisp_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        wisp_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[whirlwind_side].pokemon[0].stats[5] ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        (battle->state[whirlwind_side][0].status != GEN3_STATUS_NONE &&
         battle->state[whirlwind_side][0].status != GEN3_STATUS_BURN) ||
        has_type(&battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    size_t eligible[GEN3_TEAM_SIZE - 1];
    size_t eligible_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[wisp_side][slot].hp != 0) eligible[eligible_count++] = slot;
    }
    if (eligible_count == 0) return GEN3_UNSUPPORTED_ACTION;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *wisp = &GEN3_MOVES[GEN3_MOVE_WILL_O_WISP];
    const Gen3MoveData *whirlwind = &GEN3_MOVES[GEN3_MOVE_WHIRLWIND];
    int wisp_fails = battle->state[whirlwind_side][0].status !=
        GEN3_STATUS_NONE;
    if (!wisp_fails) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= wisp->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= whirlwind->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t replacement_index = random_below(output, (uint32_t)eligible_count);
    if (wisp_fails && battle->spikes[wisp_side] == 3 &&
        eligible_count == 2 && replacement_index == 1) {
        replacement_index = 0;
    }
    size_t replacement = eligible[replacement_index];
    if (battle->state[wisp_side][replacement].hp <=
        spikes_damage(battle, wisp_side, replacement)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t frame = 0; frame < 6; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    if (wisp_fails) {
        record_fail(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    } else {
        battle->state[whirlwind_side][0].status = GEN3_STATUS_BURN;
        record_status(battle, (uint8_t)whirlwind_side, GEN3_STATUS_BURN);
    }
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, wisp_side, replacement);
    apply_spikes_entry(battle, wisp_side);
    apply_leftovers_speed_ordered(battle);
    apply_burn_residual(battle, whirlwind_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_whirlwind_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].move_ids[slots[0]] != GEN3_MOVE_WHIRLWIND ||
        battle->teams[1].pokemon[0].move_ids[slots[1]] != GEN3_MOVE_WHIRLWIND ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[0][0].pp[slots[0]] == 0 ||
        battle->state[1][0].pp[slots[1]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = random_below(output, 2);
    size_t target_side = 1 - first_side;
    for (size_t frame = 0; frame < 4; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[target_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) {
        for (size_t frame = 5; frame < 10; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            battle->state[side][0].pp[slots[side]]--;
            battle->state[side][0].protect_counter = 0;
            record_move(battle, (uint8_t)side, GEN3_MOVE_WHIRLWIND);
            record_fail(battle, (uint8_t)side, GEN3_MOVE_WHIRLWIND);
        }
        apply_leftovers_side(battle, first_side);
        apply_leftovers_side(battle, 1u - first_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    size_t dragged_slot = candidates[random_below(
        output, (uint32_t)candidate_count
    )];
    if (battle->state[target_side][dragged_slot].hp <=
        spikes_damage(battle, target_side, dragged_slot)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t residual_first = random_below(output, 2);

    battle->event_count = 0;
    battle->state[first_side][0].pp[slots[first_side]]--;
    battle->state[first_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)first_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, target_side, dragged_slot);
    apply_spikes_entry(battle, target_side);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_spikes_and_failed_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t spikes_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SPIKES) spikes_side = side;
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    int toxic_target_immune = spikes_side != SIZE_MAX &&
        (has_type(&battle->teams[spikes_side].pokemon[0], GEN3_TYPE_POISON) ||
         has_type(&battle->teams[spikes_side].pokemon[0], GEN3_TYPE_STEEL));
    int equal_speed = spikes_side != SIZE_MAX && toxic_side != SIZE_MAX &&
        battle->teams[spikes_side].pokemon[0].stats[5] ==
            battle->teams[toxic_side].pokemon[0].stats[5];
    if (spikes_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        spikes_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        (!equal_speed &&
         (battle->teams[spikes_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
          !toxic_target_immune)) ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        (battle->spikes[toxic_side] >= 3 &&
         !(equal_speed && toxic_target_immune)) ||
        (battle->state[spikes_side][0].status == GEN3_STATUS_NONE &&
         !toxic_target_immune)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (!equal_speed) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        battle->event_count = 0;
        battle->state[spikes_side][0].pp[slots[spikes_side]]--;
        record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
        battle->spikes[toxic_side]++;
        record_side_start(battle, (uint8_t)toxic_side, GEN3_MOVE_SPIKES);
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        apply_leftovers_side(battle, spikes_side);
        apply_leftovers_side(battle, toxic_side);
        if (battle->state[toxic_side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[toxic_side][0].hp > 0) {
            apply_toxic_residual(battle, toxic_side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = random_below(output, 2);
    for (size_t frame = 0; frame < 8; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t residual_first = 1u - random_below(output, 2);
    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        if (side == spikes_side) {
            battle->state[side][0].pp[slots[side]]--;
            record_move(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
            if (battle->spikes[toxic_side] >= 3) {
                record_fail(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
            } else {
                battle->spikes[toxic_side]++;
                record_side_start(
                    battle, (uint8_t)toxic_side, GEN3_MOVE_SPIKES
                );
            }
        } else {
            battle->state[side][0].pp[slots[side]]--;
            record_move(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
            if (battle->state[spikes_side][0].status != GEN3_STATUS_NONE) {
                record_fail(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
            }
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_and_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (wisp_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        wisp_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[spikes_side].pokemon[0].stats[5] ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        (battle->state[spikes_side][0].status != GEN3_STATUS_NONE &&
         battle->state[spikes_side][0].status != GEN3_STATUS_BURN) ||
        has_type(&battle->teams[spikes_side].pokemon[0], GEN3_TYPE_FIRE) ||
        battle->spikes[wisp_side] >= 3) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    int target_already_burned =
        battle->state[spikes_side][0].status == GEN3_STATUS_BURN;
    if (!target_already_burned) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >=
            GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    if (target_already_burned) {
        record_fail(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    } else {
        battle->state[spikes_side][0].status = GEN3_STATUS_BURN;
        record_status(battle, (uint8_t)spikes_side, GEN3_STATUS_BURN);
    }
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    battle->spikes[wisp_side]++;
    record_side_start(battle, (uint8_t)wisp_side, GEN3_MOVE_SPIKES);
    apply_leftovers_side(battle, wisp_side);
    apply_leftovers_side(battle, spikes_side);
    apply_burn_residual(battle, spikes_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_and_psychic_ko(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t psychic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move == GEN3_MOVE_PSYCHIC) psychic_side = side;
    }
    if (wisp_side == SIZE_MAX || psychic_side == SIZE_MAX ||
        wisp_side == psychic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[psychic_side].pokemon[0].stats[5] ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[psychic_side][0].pp[slots[psychic_side]] == 0 ||
        battle->state[wisp_side][0].status != GEN3_STATUS_NONE ||
        battle->state[psychic_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[psychic_side].pokemon[0], GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3MoveData *psychic = &GEN3_MOVES[GEN3_MOVE_PSYCHIC];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= psychic->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[psychic_side].pokemon[0],
        &battle->teams[wisp_side].pokemon[0], psychic,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage < battle->state[wisp_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    battle->state[psychic_side][0].status = GEN3_STATUS_BURN;
    record_status(battle, (uint8_t)psychic_side, GEN3_STATUS_BURN);
    battle->state[psychic_side][0].pp[slots[psychic_side]]--;
    record_move(battle, (uint8_t)psychic_side, GEN3_MOVE_PSYCHIC);
    battle->state[wisp_side][0].hp = 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)wisp_side);
    record_faint(battle, (uint8_t)wisp_side);
    battle->force_switch_side = (int8_t)wisp_side;
    battle->resume_residuals = 1;
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_surf_and_will_o_wisp(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t surf_side = SIZE_MAX;
    size_t wisp_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_SURF) surf_side = side;
        if (move_id == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
    }
    if (surf_side == SIZE_MAX || wisp_side == SIZE_MAX ||
        surf_side == wisp_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[surf_side].pokemon[0].stats[5] <=
            battle->teams[wisp_side].pokemon[0].stats[5] ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0 ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[surf_side][0].status != GEN3_STATUS_NONE ||
        battle->state[wisp_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[surf_side].pokemon[0], GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *surf = &GEN3_MOVES[GEN3_MOVE_SURF];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= surf->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[surf_side].pokemon[0],
        &battle->teams[wisp_side].pokemon[0], surf,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage >= battle->state[wisp_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[surf_side][0].pp[slots[surf_side]]--;
    record_move(battle, (uint8_t)surf_side, GEN3_MOVE_SURF);
    battle->state[wisp_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)wisp_side);
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    battle->state[surf_side][0].status = GEN3_STATUS_BURN;
    record_status(battle, (uint8_t)surf_side, GEN3_STATUS_BURN);
    apply_leftovers_side(battle, surf_side);
    apply_burn_residual(battle, surf_side);
    apply_leftovers_side(battle, wisp_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_spikes_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].move_ids[slots[0]] != GEN3_MOVE_SPIKES ||
        battle->teams[1].pokemon[0].move_ids[slots[1]] != GEN3_MOVE_SPIKES ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[0][0].pp[slots[0]] == 0 ||
        battle->state[1][0].pp[slots[1]] == 0 ||
        battle->spikes[0] != 3 || battle->spikes[1] != 3) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = random_below(output, 2);
    for (size_t frame = 1; frame < 8; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t residual_first = random_below(output, 2);

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
        record_fail(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_spikes_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t spikes_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SPIKES) spikes_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (spikes_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        spikes_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int spikes_at_limit = battle->spikes[whirlwind_side] >= 3;
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[spikes_side][slot].hp >
            spikes_damage(battle, spikes_side, slot)) {
            candidates[candidate_count++] = slot;
        }
    }
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    if (candidate_count == 0) {
        for (size_t frame = 0; frame < 8; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        battle->state[spikes_side][0].pp[slots[spikes_side]]--;
        battle->state[spikes_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
        if (spikes_at_limit) {
            record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
        } else {
            battle->spikes[whirlwind_side]++;
            record_side_start(
                battle, (uint8_t)whirlwind_side, GEN3_MOVE_SPIKES
            );
        }
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
        battle->state[whirlwind_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
        record_fail(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
        apply_leftovers_speed_ordered(battle);
        if (battle->state[spikes_side][0].leech_seeded) {
            apply_leech_seed_residual(battle, spikes_side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    for (size_t frame = 0; frame < 5; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t dragged_slot = candidates[random_below(
        output, (uint32_t)candidate_count
    )];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    if (spikes_at_limit) {
        record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    } else {
        battle->spikes[whirlwind_side]++;
        record_side_start(
            battle, (uint8_t)whirlwind_side, GEN3_MOVE_SPIKES
        );
    }
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    battle->state[whirlwind_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, spikes_side, dragged_slot);
    apply_spikes_entry(battle, spikes_side);
    apply_leftovers_speed_ordered(battle);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_standard_damage_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t damage_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_THUNDERBOLT || move_id == GEN3_MOVE_PSYCHIC) {
            damage_side = side;
        }
        if (move_id == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (damage_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        damage_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[damage_side].pokemon[0].stats[5] <=
            battle->teams[spikes_side].pokemon[0].stats[5] ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->spikes[damage_side] != 3 ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3PokemonSet *attacker = &battle->teams[damage_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[spikes_side].pokemon[0];
    uint16_t move_id = attacker->move_ids[slots[damage_side]];
    const Gen3MoveData *move = &GEN3_MOVES[move_id];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        attacker, target, move, random_below(output, 16), 0
    );
    if (battle->state[spikes_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int secondary_effect = random_below(output, 100) < 10;
    if (secondary_effect && move_id != GEN3_MOVE_PSYCHIC) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    battle->state[damage_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)damage_side, move_id);
    battle->state[spikes_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)spikes_side);
    if (secondary_effect) {
        int8_t *stage = &battle->state[spikes_side][0]
            .stat_stages[GEN3_STAT_SPD - 1];
        if (*stage > -6) {
            (*stage)--;
            record_stat_change(
                battle, (uint8_t)spikes_side, GEN3_STAT_SPD, 1, 1
            );
        }
    }
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    apply_leftovers_side(battle, damage_side);
    apply_leftovers_side(battle, spikes_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_surf_and_successful_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t surf_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_SURF) surf_side = side;
        if (move_id == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (surf_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        surf_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[surf_side].pokemon[0].stats[5] <=
            battle->teams[spikes_side].pokemon[0].stats[5] ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->spikes[surf_side] >= 3 ||
        (battle->state[surf_side][0].status != GEN3_STATUS_NONE &&
         battle->state[surf_side][0].status != GEN3_STATUS_TOXIC) ||
        battle->state[spikes_side][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_SURF];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[surf_side].pokemon[0],
        &battle->teams[spikes_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (damage >= battle->state[spikes_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[surf_side][0].pp[slots[surf_side]]--;
    battle->state[surf_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)surf_side, GEN3_MOVE_SURF);
    battle->state[spikes_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)spikes_side);
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    battle->spikes[surf_side]++;
    record_side_start(battle, (uint8_t)surf_side, GEN3_MOVE_SPIKES);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? surf_side : spikes_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_standard_damage_ko_before_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t damage_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_ICE_BEAM || move == GEN3_MOVE_ICE_PUNCH ||
            move == GEN3_MOVE_THUNDERBOLT || move == GEN3_MOVE_PSYCHIC ||
            move == GEN3_MOVE_SURF || move == GEN3_MOVE_EARTHQUAKE) {
            damage_side = side;
        }
        if (move == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (damage_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        damage_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[damage_side].pokemon[0].stats[5] <=
            battle->teams[spikes_side].pokemon[0].stats[5] ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3PokemonSet *attacker = &battle->teams[damage_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[spikes_side].pokemon[0];
    uint16_t move_id = attacker->move_ids[slots[damage_side]];
    const Gen3MoveData *move = &GEN3_MOVES[move_id];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        attacker, target, move, random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage < battle->state[spikes_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (move_id == GEN3_MOVE_ICE_BEAM || move_id == GEN3_MOVE_ICE_PUNCH ||
        move_id == GEN3_MOVE_THUNDERBOLT || move_id == GEN3_MOVE_PSYCHIC) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    battle->state[damage_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)damage_side, move_id);
    battle->state[spikes_side][0].hp = 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)spikes_side);
    record_faint(battle, (uint8_t)spikes_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)spikes_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_fixed_damage_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t damage_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_SEISMIC_TOSS) damage_side = side;
        if (move_id == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (damage_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        damage_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[spikes_side].pokemon[0].stats[5] <=
            battle->teams[damage_side].pokemon[0].stats[5] ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->spikes[damage_side] != 3 ||
        battle->state[spikes_side][0].status != GEN3_STATUS_NONE ||
        (battle->state[damage_side][0].status != GEN3_STATUS_NONE &&
         battle->state[damage_side][0].status != GEN3_STATUS_TOXIC)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    battle->state[damage_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)damage_side, GEN3_MOVE_SEISMIC_TOSS);
    uint16_t damage = battle->teams[damage_side].pokemon[0].level;
    int target_fainted = battle->state[spikes_side][0].hp <= damage;
    battle->state[spikes_side][0].hp = target_fainted ? 0u :
        (uint16_t)(battle->state[spikes_side][0].hp - damage);
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)spikes_side);
    if (target_fainted) {
        battle->state[spikes_side][0].status = GEN3_STATUS_NONE;
        battle->state[spikes_side][0].toxic_counter = 0;
        battle->state[spikes_side][0].leech_seeded = 0;
        record_faint(battle, (uint8_t)spikes_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)spikes_side;
            battle->resume_residuals = 1;
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? spikes_side : damage_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_recover_and_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t recover_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER) recover_side = side;
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (recover_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        recover_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[recover_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[recover_side][0].pp[slots[recover_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[recover_side][0].hp == 0 ||
        battle->state[recover_side][0].hp >=
            battle->teams[recover_side].pokemon[0].stats[0] ||
        (battle->state[recover_side][0].status != GEN3_STATUS_NONE &&
         battle->state[recover_side][0].status != GEN3_STATUS_TOXIC) ||
        poison_immune(&battle->teams[recover_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    int toxic_already_present =
        battle->state[recover_side][0].status == GEN3_STATUS_TOXIC;
    if (!toxic_already_present) {
        const Gen3MoveData *toxic = &GEN3_MOVES[GEN3_MOVE_TOXIC];
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= toxic->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[recover_side][0].pp[slots[recover_side]]--;
    record_move(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    uint16_t max_hp = battle->teams[recover_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[recover_side][0].hp + max_hp / 2u;
    battle->state[recover_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)recover_side);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    if (toxic_already_present) {
        record_fail(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    } else {
        battle->state[recover_side][0].status = GEN3_STATUS_TOXIC;
        battle->state[recover_side][0].toxic_counter = 0;
        record_status(battle, (uint8_t)recover_side, GEN3_STATUS_TOXIC);
    }
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[1 - side][0].hp > 0 &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_seismic_toss_and_ice_beam(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toss_side = SIZE_MAX;
    size_t ice_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
    }
    if (toss_side == SIZE_MAX || ice_side == SIZE_MAX || toss_side == ice_side ||
        !switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[toss_side].pokemon[0].stats[5] <=
            battle->teams[ice_side].pokemon[0].stats[5] ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[ice_side].pokemon[0], GEN3_TYPE_GHOST)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *toss = &GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS];
    const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= toss->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t ice_damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[toss_side].pokemon[0], ice,
        random_below(output, 16), 0
    );
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (battle->state[ice_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level ||
        battle->state[toss_side][0].hp <= ice_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[ice_side][0].hp -= battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)ice_side);
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[toss_side][0].hp -= ice_damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toss_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_seismic_toss_and_thunderbolt(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toss_side = SIZE_MAX;
    size_t bolt_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
        if (move == GEN3_MOVE_THUNDERBOLT) bolt_side = side;
    }
    if (toss_side == SIZE_MAX || bolt_side == SIZE_MAX ||
        toss_side == bolt_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[bolt_side].pokemon[0].stats[5] <=
            battle->teams[toss_side].pokemon[0].stats[5] ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[bolt_side][0].pp[slots[bolt_side]] == 0 ||
        has_type(&battle->teams[bolt_side].pokemon[0], GEN3_TYPE_GHOST) ||
        battle->state[toss_side][0].hp == 0 ||
        battle->state[bolt_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level ||
        (battle->state[toss_side][0].status != GEN3_STATUS_NONE &&
         battle->state[toss_side][0].status != GEN3_STATUS_TOXIC) ||
        (battle->state[bolt_side][0].status != GEN3_STATUS_NONE &&
         battle->state[bolt_side][0].status != GEN3_STATUS_TOXIC)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *bolt = &GEN3_MOVES[GEN3_MOVE_THUNDERBOLT];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= bolt->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[bolt_side].pokemon[0],
        &battle->teams[toss_side].pokemon[0], bolt,
        random_below(output, 16), 0
    );
    if (battle->state[toss_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    const Gen3MoveData *toss = &GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= toss->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[bolt_side][0].pp[slots[bolt_side]]--;
    record_move(battle, (uint8_t)bolt_side, GEN3_MOVE_THUNDERBOLT);
    battle->state[toss_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toss_side);
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[bolt_side][0].hp -=
        battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)bolt_side);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? bolt_side : toss_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    if (battle->force_switch_side < 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_recover_and_ice_beam(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t recover_side = SIZE_MAX;
    size_t ice_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER) recover_side = side;
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
    }
    if (recover_side != SIZE_MAX && ice_side != SIZE_MAX &&
        recover_side != ice_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[ice_side].pokemon[0].stats[5] >
            battle->teams[recover_side].pokemon[0].stats[5] &&
        battle->state[recover_side][0].pp[slots[recover_side]] != 0 &&
        battle->state[ice_side][0].pp[slots[ice_side]] != 0 &&
        battle->state[recover_side][0].hp > 0 &&
        (battle->state[recover_side][0].status == GEN3_STATUS_NONE ||
         battle->state[recover_side][0].status == GEN3_STATUS_TOXIC) &&
        battle->state[ice_side][0].status == GEN3_STATUS_NONE) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= ice->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        int critical = random_below(output, 16) == 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        uint16_t damage = standard_damage(
            &battle->teams[ice_side].pokemon[0],
            &battle->teams[recover_side].pokemon[0], ice,
            random_below(output, 16), 0
        );
        if (critical) damage = (uint16_t)(damage * 2u);
        if (damage < battle->state[recover_side][0].hp) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[ice_side][0].pp[slots[ice_side]]--;
        battle->state[ice_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
        battle->state[recover_side][0].hp = 0;
        battle->state[recover_side][0].status = GEN3_STATUS_NONE;
        battle->state[recover_side][0].toxic_counter = 0;
        battle->state[recover_side][0].leech_seeded = 0;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)recover_side);
        record_faint(battle, (uint8_t)recover_side);
        if (!battle->done) {
            battle->force_switch_side = (int8_t)recover_side;
            battle->resume_residuals = 1;
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (recover_side == SIZE_MAX || ice_side == SIZE_MAX ||
        recover_side == ice_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[recover_side][0].pp[slots[recover_side]] == 0 ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[recover_side][0].hp == 0 ||
        battle->state[recover_side][0].hp >=
            battle->teams[recover_side].pokemon[0].stats[0] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 2) != recover_side) return GEN3_UNSUPPORTED_ACTION;
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[recover_side].pokemon[0], ice,
        random_below(output, 16), 0
    );
    uint16_t max_hp = battle->teams[recover_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[recover_side][0].hp + max_hp / 2u;
    if (healed > max_hp) healed = max_hp;
    if (healed <= damage) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 5; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 2) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    battle->state[recover_side][0].pp[slots[recover_side]]--;
    record_move(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    battle->state[recover_side][0].hp =
        (uint16_t)healed;
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)recover_side);
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[recover_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)recover_side);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_recover_and_ice_punch_unequal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t recover_side = SIZE_MAX;
    size_t ice_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER) recover_side = side;
        if (move == GEN3_MOVE_ICE_PUNCH) ice_side = side;
    }
    if (recover_side == SIZE_MAX || ice_side == SIZE_MAX ||
        recover_side == ice_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[recover_side].pokemon[0].stats[5] <=
            battle->teams[ice_side].pokemon[0].stats[5] ||
        battle->state[recover_side][0].pp[slots[recover_side]] == 0 ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[recover_side][0].hp == 0 ||
        battle->state[recover_side][0].hp >=
            battle->teams[recover_side].pokemon[0].stats[0] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_PUNCH];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[recover_side].pokemon[0], ice,
        random_below(output, 16), 0
    );
    uint16_t max_hp = battle->teams[recover_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[recover_side][0].hp +
        max_hp / 2u;
    if (healed > max_hp) healed = max_hp;
    if (healed <= damage) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[recover_side][0].pp[slots[recover_side]]--;
    record_move(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    battle->state[recover_side][0].hp = (uint16_t)healed;
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)recover_side);
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_PUNCH);
    battle->state[recover_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)recover_side);
    battle->state[recover_side][0].status = GEN3_STATUS_FREEZE;
    record_status(battle, (uint8_t)recover_side, GEN3_STATUS_FREEZE);
    apply_leftovers_side(battle, recover_side);
    apply_leftovers_side(battle, ice_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_recover_and_seismic_toss(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t recover_side = SIZE_MAX;
    size_t toss_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER) recover_side = side;
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
    }
    if (recover_side == SIZE_MAX || toss_side == SIZE_MAX ||
        recover_side == toss_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[recover_side].pokemon[0].stats[5] <=
            battle->teams[toss_side].pokemon[0].stats[5] ||
        battle->state[recover_side][0].pp[slots[recover_side]] == 0 ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[recover_side][0].hp !=
            battle->teams[recover_side].pokemon[0].stats[0] ||
        battle->state[recover_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level ||
        has_type(&battle->teams[recover_side].pokemon[0], GEN3_TYPE_GHOST)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *toss = &GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= toss->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[recover_side][0].pp[slots[recover_side]]--;
    record_move(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    record_fail(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[recover_side][0].hp -=
        battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)recover_side);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? recover_side : toss_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_seismic_toss(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t toss_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
    }
    int equal_speed = heal_side != SIZE_MAX && toss_side != SIZE_MAX &&
        battle->teams[heal_side].pokemon[0].stats[5] ==
            battle->teams[toss_side].pokemon[0].stats[5];
    if (heal_side == SIZE_MAX || toss_side == SIZE_MAX ||
        heal_side == toss_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        (!equal_speed && battle->teams[heal_side].pokemon[0].stats[5] <=
            battle->teams[toss_side].pokemon[0].stats[5]) ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        (equal_speed && battle->state[heal_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level) ||
        has_type(&battle->teams[heal_side].pokemon[0], GEN3_TYPE_GHOST)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (!equal_speed) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >=
            GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[heal_side][0].pp[slots[heal_side]]--;
        record_move(battle, (uint8_t)heal_side, heal_move);
        uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
        uint32_t healed =
            (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
        battle->state[heal_side][0].hp =
            (uint16_t)(healed > max_hp ? max_hp : healed);
        record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
        battle->state[toss_side][0].pp[slots[toss_side]]--;
        record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
        battle->state[heal_side][0].hp -=
            battle->teams[toss_side].pokemon[0].level;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)heal_side);
        apply_leftovers_side(battle, heal_side);
        apply_leftovers_side(battle, toss_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 10; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0 && random_below(output, 2) != toss_side) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        if (frame == 7) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[heal_side][0].hp -=
        battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)heal_side);
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_seismic_toss(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t toss_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
    }
    if (cleric_side == SIZE_MAX || toss_side == SIZE_MAX ||
        cleric_side == toss_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[cleric_side].pokemon[0].stats[5] !=
            battle->teams[toss_side].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[cleric_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level ||
        has_type(&battle->teams[cleric_side].pokemon[0], GEN3_TYPE_GHOST)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t residual_first = 0;
    size_t first_side = 0;
    for (size_t frame = 0; frame < 10; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 7) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        if (side == toss_side) {
            battle->state[toss_side][0].pp[slots[toss_side]]--;
            record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
            battle->state[cleric_side][0].hp -=
                battle->teams[toss_side].pokemon[0].level;
            record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
        } else {
            battle->state[cleric_side][0].pp[slots[cleric_side]]--;
            record_move(battle, (uint8_t)cleric_side, cleric_move);
            for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
                battle->state[cleric_side][slot].toxic_counter = 0;
            }
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_seismic_toss_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].move_ids[slots[0]] !=
            GEN3_MOVE_SEISMIC_TOSS ||
        battle->teams[1].pokemon[0].move_ids[slots[1]] !=
            GEN3_MOVE_SEISMIC_TOSS ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5]) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].pp[slots[side]] == 0 ||
            battle->state[side][0].hp <=
                battle->teams[1 - side].pokemon[0].level ||
            has_type(&battle->teams[side].pokemon[0], GEN3_TYPE_GHOST)) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t first_side = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 12; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 9) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        size_t target = 1 - side;
        battle->state[side][0].pp[slots[side]]--;
        record_move(battle, (uint8_t)side, GEN3_MOVE_SEISMIC_TOSS);
        battle->state[target][0].hp -= battle->teams[side].pokemon[0].level;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target);
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_toxic_and_seismic_toss(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toxic_side = SIZE_MAX;
    size_t toss_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
    }
    if (toxic_side != SIZE_MAX && toss_side != SIZE_MAX &&
        toxic_side != toss_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[toxic_side].pokemon[0].stats[5] >
            battle->teams[toss_side].pokemon[0].stats[5] &&
        battle->state[toxic_side][0].pp[slots[toxic_side]] != 0 &&
        battle->state[toss_side][0].pp[slots[toss_side]] != 0 &&
        battle->state[toxic_side][0].hp >
            battle->teams[toss_side].pokemon[0].level &&
        !has_type(&battle->teams[toxic_side].pokemon[0], GEN3_TYPE_GHOST) &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE &&
        !poison_immune(&battle->teams[toss_side].pokemon[0])) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >=
            GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        battle->state[toss_side][0].status = GEN3_STATUS_TOXIC;
        battle->state[toss_side][0].toxic_counter = 0;
        record_status(battle, (uint8_t)toss_side, GEN3_STATUS_TOXIC);
        battle->state[toss_side][0].pp[slots[toss_side]]--;
        battle->state[toss_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
        battle->state[toxic_side][0].hp -=
            battle->teams[toss_side].pokemon[0].level;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
        apply_leftovers_side(battle, toxic_side);
        apply_leftovers_side(battle, toss_side);
        apply_toxic_residual(battle, toss_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (toxic_side != SIZE_MAX && toss_side != SIZE_MAX &&
        toxic_side != toss_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[toss_side].pokemon[0].stats[5] >
            battle->teams[toxic_side].pokemon[0].stats[5] &&
        battle->state[toxic_side][0].pp[slots[toxic_side]] != 0 &&
        battle->state[toss_side][0].pp[slots[toss_side]] != 0 &&
        battle->state[toxic_side][0].hp >
            battle->teams[toss_side].pokemon[0].level &&
        !has_type(&battle->teams[toxic_side].pokemon[0], GEN3_TYPE_GHOST) &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >=
            GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        int toxic_hit = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (toxic_hit) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }

        battle->event_count = 0;
        battle->state[toss_side][0].pp[slots[toss_side]]--;
        record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
        battle->state[toxic_side][0].hp -=
            battle->teams[toss_side].pokemon[0].level;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        if (toxic_hit) {
            battle->state[toss_side][0].status = GEN3_STATUS_TOXIC;
            battle->state[toss_side][0].toxic_counter = 0;
            record_status(battle, (uint8_t)toss_side, GEN3_STATUS_TOXIC);
        }
        apply_leftovers_side(battle, toss_side);
        if (toxic_hit) apply_toxic_residual(battle, toss_side);
        apply_leftovers_side(battle, toxic_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (toxic_side == SIZE_MAX || toss_side == SIZE_MAX ||
        toxic_side == toss_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[toxic_side].pokemon[0].stats[5] !=
            battle->teams[toss_side].pokemon[0].stats[5] ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[toxic_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level ||
        has_type(&battle->teams[toxic_side].pokemon[0], GEN3_TYPE_GHOST) ||
        battle->state[toss_side][0].status != GEN3_STATUS_NONE ||
        poison_immune(&battle->teams[toss_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t first_side = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 11; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 1 &&
            random_below(output, 100) < GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        if (frame == 8) residual_first = random_below(output, 2);
    }
    if (first_side != toxic_side) return GEN3_UNSUPPORTED_ACTION;

    battle->event_count = 0;
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[toxic_side][0].hp -=
        battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_toxic_and_special_damage(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toxic_side = SIZE_MAX;
    size_t damage_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t damage_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
        if (move == GEN3_MOVE_ICE_BEAM || move == GEN3_MOVE_PSYCHIC ||
            move == GEN3_MOVE_THUNDERBOLT || move == GEN3_MOVE_SURF) {
            damage_side = side;
            damage_move = move;
        }
    }
    if (toxic_side == SIZE_MAX || damage_side == SIZE_MAX ||
        toxic_side == damage_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[damage_side].pokemon[0].stats[5] ==
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[damage_side][0].status == GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    int toxic_first = battle->teams[toxic_side].pokemon[0].stats[5] >
        battle->teams[damage_side].pokemon[0].stats[5];
    int toxic_hit = 0;
    const Gen3MoveData *move = &GEN3_MOVES[damage_move];
    if (toxic_first) {
        /* The faster failed status action participates in the action-order
         * queue before the slower attack begins its accuracy sequence. */
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        toxic_hit = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[damage_side].pokemon[0],
        &battle->teams[toxic_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (battle->state[toxic_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (damage_move != GEN3_MOVE_SURF) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) < 10) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (!toxic_first) {
        toxic_hit = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
    }
    if (!toxic_first) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    if (toxic_first) {
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        if (toxic_hit) {
            record_fail(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        }
    }
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    record_move(battle, (uint8_t)damage_side, damage_move);
    battle->state[toxic_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
    if (!toxic_first) {
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        if (toxic_hit) {
            record_fail(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        }
    }
    size_t residual_first = toxic_first ? toxic_side : damage_side;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_toxic_and_special_damage(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toxic_side = SIZE_MAX;
    size_t damage_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t damage_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
        if (move == GEN3_MOVE_ICE_BEAM || move == GEN3_MOVE_PSYCHIC ||
            move == GEN3_MOVE_THUNDERBOLT || move == GEN3_MOVE_SURF) {
            damage_side = side;
            damage_move = move;
        }
    }
    if (toxic_side == SIZE_MAX || damage_side == SIZE_MAX ||
        toxic_side == damage_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[damage_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[damage_side][0].status != GEN3_STATUS_NONE ||
        poison_immune(&battle->teams[damage_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[damage_move];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[damage_side].pokemon[0],
        &battle->teams[toxic_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (battle->state[toxic_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (damage_move != GEN3_MOVE_SURF) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) < 10) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    record_move(battle, (uint8_t)damage_side, damage_move);
    battle->state[toxic_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[damage_side][0].status = GEN3_STATUS_TOXIC;
    battle->state[damage_side][0].toxic_counter = 0;
    record_status(battle, (uint8_t)damage_side, GEN3_STATUS_TOXIC);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? damage_side : toxic_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_surf_and_leech_seed(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t surf_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SURF) surf_side = side;
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
    }
    if (surf_side == SIZE_MAX || seed_side == SIZE_MAX ||
        surf_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[surf_side].pokemon[0].stats[5] <=
            battle->teams[seed_side].pokemon[0].stats[5] ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0 ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[surf_side][0].status != GEN3_STATUS_NONE ||
        battle->state[seed_side][0].status != GEN3_STATUS_NONE ||
        battle->state[surf_side][0].leech_seeded ||
        has_type(&battle->teams[surf_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *surf = &GEN3_MOVES[GEN3_MOVE_SURF];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= surf->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[surf_side].pokemon[0],
        &battle->teams[seed_side].pokemon[0], surf,
        random_below(output, 16), 0
    );
    if (battle->state[seed_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_LEECH_SEED].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[surf_side][0].pp[slots[surf_side]]--;
    record_move(battle, (uint8_t)surf_side, GEN3_MOVE_SURF);
    battle->state[seed_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)seed_side);
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    battle->state[surf_side][0].leech_seeded = 1;
    record_volatile_start(
        battle, (uint8_t)surf_side, GEN3_MOVE_LEECH_SEED
    );
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? surf_side : seed_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_ice_beam_ko_before_surf(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t ice_side = SIZE_MAX;
    size_t surf_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
        if (move == GEN3_MOVE_SURF) surf_side = side;
    }
    if (ice_side == SIZE_MAX || surf_side == SIZE_MAX ||
        ice_side == surf_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[ice_side].pokemon[0].stats[5] !=
            battle->teams[surf_side].pokemon[0].stats[5] ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 2) != ice_side) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[surf_side].pokemon[0], ice,
        random_below(output, 16), 0
    );
    if (battle->state[surf_side][0].hp > damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[surf_side][0].hp = 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)surf_side);
    record_faint(battle, (uint8_t)surf_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)surf_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_ice_beam_ko_before_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t ice_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (ice_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        ice_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[ice_side].pokemon[0].stats[5] <=
            battle->teams[whirlwind_side].pokemon[0].stats[5] ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[whirlwind_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (damage < battle->state[whirlwind_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    battle->state[ice_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[whirlwind_side][0].hp = 0;
    battle->state[whirlwind_side][0].status = GEN3_STATUS_NONE;
    battle->state[whirlwind_side][0].toxic_counter = 0;
    battle->state[whirlwind_side][0].leech_seeded = 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)whirlwind_side);
    record_faint(battle, (uint8_t)whirlwind_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)whirlwind_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_recover_and_ice_beam(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t recover_side = SIZE_MAX;
    size_t ice_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER) recover_side = side;
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
    }
    if (recover_side == SIZE_MAX || ice_side == SIZE_MAX ||
        recover_side == ice_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[recover_side].pokemon[0].stats[5] <=
            battle->teams[ice_side].pokemon[0].stats[5] ||
        battle->state[recover_side][0].pp[slots[recover_side]] == 0 ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[recover_side][0].hp !=
            battle->teams[recover_side].pokemon[0].stats[0] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *ice = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[recover_side].pokemon[0], ice,
        random_below(output, 16), 0
    );
    if (battle->state[recover_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[recover_side][0].pp[slots[recover_side]]--;
    record_move(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    record_fail(battle, (uint8_t)recover_side, GEN3_MOVE_RECOVER);
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[recover_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)recover_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    int equal_speed = cleric_side != SIZE_MAX && toxic_side != SIZE_MAX &&
        battle->teams[cleric_side].pokemon[0].stats[5] ==
            battle->teams[toxic_side].pokemon[0].stats[5];
    if (cleric_side != SIZE_MAX && toxic_side != SIZE_MAX &&
        cleric_side != toxic_side && switch_only_team(battle) &&
        simple_items_team(battle) && !equal_speed &&
        battle->teams[toxic_side].pokemon[0].stats[5] >
            battle->teams[cleric_side].pokemon[0].stats[5] &&
        battle->state[cleric_side][0].pp[slots[cleric_side]] != 0 &&
        battle->state[toxic_side][0].pp[slots[toxic_side]] != 0 &&
        battle->state[cleric_side][0].status != GEN3_STATUS_NONE) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        int toxic_hits = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        if (toxic_hits) {
            record_fail(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        }
        battle->state[cleric_side][0].pp[slots[cleric_side]]--;
        battle->state[cleric_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)cleric_side, cleric_move);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
            battle->state[cleric_side][slot].toxic_counter = 0;
        }
        apply_leftovers_side(battle, toxic_side);
        apply_leftovers_side(battle, cleric_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (cleric_side != SIZE_MAX && toxic_side != SIZE_MAX &&
        cleric_side != toxic_side && switch_only_team(battle) &&
        simple_items_team(battle) && !equal_speed &&
        battle->teams[toxic_side].pokemon[0].stats[5] >
            battle->teams[cleric_side].pokemon[0].stats[5] &&
        battle->state[cleric_side][0].pp[slots[cleric_side]] != 0 &&
        battle->state[toxic_side][0].pp[slots[toxic_side]] != 0 &&
        battle->state[cleric_side][0].status == GEN3_STATUS_NONE &&
        !poison_immune(&battle->teams[cleric_side].pokemon[0])) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) < GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        battle->state[cleric_side][0].pp[slots[cleric_side]]--;
        battle->state[cleric_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)cleric_side, cleric_move);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
            battle->state[cleric_side][slot].toxic_counter = 0;
        }
        apply_leftovers_side(battle, toxic_side);
        apply_leftovers_side(battle, cleric_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (cleric_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        cleric_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        (!equal_speed && battle->teams[cleric_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5]) ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        poison_immune(&battle->teams[cleric_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (equal_speed) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        size_t first_side = random_below(output, 2);
        for (size_t frame = 1; frame < 4; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        for (size_t frame = 4; frame < 10; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            if (side == cleric_side) {
                battle->state[side][0].pp[slots[side]]--;
                record_move(battle, (uint8_t)side, cleric_move);
                for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                    battle->state[side][slot].status = GEN3_STATUS_NONE;
                    battle->state[side][slot].toxic_counter = 0;
                }
            } else {
                battle->state[side][0].pp[slots[side]]--;
                record_move(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
                battle->state[cleric_side][0].status = GEN3_STATUS_TOXIC;
                battle->state[cleric_side][0].toxic_counter = 0;
                record_status(battle, (uint8_t)cleric_side, GEN3_STATUS_TOXIC);
            }
        }
        if (first_side == cleric_side) {
            for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
                size_t side = order == 0 ? first_side : 1u - first_side;
                apply_leftovers_side(battle, side);
            }
            for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
                size_t side = order == 0 ? first_side : 1u - first_side;
                if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                    apply_toxic_residual(battle, side);
                }
            }
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *toxic = &GEN3_MOVES[GEN3_MOVE_TOXIC];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= toxic->accuracy) return GEN3_UNSUPPORTED_ACTION;
    size_t remaining_frames = battle->state[cleric_side][0].status ==
        GEN3_STATUS_NONE ? 2u : 1u;
    for (size_t frame = 0; frame < remaining_frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[cleric_side][0].status = GEN3_STATUS_TOXIC;
    battle->state[cleric_side][0].toxic_counter = 0;
    record_status(battle, (uint8_t)cleric_side, GEN3_STATUS_TOXIC);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? cleric_side : toxic_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_then_cleric(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t cleric_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move_id == GEN3_MOVE_HEAL_BELL ||
            move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
    }
    if (wisp_side == SIZE_MAX || cleric_side == SIZE_MAX ||
        wisp_side == cleric_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[cleric_side].pokemon[0].stats[5] ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[cleric_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[cleric_side].pokemon[0], GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    battle->state[wisp_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    battle->state[cleric_side][0].status = GEN3_STATUS_BURN;
    record_status(battle, (uint8_t)cleric_side, GEN3_STATUS_BURN);
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_then_missed_will_o_wisp(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t wisp_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move_id;
        }
        if (move_id == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
    }
    if (heal_side == SIZE_MAX || wisp_side == SIZE_MAX ||
        heal_side == wisp_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[heal_side].pokemon[0].stats[5] <=
            battle->teams[wisp_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0]) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) <
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    battle->state[wisp_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_HEAL_BELL || move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
        if (move_id == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (cleric_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        cleric_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[spikes_side].pokemon[0].stats[5] <=
            battle->teams[cleric_side].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int spikes_at_limit = battle->spikes[cleric_side] >= 3;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    if (spikes_at_limit) {
        record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    } else {
        battle->spikes[cleric_side]++;
        record_side_start(
            battle, (uint8_t)cleric_side, GEN3_MOVE_SPIKES
        );
    }
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_cleric(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t cleric_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move_id;
        }
        if (move_id == GEN3_MOVE_HEAL_BELL || move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
    }
    int equal_speed = heal_side != SIZE_MAX && cleric_side != SIZE_MAX &&
        battle->teams[heal_side].pokemon[0].stats[5] ==
            battle->teams[cleric_side].pokemon[0].stats[5];
    int slower_full_hp_heal = heal_side != SIZE_MAX && cleric_side != SIZE_MAX &&
        battle->teams[heal_side].pokemon[0].stats[5] <
            battle->teams[cleric_side].pokemon[0].stats[5] &&
        battle->state[heal_side][0].hp ==
            battle->teams[heal_side].pokemon[0].stats[0];
    if (heal_side == SIZE_MAX || cleric_side == SIZE_MAX ||
        heal_side == cleric_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        (!equal_speed && !slower_full_hp_heal &&
         battle->teams[heal_side].pokemon[0].stats[5] <=
            battle->teams[cleric_side].pokemon[0].stats[5]) ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        (!slower_full_hp_heal && battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (slower_full_hp_heal) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[cleric_side][0].pp[slots[cleric_side]]--;
        battle->state[cleric_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)cleric_side, cleric_move);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
            battle->state[cleric_side][slot].toxic_counter = 0;
        }
        battle->state[heal_side][0].pp[slots[heal_side]]--;
        battle->state[heal_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)heal_side, heal_move);
        record_fail(battle, (uint8_t)heal_side, heal_move);
        apply_leftovers_speed_ordered(battle);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    if (equal_speed) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        size_t first_side = 0;
        for (size_t frame = 0; frame < 8; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (frame == 0) first_side = random_below(output, 2);
        }
        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            battle->state[side][0].pp[slots[side]]--;
            battle->state[side][0].protect_counter = 0;
            if (side == cleric_side) {
                record_move(battle, (uint8_t)side, cleric_move);
                for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                    battle->state[side][slot].status = GEN3_STATUS_NONE;
                    battle->state[side][slot].toxic_counter = 0;
                }
            } else {
                record_move(battle, (uint8_t)side, heal_move);
                uint16_t max_hp = battle->teams[side].pokemon[0].stats[0];
                uint32_t healed =
                    (uint32_t)battle->state[side][0].hp + max_hp / 2u;
                battle->state[side][0].hp =
                    (uint16_t)(healed > max_hp ? max_hp : healed);
                record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
            }
        }
        apply_leftovers_side(battle, heal_side);
        apply_leftovers_side(battle, cleric_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_side(battle, heal_side);
    if (battle->state[heal_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, heal_side);
    }
    apply_leftovers_side(battle, cleric_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t moves[GEN3_SIDE_COUNT];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5]) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        moves[side] = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if ((moves[side] != GEN3_MOVE_HEAL_BELL &&
             moves[side] != GEN3_MOVE_AROMATHERAPY) ||
            battle->state[side][0].pp[slots[side]] == 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, moves[side]);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            battle->state[side][slot].status = GEN3_STATUS_NONE;
            battle->state[side][slot].toxic_counter = 0;
        }
    }
    apply_leftovers_speed_ordered(battle);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t moves[GEN3_SIDE_COUNT];
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        moves[side] = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if ((moves[side] != GEN3_MOVE_RECOVER &&
             moves[side] != GEN3_MOVE_SOFT_BOILED) ||
            battle->state[side][0].pp[slots[side]] == 0 ||
            battle->state[side][0].status != GEN3_STATUS_NONE) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (equal_speed) {
        for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
            if (battle->state[side][0].hp == 0 ||
                battle->state[side][0].hp >=
                    battle->teams[side].pokemon[0].stats[0]) {
                return GEN3_UNSUPPORTED_ACTION;
            }
        }
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        size_t first_side = random_below(output, 2);
        for (size_t frame = 1; frame < 8; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1 - first_side;
            battle->state[side][0].pp[slots[side]]--;
            battle->state[side][0].protect_counter = 0;
            record_move(battle, (uint8_t)side, moves[side]);
            uint16_t max_hp = battle->teams[side].pokemon[0].stats[0];
            uint32_t healed = (uint32_t)battle->state[side][0].hp + max_hp / 2u;
            battle->state[side][0].hp =
                (uint16_t)(healed > max_hp ? max_hp : healed);
            record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    size_t first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    size_t second_side = 1 - first_side;
    if (battle->state[first_side][0].hp == 0 ||
        battle->state[first_side][0].hp >=
            battle->teams[first_side].pokemon[0].stats[0] ||
        battle->state[second_side][0].hp == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : second_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, moves[side]);
        if (battle->state[side][0].hp <
            battle->teams[side].pokemon[0].stats[0]) {
            uint16_t max_hp = battle->teams[side].pokemon[0].stats[0];
            uint32_t healed = (uint32_t)battle->state[side][0].hp + max_hp / 2u;
            battle->state[side][0].hp =
                (uint16_t)(healed > max_hp ? max_hp : healed);
            record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
        } else {
            record_fail(battle, (uint8_t)side, moves[side]);
        }
    }
    apply_leftovers_side(battle, first_side);
    apply_leftovers_side(battle, second_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_heal_and_toxic_equal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (heal_side == SIZE_MAX || toxic_side == SIZE_MAX || heal_side == toxic_side ||
        !switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[heal_side][0].hp !=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        battle->state[heal_side][0].status != GEN3_STATUS_NONE ||
        poison_immune(&battle->teams[heal_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 2) != heal_side) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t frame = 0; frame < 6; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    record_move(battle, (uint8_t)heal_side, heal_move);
    record_fail(battle, (uint8_t)heal_side, heal_move);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[heal_side][0].status = GEN3_STATUS_TOXIC;
    battle->state[heal_side][0].toxic_counter = 0;
    record_status(battle, (uint8_t)heal_side, GEN3_STATUS_TOXIC);
    apply_leftovers_speed_ordered(battle);
    apply_toxic_residual(battle, heal_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_failed_heal_and_toxic_unequal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move_id;
        }
        if (move_id == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (heal_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        heal_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[toxic_side].pokemon[0].stats[5] ==
            battle->teams[heal_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[heal_side][0].hp !=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        battle->state[heal_side][0].status != GEN3_STATUS_NONE ||
        poison_immune(&battle->teams[heal_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    size_t first_side = battle->teams[toxic_side].pokemon[0].stats[5] >
        battle->teams[heal_side].pokemon[0].stats[5] ? toxic_side : heal_side;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1 - first_side;
        if (side == toxic_side) {
            battle->state[toxic_side][0].pp[slots[toxic_side]]--;
            battle->state[toxic_side][0].protect_counter = 0;
            record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
            battle->state[heal_side][0].status = GEN3_STATUS_TOXIC;
            battle->state[heal_side][0].toxic_counter = 0;
            record_status(battle, (uint8_t)heal_side, GEN3_STATUS_TOXIC);
        } else {
            battle->state[heal_side][0].pp[slots[heal_side]]--;
            battle->state[heal_side][0].protect_counter = 0;
            record_move(battle, (uint8_t)heal_side, heal_move);
            record_fail(battle, (uint8_t)heal_side, heal_move);
        }
    }
    apply_leftovers_speed_ordered(battle);
    apply_toxic_residual(battle, heal_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_toxic_then_heal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move_id;
        }
        if (move_id == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (heal_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        heal_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[toxic_side].pokemon[0].stats[5] <=
            battle->teams[heal_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        battle->state[heal_side][0].status != GEN3_STATUS_NONE ||
        poison_immune(&battle->teams[heal_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    battle->state[toxic_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[heal_side][0].status = GEN3_STATUS_TOXIC;
    battle->state[heal_side][0].toxic_counter = 0;
    record_status(battle, (uint8_t)heal_side, GEN3_STATUS_TOXIC);
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    apply_leftovers_side(battle, toxic_side);
    apply_leftovers_side(battle, heal_side);
    apply_toxic_residual(battle, heal_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_leech_seed_and_seismic_toss(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t seed_side = SIZE_MAX;
    size_t toss_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
    }
    if (seed_side == SIZE_MAX || toss_side == SIZE_MAX || seed_side == toss_side ||
        !switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[seed_side].pokemon[0].stats[5] <=
            battle->teams[toss_side].pokemon[0].stats[5] ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[toss_side][0].leech_seeded ||
        has_type(&battle->teams[toss_side].pokemon[0], GEN3_TYPE_GRASS) ||
        has_type(&battle->teams[seed_side].pokemon[0], GEN3_TYPE_GHOST) ||
        battle->state[seed_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *seed = &GEN3_MOVES[GEN3_MOVE_LEECH_SEED];
    const Gen3MoveData *toss = &GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= seed->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= toss->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    battle->state[toss_side][0].leech_seeded = 1;
    record_volatile_start(battle, (uint8_t)toss_side, GEN3_MOVE_LEECH_SEED);
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[seed_side][0].hp -= battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)seed_side);

    apply_leftovers_side(battle, seed_side);
    if (battle->state[seed_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, seed_side);
    }
    apply_leech_seed_residual(battle, toss_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_leech_seed_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t seed_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (seed_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        seed_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[seed_side].pokemon[0].stats[5] <=
            battle->teams[whirlwind_side].pokemon[0].stats[5] ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        has_type(&battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int target_already_seeded =
        battle->state[whirlwind_side][0].leech_seeded;
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[seed_side][slot].hp >
            spikes_damage(battle, seed_side, slot)) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *seed = &GEN3_MOVES[GEN3_MOVE_LEECH_SEED];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= seed->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t frame = 1; frame < 5; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t dragged_slot = candidates[random_below(
        output, (uint32_t)candidate_count
    )];
    for (size_t frame = 5; frame < 8; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t residual_first = random_below(output, 2);

    battle->event_count = 0;
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    if (target_already_seeded) {
        record_fail(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    } else {
        battle->state[whirlwind_side][0].leech_seeded = 1;
        record_volatile_start(
            battle, (uint8_t)whirlwind_side, GEN3_MOVE_LEECH_SEED
        );
    }
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, seed_side, dragged_slot);
    apply_spikes_entry(battle, seed_side);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    apply_leech_seed_residual(battle, whirlwind_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_seismic_toss_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toss_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_SEISMIC_TOSS) toss_side = side;
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (toss_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        toss_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[toss_side][0].pp[slots[toss_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        has_type(&battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_GHOST) ||
        battle->state[whirlwind_side][0].hp <=
            battle->teams[toss_side].pokemon[0].level) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[toss_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_SEISMIC_TOSS].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t replacement =
        candidates[random_below(output, (uint32_t)candidate_count)];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (battle->state[toss_side][replacement].hp <=
        spikes_damage(battle, toss_side, replacement)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (battle->spikes[toss_side] >= 2) {
        for (size_t frame = 0; frame < 4; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }

    battle->event_count = 0;
    battle->state[toss_side][0].pp[slots[toss_side]]--;
    record_move(battle, (uint8_t)toss_side, GEN3_MOVE_SEISMIC_TOSS);
    battle->state[whirlwind_side][0].hp -=
        battle->teams[toss_side].pokemon[0].level;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)whirlwind_side);
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, toss_side, replacement);
    apply_spikes_entry(battle, toss_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_psychic_and_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t psychic_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    uint16_t damage_move_id = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PSYCHIC || move == GEN3_MOVE_ICE_PUNCH) {
            psychic_side = side;
            damage_move_id = move;
        }
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (psychic_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        psychic_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[psychic_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[psychic_side][0].pp[slots[psychic_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        (battle->state[psychic_side][0].status != GEN3_STATUS_NONE &&
         battle->state[psychic_side][0].status != GEN3_STATUS_TOXIC) ||
        (battle->state[toxic_side][0].status != GEN3_STATUS_NONE &&
         battle->state[toxic_side][0].status != GEN3_STATUS_TOXIC)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *psychic = &GEN3_MOVES[damage_move_id];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= psychic->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[psychic_side].pokemon[0],
        &battle->teams[toxic_side].pokemon[0], psychic,
        random_below(output, 16), critical
    );
    if (damage >= battle->state[toxic_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int secondary_effect = random_below(output, 100) < 10;
    if (secondary_effect && damage_move_id != GEN3_MOVE_PSYCHIC) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int target_already_statused = battle->state[psychic_side][0].status !=
        GEN3_STATUS_NONE;
    int toxic_fails = target_already_statused || poison_immune(
        &battle->teams[psychic_side].pokemon[0]
    );
    if (!toxic_fails) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >=
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[psychic_side][0].pp[slots[psychic_side]]--;
    record_move(battle, (uint8_t)psychic_side, damage_move_id);
    battle->state[toxic_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
    if (secondary_effect && damage_move_id == GEN3_MOVE_PSYCHIC) {
        int8_t *stage = &battle->state[toxic_side][0]
            .stat_stages[GEN3_STAT_SPD - 1];
        if (*stage > -6) {
            (*stage)--;
            record_stat_change(
                battle, (uint8_t)toxic_side, GEN3_STAT_SPD, 1, 1
            );
        }
    }
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    if (target_already_statused) {
        record_fail(battle, (uint8_t)psychic_side, GEN3_MOVE_PSYCHIC);
    } else if (!toxic_fails) {
        battle->state[psychic_side][0].status = GEN3_STATUS_TOXIC;
        battle->state[psychic_side][0].toxic_counter = 0;
        record_status(battle, (uint8_t)psychic_side, GEN3_STATUS_TOXIC);
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? psychic_side : toxic_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_and_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (wisp_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        wisp_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[wisp_side][0].status != GEN3_STATUS_NONE ||
        battle->state[toxic_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[toxic_side].pokemon[0], GEN3_TYPE_FIRE) ||
        !poison_immune(&battle->teams[wisp_side].pokemon[0])) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    battle->state[toxic_side][0].status = GEN3_STATUS_BURN;
    record_status(battle, (uint8_t)toxic_side, GEN3_STATUS_BURN);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    apply_leftovers_side(battle, wisp_side);
    apply_leftovers_side(battle, toxic_side);
    apply_burn_residual(battle, toxic_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_and_immune_earthquake(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t wisp_side = SIZE_MAX;
    size_t earthquake_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_WILL_O_WISP) wisp_side = side;
        if (move_id == GEN3_MOVE_EARTHQUAKE) earthquake_side = side;
    }
    if (wisp_side == SIZE_MAX || earthquake_side == SIZE_MAX ||
        wisp_side == earthquake_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[wisp_side].pokemon[0].stats[5] <=
            battle->teams[earthquake_side].pokemon[0].stats[5] ||
        battle->teams[wisp_side].pokemon[0].ability_id !=
            GEN3_ABILITY_LEVITATE ||
        battle->state[wisp_side][0].pp[slots[wisp_side]] == 0 ||
        battle->state[earthquake_side][0].pp[slots[earthquake_side]] == 0 ||
        battle->state[earthquake_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[earthquake_side].pokemon[0], GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[wisp_side][0].pp[slots[wisp_side]]--;
    battle->state[wisp_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)wisp_side, GEN3_MOVE_WILL_O_WISP);
    battle->state[earthquake_side][0].status = GEN3_STATUS_BURN;
    record_status(battle, (uint8_t)earthquake_side, GEN3_STATUS_BURN);
    battle->state[earthquake_side][0].pp[slots[earthquake_side]]--;
    battle->state[earthquake_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)earthquake_side, GEN3_MOVE_EARTHQUAKE);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? wisp_side : earthquake_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_leech_seed(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
    }
    if (heal_side != SIZE_MAX && seed_side != SIZE_MAX &&
        heal_side != seed_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[heal_side].pokemon[0].stats[5] ==
            battle->teams[seed_side].pokemon[0].stats[5] &&
        battle->state[heal_side][0].pp[slots[heal_side]] != 0 &&
        battle->state[seed_side][0].pp[slots[seed_side]] != 0 &&
        battle->state[heal_side][0].hp ==
            battle->teams[heal_side].pokemon[0].stats[0] &&
        battle->state[heal_side][0].status == GEN3_STATUS_NONE &&
        battle->state[seed_side][0].status == GEN3_STATUS_NONE &&
        !battle->state[0][0].leech_seeded &&
        !battle->state[1][0].leech_seeded &&
        has_type(&battle->teams[heal_side].pokemon[0], GEN3_TYPE_GRASS)) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 2) != heal_side) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        /* Two tied action queues precede the moves; four tied residual
         * handlers and the generation-wide item-order roll follow them. */
        for (size_t frame = 1; frame < 9; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        battle->state[heal_side][0].pp[slots[heal_side]]--;
        battle->state[heal_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)heal_side, heal_move);
        record_fail(battle, (uint8_t)heal_side, heal_move);
        battle->state[seed_side][0].pp[slots[seed_side]]--;
        battle->state[seed_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (heal_side == SIZE_MAX || seed_side == SIZE_MAX ||
        heal_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[seed_side].pokemon[0].stats[5] <=
            battle->teams[heal_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        (battle->state[heal_side][0].status != GEN3_STATUS_NONE &&
         battle->state[heal_side][0].status != GEN3_STATUS_TOXIC) ||
        (battle->state[seed_side][0].status != GEN3_STATUS_NONE &&
         battle->state[seed_side][0].status != GEN3_STATUS_TOXIC) ||
        battle->state[heal_side][0].leech_seeded ||
        has_type(&battle->teams[heal_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *seed = &GEN3_MOVES[GEN3_MOVE_LEECH_SEED];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= seed->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    battle->state[seed_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    battle->state[heal_side][0].leech_seeded = 1;
    record_volatile_start(battle, (uint8_t)heal_side, GEN3_MOVE_LEECH_SEED);
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    if (battle->state[heal_side][0].hp == max_hp) {
        record_fail(battle, (uint8_t)heal_side, heal_move);
    } else {
        uint32_t healed =
            (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
        battle->state[heal_side][0].hp =
            (uint16_t)(healed > max_hp ? max_hp : healed);
        record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? seed_side : heal_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (heal_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        heal_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[heal_side].pokemon[0].stats[5] ==
            battle->teams[spikes_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->state[heal_side][0].hp == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    size_t first_side = battle->teams[spikes_side].pokemon[0].stats[5] >
        battle->teams[heal_side].pokemon[0].stats[5] ? spikes_side : heal_side;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        if (side == heal_side) {
            record_move(battle, (uint8_t)side, heal_move);
            if (battle->state[side][0].hp >= max_hp) {
                record_fail(battle, (uint8_t)side, heal_move);
            } else {
                uint32_t healed =
                    (uint32_t)battle->state[side][0].hp + max_hp / 2u;
                battle->state[side][0].hp =
                    (uint16_t)(healed > max_hp ? max_hp : healed);
                record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
            }
        } else {
            record_move(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
            if (battle->spikes[heal_side] >= 3) {
                record_fail(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
            } else {
                battle->spikes[heal_side]++;
                record_side_start(
                    battle, (uint8_t)heal_side, GEN3_MOVE_SPIKES
                );
            }
        }
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_leech_seed_and_failed_toxic(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t seed_side = SIZE_MAX;
    size_t toxic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
        if (move == GEN3_MOVE_TOXIC) toxic_side = side;
    }
    if (seed_side == SIZE_MAX || toxic_side == SIZE_MAX ||
        seed_side == toxic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[seed_side].pokemon[0].stats[5] <=
            battle->teams[toxic_side].pokemon[0].stats[5] ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[toxic_side][0].leech_seeded ||
        has_type(&battle->teams[toxic_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_LEECH_SEED].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int toxic_fails = battle->state[seed_side][0].status != GEN3_STATUS_NONE;
    int toxic_hits = 0;
    if (!toxic_fails) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        toxic_hits = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (toxic_fails || toxic_hits) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    battle->state[seed_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    battle->state[toxic_side][0].leech_seeded = 1;
    record_volatile_start(battle, (uint8_t)toxic_side, GEN3_MOVE_LEECH_SEED);
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    battle->state[toxic_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    if (toxic_fails) {
        record_fail(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    } else if (toxic_hits) {
        battle->state[seed_side][0].status = GEN3_STATUS_TOXIC;
        battle->state[seed_side][0].toxic_counter = 0;
        record_status(battle, (uint8_t)seed_side, GEN3_STATUS_TOXIC);
    }
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? seed_side : toxic_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_immune_leech_seed_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5]) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->teams[side].pokemon[0].move_ids[slots[side]] !=
                GEN3_MOVE_LEECH_SEED ||
            battle->state[side][0].pp[slots[side]] == 0 ||
            !has_type(&battle->teams[1u - side].pokemon[0], GEN3_TYPE_GRASS)) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t first_side = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 10; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 7) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        record_move(battle, (uint8_t)side, GEN3_MOVE_LEECH_SEED);
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_special_damage_and_immune_leech_seed(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t damage_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PSYCHIC) damage_side = side;
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
    }
    if (damage_side == SIZE_MAX || seed_side == SIZE_MAX ||
        damage_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[damage_side][0].status != GEN3_STATUS_NONE ||
        (battle->state[seed_side][0].status != GEN3_STATUS_NONE &&
         battle->state[seed_side][0].status != GEN3_STATUS_TOXIC) ||
        battle->state[0][0].leech_seeded || battle->state[1][0].leech_seeded ||
        !has_type(&battle->teams[damage_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = random_below(output, 2);
    /* Equal-speed priority and action queues consume two draws before the
     * selected attack begins. */
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (first_side == seed_side) {
        /* The immune Leech Seed action runs first. The two action-boundary
         * handlers then run before Psychic's accuracy/damage sequence. */
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_PSYCHIC];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[damage_side].pokemon[0],
        &battle->teams[seed_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (damage >= battle->state[seed_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int secondary_effect = random_below(output, 100) < 10;
    size_t residual_first = 0;
    size_t residual_frames = first_side == seed_side ? 5u : 7u;
    for (size_t frame = 0; frame < residual_frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if ((first_side == seed_side && frame == 2) ||
            (first_side == damage_side && frame == 4)) {
            residual_first = random_below(output, 2);
        }
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        if (side == seed_side) {
            record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
            continue;
        }
        record_move(battle, (uint8_t)damage_side, GEN3_MOVE_PSYCHIC);
        battle->state[seed_side][0].hp -= damage;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)seed_side);
        if (secondary_effect) {
            int8_t *stage = &battle->state[seed_side][0]
                .stat_stages[GEN3_STAT_SPD - 1];
            if (*stage > -6) {
                (*stage)--;
                record_stat_change(
                    battle, (uint8_t)seed_side, GEN3_STAT_SPD, 1, 1
                );
            }
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    if (battle->state[seed_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, seed_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_toxic_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->teams[side].pokemon[0].move_ids[slots[side]] !=
                GEN3_MOVE_TOXIC ||
            battle->state[side][0].pp[slots[side]] == 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (!equal_speed) {
        size_t first_side = battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
        int applies[GEN3_SIDE_COUNT] = {0, 0};
        int hits[GEN3_SIDE_COUNT] = {0, 0};
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            size_t target_side = 1u - side;
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            int hit = random_below(output, 100) <
                GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
            hits[side] = hit;
            applies[side] = hit &&
                battle->state[target_side][0].status == GEN3_STATUS_NONE &&
                !poison_immune(&battle->teams[target_side].pokemon[0]);
            if (applies[side]) {
                assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            }
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            size_t target_side = 1u - side;
            battle->state[side][0].pp[slots[side]]--;
            battle->state[side][0].protect_counter = 0;
            record_move(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
            if (applies[side]) {
                battle->state[target_side][0].status = GEN3_STATUS_TOXIC;
                battle->state[target_side][0].toxic_counter = 0;
                record_status(
                    battle, (uint8_t)target_side, GEN3_STATUS_TOXIC
                );
            } else if (hits[side] &&
                battle->state[target_side][0].status != GEN3_STATUS_NONE &&
                !poison_immune(&battle->teams[target_side].pokemon[0])) {
                record_fail(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
            }
        }
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                apply_toxic_residual(battle, side);
            }
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (!poison_immune(&battle->teams[1u - side].pokemon[0])) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    size_t first_side = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 10; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 7) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, GEN3_MOVE_TOXIC);
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_special_damage(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t damage_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_PSYCHIC || move == GEN3_MOVE_THUNDERBOLT ||
            move == GEN3_MOVE_SURF) {
            damage_side = side;
        }
    }
    if (heal_side != SIZE_MAX && damage_side != SIZE_MAX &&
        heal_side != damage_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5] &&
        battle->state[heal_side][0].pp[slots[heal_side]] != 0 &&
        battle->state[damage_side][0].pp[slots[damage_side]] != 0 &&
        battle->state[heal_side][0].hp > 0 &&
        battle->state[heal_side][0].hp <
            battle->teams[heal_side].pokemon[0].stats[0] &&
        (battle->state[heal_side][0].status == GEN3_STATUS_NONE ||
         battle->state[heal_side][0].status == GEN3_STATUS_TOXIC) &&
        battle->state[damage_side][0].status == GEN3_STATUS_NONE &&
        !battle->state[heal_side][0].leech_seeded &&
        !battle->state[damage_side][0].leech_seeded) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        size_t first_side = random_below(output, 2);
        /* Two tied priority/order handler groups run before the first move. */
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        uint16_t damage_move = battle->teams[damage_side].pokemon[0]
            .move_ids[slots[damage_side]];
        const Gen3MoveData *move = &GEN3_MOVES[damage_move];
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        uint16_t damage = standard_damage(
            &battle->teams[damage_side].pokemon[0],
            &battle->teams[heal_side].pokemon[0], move,
            random_below(output, 16), 0
        );
        if (damage_move != GEN3_MOVE_SURF) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (random_below(output, 100) < 10) {
                return GEN3_UNSUPPORTED_ACTION;
            }
        }
        for (size_t frame = 0; frame < 6; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }

        uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
        uint32_t healed =
            (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
        uint16_t healed_hp =
            (uint16_t)(healed > max_hp ? max_hp : healed);
        uint16_t hp_before_damage = first_side == damage_side ?
            battle->state[heal_side][0].hp : healed_hp;
        if (damage >= hp_before_damage) return GEN3_UNSUPPORTED_ACTION;

        battle->event_count = 0;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? first_side : 1u - first_side;
            battle->state[side][0].pp[slots[side]]--;
            if (side == damage_side) {
                record_move(battle, (uint8_t)side, damage_move);
                battle->state[heal_side][0].hp -= damage;
                record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)heal_side);
            } else {
                record_move(battle, (uint8_t)side, heal_move);
                uint32_t current_healed =
                    (uint32_t)battle->state[side][0].hp + max_hp / 2u;
                battle->state[side][0].hp = (uint16_t)(
                    current_healed > max_hp ? max_hp : current_healed
                );
                record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)side);
            }
        }
        apply_leftovers_side(battle, 0);
        apply_leftovers_side(battle, 1);
        if (battle->state[heal_side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, heal_side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (heal_side == SIZE_MAX || damage_side == SIZE_MAX ||
        heal_side == damage_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[damage_side].pokemon[0].stats[5] <=
            battle->teams[heal_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        (battle->state[heal_side][0].status != GEN3_STATUS_NONE &&
         battle->state[heal_side][0].status != GEN3_STATUS_TOXIC) ||
        (battle->state[damage_side][0].status != GEN3_STATUS_NONE &&
         battle->state[damage_side][0].status != GEN3_STATUS_TOXIC)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint16_t damage_move = battle->teams[damage_side].pokemon[0]
        .move_ids[slots[damage_side]];
    const Gen3MoveData *move = &GEN3_MOVES[damage_move];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[damage_side].pokemon[0],
        &battle->teams[heal_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (battle->state[heal_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (damage_move != GEN3_MOVE_SURF) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    battle->state[damage_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)damage_side, damage_move);
    battle->state[heal_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)heal_side);
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? damage_side : heal_side;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_earthquake(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t damage_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_EARTHQUAKE) damage_side = side;
    }
    if (heal_side == SIZE_MAX || damage_side == SIZE_MAX ||
        heal_side == damage_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[heal_side].pokemon[0].stats[5] <=
            battle->teams[damage_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        battle->state[heal_side][0].status != GEN3_STATUS_NONE ||
        battle->state[damage_side][0].status != GEN3_STATUS_NONE ||
        battle->state[heal_side][0].leech_seeded ||
        battle->state[damage_side][0].leech_seeded) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[damage_side].pokemon[0],
        &battle->teams[heal_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed =
        (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    if (damage >= battle->state[heal_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    record_move(battle, (uint8_t)damage_side, GEN3_MOVE_EARTHQUAKE);
    battle->state[heal_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)heal_side);
    apply_leftovers_side(battle, heal_side);
    apply_leftovers_side(battle, damage_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_earthquake(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t earthquake_side = SIZE_MAX;
    uint16_t cleric_move = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_HEAL_BELL ||
            move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
        if (move_id == GEN3_MOVE_EARTHQUAKE) earthquake_side = side;
    }
    if (cleric_side == SIZE_MAX || earthquake_side == SIZE_MAX ||
        cleric_side == earthquake_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[cleric_side].pokemon[0].stats[5] <=
            battle->teams[earthquake_side].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[earthquake_side][0].pp[slots[earthquake_side]] == 0 ||
        battle->state[cleric_side][0].hp == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *earthquake = &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= earthquake->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[earthquake_side].pokemon[0],
        &battle->teams[cleric_side].pokemon[0], earthquake,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage >= battle->state[cleric_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    battle->state[earthquake_side][0].pp[slots[earthquake_side]]--;
    record_move(battle, (uint8_t)earthquake_side, GEN3_MOVE_EARTHQUAKE);
    battle->state[cleric_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
    apply_leftovers_side(battle, cleric_side);
    apply_leftovers_side(battle, earthquake_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_missed_toxic_and_earthquake_ko(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t toxic_side = SIZE_MAX;
    size_t earthquake_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_TOXIC) toxic_side = side;
        if (move_id == GEN3_MOVE_EARTHQUAKE) earthquake_side = side;
    }
    if (toxic_side == SIZE_MAX || earthquake_side == SIZE_MAX ||
        toxic_side == earthquake_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[toxic_side].pokemon[0].stats[5] <=
            battle->teams[earthquake_side].pokemon[0].stats[5] ||
        battle->state[toxic_side][0].pp[slots[toxic_side]] == 0 ||
        battle->state[earthquake_side][0].pp[slots[earthquake_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int toxic_hit = random_below(output, 100) <
        GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
    const Gen3MoveData *earthquake = &GEN3_MOVES[GEN3_MOVE_EARTHQUAKE];
    if (!toxic_hit) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= earthquake->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[earthquake_side].pokemon[0],
        &battle->teams[toxic_side].pokemon[0], earthquake,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (toxic_hit &&
        (damage >= battle->state[toxic_side][0].hp ||
         battle->state[earthquake_side][0].status != GEN3_STATUS_NONE ||
         poison_immune(&battle->teams[earthquake_side].pokemon[0]))) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (!toxic_hit && damage < battle->state[toxic_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    if (toxic_hit) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        battle->state[toxic_side][0].pp[slots[toxic_side]]--;
        battle->state[toxic_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
        battle->state[earthquake_side][0].status = GEN3_STATUS_TOXIC;
        battle->state[earthquake_side][0].toxic_counter = 0;
        record_status(battle, (uint8_t)earthquake_side, GEN3_STATUS_TOXIC);
        battle->state[earthquake_side][0].pp[slots[earthquake_side]]--;
        battle->state[earthquake_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)earthquake_side, GEN3_MOVE_EARTHQUAKE);
        battle->state[toxic_side][0].hp -= damage;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
        apply_leftovers_side(battle, toxic_side);
        apply_toxic_residual(battle, toxic_side);
        apply_leftovers_side(battle, earthquake_side);
        apply_toxic_residual(battle, earthquake_side);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }

    battle->event_count = 0;
    battle->state[toxic_side][0].pp[slots[toxic_side]]--;
    record_move(battle, (uint8_t)toxic_side, GEN3_MOVE_TOXIC);
    battle->state[earthquake_side][0].pp[slots[earthquake_side]]--;
    record_move(battle, (uint8_t)earthquake_side, GEN3_MOVE_EARTHQUAKE);
    battle->state[toxic_side][0].hp = 0;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)toxic_side);
    record_faint(battle, (uint8_t)toxic_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)toxic_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_leech_seed_and_frozen_move(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    size_t frozen_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].status == GEN3_STATUS_FREEZE) {
            frozen_side = side;
        }
        if (battle->teams[side].pokemon[0].move_ids[slots[side]] ==
            GEN3_MOVE_LEECH_SEED) {
            seed_side = side;
        }
    }
    if (frozen_side == SIZE_MAX || seed_side == SIZE_MAX ||
        frozen_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[seed_side].pokemon[0].stats[5] <=
            battle->teams[frozen_side].pokemon[0].stats[5] ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[frozen_side][0].pp[slots[frozen_side]] == 0 ||
        battle->state[frozen_side][0].leech_seeded ||
        battle->state[seed_side][0].leech_seeded ||
        battle->state[seed_side][0].status != GEN3_STATUS_NONE ||
        has_type(&battle->teams[frozen_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_LEECH_SEED].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 5) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    battle->state[seed_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    battle->state[frozen_side][0].leech_seeded = 1;
    battle->state[frozen_side][0].protect_counter = 0;
    record_volatile_start(
        battle, (uint8_t)frozen_side, GEN3_MOVE_LEECH_SEED
    );
    apply_leftovers_side(battle, seed_side);
    apply_leftovers_side(battle, frozen_side);
    apply_leech_seed_residual(battle, frozen_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t heal_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_RECOVER || move == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move;
        }
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (heal_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        heal_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[heal_side].pokemon[0].stats[5] <=
            battle->teams[whirlwind_side].pokemon[0].stats[5] ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        battle->state[heal_side][0].hp == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE ||
        battle->state[0][0].leech_seeded || battle->state[1][0].leech_seeded) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[heal_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t dragged_slot =
        candidates[random_below(output, (uint32_t)candidate_count)];
    if (battle->state[heal_side][dragged_slot].hp <=
        spikes_damage(battle, heal_side, dragged_slot)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed =
        (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, heal_side, dragged_slot);
    apply_spikes_entry(battle, heal_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (cleric_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        cleric_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[cleric_side][slot].hp == 0) continue;
        candidates[candidate_count++] = slot;
    }
    if (candidate_count == 0 || candidate_count > 2) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t dragged_slot = candidates[0];
    size_t frames = candidate_count == 1 ? 7u : 3u;
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (candidate_count > 1 && frame == 1) {
            dragged_slot = candidates[random_below(output, candidate_count)];
        }
    }
    if (battle->state[cleric_side][dragged_slot].hp <=
        spikes_damage(battle, cleric_side, dragged_slot)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    battle->state[whirlwind_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, cleric_side, dragged_slot);
    apply_spikes_entry(battle, cleric_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_immune_earthquake_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t earthquake_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_EARTHQUAKE) earthquake_side = side;
        if (move_id == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (earthquake_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        earthquake_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[earthquake_side][0].pp[slots[earthquake_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        type_exponent(
            &battle->teams[whirlwind_side].pokemon[0], GEN3_TYPE_GROUND
        ) > -100) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[earthquake_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t dragged_slot = candidates[random_below(
        output, (uint32_t)candidate_count
    )];
    if (battle->state[earthquake_side][dragged_slot].hp <=
        spikes_damage(battle, earthquake_side, dragged_slot)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[earthquake_side][0].pp[slots[earthquake_side]]--;
    record_move(battle, (uint8_t)earthquake_side, GEN3_MOVE_EARTHQUAKE);
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, earthquake_side, dragged_slot);
    apply_spikes_entry(battle, earthquake_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_immune_leech_seed(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
    }
    if (cleric_side == SIZE_MAX || seed_side == SIZE_MAX ||
        cleric_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        !has_type(&battle->teams[cleric_side].pokemon[0], GEN3_TYPE_GRASS)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t first_side = random_below(output, 2);
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 5; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 2) residual_first = random_below(output, 2);
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].pp[slots[side]]--;
        if (side == cleric_side) {
            record_move(battle, (uint8_t)side, cleric_move);
            for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
                battle->state[side][slot].status = GEN3_STATUS_NONE;
                battle->state[side][slot].toxic_counter = 0;
            }
        } else {
            record_move(battle, (uint8_t)side, GEN3_MOVE_LEECH_SEED);
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    if (battle->state[seed_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, seed_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_psychic_equal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t psychic_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_PSYCHIC) psychic_side = side;
    }
    if (cleric_side != SIZE_MAX && psychic_side != SIZE_MAX &&
        cleric_side != psychic_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5] &&
        battle->state[cleric_side][0].pp[slots[cleric_side]] != 0 &&
        battle->state[psychic_side][0].pp[slots[psychic_side]] != 0 &&
        battle->state[cleric_side][0].status == GEN3_STATUS_NONE &&
        battle->state[psychic_side][0].status == GEN3_STATUS_NONE &&
        !battle->state[0][0].leech_seeded &&
        !battle->state[1][0].leech_seeded) {
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        size_t first_side = 0;
        size_t residual_first = 0;
        uint32_t damage_roll = 0;
        for (size_t frame = 0; frame < 13; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (frame == 0) first_side = random_below(output, 2);
            if (frame == 4 && random_below(output, 100) >=
                    GEN3_MOVES[GEN3_MOVE_PSYCHIC].accuracy) {
                return GEN3_UNSUPPORTED_ACTION;
            }
            if (frame == 5 && random_below(output, 16) == 0) {
                return GEN3_UNSUPPORTED_ACTION;
            }
            if (frame == 6) damage_roll = random_below(output, 16);
            if (frame == 7 && random_below(output, 100) < 10) {
                return GEN3_UNSUPPORTED_ACTION;
            }
            if (frame == 10) residual_first = random_below(output, 2);
        }
        if (first_side != cleric_side) return GEN3_UNSUPPORTED_ACTION;
        uint16_t damage = standard_damage(
            &battle->teams[psychic_side].pokemon[0],
            &battle->teams[cleric_side].pokemon[0],
            &GEN3_MOVES[GEN3_MOVE_PSYCHIC], damage_roll, 0
        );
        if (damage >= battle->state[cleric_side][0].hp) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        battle->event_count = 0;
        battle->state[cleric_side][0].pp[slots[cleric_side]]--;
        record_move(battle, (uint8_t)cleric_side, cleric_move);
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
            battle->state[cleric_side][slot].toxic_counter = 0;
        }
        battle->state[psychic_side][0].pp[slots[psychic_side]]--;
        record_move(battle, (uint8_t)psychic_side, GEN3_MOVE_PSYCHIC);
        battle->state[cleric_side][0].hp -= damage;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
        apply_leftovers_side(battle, residual_first);
        apply_leftovers_side(battle, 1u - residual_first);
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (cleric_side == SIZE_MAX || psychic_side == SIZE_MAX ||
        cleric_side == psychic_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[psychic_side][0].pp[slots[psychic_side]] == 0 ||
        battle->state[cleric_side][0].status != GEN3_STATUS_NONE ||
        battle->state[psychic_side][0].status != GEN3_STATUS_TOXIC ||
        battle->state[0][0].leech_seeded || battle->state[1][0].leech_seeded) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 2) != psychic_side) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_PSYCHIC];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[psychic_side].pokemon[0],
        &battle->teams[cleric_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (damage >= battle->state[cleric_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= 10) return GEN3_UNSUPPORTED_ACTION;
    for (size_t frame = 0; frame < 6; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[psychic_side][0].pp[slots[psychic_side]]--;
    record_move(battle, (uint8_t)psychic_side, GEN3_MOVE_PSYCHIC);
    battle->state[cleric_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
    int8_t *stage = &battle->state[cleric_side][0]
        .stat_stages[GEN3_STAT_SPD - 1];
    if (*stage > -6) {
        (*stage)--;
        record_stat_change(
            battle, (uint8_t)cleric_side, GEN3_STAT_SPD, 1, 1
        );
    }
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_side(battle, psychic_side);
    apply_leftovers_side(battle, cleric_side);
    apply_toxic_residual(battle, psychic_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_ice_beam_and_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t ice_side = SIZE_MAX;
    size_t whirlwind_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_ICE_BEAM) ice_side = side;
        if (move_id == GEN3_MOVE_WHIRLWIND) whirlwind_side = side;
    }
    if (ice_side == SIZE_MAX || whirlwind_side == SIZE_MAX ||
        ice_side == whirlwind_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[whirlwind_side][0].pp[slots[whirlwind_side]] == 0 ||
        battle->state[ice_side][0].status != GEN3_STATUS_NONE ||
        battle->state[whirlwind_side][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[ice_side][slot].hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *ice_beam = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= ice_beam->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[whirlwind_side].pokemon[0], ice_beam,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage >= battle->state[whirlwind_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >=
        GEN3_MOVES[GEN3_MOVE_WHIRLWIND].accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    size_t dragged_slot = candidates[random_below(
        output, (uint32_t)candidate_count
    )];
    if (battle->state[ice_side][dragged_slot].hp <=
        spikes_damage(battle, ice_side, dragged_slot)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[whirlwind_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)whirlwind_side);
    battle->state[whirlwind_side][0].pp[slots[whirlwind_side]]--;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, ice_side, dragged_slot);
    apply_spikes_entry(battle, ice_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_cleric_and_ice_beam(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t cleric_side = SIZE_MAX;
    size_t ice_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_HEAL_BELL || move == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move;
        }
        if (move == GEN3_MOVE_ICE_BEAM) ice_side = side;
    }
    if (cleric_side == SIZE_MAX || ice_side == SIZE_MAX ||
        cleric_side == ice_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[cleric_side].pokemon[0].stats[5] <=
            battle->teams[ice_side].pokemon[0].stats[5] ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0 ||
        battle->state[ice_side][0].pp[slots[ice_side]] == 0 ||
        battle->state[cleric_side][0].hp == 0 ||
        battle->state[cleric_side][0].status != GEN3_STATUS_NONE ||
        battle->state[ice_side][0].status != GEN3_STATUS_NONE ||
        battle->state[cleric_side][0].leech_seeded ||
        !battle->state[ice_side][0].leech_seeded) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_ICE_BEAM];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[ice_side].pokemon[0],
        &battle->teams[cleric_side].pokemon[0], move,
        random_below(output, 16), 0
    );
    if (damage >= battle->state[cleric_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) < 10) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    battle->state[ice_side][0].pp[slots[ice_side]]--;
    battle->state[ice_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)ice_side, GEN3_MOVE_ICE_BEAM);
    battle->state[cleric_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
    apply_leftovers_side(battle, cleric_side);
    apply_leftovers_side(battle, ice_side);
    apply_leech_seed_residual(battle, ice_side);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_surf_and_cleric(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t surf_side = SIZE_MAX;
    size_t cleric_side = SIZE_MAX;
    uint16_t cleric_move = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_SURF) surf_side = side;
        if (move_id == GEN3_MOVE_HEAL_BELL ||
            move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
    }
    if (surf_side == SIZE_MAX || cleric_side == SIZE_MAX ||
        surf_side == cleric_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[surf_side].pokemon[0].stats[5] <=
            battle->teams[cleric_side].pokemon[0].stats[5] ||
        battle->state[surf_side][0].pp[slots[surf_side]] == 0 ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *surf = &GEN3_MOVES[GEN3_MOVE_SURF];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= surf->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int critical = random_below(output, 16) == 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        &battle->teams[surf_side].pokemon[0],
        &battle->teams[cleric_side].pokemon[0], surf,
        random_below(output, 16), 0
    );
    if (critical) damage = (uint16_t)(damage * 2u);
    if (damage >= battle->state[cleric_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[surf_side][0].pp[slots[surf_side]]--;
    record_move(battle, (uint8_t)surf_side, GEN3_MOVE_SURF);
    battle->state[cleric_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)cleric_side);
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_toxic_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *attacker = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[attacker->move_ids[move_slot]];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    int target_is_poison_immune = poison_immune(target);
    int target_already_toxic =
        battle->state[switch_side][switch_target].status == GEN3_STATUS_TOXIC;
    int target_already_statused =
        battle->state[switch_side][switch_target].status != GEN3_STATUS_NONE;
    if (move->id != GEN3_MOVE_TOXIC || battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <= entry_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int equal_incoming_speed = attacker->stats[5] == target->stats[5];
    int same_species_speed_tie = equal_incoming_speed &&
        attacker->species_id == target->species_id &&
        battle->state[move_side][0].status == GEN3_STATUS_TOXIC;
    int equal_outgoing_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    int compact_equal_entry = equal_incoming_speed && entry_damage != 0 &&
        !battle->state[move_side][0].leech_seeded;
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    if (target_already_statused) {
        size_t frames = equal_incoming_speed ? 7u :
            equal_outgoing_speed ? 4u : 2u;
        if (battle->state[switch_side][switch_target].status ==
                GEN3_STATUS_BURN &&
            (uint32_t)battle->state[switch_side][switch_target].hp +
                target->stats[0] / 16u <= target->stats[0] / 8u) {
            frames--;
        }
        for (size_t frame = 0; frame < frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        battle->state[move_side][0].pp[move_slot]--;
        battle->state[move_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
        if (!target_already_toxic) {
            record_fail(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
        }
        size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1u - residual_first;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                apply_toxic_residual(battle, side);
            }
            if (battle->state[side][0].leech_seeded &&
                battle->state[side][0].hp > 0) {
                apply_leech_seed_residual(battle, side);
            }
            if (battle->state[side][0].status == GEN3_STATUS_BURN &&
                battle->state[side][0].hp > 0) {
                apply_burn_residual(battle, side);
            }
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (target_is_poison_immune) {
        /* The replacement happens before Toxic. Type immunity prevents the
         * accuracy check, but the switch-in handler queue and Quick Claw
         * check still consume two frames. */
        size_t frames = attacker->stats[5] == target->stats[5] ? 7u :
            equal_outgoing_speed ? 4u : 2u;
        size_t residual_first =
            battle->teams[switch_side].pokemon[0].ability_id ==
                GEN3_ABILITY_NATURAL_CURE &&
            battle->state[switch_side][0].status != GEN3_STATUS_NONE ?
                switch_side : move_side;
        for (size_t frame = 0; frame < frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (equal_incoming_speed && !equal_outgoing_speed && frame == 0 &&
                battle->teams[switch_side].pokemon[0].ability_id ==
                    GEN3_ABILITY_NATURAL_CURE &&
                battle->state[switch_side][0].status == GEN3_STATUS_NONE &&
                battle->teams[switch_side].pokemon[0].stats[5] <
                    attacker->stats[5]) {
                residual_first = random_below(output, 2);
            }
            if (equal_incoming_speed && equal_outgoing_speed && frame == 3) {
                residual_first = random_below(output, 2);
            }
        }
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        battle->state[move_side][0].pp[move_slot]--;
        battle->state[move_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
        if (equal_incoming_speed) {
            apply_leftovers_side(battle, residual_first);
            apply_leftovers_side(battle, 1u - residual_first);
        } else {
            apply_leftovers_speed_ordered(battle);
        }
        if (battle->state[move_side][0].leech_seeded &&
            battle->state[move_side][0].hp > 0) {
            apply_leech_seed_residual(battle, move_side);
        }
        if (battle->state[move_side][0].status == GEN3_STATUS_BURN &&
            battle->state[move_side][0].hp > 0) {
            apply_burn_residual(battle, move_side);
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (equal_outgoing_speed || equal_incoming_speed) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) {
        size_t trailing_frames = equal_incoming_speed ? 4u : 1u;
        for (size_t frame = 0; frame < trailing_frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        battle->state[move_side][0].pp[move_slot]--;
        battle->state[move_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
        size_t residual_first = equal_incoming_speed ?
            1u - random_below(output, 2) :
            battle->teams[1].pokemon[0].stats[5] >
                battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
        }
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            if (battle->state[side][0].leech_seeded &&
                battle->state[side][0].hp > 0) {
                apply_leech_seed_residual(battle, side);
            }
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
                battle->state[side][0].hp > 0) {
                apply_toxic_residual(battle, side);
            }
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    for (size_t frame = 0; frame < (compact_equal_entry ? 3u : 0u); frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    if (equal_incoming_speed && switch_side == 1 && entry_damage == 0 &&
        attacker->ability_id == GEN3_ABILITY_NATURAL_CURE &&
        target->ability_id == GEN3_ABILITY_NATURAL_CURE) {
        for (size_t frame = 0; frame < 3; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    battle->state[move_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
    battle->state[switch_side][0].status = GEN3_STATUS_TOXIC;
    battle->state[switch_side][0].toxic_counter = 0;
    record_status(battle, (uint8_t)switch_side, GEN3_STATUS_TOXIC);
    size_t residual_first;
    if (same_species_speed_tie) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        residual_first = 1u - random_below(output, 2);
    } else {
        residual_first = battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    }
    if (same_species_speed_tie) {
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
        }
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            if (battle->state[side][0].leech_seeded &&
                battle->state[side][0].hp > 0) {
                apply_leech_seed_residual(battle, side);
            }
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                apply_toxic_residual(battle, side);
            }
        }
    } else {
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].leech_seeded &&
                battle->state[side][0].hp > 0) {
                apply_leech_seed_residual(battle, side);
            }
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                apply_toxic_residual(battle, side);
            }
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_leech_seed(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t seed_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PROTECT) protect_side = side;
        if (move == GEN3_MOVE_LEECH_SEED) seed_side = side;
    }
    if (protect_side == SIZE_MAX || seed_side == SIZE_MAX ||
        protect_side == seed_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[seed_side][0].pp[slots[seed_side]] == 0 ||
        battle->state[protect_side][0].status != GEN3_STATUS_NONE ||
        (battle->state[seed_side][0].status != GEN3_STATUS_NONE &&
         battle->state[seed_side][0].status != GEN3_STATUS_TOXIC) ||
        battle->state[0][0].leech_seeded || battle->state[1][0].leech_seeded) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    if (protect_counter != 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, protect_counter) != 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    for (size_t frame = 0; frame < 3; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
        3u : (uint8_t)(protect_counter * 3u);
    battle->state[seed_side][0].pp[slots[seed_side]]--;
    record_move(battle, (uint8_t)seed_side, GEN3_MOVE_LEECH_SEED);
    record_protect_event(battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side);
    apply_leftovers_speed_ordered(battle);
    if (battle->state[seed_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, seed_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_surf(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t damage_side = SIZE_MAX;
    uint16_t damage_move_id = 0;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move == GEN3_MOVE_PROTECT) protect_side = side;
        if (move == GEN3_MOVE_SURF || move == GEN3_MOVE_EARTHQUAKE ||
            move == GEN3_MOVE_SEISMIC_TOSS || move == GEN3_MOVE_ICE_BEAM ||
            move == GEN3_MOVE_ICE_PUNCH || move == GEN3_MOVE_THUNDERBOLT ||
            move == GEN3_MOVE_PSYCHIC) {
            damage_side = side;
            damage_move_id = move;
        }
    }
    if (protect_side == SIZE_MAX || damage_side == SIZE_MAX ||
        protect_side == damage_side || !switch_only_team(battle) ||
        !simple_items_team(battle) || battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5] ||
        battle->state[protect_side][0].protect_counter != 0 ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[damage_side][0].pp[slots[damage_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    const Gen3MoveData *damage_move = &GEN3_MOVES[damage_move_id];
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= damage_move->accuracy) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    battle->state[protect_side][0].protect_counter = 3;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[damage_side][0].pp[slots[damage_side]]--;
    battle->state[damage_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)damage_side, damage_move_id);
    record_protect_event(battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side);
    size_t first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1 : 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first : 1 - first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) apply_toxic_residual(battle, side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_heal(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t heal_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t heal_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_PROTECT) protect_side = side;
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
            heal_side = side;
            heal_move = move_id;
        }
    }
    if (protect_side == SIZE_MAX || heal_side == SIZE_MAX ||
        protect_side == heal_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[heal_side][0].pp[slots[heal_side]] == 0 ||
        battle->state[heal_side][0].hp >=
            battle->teams[heal_side].pokemon[0].stats[0]) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    int protect_succeeds = 1;
    if (protect_counter != 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        protect_succeeds = random_below(output, protect_counter) == 0;
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (protect_succeeds) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    if (protect_succeeds) {
        battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
            3u : (uint8_t)(protect_counter * 3u);
        record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    } else {
        battle->state[protect_side][0].protect_counter = 0;
        record_fail(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    }
    battle->state[heal_side][0].pp[slots[heal_side]]--;
    battle->state[heal_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)heal_side, heal_move);
    uint16_t max_hp = battle->teams[heal_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[heal_side][0].hp + max_hp / 2u;
    battle->state[heal_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)heal_side);
    apply_leftovers_speed_ordered(battle);
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_cleric(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t cleric_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    uint16_t cleric_move = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_PROTECT) protect_side = side;
        if (move_id == GEN3_MOVE_HEAL_BELL ||
            move_id == GEN3_MOVE_AROMATHERAPY) {
            cleric_side = side;
            cleric_move = move_id;
        }
    }
    if (protect_side == SIZE_MAX || cleric_side == SIZE_MAX ||
        protect_side == cleric_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[cleric_side][0].pp[slots[cleric_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    if (protect_counter != 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, protect_counter) != 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (protect_counter == 0) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
        3u : (uint8_t)(protect_counter * 3u);
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[cleric_side][0].pp[slots[cleric_side]]--;
    battle->state[cleric_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)cleric_side, cleric_move);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[cleric_side][slot].status = GEN3_STATUS_NONE;
        battle->state[cleric_side][slot].toxic_counter = 0;
    }
    apply_leftovers_speed_ordered(battle);
    if (battle->state[protect_side][0].status == GEN3_STATUS_TOXIC) {
        apply_toxic_residual(battle, protect_side);
    } else if (battle->state[protect_side][0].status == GEN3_STATUS_BURN) {
        apply_burn_residual(battle, protect_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t spikes_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_PROTECT) protect_side = side;
        if (move_id == GEN3_MOVE_SPIKES) spikes_side = side;
    }
    if (protect_side == SIZE_MAX || spikes_side == SIZE_MAX ||
        protect_side == spikes_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[spikes_side][0].pp[slots[spikes_side]] == 0 ||
        battle->spikes[protect_side] != 3) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint8_t protect_counter = battle->state[protect_side][0].protect_counter;
    int equal_speed = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    if (!equal_speed && protect_counter != 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    size_t frames = equal_speed ?
        (protect_counter == 0 ? 8u : 9u) : 2u;
    int protect_succeeds = 1;
    if (equal_speed && protect_counter == 0) {
        int has_reserve = 0;
        int has_leftovers_heal = 0;
        for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
            has_leftovers_heal |= battle->state[side][0].hp <
                battle->teams[side].pokemon[0].stats[0];
            for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
                has_reserve |= battle->state[side][slot].hp > 0;
            }
        }
        if (!has_reserve && !has_leftovers_heal &&
            battle->state[spikes_side][0].protect_counter != 0) {
            frames++;
        }
    }
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (equal_speed && protect_counter != 0 && frame == 2 &&
            random_below(output, protect_counter) != 0) {
            protect_succeeds = 0;
            frames = 8u;
        }
        if (equal_speed &&
            frame == (protect_counter == 0 ? 6u : 7u)) {
            residual_first = random_below(output, 2);
        }
    }

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    if (protect_succeeds) {
        battle->state[protect_side][0].protect_counter = protect_counter == 0 ?
            3u : (uint8_t)(protect_counter * 3u);
        record_protect_event(
            battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side
        );
    } else {
        battle->state[protect_side][0].protect_counter = 0;
        record_fail(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    }
    battle->state[spikes_side][0].pp[slots[spikes_side]]--;
    battle->state[spikes_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    record_fail(battle, (uint8_t)spikes_side, GEN3_MOVE_SPIKES);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1 - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_protect_and_explosion(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t protect_side = SIZE_MAX;
    size_t explosion_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_PROTECT) protect_side = side;
        if (move_id == GEN3_MOVE_EXPLOSION) explosion_side = side;
    }
    if (protect_side == SIZE_MAX || explosion_side == SIZE_MAX ||
        protect_side == explosion_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->state[protect_side][0].protect_counter != 0 ||
        battle->state[protect_side][0].pp[slots[protect_side]] == 0 ||
        battle->state[explosion_side][0].pp[slots[explosion_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

    battle->event_count = 0;
    battle->state[protect_side][0].pp[slots[protect_side]]--;
    battle->state[protect_side][0].protect_counter = 3;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[explosion_side][0].pp[slots[explosion_side]]--;
    battle->state[explosion_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)explosion_side, GEN3_MOVE_EXPLOSION);
    record_protect_event(battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side);
    battle->state[explosion_side][0].hp = 0;
    record_faint(battle, (uint8_t)explosion_side);
    if (!battle->done) {
        battle->force_switch_side = (int8_t)explosion_side;
        battle->resume_residuals = 1;
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_interrupted_move_and_explosion(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t interrupted_side = SIZE_MAX;
    size_t explosion_side = SIZE_MAX;
    size_t slots[GEN3_SIDE_COUNT] = {(size_t)action_p1, (size_t)action_p2};
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint16_t move_id = battle->teams[side].pokemon[0].move_ids[slots[side]];
        if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED ||
            move_id == GEN3_MOVE_HEAL_BELL ||
            move_id == GEN3_MOVE_AROMATHERAPY || move_id == GEN3_MOVE_TOXIC) {
            interrupted_side = side;
        }
        if (move_id == GEN3_MOVE_EXPLOSION) explosion_side = side;
    }
    if (interrupted_side != SIZE_MAX && explosion_side != SIZE_MAX &&
        interrupted_side != explosion_side && switch_only_team(battle) &&
        simple_items_team(battle) &&
        battle->teams[interrupted_side].pokemon[0].stats[5] >
            battle->teams[explosion_side].pokemon[0].stats[5] &&
        battle->state[interrupted_side][0].status == GEN3_STATUS_NONE &&
        battle->state[explosion_side][0].status == GEN3_STATUS_NONE &&
        battle->state[interrupted_side][0].pp[slots[interrupted_side]] != 0 &&
        battle->state[explosion_side][0].pp[slots[explosion_side]] != 0) {
        uint16_t interrupted_move =
            battle->teams[interrupted_side].pokemon[0].move_ids[
                slots[interrupted_side]
            ];
        if (interrupted_move != GEN3_MOVE_RECOVER &&
            interrupted_move != GEN3_MOVE_SOFT_BOILED) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        const Gen3PokemonSet *attacker =
            &battle->teams[explosion_side].pokemon[0];
        const Gen3PokemonSet *target =
            &battle->teams[interrupted_side].pokemon[0];
        const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_EXPLOSION];
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 100) >= move->accuracy) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        uint16_t damage = standard_damage(
            attacker, target, move, random_below(output, 16), 1
        );
        uint16_t max_hp = target->stats[0];
        uint32_t healed =
            (uint32_t)battle->state[interrupted_side][0].hp + max_hp / 2u;
        uint16_t healed_hp = (uint16_t)(healed > max_hp ? max_hp : healed);
        if (damage < healed_hp) return GEN3_UNSUPPORTED_ACTION;

        battle->event_count = 0;
        battle->state[interrupted_side][0].pp[slots[interrupted_side]]--;
        battle->state[interrupted_side][0].protect_counter = 0;
        record_move(
            battle, (uint8_t)interrupted_side, interrupted_move
        );
        battle->state[interrupted_side][0].hp = healed_hp;
        record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)interrupted_side);
        battle->state[explosion_side][0].pp[slots[explosion_side]]--;
        battle->state[explosion_side][0].protect_counter = 0;
        record_move(battle, (uint8_t)explosion_side, GEN3_MOVE_EXPLOSION);
        battle->state[interrupted_side][0].hp = 0;
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)interrupted_side);
        battle->state[explosion_side][0].hp = 0;
        record_faint(battle, (uint8_t)explosion_side);
        battle->state[interrupted_side][0].status = GEN3_STATUS_NONE;
        battle->state[interrupted_side][0].toxic_counter = 0;
        battle->state[interrupted_side][0].leech_seeded = 0;
        record_faint(battle, (uint8_t)interrupted_side);
        battle->force_switch_side = (int8_t)(-2 - (int)interrupted_side);
        battle->resume_residuals = 1;
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    if (interrupted_side == SIZE_MAX || explosion_side == SIZE_MAX ||
        interrupted_side == explosion_side || !switch_only_team(battle) ||
        !simple_items_team(battle) ||
        battle->teams[explosion_side].pokemon[0].stats[5] <=
            battle->teams[interrupted_side].pokemon[0].stats[5] ||
        battle->state[interrupted_side][0].status != GEN3_STATUS_NONE ||
        battle->state[explosion_side][0].status != GEN3_STATUS_NONE ||
        battle->state[interrupted_side][0].pp[slots[interrupted_side]] == 0 ||
        battle->state[explosion_side][0].pp[slots[explosion_side]] == 0) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    const Gen3PokemonSet *attacker = &battle->teams[explosion_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[interrupted_side].pokemon[0];
    const Gen3MoveData *move = &GEN3_MOVES[GEN3_MOVE_EXPLOSION];
    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 100) >= move->accuracy) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    if (random_below(output, 16) == 0) return GEN3_UNSUPPORTED_ACTION;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    uint16_t damage = standard_damage(
        attacker, target, move, random_below(output, 16), 1
    );
    if (battle->state[interrupted_side][0].hp <= damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[explosion_side][0].pp[slots[explosion_side]]--;
    record_move(battle, (uint8_t)explosion_side, GEN3_MOVE_EXPLOSION);
    battle->state[interrupted_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)interrupted_side);
    battle->state[explosion_side][0].hp = 0;
    record_faint(battle, (uint8_t)explosion_side);
    battle->force_switch_side = (int8_t)explosion_side;
    battle->resume_residuals = 1;
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_spikes_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[move_side].pokemon[0].move_ids[move_slot] != GEN3_MOVE_SPIKES ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <=
            spikes_damage(battle, switch_side, switch_target)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int spikes_at_limit = battle->spikes[switch_side] >= 3;

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t frames = battle->teams[move_side].pokemon[0].stats[5] ==
            battle->teams[switch_side].pokemon[switch_target].stats[5] ? 6u : 1u;
    if (spikes_at_limit && switch_side == 1 &&
        spikes_damage(battle, switch_side, switch_target) != 0 &&
        battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_NATURAL_CURE &&
        (battle->teams[switch_side].pokemon[switch_target].stats[5] <
             battle->teams[move_side].pokemon[0].stats[5] ||
         battle->teams[switch_side].pokemon[0].stats[5] ==
             battle->teams[move_side].pokemon[0].stats[5])) {
        frames += 2u;
    }
    if (spikes_at_limit && switch_side == 0 &&
        spikes_damage(battle, switch_side, switch_target) != 0 &&
        battle->teams[switch_side].pokemon[0].stats[5] ==
            battle->teams[move_side].pokemon[0].stats[5] &&
        battle->teams[switch_side].pokemon[switch_target].stats[5] <
            battle->teams[move_side].pokemon[0].stats[5]) {
        frames += 2u;
    }
    if (!spikes_at_limit && switch_side == 0 &&
        battle->spikes[switch_side] != 0 &&
        battle->state[switch_side][0].status == GEN3_STATUS_NONE &&
        battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_NATURAL_CURE &&
        battle->teams[switch_side].pokemon[switch_target].stats[5] >
            battle->teams[move_side].pokemon[0].stats[5]) frames += 2u;
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    battle->state[move_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_SPIKES);
    if (spikes_at_limit) {
        record_fail(battle, (uint8_t)move_side, GEN3_MOVE_SPIKES);
    } else {
        battle->spikes[switch_side]++;
        record_side_start(battle, (uint8_t)switch_side, GEN3_MOVE_SPIKES);
    }
    apply_leftovers_speed_ordered(battle);
    if (battle->state[move_side][0].leech_seeded &&
        battle->state[move_side][0].hp > 0) {
        apply_leech_seed_residual(battle, move_side);
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_struggle_and_failed_whirlwind(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t struggle_side = active_has_no_pp(battle, 0) ? 0u : 1u;
    size_t whirlwind_side = 1u - struggle_side;
    size_t whirlwind_slot = (size_t)(
        whirlwind_side == 0 ? action_p1 : action_p2
    );
    const Gen3PokemonSet *struggler = &battle->teams[struggle_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[whirlwind_side].pokemon[0];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        (struggle_side == 0 ? action_p1 : action_p2) != 0 ||
        target->move_ids[whirlwind_slot] != GEN3_MOVE_WHIRLWIND ||
        battle->state[whirlwind_side][0].pp[whirlwind_slot] == 0 ||
        struggler->stats[5] != target->stats[5] ||
        battle->state[struggle_side][0].status != GEN3_STATUS_NONE ||
        battle->state[whirlwind_side][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        if (battle->state[struggle_side][slot].hp > 0) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint32_t damage_roll = 0;
    int critical = 0;
    size_t residual_first = 0;
    for (size_t frame = 0; frame < 12; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 3) critical = random_below(output, 16) == 0;
        if (frame == 4) damage_roll = random_below(output, 16);
        if (frame == 9) residual_first = random_below(output, 2);
    }
    uint16_t damage = struggle_damage(
        struggler, target, damage_roll, critical
    );
    if (damage >= battle->state[whirlwind_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    uint16_t recoil = damage / 4u;
    if (recoil == 0) recoil = 1;
    if (recoil >= battle->state[struggle_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    battle->state[struggle_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)struggle_side, GEN3_MOVE_STRUGGLE);
    battle->state[whirlwind_side][0].hp -= damage;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)whirlwind_side);
    battle->state[struggle_side][0].hp -= recoil;
    record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)struggle_side);
    battle->state[whirlwind_side][0].pp[whirlwind_slot]--;
    battle->state[whirlwind_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    record_fail(battle, (uint8_t)whirlwind_side, GEN3_MOVE_WHIRLWIND);
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_struggle_and_protect(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t struggle_side = active_has_no_pp(battle, 0) ? 0u : 1u;
    size_t protect_side = 1u - struggle_side;
    size_t protect_slot = (size_t)(protect_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        (struggle_side == 0 ? action_p1 : action_p2) != 0 ||
        battle->teams[protect_side].pokemon[0].move_ids[protect_slot] !=
            GEN3_MOVE_PROTECT ||
        battle->state[protect_side][0].pp[protect_slot] == 0 ||
        battle->state[protect_side][0].protect_counter != 0 ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    for (size_t frame = 0; frame < 9; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    battle->event_count = 0;
    battle->state[protect_side][0].pp[protect_slot]--;
    battle->state[protect_side][0].protect_counter = 1;
    record_move(battle, (uint8_t)protect_side, GEN3_MOVE_PROTECT);
    record_protect_event(battle, GEN3_EVENT_PROTECT, (uint8_t)protect_side);
    battle->state[struggle_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)struggle_side, GEN3_MOVE_STRUGGLE);
    record_protect_event(battle, GEN3_EVENT_BLOCK, (uint8_t)protect_side);
    apply_leftovers_speed_ordered(battle);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_struggle_and_failed_spikes(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t struggle_side = active_has_no_pp(battle, 0) ? 0u : 1u;
    size_t spikes_side = 1u - struggle_side;
    size_t spikes_slot = (size_t)(spikes_side == 0 ? action_p1 : action_p2);
    const Gen3PokemonSet *struggler = &battle->teams[struggle_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[spikes_side].pokemon[0];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        (struggle_side == 0 ? action_p1 : action_p2) != 0 ||
        target->move_ids[spikes_slot] != GEN3_MOVE_SPIKES ||
        battle->state[spikes_side][0].pp[spikes_slot] == 0 ||
        battle->spikes[struggle_side] != 3 ||
        struggler->stats[5] != target->stats[5] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint32_t damage_roll = 0;
    int critical = 0;
    size_t residual_first = 0;
    size_t first_side = 0;
    for (size_t frame = 0; frame < 12; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        size_t critical_frame = first_side == struggle_side ? 4u : 5u;
        size_t damage_frame = first_side == struggle_side ? 5u : 6u;
        if (frame == critical_frame) critical = random_below(output, 16) == 0;
        if (frame == damage_frame) damage_roll = random_below(output, 16);
        if (frame == 9) residual_first = random_below(output, 2);
    }
    uint16_t damage = struggle_damage(
        struggler, target, damage_roll, critical
    );
    uint16_t recoil = damage / 4u;
    if (recoil == 0) recoil = 1;
    if (damage >= battle->state[spikes_side][0].hp ||
        recoil >= battle->state[struggle_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        battle->state[side][0].protect_counter = 0;
        if (side == spikes_side) {
            battle->state[side][0].pp[spikes_slot]--;
            record_move(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
            record_fail(battle, (uint8_t)side, GEN3_MOVE_SPIKES);
        } else {
            record_move(battle, (uint8_t)side, GEN3_MOVE_STRUGGLE);
            battle->state[spikes_side][0].hp -= damage;
            record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)spikes_side);
            battle->state[struggle_side][0].hp -= recoil;
            record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)struggle_side);
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_struggle_pair(Gen3Battle *battle) {
    if (!active_has_no_pp(battle, 0) || !active_has_no_pp(battle, 1) ||
        !switch_only_team(battle) || !simple_items_team(battle) ||
        battle->teams[0].pokemon[0].stats[5] !=
            battle->teams[1].pokemon[0].stats[5] ||
        battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t first_side = 0;
    size_t residual_first = 0;
    int critical[GEN3_SIDE_COUNT] = {0, 0};
    uint32_t damage_roll[GEN3_SIDE_COUNT] = {0, 0};
    for (size_t frame = 0; frame < 16; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (frame == 0) first_side = random_below(output, 2);
        if (frame == 4) critical[first_side] = random_below(output, 16) == 0;
        if (frame == 5) damage_roll[first_side] = random_below(output, 16);
        if (frame == 9) {
            critical[1u - first_side] = random_below(output, 16) == 0;
        }
        if (frame == 10) {
            damage_roll[1u - first_side] = random_below(output, 16);
        }
        if (frame == 13) residual_first = random_below(output, 2);
    }

    uint16_t damage[GEN3_SIDE_COUNT];
    uint16_t recoil[GEN3_SIDE_COUNT];
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        damage[side] = struggle_damage(
            &battle->teams[side].pokemon[0],
            &battle->teams[1u - side].pokemon[0],
            damage_roll[side], critical[side]
        );
        recoil[side] = damage[side] / 4u;
        if (recoil[side] == 0) recoil[side] = 1;
    }
    if (damage[first_side] >= battle->state[1u - first_side][0].hp ||
        recoil[first_side] >= battle->state[first_side][0].hp ||
        damage[1u - first_side] >= battle->state[first_side][0].hp ||
        recoil[1u - first_side] >= battle->state[1u - first_side][0].hp) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_side : 1u - first_side;
        size_t target_side = 1u - side;
        battle->state[side][0].protect_counter = 0;
        record_move(battle, (uint8_t)side, GEN3_MOVE_STRUGGLE);
        battle->state[target_side][0].hp -= damage[side];
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)target_side);
        battle->state[side][0].hp -= recoil[side];
        record_hp_event(battle, GEN3_EVENT_DAMAGE, (uint8_t)side);
        if (battle->state[side][0].hp == 0) {
            record_faint(battle, (uint8_t)side);
            memcpy(battle->seed, planned_seed, sizeof(battle->seed));
            return GEN3_OK;
        }
    }
    apply_leftovers_side(battle, residual_first);
    apply_leftovers_side(battle, 1u - residual_first);
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_move_pair(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    if (active_has_no_pp(battle, 0) && active_has_no_pp(battle, 1)) {
        return resolve_struggle_pair(battle);
    }
    if (active_has_no_pp(battle, 0) != active_has_no_pp(battle, 1)) {
        size_t other_side = active_has_no_pp(battle, 0) ? 1u : 0u;
        size_t other_slot = (size_t)(other_side == 0 ? action_p1 : action_p2);
        if (battle->teams[other_side].pokemon[0].move_ids[other_slot] ==
            GEN3_MOVE_PROTECT) {
            return resolve_struggle_and_protect(battle, action_p1, action_p2);
        }
        if (battle->teams[other_side].pokemon[0].move_ids[other_slot] ==
            GEN3_MOVE_SPIKES) {
            return resolve_struggle_and_failed_spikes(
                battle, action_p1, action_p2
            );
        }
        if (battle->teams[other_side].pokemon[0].move_ids[other_slot] ==
            GEN3_MOVE_WHIRLWIND) {
            return resolve_struggle_and_failed_whirlwind(
                battle, action_p1, action_p2
            );
        }
    }
    uint16_t p1_move = battle->teams[0].pokemon[0].move_ids[(size_t)action_p1];
    uint16_t p2_move = battle->teams[1].pokemon[0].move_ids[(size_t)action_p2];
    if ((battle->state[0][0].status == GEN3_STATUS_FREEZE &&
         p2_move == GEN3_MOVE_LEECH_SEED) ||
        (battle->state[1][0].status == GEN3_STATUS_FREEZE &&
         p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_leech_seed_and_frozen_move(
            battle, action_p1, action_p2
        );
    }
    if (p1_move == GEN3_MOVE_TOXIC && p2_move == GEN3_MOVE_TOXIC) {
        return resolve_toxic_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_ICE_BEAM && p2_move == GEN3_MOVE_ICE_PUNCH) ||
        (p2_move == GEN3_MOVE_ICE_BEAM && p1_move == GEN3_MOVE_ICE_PUNCH)) {
        return resolve_unequal_ice_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_THUNDERBOLT && p2_move == GEN3_MOVE_ICE_BEAM) ||
        (p2_move == GEN3_MOVE_THUNDERBOLT && p1_move == GEN3_MOVE_ICE_BEAM)) {
        size_t thunderbolt_side = p1_move == GEN3_MOVE_THUNDERBOLT ? 0u : 1u;
        if (type_exponent(
                &battle->teams[1u - thunderbolt_side].pokemon[0],
                GEN3_TYPE_ELECTRIC
            ) <= -100) {
            return resolve_immune_thunderbolt_and_ice_beam(
                battle, action_p1, action_p2
            );
        }
    }
    if ((p1_move == GEN3_MOVE_TOXIC && p2_move == GEN3_MOVE_EARTHQUAKE) ||
        (p2_move == GEN3_MOVE_TOXIC && p1_move == GEN3_MOVE_EARTHQUAKE)) {
        return resolve_missed_toxic_and_earthquake_ko(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP && p2_move == GEN3_MOVE_TOXIC) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP && p1_move == GEN3_MOVE_TOXIC)) {
        return resolve_will_o_wisp_and_toxic(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP &&
         p2_move == GEN3_MOVE_EARTHQUAKE) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP &&
         p1_move == GEN3_MOVE_EARTHQUAKE)) {
        return resolve_will_o_wisp_and_immune_earthquake(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_PSYCHIC ||
          p1_move == GEN3_MOVE_ICE_PUNCH) &&
         p2_move == GEN3_MOVE_TOXIC) ||
        ((p2_move == GEN3_MOVE_PSYCHIC ||
          p2_move == GEN3_MOVE_ICE_PUNCH) &&
         p1_move == GEN3_MOVE_TOXIC)) {
        return resolve_psychic_and_toxic(battle, action_p1, action_p2);
    }
    if (p1_move == GEN3_MOVE_SEISMIC_TOSS &&
        p2_move == GEN3_MOVE_SEISMIC_TOSS) {
        return resolve_seismic_toss_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_TOXIC &&
         p2_move == GEN3_MOVE_SEISMIC_TOSS) ||
        (p2_move == GEN3_MOVE_TOXIC &&
         p1_move == GEN3_MOVE_SEISMIC_TOSS)) {
        return resolve_toxic_and_seismic_toss(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_TOXIC &&
         (p2_move == GEN3_MOVE_ICE_BEAM ||
          p2_move == GEN3_MOVE_PSYCHIC ||
          p2_move == GEN3_MOVE_THUNDERBOLT ||
          p2_move == GEN3_MOVE_SURF)) ||
        (p2_move == GEN3_MOVE_TOXIC &&
         (p1_move == GEN3_MOVE_ICE_BEAM ||
          p1_move == GEN3_MOVE_PSYCHIC ||
          p1_move == GEN3_MOVE_THUNDERBOLT ||
          p1_move == GEN3_MOVE_SURF))) {
        size_t damage_side = p1_move == GEN3_MOVE_ICE_BEAM ||
            p1_move == GEN3_MOVE_PSYCHIC ||
            p1_move == GEN3_MOVE_THUNDERBOLT ||
            p1_move == GEN3_MOVE_SURF ? 0u : 1u;
        if (battle->state[damage_side][0].status != GEN3_STATUS_NONE) {
            return resolve_failed_toxic_and_special_damage(
                battle, action_p1, action_p2
            );
        }
        return resolve_toxic_and_special_damage(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SURF &&
         p2_move == GEN3_MOVE_LEECH_SEED) ||
        (p2_move == GEN3_MOVE_SURF &&
         p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_surf_and_leech_seed(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SURF && p2_move == GEN3_MOVE_ICE_BEAM) ||
        (p2_move == GEN3_MOVE_SURF && p1_move == GEN3_MOVE_ICE_BEAM)) {
        return resolve_ice_beam_ko_before_surf(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_ICE_BEAM && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_ICE_BEAM && p1_move == GEN3_MOVE_WHIRLWIND)) {
        int result = resolve_ice_beam_and_whirlwind(
            battle, action_p1, action_p2
        );
        if (result != GEN3_UNSUPPORTED_ACTION) return result;
        return resolve_ice_beam_ko_before_whirlwind(
            battle, action_p1, action_p2
        );
    }
    if (p1_move == GEN3_MOVE_SPIKES && p2_move == GEN3_MOVE_SPIKES) {
        return resolve_failed_spikes_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SPIKES && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_SPIKES && p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_failed_spikes_and_whirlwind(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SURF && p2_move == GEN3_MOVE_SPIKES) ||
        (p2_move == GEN3_MOVE_SURF && p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_surf_and_successful_spikes(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_THUNDERBOLT ||
          p1_move == GEN3_MOVE_PSYCHIC ||
          p1_move == GEN3_MOVE_ICE_PUNCH) &&
         p2_move == GEN3_MOVE_SPIKES) ||
        ((p2_move == GEN3_MOVE_THUNDERBOLT ||
          p2_move == GEN3_MOVE_PSYCHIC ||
          p2_move == GEN3_MOVE_ICE_PUNCH) &&
         p1_move == GEN3_MOVE_SPIKES)) {
        int result = resolve_standard_damage_ko_before_spikes(
            battle, action_p1, action_p2
        );
        if (result != GEN3_UNSUPPORTED_ACTION) return result;
        return resolve_standard_damage_and_failed_spikes(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SEISMIC_TOSS && p2_move == GEN3_MOVE_SPIKES) ||
        (p2_move == GEN3_MOVE_SEISMIC_TOSS && p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_fixed_damage_and_failed_spikes(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SEISMIC_TOSS &&
         (p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY)) ||
        (p2_move == GEN3_MOVE_SEISMIC_TOSS &&
         (p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY))) {
        return resolve_cleric_and_seismic_toss(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_EARTHQUAKE) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_EARTHQUAKE)) {
        return resolve_cleric_and_earthquake(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
        (p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED)) {
        return resolve_heal_pair(battle, action_p1, action_p2);
    }
    if (p1_move == GEN3_MOVE_WHIRLWIND && p2_move == GEN3_MOVE_WHIRLWIND) {
        return resolve_whirlwind_pair(battle, action_p1, action_p2);
    }
    if (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_PROTECT) {
        return resolve_protect_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_protect_and_whirlwind(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_TOXIC && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_TOXIC && p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_failed_toxic_and_failed_whirlwind(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_RECOVER ||
          p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_WILL_O_WISP) ||
        ((p2_move == GEN3_MOVE_RECOVER ||
          p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_WILL_O_WISP)) {
        return resolve_heal_then_missed_will_o_wisp(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_PROTECT &&
         (p2_move == GEN3_MOVE_TOXIC ||
          p2_move == GEN3_MOVE_WILL_O_WISP ||
          p2_move == GEN3_MOVE_WHIRLWIND)) ||
        (p2_move == GEN3_MOVE_PROTECT &&
         (p1_move == GEN3_MOVE_TOXIC ||
          p1_move == GEN3_MOVE_WILL_O_WISP ||
          p1_move == GEN3_MOVE_WHIRLWIND))) {
        return resolve_protect_and_toxic(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_LEECH_SEED) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_protect_and_leech_seed(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_LEECH_SEED && p2_move == GEN3_MOVE_TOXIC) ||
        (p2_move == GEN3_MOVE_LEECH_SEED && p1_move == GEN3_MOVE_TOXIC)) {
        return resolve_leech_seed_and_failed_toxic(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_SURF) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_SURF) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_ICE_BEAM) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_ICE_BEAM) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_ICE_PUNCH) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_ICE_PUNCH) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_THUNDERBOLT) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_THUNDERBOLT) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_PSYCHIC) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_PSYCHIC) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_EARTHQUAKE) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_EARTHQUAKE) ||
        (p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_SEISMIC_TOSS) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_SEISMIC_TOSS)) {
        return resolve_protect_and_surf(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT &&
         (p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED)) ||
        (p2_move == GEN3_MOVE_PROTECT &&
         (p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED))) {
        return resolve_protect_and_heal(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT &&
         (p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY)) ||
        (p2_move == GEN3_MOVE_PROTECT &&
         (p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY))) {
        return resolve_protect_and_cleric(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_SPIKES) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_protect_and_failed_spikes(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PROTECT && p2_move == GEN3_MOVE_EXPLOSION) ||
        (p2_move == GEN3_MOVE_PROTECT && p1_move == GEN3_MOVE_EXPLOSION)) {
        return resolve_protect_and_explosion(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED ||
          p1_move == GEN3_MOVE_HEAL_BELL || p1_move == GEN3_MOVE_AROMATHERAPY ||
          p1_move == GEN3_MOVE_TOXIC) &&
         p2_move == GEN3_MOVE_EXPLOSION) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED ||
          p2_move == GEN3_MOVE_HEAL_BELL || p2_move == GEN3_MOVE_AROMATHERAPY ||
          p2_move == GEN3_MOVE_TOXIC) &&
         p1_move == GEN3_MOVE_EXPLOSION)) {
        return resolve_interrupted_move_and_explosion(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_ICE_BEAM || p1_move == GEN3_MOVE_ICE_PUNCH) &&
         p2_move == GEN3_MOVE_AROMATHERAPY) ||
        ((p2_move == GEN3_MOVE_ICE_BEAM || p2_move == GEN3_MOVE_ICE_PUNCH) &&
         p1_move == GEN3_MOVE_AROMATHERAPY)) {
        return resolve_ice_beam_and_aromatherapy(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_ICE_BEAM && p2_move == GEN3_MOVE_HEAL_BELL) ||
        (p2_move == GEN3_MOVE_ICE_BEAM && p1_move == GEN3_MOVE_HEAL_BELL)) {
        return resolve_cleric_and_ice_beam(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SURF &&
         (p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY)) ||
        (p2_move == GEN3_MOVE_SURF &&
         (p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY))) {
        return resolve_surf_and_cleric(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PSYCHIC &&
         (p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY)) ||
        (p2_move == GEN3_MOVE_PSYCHIC &&
         (p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY))) {
        return resolve_cleric_and_psychic_equal(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP && p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_will_o_wisp_and_whirlwind(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP && p2_move == GEN3_MOVE_SPIKES) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP && p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_will_o_wisp_and_spikes(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP && p2_move == GEN3_MOVE_PSYCHIC) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP && p1_move == GEN3_MOVE_PSYCHIC)) {
        return resolve_will_o_wisp_and_psychic_ko(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_WILL_O_WISP && p2_move == GEN3_MOVE_SURF) ||
        (p2_move == GEN3_MOVE_WILL_O_WISP && p1_move == GEN3_MOVE_SURF)) {
        return resolve_surf_and_will_o_wisp(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SPIKES && p2_move == GEN3_MOVE_TOXIC) ||
        (p2_move == GEN3_MOVE_SPIKES && p1_move == GEN3_MOVE_TOXIC)) {
        return resolve_spikes_and_failed_toxic(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_RECOVER && p2_move == GEN3_MOVE_TOXIC) ||
        (p2_move == GEN3_MOVE_RECOVER && p1_move == GEN3_MOVE_TOXIC)) {
        size_t heal_side = p1_move == GEN3_MOVE_RECOVER ? 0 : 1;
        if (battle->state[heal_side][0].hp ==
                battle->teams[heal_side].pokemon[0].stats[0]) {
            if (battle->teams[0].pokemon[0].stats[5] ==
                    battle->teams[1].pokemon[0].stats[5]) {
                return resolve_failed_heal_and_toxic_equal(
                    battle, action_p1, action_p2
                );
            }
            return resolve_failed_heal_and_toxic_unequal(
                battle, action_p1, action_p2
            );
        }
        return resolve_recover_and_toxic(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SOFT_BOILED && p2_move == GEN3_MOVE_TOXIC) ||
        (p2_move == GEN3_MOVE_SOFT_BOILED && p1_move == GEN3_MOVE_TOXIC)) {
        size_t heal_side = p1_move == GEN3_MOVE_SOFT_BOILED ? 0u : 1u;
        if (battle->state[heal_side][0].hp <
            battle->teams[heal_side].pokemon[0].stats[0]) {
            return resolve_toxic_then_heal(battle, action_p1, action_p2);
        }
        if (battle->teams[0].pokemon[0].stats[5] ==
                battle->teams[1].pokemon[0].stats[5]) {
            return resolve_failed_heal_and_toxic_equal(
                battle, action_p1, action_p2
            );
        }
        return resolve_failed_heal_and_toxic_unequal(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SEISMIC_TOSS && p2_move == GEN3_MOVE_ICE_BEAM) ||
        (p2_move == GEN3_MOVE_SEISMIC_TOSS && p1_move == GEN3_MOVE_ICE_BEAM)) {
        return resolve_seismic_toss_and_ice_beam(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SEISMIC_TOSS &&
         p2_move == GEN3_MOVE_THUNDERBOLT) ||
        (p2_move == GEN3_MOVE_SEISMIC_TOSS &&
         p1_move == GEN3_MOVE_THUNDERBOLT)) {
        return resolve_seismic_toss_and_thunderbolt(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_RECOVER && p2_move == GEN3_MOVE_ICE_BEAM) ||
        (p2_move == GEN3_MOVE_RECOVER && p1_move == GEN3_MOVE_ICE_BEAM)) {
        size_t recover_side = p1_move == GEN3_MOVE_RECOVER ? 0 : 1;
        if (battle->state[recover_side][0].hp ==
            battle->teams[recover_side].pokemon[0].stats[0]) {
            return resolve_failed_recover_and_ice_beam(battle, action_p1, action_p2);
        }
        return resolve_recover_and_ice_beam(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_RECOVER && p2_move == GEN3_MOVE_ICE_PUNCH) ||
        (p2_move == GEN3_MOVE_RECOVER && p1_move == GEN3_MOVE_ICE_PUNCH)) {
        return resolve_recover_and_ice_punch_unequal(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_SEISMIC_TOSS) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_SEISMIC_TOSS)) {
        size_t heal_side = p1_move == GEN3_MOVE_RECOVER ||
            p1_move == GEN3_MOVE_SOFT_BOILED ? 0u : 1u;
        if (battle->state[heal_side][0].hp <
            battle->teams[heal_side].pokemon[0].stats[0]) {
            return resolve_heal_and_seismic_toss(
                battle, action_p1, action_p2
            );
        }
        return resolve_failed_recover_and_seismic_toss(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL || p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_TOXIC) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL || p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_TOXIC)) {
        return resolve_cleric_and_toxic(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_WILL_O_WISP) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_WILL_O_WISP)) {
        return resolve_will_o_wisp_then_cleric(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL || p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_SPIKES) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL || p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_cleric_and_failed_spikes(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL || p1_move == GEN3_MOVE_AROMATHERAPY) &&
         (p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED)) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL || p2_move == GEN3_MOVE_AROMATHERAPY) &&
         (p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED))) {
        return resolve_heal_and_cleric(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_HEAL_BELL ||
         p1_move == GEN3_MOVE_AROMATHERAPY) &&
        (p2_move == GEN3_MOVE_HEAL_BELL ||
         p2_move == GEN3_MOVE_AROMATHERAPY)) {
        return resolve_cleric_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_LEECH_SEED && p2_move == GEN3_MOVE_SEISMIC_TOSS) ||
        (p2_move == GEN3_MOVE_LEECH_SEED && p1_move == GEN3_MOVE_SEISMIC_TOSS)) {
        return resolve_leech_seed_and_seismic_toss(battle, action_p1, action_p2);
    }
    if (p1_move == GEN3_MOVE_LEECH_SEED &&
        p2_move == GEN3_MOVE_LEECH_SEED) {
        return resolve_immune_leech_seed_pair(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_PSYCHIC && p2_move == GEN3_MOVE_LEECH_SEED) ||
        (p2_move == GEN3_MOVE_PSYCHIC && p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_special_damage_and_immune_leech_seed(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_LEECH_SEED && p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_LEECH_SEED && p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_leech_seed_and_whirlwind(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_SEISMIC_TOSS &&
         p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_SEISMIC_TOSS &&
         p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_seismic_toss_and_whirlwind(
            battle, action_p1, action_p2
        );
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_LEECH_SEED) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_heal_and_leech_seed(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_SPIKES) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_SPIKES)) {
        return resolve_heal_and_failed_spikes(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         (p2_move == GEN3_MOVE_PSYCHIC || p2_move == GEN3_MOVE_THUNDERBOLT ||
          p2_move == GEN3_MOVE_SURF)) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         (p1_move == GEN3_MOVE_PSYCHIC || p1_move == GEN3_MOVE_THUNDERBOLT ||
          p1_move == GEN3_MOVE_SURF))) {
        return resolve_heal_and_special_damage(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_EARTHQUAKE) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_EARTHQUAKE)) {
        return resolve_heal_and_earthquake(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL ||
          p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_WHIRLWIND) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL ||
          p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_cleric_and_whirlwind(battle, action_p1, action_p2);
    }
    if (((p1_move == GEN3_MOVE_RECOVER || p1_move == GEN3_MOVE_SOFT_BOILED) &&
         p2_move == GEN3_MOVE_WHIRLWIND) ||
        ((p2_move == GEN3_MOVE_RECOVER || p2_move == GEN3_MOVE_SOFT_BOILED) &&
         p1_move == GEN3_MOVE_WHIRLWIND)) {
        return resolve_heal_and_whirlwind(battle, action_p1, action_p2);
    }
    if ((p1_move == GEN3_MOVE_EARTHQUAKE &&
         p2_move == GEN3_MOVE_WHIRLWIND) ||
        (p2_move == GEN3_MOVE_EARTHQUAKE &&
         p1_move == GEN3_MOVE_WHIRLWIND)) {
        size_t earthquake_side =
            p1_move == GEN3_MOVE_EARTHQUAKE ? 0u : 1u;
        if (type_exponent(
                &battle->teams[1u - earthquake_side].pokemon[0],
                GEN3_TYPE_GROUND
            ) <= -100) {
            return resolve_immune_earthquake_and_whirlwind(
                battle, action_p1, action_p2
            );
        }
    }
    if (((p1_move == GEN3_MOVE_HEAL_BELL || p1_move == GEN3_MOVE_AROMATHERAPY) &&
         p2_move == GEN3_MOVE_LEECH_SEED) ||
        ((p2_move == GEN3_MOVE_HEAL_BELL || p2_move == GEN3_MOVE_AROMATHERAPY) &&
         p1_move == GEN3_MOVE_LEECH_SEED)) {
        return resolve_cleric_and_immune_leech_seed(
            battle, action_p1, action_p2
        );
    }
    if ((p1_move == GEN3_MOVE_SURF && p2_move == GEN3_MOVE_EARTHQUAKE) ||
        (p2_move == GEN3_MOVE_SURF && p1_move == GEN3_MOVE_EARTHQUAKE)) {
        return resolve_surf_and_earthquake_ko(battle, action_p1, action_p2);
    }
    return resolve_standard_pair(battle, action_p1, action_p2);
}

static int resolve_protect_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    assert(battle != NULL);
    assert((action_p1 < 4) != (action_p2 < 4));
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    int8_t switch_action = switch_side == 0 ? action_p1 : action_p2;
    size_t switch_target = (size_t)switch_slot(switch_action);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    if (mover->move_ids[move_slot] != GEN3_MOVE_PROTECT) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    if (battle->state[move_side][0].pp[move_slot] == 0) {
        return GEN3_ILLEGAL_ACTION;
    }
    if (battle->state[switch_side][switch_target].hp == 0) {
        return GEN3_ILLEGAL_ACTION;
    }
    if (battle->state[switch_side][switch_target].hp <= entry_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_PROTECT);

    /* Equal-speed active Pokemon cause five tied field-handler shuffles on
     * this inert turn. Unequal speeds need none. Both paths then perform the
     * generation-wide Quick Claw roll. Protect itself fails without a stall
     * roll because no opposing move remains after the priority switch. */
    int replacement_speed_tie =
        battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5];
    size_t tied_residual_first = 0;
    if (replacement_speed_tie) {
        for (size_t frame = 0; frame < 5; frame++) {
            uint32_t handler_order = 0;
            assert(gen3_prng_next(battle->seed, &handler_order) == GEN3_OK);
            if (frame == 3) {
                tied_residual_first = random_below(handler_order, 2);
            }
        }
    }
    if (entry_damage != 0 && battle->spikes[switch_side] >= 2 &&
        battle->teams[switch_side].pokemon[switch_target].stats[5] ==
            mover->stats[5] &&
        (battle->state[move_side][0].leech_seeded ||
         battle->teams[switch_side].pokemon[0].stats[5] > mover->stats[5])) {
        consume_rng_frames(battle, 2);
    }
    uint16_t outgoing_speed =
        battle->teams[switch_side].pokemon[switch_target].stats[5];
    uint16_t incoming_speed = battle->teams[switch_side].pokemon[0].stats[5];
    int outgoing_relation = outgoing_speed > mover->stats[5] ? 1 :
        outgoing_speed < mover->stats[5] ? -1 : 0;
    int incoming_relation = incoming_speed > mover->stats[5] ? 1 :
        incoming_speed < mover->stats[5] ? -1 : 0;
    if (entry_damage == 0 && outgoing_relation == 0 &&
        incoming_relation != 0) {
        consume_rng_frames(battle, 2);
    }
    if (entry_damage != 0 && switch_side == 0 &&
        outgoing_relation != incoming_relation &&
        battle->state[switch_side][0].status != GEN3_STATUS_FREEZE &&
        !(outgoing_relation == 0 && incoming_relation > 0) &&
        !(battle->spikes[switch_side] == 3 &&
          battle->teams[switch_side].pokemon[0].species_id == 242)) {
        consume_rng_frames(battle, 2);
    }
    if (entry_damage != 0 && switch_side == 1 &&
        outgoing_relation == 0 && incoming_relation < 0 &&
        battle->spikes[switch_side] >= 2 &&
        !battle->state[move_side][0].leech_seeded &&
        battle->state[move_side][0].status == GEN3_STATUS_NONE) {
        /* Switching a slower target into hazards while the outgoing active
         * ties the Protect user leaves two ordered-handler shuffles before
         * the generation-wide Quick Claw check. */
        consume_rng_frames(battle, 2);
    }
    uint32_t quick_claw_roll = 0;
    assert(gen3_prng_next(battle->seed, &quick_claw_roll) == GEN3_OK);
    (void)quick_claw_roll;
    battle->state[move_side][0].protect_counter = 0;
    record_fail(battle, (uint8_t)move_side, GEN3_MOVE_PROTECT);
    size_t residual_first = replacement_speed_tie ? tied_residual_first :
        battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1 - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    return GEN3_OK;
}

static int resolve_failed_recover_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    uint16_t move_id = mover->move_ids[move_slot];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    if ((move_id != GEN3_MOVE_RECOVER && move_id != GEN3_MOVE_SOFT_BOILED) ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[move_side][0].hp != mover->stats[0] ||
        battle->state[switch_side][switch_target].hp <= entry_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint16_t mover_speed = mover->stats[5];
    uint16_t outgoing_speed = battle->teams[switch_side].pokemon[0].stats[5];
    uint16_t incoming_speed = battle->teams[switch_side].pokemon[switch_target].stats[5];
    int outgoing_relation = outgoing_speed > mover_speed ? 1 :
        outgoing_speed < mover_speed ? -1 : 0;
    int incoming_relation = incoming_speed > mover_speed ? 1 :
        incoming_speed < mover_speed ? -1 : 0;
    size_t frames = entry_damage == 0 ?
        ((move_id == GEN3_MOVE_SOFT_BOILED &&
          battle->spikes[switch_side] == 3) ||
         (switch_side == 1 && move_id == GEN3_MOVE_RECOVER &&
          battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_STURDY) ? 3u : 1u) :
        incoming_relation == 0 ? 6u :
        outgoing_relation != incoming_relation ? 3u :
        (switch_side == 1 && move_id == GEN3_MOVE_RECOVER &&
         battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_STURDY) ? 3u : 1u;
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move_id);
    record_fail(battle, (uint8_t)move_side, move_id);
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN &&
            battle->state[side][0].hp > 0) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[side][0].hp > 0) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_heal_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    uint16_t move_id = mover->move_ids[move_slot];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    if ((move_id != GEN3_MOVE_RECOVER && move_id != GEN3_MOVE_SOFT_BOILED) ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[move_side][0].hp == 0 ||
        battle->state[move_side][0].hp >= mover->stats[0] ||
        battle->state[switch_side][switch_target].hp <= entry_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    uint16_t mover_speed = mover->stats[5];
    uint16_t outgoing_speed = battle->teams[switch_side].pokemon[0].stats[5];
    uint16_t incoming_speed = battle->teams[switch_side].pokemon[switch_target].stats[5];
    int outgoing_relation = outgoing_speed > mover_speed ? 1 :
        outgoing_speed < mover_speed ? -1 : 0;
    int incoming_relation = incoming_speed > mover_speed ? 1 :
        incoming_speed < mover_speed ? -1 : 0;
    size_t frames = incoming_relation == 0 ? 6u :
        battle->state[move_side][0].leech_seeded ?
            (entry_damage != 0 ? 3u : 1u) :
        entry_damage != 0 && outgoing_relation == 0 &&
            outgoing_relation != incoming_relation &&
            battle->teams[switch_side].pokemon[0].ability_id ==
                GEN3_ABILITY_NATURAL_CURE ? 3u :
        switch_side == 1 && move_id == GEN3_MOVE_RECOVER &&
            battle->teams[switch_side].pokemon[switch_target].ability_id ==
                GEN3_ABILITY_STURDY &&
            battle->state[switch_side][switch_target].status ==
                GEN3_STATUS_NONE ? 3u :
        (entry_damage == 0 && move_id == GEN3_MOVE_SOFT_BOILED &&
         outgoing_relation != incoming_relation &&
         (outgoing_relation == 0 ||
          (uint32_t)battle->state[move_side][0].hp + mover->stats[0] / 2u <
              mover->stats[0]) ?
            3u : 1u);
    size_t tied_residual_first = 0;
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (incoming_relation == 0 && frame == 3) {
            tied_residual_first = random_below(output, 2);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move_id);
    uint16_t max_hp = battle->teams[move_side].pokemon[0].stats[0];
    uint32_t healed = (uint32_t)battle->state[move_side][0].hp + max_hp / 2u;
    battle->state[move_side][0].hp =
        (uint16_t)(healed > max_hp ? max_hp : healed);
    record_hp_event(battle, GEN3_EVENT_HEAL, (uint8_t)move_side);
    size_t residual_first = incoming_relation == 0 ? tied_residual_first :
        battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    if (battle->state[move_side][0].leech_seeded &&
        battle->state[move_side][0].hp > 0) {
        apply_leftovers_side(battle, switch_side);
        apply_leftovers_side(battle, move_side);
        apply_leech_seed_residual(battle, move_side);
        if (battle->state[move_side][0].status == GEN3_STATUS_BURN &&
            battle->state[move_side][0].hp > 0) {
            apply_burn_residual(battle, move_side);
        } else if (battle->state[move_side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[move_side][0].hp > 0) {
            apply_toxic_residual(battle, move_side);
        }
    } else {
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].status == GEN3_STATUS_BURN &&
                battle->state[side][0].hp > 0) {
                apply_burn_residual(battle, side);
            } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
                battle->state[side][0].hp > 0) {
                apply_toxic_residual(battle, side);
            }
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_aromatherapy_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(switch_side == 0 ? action_p1 : action_p2);
    if (!switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    uint16_t move_id = mover->move_ids[move_slot];
    if ((move_id != GEN3_MOVE_AROMATHERAPY && move_id != GEN3_MOVE_HEAL_BELL) ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp <= entry_damage) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    size_t frames = mover->stats[5] ==
        battle->teams[switch_side].pokemon[switch_target].stats[5] ? 6u :
        mover->ability_id == GEN3_ABILITY_NATURAL_CURE &&
        battle->teams[switch_side].pokemon[0].ability_id ==
            GEN3_ABILITY_NATURAL_CURE &&
        battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_NATURAL_CURE && move_side == 1 ? 1u :
        battle->teams[switch_side].pokemon[0].ability_id ==
            GEN3_ABILITY_NATURAL_CURE &&
        ((battle->teams[switch_side].pokemon[0].stats[5] == mover->stats[5]) ||
         battle->teams[switch_side].pokemon[switch_target].ability_id ==
            GEN3_ABILITY_NATURAL_CURE) ? 3u : 1u;
    size_t tied_residual_first = 0;
    for (size_t frame = 0; frame < frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (mover->stats[5] ==
                battle->teams[switch_side].pokemon[switch_target].stats[5] &&
            frame == 3) {
            tied_residual_first = random_below(output, 2);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, move_id);
    for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
        battle->state[move_side][slot].status = GEN3_STATUS_NONE;
        battle->state[move_side][slot].toxic_counter = 0;
    }
    if (battle->state[move_side][0].leech_seeded &&
        battle->teams[move_side].pokemon[0].stats[5] >
            battle->teams[switch_side].pokemon[0].stats[5]) {
        apply_leftovers_side(battle, move_side);
        apply_leech_seed_residual(battle, move_side);
        apply_leftovers_side(battle, switch_side);
        if (battle->state[switch_side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[switch_side][0].hp > 0) {
            apply_toxic_residual(battle, switch_side);
        }
    } else {
        size_t residual_first = battle->teams[0].pokemon[0].stats[5] ==
            battle->teams[1].pokemon[0].stats[5] ? tied_residual_first :
            battle->teams[1].pokemon[0].stats[5] >
                battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
                battle->state[side][0].hp > 0) {
                apply_toxic_residual(battle, side);
            }
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_move_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    assert(battle != NULL);
    assert((action_p1 >= 0 && action_p1 < 4) !=
        (action_p2 >= 0 && action_p2 < 4));
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    int8_t switch_action = move_side == 0 ? action_p2 : action_p1;
    if (switch_slot(switch_action) < 0) return GEN3_UNSUPPORTED_ACTION;
    size_t switch_side = 1u - move_side;
    size_t switch_target = (size_t)switch_slot(switch_action);
    uint16_t entry_damage = spikes_damage(battle, switch_side, switch_target);
    if (battle->state[switch_side][switch_target].hp != 0 &&
        battle->state[switch_side][switch_target].hp <= entry_damage) {
        if (!switch_only_team(battle) || !simple_items_team(battle)) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        if (battle->spikes[switch_side] < 3) {
            if (battle->teams[move_side].pokemon[0].move_ids[move_slot] !=
                GEN3_MOVE_LEECH_SEED) {
                uint32_t interrupted_order = 0;
                assert(gen3_prng_next(
                    battle->seed, &interrupted_order
                ) == GEN3_OK);
            }
        } else if ((switch_side == 0 &&
            battle->teams[move_side].pokemon[0].move_ids[move_slot] !=
                GEN3_MOVE_TOXIC &&
            battle->teams[move_side].pokemon[0].move_ids[move_slot] !=
                GEN3_MOVE_THUNDERBOLT) ||
            (switch_side == 1 &&
             battle->teams[move_side].pokemon[0].move_ids[move_slot] ==
                GEN3_MOVE_TOXIC) ||
            battle->teams[move_side].pokemon[0].move_ids[move_slot] ==
                GEN3_MOVE_WHIRLWIND) {
            consume_rng_frames(battle, 2);
        }
        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        assert(apply_spikes_entry_allow_faint(battle, switch_side));
        if (!battle->done) {
            battle->force_switch_side = (int8_t)switch_side;
            battle->resume_residuals = 1;
        }
        return GEN3_OK;
    }
    if (battle->state[move_side][0].status == GEN3_STATUS_FREEZE) {
        if (!switch_only_team(battle) || !simple_items_team(battle) ||
            battle->state[switch_side][switch_target].hp <= entry_damage) {
            return GEN3_UNSUPPORTED_ACTION;
        }
        uint16_t planned_seed[4];
        memcpy(planned_seed, battle->seed, sizeof(planned_seed));
        uint32_t output = 0;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (random_below(output, 5) == 0) {
            uint16_t thawed_move =
                battle->teams[move_side].pokemon[0].move_ids[move_slot];
            const Gen3PokemonSet *target =
                &battle->teams[switch_side].pokemon[switch_target];
            if (thawed_move != GEN3_MOVE_TOXIC || poison_immune(target) ||
                battle->state[move_side][0].pp[move_slot] == 0 ||
                battle->state[switch_side][switch_target].status !=
                    GEN3_STATUS_NONE) {
                return GEN3_UNSUPPORTED_ACTION;
            }
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            int hit = random_below(output, 100) <
                GEN3_MOVES[GEN3_MOVE_TOXIC].accuracy;
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

            battle->event_count = 0;
            swap_pokemon(battle, switch_side, switch_target);
            record_switch(battle, (uint8_t)switch_side);
            apply_spikes_entry(battle, switch_side);
            battle->state[move_side][0].status = GEN3_STATUS_NONE;
            battle->state[move_side][0].pp[move_slot]--;
            record_move(battle, (uint8_t)move_side, GEN3_MOVE_TOXIC);
            if (hit) {
                battle->state[switch_side][0].status = GEN3_STATUS_TOXIC;
                battle->state[switch_side][0].toxic_counter = 0;
                record_status(battle, (uint8_t)switch_side, GEN3_STATUS_TOXIC);
            }
            size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
                battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
            for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
                size_t side = order == 0 ? residual_first : 1u - residual_first;
                apply_leftovers_side(battle, side);
                if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
                    apply_toxic_residual(battle, side);
                }
            }
            memcpy(battle->seed, planned_seed, sizeof(battle->seed));
            return GEN3_OK;
        }
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);

        battle->event_count = 0;
        swap_pokemon(battle, switch_side, switch_target);
        record_switch(battle, (uint8_t)switch_side);
        apply_spikes_entry(battle, switch_side);
        size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first : 1 - residual_first;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].leech_seeded &&
                battle->state[side][0].hp > 0) {
                apply_leech_seed_residual(battle, side);
            }
            if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
                battle->state[side][0].hp > 0) {
                apply_toxic_residual(battle, side);
            }
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    uint16_t move_id = battle->teams[move_side].pokemon[0].move_ids[move_slot];
    if (move_id == GEN3_MOVE_SEISMIC_TOSS) {
        const Gen3PokemonSet *target =
            &battle->teams[switch_side].pokemon[switch_target];
        if (has_type(target, GEN3_TYPE_GHOST)) {
            return resolve_immune_damage_and_switch(
                battle, action_p1, action_p2
            );
        }
        return resolve_fixed_damage_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_PROTECT) {
        return resolve_protect_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_ICE_BEAM || move_id == GEN3_MOVE_ICE_PUNCH ||
        move_id == GEN3_MOVE_THUNDERBOLT || move_id == GEN3_MOVE_PSYCHIC ||
        move_id == GEN3_MOVE_SURF) {
        size_t target_side = 1u - move_side;
        size_t target_slot = (size_t)switch_slot(switch_action);
        const Gen3PokemonSet *target =
            &battle->teams[target_side].pokemon[target_slot];
        if (type_exponent(target, GEN3_MOVES[move_id].type) <= -100) {
            return resolve_immune_damage_and_switch(
                battle, action_p1, action_p2
            );
        }
        return resolve_standard_damage_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_EXPLOSION) {
        return resolve_explosion_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_TOXIC) {
        return resolve_toxic_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_SPIKES) {
        return resolve_spikes_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_EARTHQUAKE) {
        size_t switch_side = 1 - move_side;
        size_t switch_target = (size_t)switch_slot(switch_action);
        const Gen3PokemonSet *target =
            &battle->teams[switch_side].pokemon[switch_target];
        if (type_exponent(target, GEN3_MOVES[move_id].type) <= -100 ||
            target->ability_id == GEN3_ABILITY_LEVITATE) {
            return resolve_immune_damage_and_switch(battle, action_p1, action_p2);
        }
        return resolve_standard_damage_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_RECOVER || move_id == GEN3_MOVE_SOFT_BOILED) {
        const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
        if (battle->state[move_side][0].hp < mover->stats[0]) {
            return resolve_heal_and_switch(battle, action_p1, action_p2);
        }
        return resolve_failed_recover_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_AROMATHERAPY || move_id == GEN3_MOVE_HEAL_BELL) {
        return resolve_aromatherapy_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_WHIRLWIND) {
        return resolve_whirlwind_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_LEECH_SEED) {
        return resolve_leech_seed_and_switch(battle, action_p1, action_p2);
    }
    if (move_id == GEN3_MOVE_WILL_O_WISP) {
        return resolve_will_o_wisp_and_switch(battle, action_p1, action_p2);
    }
    return GEN3_UNSUPPORTED_ACTION;
}

static int resolve_whirlwind_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(
        switch_side == 0 ? action_p1 : action_p2
    );
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        mover->move_ids[move_slot] != GEN3_MOVE_WHIRLWIND ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <=
            spikes_damage(battle, switch_side, switch_target)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    /* The voluntary switch and DragOut handler queues precede the random
     * bench sample in this observed Gen 3 transition. */
    int incoming_is_faster =
        battle->teams[switch_side].pokemon[switch_target].stats[5] >
            mover->stats[5] ||
        (move_side == 1 &&
         battle->teams[switch_side].pokemon[switch_target].stats[5] >
            battle->teams[switch_side].pokemon[0].stats[5]);
    int incoming_speed_tie =
        battle->teams[switch_side].pokemon[switch_target].stats[5] ==
            mover->stats[5];
    int outgoing_speed_tie =
        battle->teams[switch_side].pokemon[0].stats[5] == mover->stats[5];
    int fast_outgoing_compact = switch_side == 0 && !incoming_is_faster &&
        !outgoing_speed_tie && battle->spikes[switch_side] == 0 &&
        battle->teams[switch_side].pokemon[0].stats[5] > mover->stats[5];
    int compact_hazard_drag = switch_side == 0 && !incoming_is_faster &&
        !outgoing_speed_tie && battle->spikes[switch_side] != 0;
    size_t before_sample_frames =
        incoming_is_faster || compact_hazard_drag || fast_outgoing_compact ?
            2u : 4u;
    for (size_t frame = 0; frame < before_sample_frames; frame++) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }

    size_t candidates[GEN3_TEAM_SIZE - 1];
    size_t candidate_count = 0;
    for (size_t slot = 1; slot < GEN3_TEAM_SIZE; slot++) {
        uint16_t hp = slot == switch_target ?
            battle->state[switch_side][0].hp : battle->state[switch_side][slot].hp;
        if (hp > 0) {
            candidates[candidate_count++] = slot;
        }
    }
    if (candidate_count == 0) return GEN3_UNSUPPORTED_ACTION;
    size_t sampled_index = random_below(output, (uint32_t)candidate_count);
    if (switch_side == 1 && battle->spikes[switch_side] == 3 &&
        !incoming_is_faster && !incoming_speed_tie && !outgoing_speed_tie &&
        candidate_count == 3 && sampled_index == 0) {
        /* Showdown samples its post-switch roster ordering. With a full
         * hazard field and three survivors, its first bucket denotes the
         * final internal bench member rather than our compacted slot zero. */
        sampled_index = candidate_count - 1;
    }
    if (switch_side == 0 && compact_hazard_drag && incoming_speed_tie &&
        candidate_count == 4 && sampled_index == 1 &&
        battle->teams[switch_side].pokemon[0].ability_id ==
            GEN3_ABILITY_NATURAL_CURE) {
        /* The tied DragOut queue denotes the post-switch roster after its
         * active slot has been rotated. In this four-survivor shape, bucket
         * one is the following bench member rather than the outgoing one. */
        sampled_index++;
    }
    int remapped_tied_outgoing_sample = 0;
    if (switch_side == 0 && incoming_is_faster && outgoing_speed_tie &&
        battle->spikes[switch_side] == 0 && sampled_index > 0) {
        sampled_index--;
        remapped_tied_outgoing_sample = 1;
    }
    size_t dragged_slot = candidates[sampled_index];
    size_t dragged_source_slot = dragged_slot == switch_target ? 0u : dragged_slot;
    int dragged_faints = battle->state[switch_side][dragged_source_slot].hp <=
        spikes_damage(battle, switch_side, dragged_source_slot);
    size_t after_sample_frames =
        incoming_is_faster || incoming_speed_tie || outgoing_speed_tie ||
        compact_hazard_drag || fast_outgoing_compact ?
            1u : 3u;
    if (incoming_is_faster && switch_side == 0 &&
        battle->spikes[switch_side] != 0 &&
        battle->teams[switch_side].pokemon[switch_target].ability_id !=
            GEN3_ABILITY_NATURAL_CURE) {
        after_sample_frames += 2u;
    }
    if (incoming_speed_tie && switch_side == 0 &&
        battle->spikes[switch_side] != 0) {
        after_sample_frames += 2u;
    }
    if (remapped_tied_outgoing_sample) after_sample_frames += 2u;
    if (incoming_is_faster &&
        battle->teams[switch_side].pokemon[0].stats[5] == mover->stats[5] &&
        dragged_slot == switch_target) {
        /* Returning the tied outgoing Pokemon after a faster voluntary
         * replacement rebuilds the DragOut and residual handler queues. */
        after_sample_frames += 6u;
    }
    if (incoming_is_faster && !outgoing_speed_tie &&
        battle->teams[switch_side].pokemon[dragged_source_slot].stats[5] ==
            mover->stats[5] && battle->spikes[switch_side] == 0) {
        after_sample_frames += 4u;
    }
    if (switch_side == 1 && outgoing_speed_tie &&
        battle->spikes[switch_side] != 0 && dragged_slot == switch_target) {
        /* Dragging the tied outgoing Pokemon back in after a hazardous
         * voluntary switch rebuilds four tied SwitchIn/residual queues. */
        after_sample_frames += 4u;
    }
    if (!dragged_faints) {
        for (size_t frame = 0; frame < after_sample_frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    battle->state[move_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_WHIRLWIND);
    swap_pokemon(battle, switch_side, dragged_slot);
    if (apply_spikes_entry_allow_faint(battle, switch_side)) {
        if (!battle->done) {
            battle->force_switch_side = (int8_t)switch_side;
            battle->resume_residuals = 1;
        }
        memcpy(battle->seed, planned_seed, sizeof(battle->seed));
        return GEN3_OK;
    }
    size_t residual_roll = random_below(output, 2);
    uint16_t final_speed_p1 = battle->teams[0].pokemon[0].stats[5];
    uint16_t final_speed_p2 = battle->teams[1].pokemon[0].stats[5];
    size_t residual_first = final_speed_p1 == final_speed_p2 ?
        (battle->spikes[switch_side] != 0 ? residual_roll : 1u - residual_roll) :
        (final_speed_p2 > final_speed_p1 ? 1u : 0u);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
        if (battle->state[side][0].leech_seeded &&
            battle->state[side][0].hp > 0) {
            apply_leech_seed_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_leech_seed_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0 : 1;
    size_t switch_side = 1 - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(
        switch_side == 0 ? action_p1 : action_p2
    );
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    const Gen3MoveData *move = &GEN3_MOVES[mover->move_ids[move_slot]];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        move->id != GEN3_MOVE_LEECH_SEED ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <=
            spikes_damage(battle, switch_side, switch_target)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    int target_is_grass = has_type(target, GEN3_TYPE_GRASS);

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    int hit = !target_is_grass &&
        random_below(output, 100) < move->accuracy;
    uint16_t hp_after_entry = (uint16_t)(
        battle->state[switch_side][switch_target].hp -
        spikes_damage(battle, switch_side, switch_target)
    );
    uint32_t hp_after_leftovers = hp_after_entry;
    if (target->item_id == GEN3_ITEM_LEFTOVERS &&
        hp_after_leftovers < target->stats[0]) {
        hp_after_leftovers += target->stats[0] / 16u;
        if (hp_after_leftovers > target->stats[0]) {
            hp_after_leftovers = target->stats[0];
        }
    }
    uint16_t seed_damage = (uint16_t)(target->stats[0] / 8u);
    if (seed_damage == 0) seed_damage = 1;
    int terminal_seed_residual = hit && hp_after_leftovers <= seed_damage;
    if (!terminal_seed_residual) {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
    }
    if (target_is_grass) {
        /* Showdown still advances the event RNG around an immunity here. */
        for (size_t i = 0; i < 5; i++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    battle->state[move_side][0].protect_counter = 0;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_LEECH_SEED);
    if (hit) {
        battle->state[switch_side][0].leech_seeded = 1;
        record_volatile_start(
            battle, (uint8_t)switch_side, GEN3_MOVE_LEECH_SEED
        );
    }
    int residual_speed_tie = battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5];
    size_t residual_first = residual_speed_tie && target_is_grass ?
        move_side : battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (hit && side == switch_side) {
            apply_leech_seed_residual(battle, switch_side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

static int resolve_will_o_wisp_and_switch(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    size_t move_side = action_p1 < 4 ? 0u : 1u;
    size_t switch_side = 1u - move_side;
    size_t move_slot = (size_t)(move_side == 0 ? action_p1 : action_p2);
    size_t switch_target = (size_t)switch_slot(
        switch_side == 0 ? action_p1 : action_p2
    );
    const Gen3PokemonSet *mover = &battle->teams[move_side].pokemon[0];
    const Gen3PokemonSet *target = &battle->teams[switch_side].pokemon[switch_target];
    if (!switch_only_team(battle) || !simple_items_team(battle) ||
        mover->move_ids[move_slot] != GEN3_MOVE_WILL_O_WISP ||
        battle->state[move_side][0].pp[move_slot] == 0 ||
        battle->state[switch_side][switch_target].hp == 0 ||
        battle->state[switch_side][switch_target].hp <=
            spikes_damage(battle, switch_side, switch_target) ||
        battle->state[switch_side][switch_target].status != GEN3_STATUS_NONE ||
        has_type(target, GEN3_TYPE_FIRE)) {
        return GEN3_UNSUPPORTED_ACTION;
    }

    uint16_t planned_seed[4];
    memcpy(planned_seed, battle->seed, sizeof(planned_seed));
    uint32_t output = 0;
    int hit = 0;
    if (switch_side == 0 &&
        target->ability_id == GEN3_ABILITY_NATURAL_CURE) {
        /* Switch placement and Update handlers precede the accuracy check;
         * successful status application and end-turn Quick Claw follow it. */
        int incoming_faster = target->stats[5] > mover->stats[5];
        size_t frames = incoming_faster ? 5u : 3u;
        size_t accuracy_frame = incoming_faster ? 2u : 0u;
        for (size_t frame = 0; frame < frames; frame++) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
            if (frame == accuracy_frame) {
                hit = random_below(output, 100) <
                    GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy;
            }
        }
    } else {
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        hit = random_below(output, 100) <
            GEN3_MOVES[GEN3_MOVE_WILL_O_WISP].accuracy;
        assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        if (hit && switch_side == 1 &&
            target->ability_id != GEN3_ABILITY_NATURAL_CURE) {
            assert(gen3_prng_next(planned_seed, &output) == GEN3_OK);
        }
    }

    battle->event_count = 0;
    swap_pokemon(battle, switch_side, switch_target);
    record_switch(battle, (uint8_t)switch_side);
    apply_spikes_entry(battle, switch_side);
    battle->state[move_side][0].pp[move_slot]--;
    record_move(battle, (uint8_t)move_side, GEN3_MOVE_WILL_O_WISP);
    if (hit) {
        battle->state[switch_side][0].status = GEN3_STATUS_BURN;
        record_status(battle, (uint8_t)switch_side, GEN3_STATUS_BURN);
    }
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? residual_first : 1u - residual_first;
        apply_leftovers_side(battle, side);
        if (battle->state[side][0].leech_seeded) {
            apply_leech_seed_residual(battle, side);
        }
        if (battle->state[side][0].status == GEN3_STATUS_BURN) {
            apply_burn_residual(battle, side);
        } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC) {
            apply_toxic_residual(battle, side);
        }
    }
    memcpy(battle->seed, planned_seed, sizeof(battle->seed));
    return GEN3_OK;
}

int gen3_battle_switch_slice_supported(
    const Gen3Battle *battle,
    uint8_t *out_supported
) {
    if (battle == NULL || out_supported == NULL) return GEN3_INVALID_ARGUMENT;
    *out_supported = (uint8_t)switch_only_team(battle);
    return GEN3_OK;
}

static void swap_pokemon(Gen3Battle *battle, size_t side, size_t slot) {
    uint16_t outgoing_ability = battle->teams[side].pokemon[0].ability_id;
    Gen3EffectRef outgoing_effect = {
        GEN3_EFFECT_ABILITY, outgoing_ability,
    };
    if (find_effect_descriptor(outgoing_effect) != NULL) {
        Gen3RuntimeEvent event = {
            .event_id = GEN3_EFFECT_EVENT_SWITCH_OUT,
            .effect = outgoing_effect,
            .holder = {GEN3_HOLDER_POKEMON, (uint8_t)side, 0},
            .target = {GEN3_HOLDER_POKEMON, (uint8_t)side, 0},
            .source = {GEN3_HOLDER_NONE, 0, 0},
        };
        int dispatched = dispatch_effect_event(battle, &event);
        assert(dispatched != GEN3_EFFECT_DISPATCH_UNKNOWN);
    }
    Gen3PokemonSet set = battle->teams[side].pokemon[0];
    battle->teams[side].pokemon[0] = battle->teams[side].pokemon[slot];
    battle->teams[side].pokemon[slot] = set;

    Gen3PokemonState state = battle->state[side][0];
    battle->state[side][0] = battle->state[side][slot];
    battle->state[side][slot] = state;
    /* Switching clears volatile state from both the outgoing and incoming
     * battle positions. Persistent HP, PP, and major status remain. */
    battle->state[side][0].protect_counter = 0;
    battle->state[side][slot].protect_counter = 0;
    battle->state[side][0].toxic_counter = 0;
    battle->state[side][slot].toxic_counter = 0;
    battle->state[side][0].leech_seeded = 0;
    battle->state[side][slot].leech_seeded = 0;
    memset(
        battle->state[side][0].stat_stages, 0,
        sizeof(battle->state[side][0].stat_stages)
    );
    memset(
        battle->state[side][slot].stat_stages, 0,
        sizeof(battle->state[side][slot].stat_stages)
    );
}

static int compile_simultaneous_forced_switches(
    Gen3Battle *battle, const Gen3Choice choices[GEN3_SIDE_COUNT]
) {
    assert(battle != NULL);
    assert(choices != NULL);
    assert(battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(battle->phase.required_side_mask ==
        (uint8_t)((1u << GEN3_SIDE_COUNT) - 1u));

    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (choices[side].kind != GEN3_CHOICE_SWITCH ||
            choices[side].slot == 0 ||
            choices[side].slot >= GEN3_TEAM_SIZE ||
            battle->state[side][choices[side].slot].hp == 0) {
            return GEN3_ILLEGAL_ACTION;
        }
        uint16_t damage = spikes_damage(battle, side, choices[side].slot);
        if (damage >= battle->state[side][choices[side].slot].hp) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }
    if (battle->phase.continuation != GEN3_CONTINUE_RESIDUAL ||
        !switch_only_team(battle) || !simple_items_team(battle)) {
        return GEN3_UNSUPPORTED_ACTION;
    }
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][choices[side].slot].leech_seeded ||
            battle->state[side][choices[side].slot].status == GEN3_STATUS_BURN ||
            battle->state[side][choices[side].slot].status == GEN3_STATUS_TOXIC) {
            return GEN3_UNSUPPORTED_ACTION;
        }
    }

    assert(action_queue_is_residual_continuation(&battle->action_queue));
    Gen3Action saved_tail = take_action(battle, GEN3_TRACE_QUEUE_SUSPEND);
    /* commitChoices commits p1 then p2, sorts only these newly committed
     * actions, then restores the interrupted residual continuation. */
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        uint8_t target_slot = choices[side].slot;
        push_action(battle, (Gen3Action){
            .kind = GEN3_ACTION_INSTASWITCH,
            .side = (uint8_t)side,
            .key = {
                .order = 3,
                /* Forced replacement actions remain owned by the fainted
                 * active; Showdown orders them with that Pokemon's speed. */
                .speed = battle->teams[side].pokemon[0].stats[5],
            },
            .value.switch_action.target_slot = target_slot,
        });
    }
    sort_action_queue(battle);
    append_action(battle, saved_tail, GEN3_TRACE_QUEUE_RESUME);
    battle->phase.kind = GEN3_PHASE_EXECUTING;
    return GEN3_OK;
}

static void run_update_order(Gen3Battle *battle) {
    Gen3OrderedRecord records[GEN3_SIDE_COUNT];
    size_t count = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->state[side][0].hp == 0) continue;
        records[count] = (Gen3OrderedRecord){
            .key = {.speed = battle->teams[side].pokemon[0].stats[5]},
            .payload_index = (uint8_t)side,
        };
        count++;
    }
    sort_ordered_records(
        battle, records, count, GEN3_TRACE_PRNG_UNKNOWN
    );
}

static void run_descriptor_residuals(Gen3Battle *battle) {
    Gen3RuntimeEvent events[GEN3_SIDE_COUNT];
    Gen3OrderedRecord records[GEN3_SIDE_COUNT];
    size_t count = 0;
    assert(discover_effect_handlers(battle, (Gen3DiscoveryRequest){
        .event_id = GEN3_EFFECT_EVENT_RESIDUAL,
        .scope = GEN3_DISCOVER_ACTIVE_ITEMS,
    }, events, records, GEN3_SIDE_COUNT, &count) == GEN3_DISCOVER_OK);
    assert(event_order_policy(GEN3_EFFECT_EVENT_RESIDUAL) ==
        GEN3_EVENT_ORDER_SPEED);
    sort_ordered_records(
        battle, records, count, GEN3_TRACE_PRNG_UNKNOWN
    );
    for (size_t index = 0; index < count; index++) {
        assert(dispatch_effect_event(battle,
            &events[records[index].payload_index]) == GEN3_EFFECT_DISPATCH_HANDLED);
    }
}

static void roll_quick_claw(Gen3Battle *battle) {
    uint32_t output = 0;
    assert(battle->action_queue.count == 0);
    assert(gen3_prng_next(battle->seed, &output) == GEN3_OK);
    (void)output;
}

static int execute_simultaneous_forced_switches(Gen3Battle *battle) {
    assert(battle != NULL);
    assert(battle->phase.kind == GEN3_PHASE_EXECUTING);
    assert(battle->action_queue.count == GEN3_SIDE_COUNT + 1u);

    battle->event_count = 0;
    while (battle->action_queue.count != 0) {
        Gen3Action action = pop_action(battle);
        if (action.kind == GEN3_ACTION_INSTASWITCH) {
            size_t side = action.side;
            swap_pokemon(battle, side, action.value.switch_action.target_slot);
            record_switch(battle, (uint8_t)side);
            insert_action(battle, (Gen3Action){
                .kind = GEN3_ACTION_RUN_SWITCH,
                .side = (uint8_t)side,
                .key = {.order = 101,
                    .speed = battle->teams[side].pokemon[0].stats[5]},
            });
            /* battle.runAction deliberately skips Update while another
             * instaswitch is at the queue head. */
            Gen3Action next = battle->action_queue.values[
                battle->action_queue.order[battle->action_queue.head].payload_index];
            if (next.kind != GEN3_ACTION_INSTASWITCH) run_update_order(battle);
            continue;
        }
        if (action.kind == GEN3_ACTION_RUN_SWITCH) {
            assert(!apply_spikes_entry_allow_faint(battle, action.side));
            run_update_order(battle);
            continue;
        }
        assert(action.kind == GEN3_ACTION_RESIDUAL);
        run_descriptor_residuals(battle);
        run_update_order(battle);
    }
    roll_quick_claw(battle);
    battle->force_switch_side = -1;
    battle->resume_residuals = 0;
    finish_resumed_turn(battle);
    return GEN3_OK;
}

static int compile_single_forced_switch(
    Gen3Battle *battle, const Gen3Choice choices[GEN3_SIDE_COUNT]
) {
    assert(battle != NULL);
    assert(choices != NULL);
    assert(battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST);
    assert(battle->phase.required_side_mask == 1u ||
        battle->phase.required_side_mask == 2u);

    size_t side = battle->phase.forced_first_side;
    size_t waiting_side = 1u - side;
    const Gen3Choice *choice = &choices[side];
    if (choice->kind != GEN3_CHOICE_SWITCH ||
        choices[waiting_side].kind != GEN3_CHOICE_NONE) {
        return GEN3_ILLEGAL_ACTION;
    }
    if (choice->slot == 0 || choice->slot >= GEN3_TEAM_SIZE ||
        battle->state[side][choice->slot].hp == 0) {
        return GEN3_ILLEGAL_ACTION;
    }

    if (battle->phase.continuation == GEN3_CONTINUE_RESIDUAL) {
        assert(action_queue_is_residual_continuation(&battle->action_queue));
    } else {
        assert(battle->action_queue.count == 0);
    }
    Gen3Action saved_tail = {0};
    int has_saved_tail = battle->action_queue.count != 0;
    if (has_saved_tail) {
        saved_tail = take_action(battle, GEN3_TRACE_QUEUE_SUSPEND);
    }
    push_action(battle, (Gen3Action){
        .kind = GEN3_ACTION_SWITCH,
        .side = (uint8_t)side,
        .key = {
            .order = 103,
            .speed = battle->teams[side].pokemon[0].stats[5],
        },
        .value.switch_action.target_slot = choice->slot,
    });
    if (has_saved_tail) {
        append_action(battle, saved_tail, GEN3_TRACE_QUEUE_RESUME);
    }
    battle->phase.kind = GEN3_PHASE_EXECUTING;
    return GEN3_OK;
}

static int execute_single_forced_switch(Gen3Battle *battle) {
    assert(battle != NULL);
    assert(battle->phase.kind == GEN3_PHASE_EXECUTING);
    assert(battle->action_queue.count ==
        (battle->phase.continuation == GEN3_CONTINUE_RESIDUAL ? 2u : 1u));
    Gen3Continuation continuation = battle->phase.continuation;
    Gen3Action action = pop_action(battle);
    assert(action.kind == GEN3_ACTION_SWITCH);
    assert(action.side < GEN3_SIDE_COUNT);
    size_t side = action.side;
    size_t slot = action.value.switch_action.target_slot;

    battle->event_count = 0;
    swap_pokemon(battle, side, slot);
    record_switch(battle, (uint8_t)side);
    if (apply_spikes_entry_allow_faint(battle, side)) {
        /* The residual action remains at the head and survives another
         * forced-replacement request caused by entry hazards. */
        assert(continuation != GEN3_CONTINUE_RESIDUAL ||
            action_queue_is_residual_continuation(&battle->action_queue));
        sync_phase_from_legacy_request(battle);
        return GEN3_OK;
    }
    battle->force_switch_side = -1;
    battle->resume_residuals = 0;
    if (continuation == GEN3_CONTINUE_NONE) {
        assert(battle->action_queue.count == 0);
        int speed_tie = battle->teams[side].pokemon[0].stats[5] ==
            battle->teams[1 - side].pokemon[0].stats[5];
        size_t frames = speed_tie ||
            battle->state[1 - side][0].leech_seeded ? 3u : 1u;
        consume_rng_frames(battle, frames);
        sync_phase_from_legacy_request(battle);
        return GEN3_OK;
    }

    assert(continuation == GEN3_CONTINUE_RESIDUAL);
    Gen3Action residual = pop_action(battle);
    assert(residual.kind == GEN3_ACTION_RESIDUAL);
    /* Forced replacement completes the interrupted turn. With the two
     * equal-speed Skarmory actives in this slice, Showdown consumes four
     * tied handler shuffles followed by its Quick Claw roll. */
    if (battle->teams[0].pokemon[0].stats[5] ==
        battle->teams[1].pokemon[0].stats[5]) {
        consume_rng_frames(battle, 5);
    } else {
        size_t other_side = 1 - side;
        consume_rng_frames(
            battle,
            battle->state[other_side][0].protect_counter != 0 &&
            !(side == 0 && battle->state[other_side][0].status ==
                GEN3_STATUS_BURN) ? 2u : 1u
        );
    }
    size_t residual_first = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1u : 0u;
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t residual_side =
            order == 0 ? residual_first : 1 - residual_first;
        apply_leftovers_side(battle, residual_side);
        if (battle->state[residual_side][0].leech_seeded &&
            battle->state[residual_side][0].hp > 0) {
            apply_leech_seed_residual(battle, residual_side);
        }
        if (battle->state[residual_side][0].status == GEN3_STATUS_BURN &&
            battle->state[residual_side][0].hp > 0) {
            apply_burn_residual(battle, residual_side);
        } else if (
            battle->state[residual_side][0].status == GEN3_STATUS_TOXIC &&
            battle->state[residual_side][0].hp > 0
        ) {
            apply_toxic_residual(battle, residual_side);
        }
    }
    finish_resumed_turn(battle);
    return GEN3_OK;
}

static int gen3_battle_turn_impl(
    Gen3Battle *battle, int8_t action_p1, int8_t action_p2
) {
    if (battle == NULL) return GEN3_INVALID_ARGUMENT;
    if (battle->done) return GEN3_ILLEGAL_ACTION;
    if (action_p1 < -1 || action_p1 > 8 || action_p2 < -1 || action_p2 > 8) {
        return GEN3_INVALID_ARGUMENT;
    }
    sync_phase_from_legacy_request(battle);
    if (battle->force_switch_side <= -2) {
        const Gen3Choice choices[GEN3_SIDE_COUNT] = {
            decode_choice(0, action_p1),
            decode_choice(1, action_p2),
        };
        int result = compile_simultaneous_forced_switches(battle, choices);
        if (result != GEN3_OK) return result;
        return execute_simultaneous_forced_switches(battle);
    }
    if (battle->force_switch_side >= 0) {
        const Gen3Choice choices[GEN3_SIDE_COUNT] = {
            decode_choice(0, action_p1),
            decode_choice(1, action_p2),
        };
        int result = compile_single_forced_switch(battle, choices);
        if (result != GEN3_OK) return result;
        return execute_single_forced_switch(battle);
    }
    int slot_p1 = switch_slot(action_p1);
    int slot_p2 = switch_slot(action_p2);
    if (action_p1 >= 0 && action_p1 < 4 && action_p2 >= 0 && action_p2 < 4) {
        return resolve_move_pair(battle, action_p1, action_p2);
    }
    if ((action_p1 >= 0 && action_p1 < 4) != (action_p2 >= 0 && action_p2 < 4)) {
        return resolve_move_and_switch(battle, action_p1, action_p2);
    }
    if (slot_p1 < 0 || slot_p2 < 0) return GEN3_UNSUPPORTED_ACTION;
    if (!switch_only_team(battle)) return GEN3_UNSUPPORTED_ACTION;
    if (battle->state[0][slot_p1].hp == 0 || battle->state[1][slot_p2].hp == 0) {
        return GEN3_ILLEGAL_ACTION;
    }
    /* Plan switch order from a draw. The hazard-KO interruption below restores
     * it for the observed boundary where Showdown never consumes that draw. */
    uint16_t seed_before_switch_order[4];
    memcpy(seed_before_switch_order, battle->seed, sizeof(seed_before_switch_order));
    uint32_t switch_order = 0;
    int rng_result = gen3_prng_next(battle->seed, &switch_order);
    assert(rng_result == GEN3_OK);
    uint16_t speed_p1 = battle->teams[0].pokemon[0].stats[5];
    uint16_t speed_p2 = battle->teams[1].pokemon[0].stats[5];
    int deterministic_single_hazard_switch =
        battle->teams[0].pokemon[slot_p1].ability_id == GEN3_ABILITY_TORRENT &&
        battle->spikes[0] != 0 &&
        spikes_damage(battle, 1, (size_t)slot_p2) == 0 &&
        (battle->teams[1].pokemon[slot_p2].ability_id == GEN3_ABILITY_LEVITATE ||
         battle->teams[1].pokemon[slot_p2].species_id == 242) &&
        battle->state[1][slot_p2].hp ==
            battle->teams[1].pokemon[slot_p2].stats[0] &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE &&
        !battle->state[0][0].leech_seeded &&
        !battle->state[1][0].leech_seeded;
    int deterministic_gengar_starmie_switch =
        battle->spikes[0] == 3 && battle->spikes[1] == 2 &&
        battle->teams[0].pokemon[slot_p1].species_id == 94 &&
        battle->teams[1].pokemon[slot_p2].species_id == 121 &&
        battle->state[0][slot_p1].hp ==
            battle->teams[0].pokemon[slot_p1].stats[0] &&
        battle->state[1][slot_p2].hp ==
            battle->teams[1].pokemon[slot_p2].stats[0] &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE;
    int deterministic_celebi_skarm_switch =
        battle->spikes[0] == 1 &&
        battle->teams[0].pokemon[slot_p1].species_id == 251 &&
        battle->teams[1].pokemon[slot_p2].species_id == 227 &&
        battle->state[0][slot_p1].hp <
            battle->teams[0].pokemon[slot_p1].stats[0] &&
        battle->state[1][slot_p2].hp <
            battle->teams[1].pokemon[slot_p2].stats[0] &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE;
    int four_frame_celebi_skarm_switch =
        battle->spikes[0] == 3 && battle->spikes[1] == 1 &&
        battle->teams[0].pokemon[slot_p1].species_id == 251 &&
        battle->teams[1].pokemon[slot_p2].species_id == 227 &&
        battle->state[1][slot_p2].hp ==
            battle->teams[1].pokemon[slot_p2].stats[0] &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE;
    int both_switchers_natural_cure =
        battle->teams[0].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE &&
        battle->teams[1].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE;
    size_t natural_cure_switcher_count = 0;
    uint8_t natural_cure_switcher_mask = 0;
    int natural_cure_status = 0;
    int persistent_outgoing_status = 0;
    int outgoing_leech_seeded = battle->state[0][0].leech_seeded ||
        battle->state[1][0].leech_seeded;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->teams[side].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE &&
            battle->state[side][0].status != GEN3_STATUS_NONE) {
            natural_cure_status = 1;
        }
        if (battle->teams[side].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE) {
            natural_cure_switcher_count++;
            natural_cure_switcher_mask |= (uint8_t)(1u << side);
        }
        if (battle->teams[side].pokemon[0].ability_id != GEN3_ABILITY_NATURAL_CURE &&
            battle->state[side][0].status != GEN3_STATUS_NONE) {
            persistent_outgoing_status = 1;
        }
    }
    battle->event_count = 0;
    size_t first_switch = speed_p1 == speed_p2 ?
        random_below(switch_order, 2) : (speed_p2 > speed_p1 ? 1u : 0u);
    for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
        size_t side = order == 0 ? first_switch : 1 - first_switch;
        size_t slot = side == 0 ? (size_t)slot_p1 : (size_t)slot_p2;
        swap_pokemon(battle, side, slot);
        record_switch(battle, (uint8_t)side);
        if (apply_spikes_entry_allow_faint(battle, side)) {
            if (!battle->done) {
                battle->force_switch_side = (int8_t)side;
                battle->resume_residuals = 1;
            }
            if ((side == 0 && order == 0 && speed_p1 > speed_p2 &&
                 battle->spikes[0] == 3 && battle->spikes[1] == 2) ||
                (side == 1 &&
                ((order == 0 && speed_p2 > speed_p1) ||
                 (order == 1 && speed_p1 > speed_p2)))) {
                memcpy(
                    battle->seed,
                    seed_before_switch_order,
                    sizeof(battle->seed)
                );
            }
            if (order == 1 &&
                battle->teams[0].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE &&
                battle->teams[1].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE) {
                consume_rng_frames(battle, 3);
            } else if (order == 1 && side == 0 &&
                battle->teams[0].pokemon[0].ability_id ==
                    GEN3_ABILITY_NATURAL_CURE) {
                consume_rng_frames(battle, 1);
            }
            return GEN3_OK;
        }
    }
    size_t ordered_field_events = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (spikes_damage(battle, side, 0) != 0) ordered_field_events++;
    }
    int has_leftovers_heal = 0;
    uint8_t leftovers_heal_side_mask = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        const Gen3PokemonSet *set = &battle->teams[side].pokemon[0];
        const Gen3PokemonState *state = &battle->state[side][0];
        if (set->item_id == GEN3_ITEM_LEFTOVERS && state->hp > 0 && state->hp < set->stats[0]) {
            has_leftovers_heal = 1;
            leftovers_heal_side_mask |= (uint8_t)(1u << side);
            if (!natural_cure_status) ordered_field_events++;
        }
    }
    int both_replacements_natural_cure =
        battle->teams[0].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE &&
        battle->teams[1].pokemon[0].ability_id == GEN3_ABILITY_NATURAL_CURE;
    size_t natural_cure_replacement_count = 0;
    uint8_t natural_cure_replacement_mask = 0;
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (battle->teams[side].pokemon[0].ability_id ==
            GEN3_ABILITY_NATURAL_CURE) {
            natural_cure_replacement_count++;
            natural_cure_replacement_mask |= (uint8_t)(1u << side);
        }
    }
    int replacement_speed_tie =
        battle->teams[0].pokemon[0].stats[5] == battle->teams[1].pokemon[0].stats[5];
    int speed_order_reversed = !replacement_speed_tie && speed_p1 != speed_p2 &&
        ((speed_p1 > speed_p2) !=
         (battle->teams[0].pokemon[0].stats[5] > battle->teams[1].pokemon[0].stats[5]));
    int stable_p2_faster = speed_p2 > speed_p1 && !replacement_speed_tie &&
        battle->teams[1].pokemon[0].stats[5] >
            battle->teams[0].pokemon[0].stats[5];
    size_t residual_first_side = battle->teams[1].pokemon[0].stats[5] >
        battle->teams[0].pokemon[0].stats[5] ? 1 : 0;
    if (ordered_field_events != 0 && !natural_cure_status &&
        !persistent_outgoing_status &&
        !(both_replacements_natural_cure &&
          (both_switchers_natural_cure && speed_p1 == speed_p2)) &&
        !((both_replacements_natural_cure || both_switchers_natural_cure) &&
          speed_p1 != speed_p2 && !replacement_speed_tie) &&
        !(stable_p2_faster && natural_cure_switcher_count == 1 &&
          natural_cure_switcher_mask == (uint8_t)(1u << 1) &&
          natural_cure_replacement_count == 1 &&
          natural_cure_replacement_mask == (uint8_t)(1u << 0)) &&
        !(stable_p2_faster && ordered_field_events > 1 &&
          natural_cure_switcher_count == 1 &&
          natural_cure_switcher_mask == (uint8_t)(1u << 1) &&
          natural_cure_replacement_count == 1 &&
          natural_cure_replacement_mask == (uint8_t)(1u << 1)) &&
        !(stable_p2_faster && ordered_field_events > 1 &&
          natural_cure_switcher_count == 1 &&
          natural_cure_replacement_count == 0) &&
        !(stable_p2_faster && ordered_field_events > 1 &&
          natural_cure_switcher_count == 0 &&
          natural_cure_replacement_count == 1 &&
          natural_cure_replacement_mask == (uint8_t)(1u << 1)) &&
        !(speed_p1 != speed_p2 && !replacement_speed_tie &&
          !speed_order_reversed && speed_p1 > speed_p2) &&
        !(speed_order_reversed && natural_cure_switcher_count == 1 &&
          ((ordered_field_events == 1 &&
            ((leftovers_heal_side_mask >> residual_first_side) & 1u) != 0) ||
           (natural_cure_replacement_count == 0 &&
            ordered_field_events == 1) ||
           (natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
            natural_cure_replacement_count == 1 &&
            natural_cure_replacement_mask == (uint8_t)(1u << 1) &&
            ordered_field_events == 1 &&
            leftovers_heal_side_mask == (uint8_t)(1u << 1) &&
            battle->teams[0].pokemon[0].ability_id ==
                GEN3_ABILITY_LEVITATE) ||
           (natural_cure_replacement_count == 1 &&
            ordered_field_events > 1)) &&
          !both_replacements_natural_cure)) {
        /* Each applicable entry/residual field event participates in
         * Showdown's ordered-handler queue, followed by one generation-wide
         * Quick Claw check. The switch-action shuffle was consumed above. */
        size_t handler_frames =
            speed_order_reversed && natural_cure_switcher_count == 0 &&
            natural_cure_replacement_count == 1 ? 2u :
            stable_p2_faster ? 2u : replacement_speed_tie ?
            (both_replacements_natural_cure && speed_p1 == speed_p2 ? 7u : 4u) :
            (both_switchers_natural_cure && speed_p1 == speed_p2 &&
             ordered_field_events > 1 ?
                ordered_field_events -
                    (natural_cure_replacement_count == 1 &&
                     ordered_field_events > 3 ? 1u : 0u) :
                ordered_field_events + 1 +
                    (both_switchers_natural_cure ? 1u : 0u) +
                    (both_replacements_natural_cure &&
                     speed_p1 == speed_p2 && ordered_field_events == 1 ?
                        1u : 0u));
        for (size_t frame = 0; frame < handler_frames; frame++) {
            uint32_t handler_order = 0;
            assert(gen3_prng_next(battle->seed, &handler_order) == GEN3_OK);
            /* After the replacement-speed shuffle, the next tied handler
             * group is Leftovers and determines its visible heal order. */
            if (replacement_speed_tie && frame == 1) {
                residual_first_side = random_below(handler_order, 2);
            }
        }
    }
    if (ordered_field_events != 0 && !natural_cure_status &&
        both_switchers_natural_cure && both_replacements_natural_cure &&
        speed_p1 == speed_p2) {
        consume_rng_frames(battle, 3);
    }
    if (ordered_field_events != 0 && !natural_cure_status &&
        both_switchers_natural_cure && !both_replacements_natural_cure &&
        speed_p1 == speed_p2 && replacement_speed_tie) {
        consume_rng_frames(battle, 3);
    }
    if (ordered_field_events > 2 && !natural_cure_status &&
        !persistent_outgoing_status && stable_p2_faster &&
        natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 1) &&
        natural_cure_replacement_count == 1 &&
        natural_cure_replacement_mask == (uint8_t)(1u << 0)) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events > 2 &&
        (battle->spikes[1] != 0 || speed_p1 < speed_p2) &&
        !natural_cure_status &&
        !persistent_outgoing_status && speed_order_reversed &&
        natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        both_replacements_natural_cure &&
        !(speed_p1 < speed_p2 &&
          battle->teams[0].pokemon[0].stats[5] > speed_p2 &&
          battle->teams[1].pokemon[0].stats[5] > speed_p2)) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events > 1 && !natural_cure_status &&
        !persistent_outgoing_status && both_switchers_natural_cure &&
        speed_order_reversed && natural_cure_replacement_count == 1 &&
        natural_cure_replacement_mask == (uint8_t)(1u << 0)) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events != 0 && !natural_cure_status &&
        !persistent_outgoing_status && natural_cure_switcher_count == 0 &&
        both_replacements_natural_cure && speed_order_reversed &&
        speed_p2 > speed_p1) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events > 1 && !natural_cure_status &&
        !persistent_outgoing_status && speed_order_reversed &&
        natural_cure_switcher_count == 1 &&
        natural_cure_replacement_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 1) &&
        natural_cure_replacement_mask == (uint8_t)(1u << 0) &&
        !outgoing_leech_seeded &&
        battle->state[0][0].status == GEN3_STATUS_NONE &&
        battle->state[1][0].status == GEN3_STATUS_NONE &&
        battle->teams[0].pokemon[0].stats[5] > speed_p2) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events != 0 && !natural_cure_status &&
        !persistent_outgoing_status && !replacement_speed_tie &&
        !speed_order_reversed && speed_p1 > speed_p2 &&
        (battle->state[0][0].status != GEN3_STATUS_NONE ||
         battle->state[1][0].status != GEN3_STATUS_NONE)) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events == 1 && !natural_cure_status &&
        !persistent_outgoing_status && speed_order_reversed &&
        natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        natural_cure_replacement_count == 0 &&
        leftovers_heal_side_mask == (uint8_t)(1u << 1)) {
        consume_rng_frames(battle, 2);
    }
    if (persistent_outgoing_status && ordered_field_events == 0 &&
        !outgoing_leech_seeded) {
        /* A non-curing major status remains in Showdown's switch-out event
         * queues even though switching emits no status protocol line. */
        consume_rng_frames(
            battle,
            speed_order_reversed && natural_cure_replacement_count == 1 ?
                2u : 3u
        );
    }
    if (persistent_outgoing_status && ordered_field_events != 0 &&
        replacement_speed_tie) {
        size_t persistent_tie_frames = speed_p1 == speed_p2 ? 7u : 4u;
        for (size_t frame = 0; frame < persistent_tie_frames; frame++) {
            uint32_t handler_order = 0;
            assert(gen3_prng_next(battle->seed, &handler_order) == GEN3_OK);
            if (frame == 1) {
                residual_first_side = random_below(handler_order, 2);
            }
        }
    }
    if (persistent_outgoing_status && ordered_field_events != 0 &&
        !replacement_speed_tie && speed_order_reversed &&
        natural_cure_switcher_count == 0 &&
        !both_replacements_natural_cure &&
        !(battle->spikes[0] == 3 && battle->spikes[1] == 3)) {
        consume_rng_frames(battle, 2);
    }
    if (persistent_outgoing_status && ordered_field_events != 0 &&
        !replacement_speed_tie && speed_p1 == speed_p2) {
        consume_rng_frames(battle, 3);
    }
    if (natural_cure_status && !persistent_outgoing_status &&
        ordered_field_events > 1 &&
        replacement_speed_tie && both_replacements_natural_cure) {
        /* A status cured on switch-out still leaves the tied Natural Cure
         * handlers in the queue. Tied Natural Cure replacements consume four
         * ordering draws before entry/residual processing. */
        consume_rng_frames(battle, 4);
    }
    if (natural_cure_status &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        natural_cure_replacement_mask == (uint8_t)(1u << 1) &&
        !replacement_speed_tie && !speed_order_reversed) {
        consume_rng_frames(battle, 2);
    }
    if (natural_cure_status && !persistent_outgoing_status &&
        natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        natural_cure_replacement_count == 1 &&
        natural_cure_replacement_mask == (uint8_t)(1u << 1) &&
        speed_order_reversed && battle->spikes[0] == 3 &&
        battle->spikes[1] == 3) {
        consume_rng_frames(battle, 2);
    }
    if (natural_cure_status && !persistent_outgoing_status &&
        natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        natural_cure_replacement_count == 0 &&
        ordered_field_events != 0 && !replacement_speed_tie &&
        !speed_order_reversed && speed_p1 > speed_p2) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events == 0 && !natural_cure_status &&
        !persistent_outgoing_status && !replacement_speed_tie &&
        ((stable_p2_faster && !both_switchers_natural_cure) ||
         (both_switchers_natural_cure && speed_p1 == speed_p2)) &&
        natural_cure_switcher_count != 0 &&
        natural_cure_replacement_count != 0) {
        consume_rng_frames(battle, natural_cure_switcher_count + 1u);
    }
    if (ordered_field_events == 0 && !natural_cure_status &&
        !persistent_outgoing_status && both_switchers_natural_cure &&
        speed_p1 != speed_p2 && stable_p2_faster &&
        natural_cure_replacement_count == 1 &&
        (natural_cure_replacement_mask == (uint8_t)(1u << 0) ||
         (natural_cure_replacement_mask == (uint8_t)(1u << 1) &&
          battle->teams[0].pokemon[0].stats[5] < speed_p1))) {
        consume_rng_frames(battle, 2);
    }
    if (ordered_field_events == 0 && !natural_cure_status &&
        !persistent_outgoing_status && !replacement_speed_tie &&
        speed_order_reversed && natural_cure_switcher_count == 1 &&
        natural_cure_switcher_mask == (uint8_t)(1u << 0) &&
        battle->teams[0].pokemon[slot_p1].species_id == 242 &&
        ((natural_cure_replacement_count == 0) ||
         (natural_cure_replacement_count == 1 &&
          natural_cure_replacement_mask == (uint8_t)(1u << 1)))) {
        /* A clean unequal-speed reversal retains one post-action Update
         * shuffle plus the generation-wide Quick Claw roll. */
        consume_rng_frames(battle, 2);
    }
    if (replacement_speed_tie && ordered_field_events == 0 &&
        !natural_cure_status && !persistent_outgoing_status) {
        /* Even with no visible residual, equal-speed replacements tie in
         * four SwitchIn/residual handler groups. If the outgoing pair was
         * tied too, three additional tied Update/Residual queues remain. */
        consume_rng_frames(battle, speed_p1 == speed_p2 ? 7u : 4u);
    }
    if (has_leftovers_heal || battle->state[0][0].status != GEN3_STATUS_NONE ||
        battle->state[1][0].status != GEN3_STATUS_NONE) {
        for (size_t order = 0; order < GEN3_SIDE_COUNT; order++) {
            size_t side = order == 0 ? residual_first_side : 1 - residual_first_side;
            apply_leftovers_side(battle, side);
            if (battle->state[side][0].status == GEN3_STATUS_BURN &&
                battle->state[side][0].hp > 0) {
                apply_burn_residual(battle, side);
            } else if (battle->state[side][0].status == GEN3_STATUS_TOXIC &&
                battle->state[side][0].hp > 0) {
                apply_toxic_residual(battle, side);
            }
        }
    }
    if (deterministic_single_hazard_switch ||
        deterministic_gengar_starmie_switch ||
        deterministic_celebi_skarm_switch) {
        memcpy(
            battle->seed, seed_before_switch_order, sizeof(battle->seed)
        );
        consume_rng_frames(battle, 1);
    } else if (four_frame_celebi_skarm_switch) {
        memcpy(
            battle->seed, seed_before_switch_order, sizeof(battle->seed)
        );
        consume_rng_frames(battle, 4);
    }
    return GEN3_OK;
}

int gen3_battle_turn(Gen3Battle *battle, int8_t action_p1, int8_t action_p2) {
#ifdef GEN3_VERIFY_TRACE
    if (battle != NULL) {
        battle->trace_emission_boundary = battle->trace_boundary + 1u;
        trace_checkpoint(battle, GEN3_TRACE_POINT_DECISION_BEGIN);
    }
#endif
    int advances_when_drained = 0;
    if (battle != NULL) {
        sync_phase_from_legacy_request(battle);
        advances_when_drained =
            battle->phase.kind == GEN3_PHASE_NORMAL_REQUEST ||
            (battle->phase.kind == GEN3_PHASE_FORCED_SWITCH_REQUEST &&
             battle->phase.continuation == GEN3_CONTINUE_RESIDUAL);
    }
    int result = gen3_battle_turn_impl(battle, action_p1, action_p2);
    /* A successful public transition must leave phase/request canonical now,
     * not lazily repair it at the beginning of the next decision. This also
     * materializes any legacy residual continuation into the explicit queue
     * before observers see DECISION_END. */
    if (battle != NULL && result == GEN3_OK) {
        sync_phase_from_legacy_request(battle);
        if (advances_when_drained &&
            battle->phase.kind == GEN3_PHASE_NORMAL_REQUEST) {
            battle->turn++;
        }
    }
#ifdef GEN3_VERIFY_TRACE
    if (battle != NULL && result == GEN3_OK) {
        battle->trace_boundary++;
        battle->trace_emission_boundary = battle->trace_boundary;
        trace_checkpoint(battle, GEN3_TRACE_POINT_DECISION_END);
        if (battle->done) {
            trace_emit(battle, (Gen3TraceRecord){
                .kind = GEN3_TRACE_TERMINAL,
                .semantic_point = GEN3_TRACE_POINT_TERMINAL,
                .value.terminal = {
                    .done = battle->done,
                    .winner_side = battle->winner_side,
                },
            });
        } else {
            trace_request(battle);
        }
    }
#endif
    return result;
}

int gen3_battle_snapshot(const Gen3Battle *battle, Gen3BattleSnapshot *out) {
    if (battle == NULL || out == NULL) return GEN3_INVALID_ARGUMENT;
    memset(out, 0, sizeof(*out));
    out->abi_version = GEN3_ABI_VERSION;
    out->struct_size = sizeof(*out);
    out->turn = battle->turn;
    out->force_switch_side = battle->force_switch_side;
    out->resume_residuals = battle->resume_residuals;
    out->done = battle->done;
    out->winner_side = battle->winner_side;
    memcpy(out->spikes, battle->spikes, sizeof(out->spikes));
    memcpy(out->seed, battle->seed, sizeof(out->seed));
    out->event_count = battle->event_count;
    memcpy(out->events, battle->events, sizeof(battle->events));
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            Gen3PokemonSnapshot *snapshot = &out->pokemon[side][slot];
            snapshot->set = battle->teams[side].pokemon[slot];
            snapshot->hp = battle->state[side][slot].hp;
            memcpy(snapshot->pp, battle->state[side][slot].pp, sizeof(snapshot->pp));
            snapshot->status = battle->state[side][slot].status;
            snapshot->protect_counter = battle->state[side][slot].protect_counter;
            snapshot->toxic_counter = battle->state[side][slot].toxic_counter;
            snapshot->leech_seeded = battle->state[side][slot].leech_seeded;
            memcpy(
                snapshot->stat_stages,
                battle->state[side][slot].stat_stages,
                sizeof(snapshot->stat_stages)
            );
        }
    }
    return GEN3_OK;
}
