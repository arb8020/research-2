#include "gen3_abi.h"
#include "gen3_verify_trace.h"

#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_DECISIONS 16u
#define MAX_PROTOCOL_EVENTS 64u

typedef struct {
    char id[96];
    uint16_t seed[4];
    int8_t decisions[MAX_DECISIONS][GEN3_SIDE_COUNT];
    size_t decision_count;
} BoundaryCase;

typedef struct {
    const char *case_id;
    Gen3TracePhaseValue phase;
    Gen3BattleEvent events[MAX_PROTOCOL_EVENTS];
    size_t event_count;
} Observer;

_Static_assert(sizeof(Gen3PokemonSet) == 48, "verifier normalization layout drift");
_Static_assert(sizeof(Gen3BattleTeam) == 296, "verifier normalization layout drift");
_Static_assert(sizeof(Gen3BattleInit) == 608, "verifier normalization layout drift");

static int valid_case_id(const char *text) {
    if (*text == '\0') return 0;
    for (const unsigned char *cursor = (const unsigned char *)text;
         *cursor != '\0'; cursor++) {
        if ((*cursor < 'a' || *cursor > 'z') &&
            (*cursor < '0' || *cursor > '9') &&
            *cursor != '.' && *cursor != '_' && *cursor != '-') return 0;
    }
    return 1;
}

static void die(const char *message) {
    fprintf(stderr, "native-boundary-driver: %s\n", message);
    exit(2);
}

static int parse_i8(const char *text, int8_t *out) {
    char *end = NULL;
    errno = 0;
    long value = strtol(text, &end, 10);
    if (errno != 0 || end == text || *end != '\0' || value < -1 || value > 8) {
        return 0;
    }
    *out = (int8_t)value;
    return 1;
}

static BoundaryCase load_case(const char *path) {
    FILE *file = fopen(path, "r");
    if (file == NULL) die("cannot open case file");
    BoundaryCase value = {0};
    char line[256];
    int saw_schema = 0;
    int saw_seed = 0;
    while (fgets(line, sizeof(line), file) != NULL) {
        line[strcspn(line, "\r\n")] = '\0';
        if (line[0] == '\0' || line[0] == '#') continue;
        if (strcmp(line, "schema=gen3ou-native-projection-v1") == 0) {
            if (saw_schema) die("duplicate schema");
            saw_schema = 1;
            continue;
        }
        if (strncmp(line, "id=", 3) == 0) {
            if (value.id[0] != '\0' || strlen(line + 3) >= sizeof(value.id)) {
                die("invalid or duplicate id");
            }
            strcpy(value.id, line + 3);
            continue;
        }
        if (strncmp(line, "seed=", 5) == 0) {
            unsigned seed[4];
            char tail;
            if (saw_seed || sscanf(line + 5, "%u,%u,%u,%u%c",
                    &seed[0], &seed[1], &seed[2], &seed[3], &tail) != 4) {
                die("invalid or duplicate seed");
            }
            for (size_t i = 0; i < 4; i++) {
                if (seed[i] > UINT16_MAX) die("seed word exceeds uint16");
                value.seed[i] = (uint16_t)seed[i];
            }
            saw_seed = 1;
            continue;
        }
        if (strncmp(line, "decision=", 9) == 0) {
            if (value.decision_count == MAX_DECISIONS) die("too many decisions");
            char first[16];
            char second[16];
            char tail;
            if (sscanf(line + 9, "%15[^,],%15s%c", first, second, &tail) != 2 ||
                !parse_i8(first, &value.decisions[value.decision_count][0]) ||
                !parse_i8(second, &value.decisions[value.decision_count][1])) {
                die("invalid decision");
            }
            value.decision_count++;
            continue;
        }
        die("unknown case-file field");
    }
    if (ferror(file)) die("failed while reading case file");
    fclose(file);
    if (!saw_schema || value.id[0] == '\0' || !saw_seed || value.decision_count == 0) {
        die("case is missing schema, id, seed, or decisions");
    }
    if (!valid_case_id(value.id)) die("case id is not canonical");
    return value;
}

static Gen3BattleInit load_init(const char *path, const BoundaryCase *input) {
    FILE *file = fopen(path, "rb");
    if (file == NULL) die("cannot open normalized Gen3BattleInit");
    Gen3BattleInit init;
    if (fread(&init, 1, sizeof(init), file) != sizeof(init) || fgetc(file) != EOF) {
        fclose(file);
        die("normalized Gen3BattleInit has the wrong size");
    }
    fclose(file);
    if (memcmp(init.seed, input->seed, sizeof(init.seed)) != 0) {
        die("normalized Gen3BattleInit seed disagrees with shared case");
    }
    return init;
}

static void print_phase(const Gen3TracePhaseValue *phase) {
    printf("{\"kind\":%u,\"required_side_mask\":%u,"
           "\"forced_first_side\":%u,\"continuation\":%u}",
        phase->kind, phase->required_side_mask, phase->forced_first_side,
        phase->continuation);
}

static void print_events(const Observer *observer) {
    printf("[");
    for (size_t i = 0; i < observer->event_count; i++) {
        const Gen3BattleEvent *event = &observer->events[i];
        if (i != 0) printf(",");
        printf("{\"kind\":%u,\"side\":%u,\"status\":%u,\"amount\":%u,"
               "\"species_id\":%u,\"move_id\":%u,\"hp\":%u,\"max_hp\":%u}",
            event->kind, event->side, event->status, event->amount,
            event->species_id, event->move_id, event->hp, event->max_hp);
    }
    printf("]");
}

static void print_snapshot(const Gen3BattleSnapshot *snapshot) {
    printf("{\"turn\":%" PRIu32 ",\"seed\":[%u,%u,%u,%u],"
           "\"force_switch_side\":%d,\"spikes\":[%u,%u],"
           "\"resume_residuals\":%u,\"done\":%u,\"winner_side\":%d,"
           "\"pokemon\":[",
        snapshot->turn, snapshot->seed[0], snapshot->seed[1], snapshot->seed[2],
        snapshot->seed[3], snapshot->force_switch_side, snapshot->spikes[0],
        snapshot->spikes[1], snapshot->resume_residuals, snapshot->done,
        snapshot->winner_side);
    for (size_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (side != 0) printf(",");
        printf("[");
        for (size_t slot = 0; slot < GEN3_TEAM_SIZE; slot++) {
            const Gen3PokemonSnapshot *pokemon = &snapshot->pokemon[side][slot];
            if (slot != 0) printf(",");
            printf("{\"species_id\":%u,\"hp\":%u,\"max_hp\":%u,"
                   "\"pp\":[%u,%u,%u,%u],\"status\":%u,"
                   "\"protect_counter\":%u,\"toxic_counter\":%u,"
                   "\"leech_seeded\":%u,\"stat_stages\":[%d,%d,%d,%d,%d]}",
                pokemon->set.species_id, pokemon->hp, pokemon->set.stats[0],
                pokemon->pp[0], pokemon->pp[1], pokemon->pp[2], pokemon->pp[3],
                pokemon->status, pokemon->protect_counter, pokemon->toxic_counter,
                pokemon->leech_seeded, pokemon->stat_stages[0],
                pokemon->stat_stages[1], pokemon->stat_stages[2],
                pokemon->stat_stages[3], pokemon->stat_stages[4]);
        }
        printf("]");
    }
    printf("]}");
}

static Gen3TracePhaseValue expected_phase(const Gen3BattleSnapshot *snapshot) {
    Gen3TracePhaseValue phase = {0};
    if (snapshot->done) {
        phase.kind = 3; /* GEN3_PHASE_TERMINAL */
    } else if (snapshot->force_switch_side >= 0) {
        phase.kind = 1; /* GEN3_PHASE_FORCED_SWITCH_REQUEST */
        phase.required_side_mask =
            (uint8_t)(1u << (unsigned)snapshot->force_switch_side);
        phase.forced_first_side = (uint8_t)snapshot->force_switch_side;
        phase.continuation = snapshot->resume_residuals ? 1u : 0u;
    } else if (snapshot->force_switch_side <= -2) {
        phase.kind = 1;
        phase.required_side_mask = 3;
        phase.forced_first_side = (uint8_t)(-2 - snapshot->force_switch_side);
        phase.continuation = snapshot->resume_residuals ? 1u : 0u;
    } else {
        phase.kind = 0; /* GEN3_PHASE_NORMAL_REQUEST */
        phase.required_side_mask = 3;
    }
    return phase;
}

static void assert_trace_phase_matches_snapshot(
    const Gen3TracePhaseValue *actual, const Gen3BattleSnapshot *snapshot
) {
    Gen3TracePhaseValue expected = expected_phase(snapshot);
    if (memcmp(actual, &expected, sizeof(expected)) != 0) {
        die("trace phase disagrees with canonical snapshot request");
    }
}

static void emit_boundary(Observer *observer, const Gen3Battle *battle,
    const Gen3TraceRecord *record, const char *point) {
    Gen3BattleSnapshot snapshot;
    uint16_t legal[GEN3_SIDE_COUNT];
    if (gen3_battle_snapshot(battle, &snapshot) != GEN3_OK) die("snapshot failed");
    for (uint8_t side = 0; side < GEN3_SIDE_COUNT; side++) {
        if (gen3_battle_legal_actions(battle, side, &legal[side]) != GEN3_OK) {
            die("legal-action query failed");
        }
    }
    assert_trace_phase_matches_snapshot(&observer->phase, &snapshot);
    printf("{\"schema\":\"gen3-boundary-v1\",\"case_id\":\"%s\"," 
           "\"boundary\":%" PRIu32
           ",\"point\":\"%s\",\"phase\":",
        observer->case_id, record->boundary, point);
    print_phase(&observer->phase);
    printf(",\"legal_masks\":[%u,%u],\"state\":", legal[0], legal[1]);
    print_snapshot(&snapshot);
    printf(",\"events\":");
    print_events(observer);
    printf("}\n");
    observer->event_count = 0;
}

static void observe(void *context, const Gen3Battle *battle,
    const Gen3TraceRecord *record) {
    Observer *observer = context;
    if (record->kind == GEN3_TRACE_PHASE) {
        observer->phase = record->value.phase.after;
    } else if (record->kind == GEN3_TRACE_PROTOCOL) {
        if (observer->event_count == MAX_PROTOCOL_EVENTS) die("protocol overflow");
        observer->events[observer->event_count++] = record->value.protocol;
    } else if (record->kind == GEN3_TRACE_REQUEST && record->boundary != 0) {
        observer->phase = record->value.request.phase;
        emit_boundary(observer, battle, record, "request");
    }
}

int main(int argc, char **argv) {
    if (argc != 3) die("usage: native_boundary_driver CASE BATTLE_INIT");
    BoundaryCase input = load_case(argv[1]);
    Gen3BattleInit init = load_init(argv[2], &input);
    Gen3Battle *battle = NULL;
    char error[256];
    int rc = gen3_battle_create(&init, &battle, error, sizeof(error));
    if (rc != GEN3_OK) die(error[0] == '\0' ? "battle creation failed" : error);
    Observer observer = {.case_id = input.id};
    Gen3TraceSink sink = {
        .abi_version = GEN3_TRACE_ABI_VERSION,
        .struct_size = sizeof(sink),
        .context = &observer,
        .emit = observe,
    };
    if (gen3_battle_set_trace_sink(battle, &sink) != GEN3_OK) die("sink install failed");
    for (size_t i = 0; i < input.decision_count; i++) {
        rc = gen3_battle_turn(battle, input.decisions[i][0], input.decisions[i][1]);
        if (rc != GEN3_OK) {
            fprintf(stderr, "native-boundary-driver: decision %zu failed with %d\n", i, rc);
            gen3_battle_destroy(battle);
            return 3;
        }
    }
    gen3_battle_destroy(battle);
    return 0;
}
