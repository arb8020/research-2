#ifndef POKEMON_ACQUISITION_H
#define POKEMON_ACQUISITION_H

#include "pokemon_admission.h"

#include <stdint.h>

typedef enum {
    POKEMON_ACQUISITION_METHOD_MACHINE = UINT8_C(1) << 0,
    POKEMON_ACQUISITION_METHOD_TUTOR = UINT8_C(1) << 1,
    POKEMON_ACQUISITION_METHOD_EGG = UINT8_C(1) << 2,
    POKEMON_ACQUISITION_METHOD_RESTRICTED = UINT8_C(1) << 3,
    POKEMON_ACQUISITION_METHOD_LEVEL_UP_EGG = UINT8_C(1) << 4,
} PokemonAcquisitionMethodFlag;

typedef struct {
    uint32_t first_move_row;
    uint16_t move_row_count;
    uint16_t event_only_offset;
    uint16_t parent_species_id;
    uint16_t egg_group_mask;
    uint16_t ability_ids[2];
    uint8_t evolution_level;
    uint8_t fixed_gender;
    uint8_t can_hatch;
    uint8_t event_only_count;
} PokemonAcquisitionSpecies;

typedef struct {
    uint16_t move_id;
    uint32_t level_offset;
    uint32_t event_offset;
    uint8_t method_flags;
    uint8_t level_count;
    uint8_t event_count;
} PokemonAcquisitionMoveRow;

typedef struct {
    uint16_t species_id;
    uint16_t ability_id;
    uint8_t local_index;
    uint8_t level;
    uint8_t gender;
    uint8_t flags;
    uint8_t ability_slot; /* zero means unconstrained; otherwise slot + 1. */
    const char *nature_id;
    uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT]; /* 255 means unconstrained. */
    uint16_t moves[POKEMON_ADMISSION_MAX_MOVES];
    uint8_t move_count;
} PokemonAcquisitionEvent;

enum {
    POKEMON_ACQUISITION_EVENT_SHINY = UINT8_C(1) << 0,
    POKEMON_ACQUISITION_EVENT_EMERALD_EGG = UINT8_C(1) << 1,
    POKEMON_ACQUISITION_EVENT_SHINY_OPTIONAL = UINT8_C(1) << 2,
};

typedef struct PokemonAcquisitionData {
    uint64_t plugin_fingerprint;
    const PokemonAcquisitionSpecies *species;
    uint16_t species_count;
    const PokemonAcquisitionMoveRow *move_rows;
    uint32_t move_row_count;
    const uint16_t *move_source_ids; /* One entry per admission move identity. */
    uint16_t move_source_id_count;
    const uint8_t *move_sketchable;
    uint16_t move_sketchable_count;
    uint16_t sketch_move_id;
    uint16_t hidden_power_move_id;
    const uint8_t *levels;
    uint32_t level_count;
    const uint16_t *event_refs;
    uint32_t event_ref_count;
    const PokemonAcquisitionEvent *events;
    uint16_t event_count;
    const uint16_t *event_only_refs;
    uint16_t event_only_ref_count;
    const char *const *nature_ids;
    uint8_t nature_count;
    const char *const *hidden_power_type_ids;
    const uint8_t (*hidden_power_ivs)[POKEMON_ADMISSION_STAT_COUNT];
    uint8_t hidden_power_type_count;
    const uint8_t *move_hidden_power_type;
    uint8_t max_lineage_depth;
    uint8_t max_sources_per_move;
    uint16_t breeding_group_mask;
    uint16_t ditto_group_mask;
    uint16_t undiscovered_group_mask;
    uint16_t unrestricted_egg_group_mask;
} PokemonAcquisitionData;

uint8_t pokemon_acquisition_hidden_power_type(
    const PokemonAcquisitionData *data,
    const uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT]
);

typedef struct {
    uint8_t obtainable;
    uint8_t failing_move_index;
    uint8_t set_field_failure;
    /* One-based witness into events, or zero for a non-event source. */
    uint16_t event_id;
} PokemonAcquisitionDecision;

int pokemon_acquisition_validate(
    const PokemonAcquisitionData *data,
    const PokemonAdmissionUniverse *universe
);

PokemonAcquisitionDecision pokemon_acquisition_check(
    const PokemonAcquisitionData *data,
    const PokemonAdmissionUniverse *universe,
    const PokemonAdmissionFormatPolicy *policy,
    uint16_t species_id,
    const uint16_t moves[POKEMON_ADMISSION_MAX_MOVES],
    const PokemonAdmissionSetInput *input
);

#endif
