#include "pokemon_acquisition.h"

#include <stddef.h>
#include <string.h>

static int canonical_id_or_empty(const char *id) {
    if (id == NULL) return 0;
    for (const unsigned char *p = (const unsigned char *)id; *p; p++) {
        if (!((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9'))) return 0;
    }
    return 1;
}

static int slice_valid(uint32_t first, uint32_t count, uint32_t total) {
    return first <= total && count <= total - first;
}

int pokemon_acquisition_validate(
    const PokemonAcquisitionData *data,
    const PokemonAdmissionUniverse *universe
) {
    if (data == NULL || universe == NULL || data->plugin_fingerprint == 0 ||
        data->plugin_fingerprint != universe->plugin_fingerprint ||
        data->species == NULL || data->species_count !=
            universe->identities[POKEMON_ADMISSION_SPECIES].count ||
        data->move_rows == NULL || data->move_row_count == 0 ||
        data->move_source_ids == NULL || data->move_source_id_count !=
            universe->identities[POKEMON_ADMISSION_MOVE].count ||
        data->move_sketchable == NULL || data->move_sketchable_count !=
            universe->identities[POKEMON_ADMISSION_MOVE].count ||
        data->sketch_move_id == 0 || data->sketch_move_id >
            universe->identities[POKEMON_ADMISSION_MOVE].count ||
        data->hidden_power_move_id == 0 || data->hidden_power_move_id >
            universe->identities[POKEMON_ADMISSION_MOVE].count ||
        data->levels == NULL || data->level_count == 0 ||
        data->event_refs == NULL || data->event_ref_count == 0 ||
        data->events == NULL || data->event_count == 0 ||
        data->event_only_refs == NULL || data->event_only_ref_count == 0 ||
        data->nature_ids == NULL || data->nature_count == 0 ||
        data->hidden_power_type_ids == NULL || data->hidden_power_ivs == NULL ||
        data->hidden_power_type_count != 16 || data->move_hidden_power_type == NULL ||
        data->max_lineage_depth == 0 || data->max_lineage_depth > 8 ||
        data->max_sources_per_move == 0 || data->max_sources_per_move > 32) return 0;

    const uint16_t move_count =
        universe->identities[POKEMON_ADMISSION_MOVE].count;
    for (uint16_t move = 0; move < data->move_source_id_count; move++) {
        if (data->move_source_ids[move] > move_count ||
            data->move_sketchable[move] > 1 ||
            data->move_hidden_power_type[move] > data->hidden_power_type_count) return 0;
    }
    for (uint8_t nature = 0; nature < data->nature_count; nature++) {
        if (!canonical_id_or_empty(data->nature_ids[nature]) ||
            !data->nature_ids[nature][0] ||
            (nature && strcmp(data->nature_ids[nature - 1],
                data->nature_ids[nature]) >= 0)) return 0;
    }
    for (uint8_t type = 0; type < data->hidden_power_type_count; type++) {
        if (!canonical_id_or_empty(data->hidden_power_type_ids[type]) ||
            !data->hidden_power_type_ids[type][0]) return 0;
        for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
            if (data->hidden_power_ivs[type][stat] > 31) return 0;
        }
    }
    for (uint16_t species = 0; species < data->species_count; species++) {
        const PokemonAcquisitionSpecies *row = &data->species[species];
        if (!slice_valid(row->first_move_row, row->move_row_count,
                data->move_row_count) ||
            !slice_valid(row->event_only_offset, row->event_only_count,
                data->event_only_ref_count) ||
            row->parent_species_id > data->species_count ||
            row->parent_species_id == species + 1 || row->fixed_gender > 3 ||
            row->can_hatch > 1) return 0;
        for (size_t slot = 0; slot < 2; slot++) {
            if (row->ability_ids[slot] >
                universe->identities[POKEMON_ADMISSION_ABILITY].count) return 0;
        }
        uint16_t previous_move = 0;
        for (uint32_t index = row->first_move_row;
             index < row->first_move_row + row->move_row_count; index++) {
            const PokemonAcquisitionMoveRow *move = &data->move_rows[index];
            const uint8_t known = POKEMON_ACQUISITION_METHOD_MACHINE |
                POKEMON_ACQUISITION_METHOD_TUTOR |
                POKEMON_ACQUISITION_METHOD_EGG |
                POKEMON_ACQUISITION_METHOD_RESTRICTED |
                POKEMON_ACQUISITION_METHOD_LEVEL_UP_EGG;
            if (move->move_id == 0 || move->move_id > move_count ||
                move->move_id <= previous_move ||
                (move->method_flags & (uint8_t)~known) ||
                !slice_valid(move->level_offset, move->level_count,
                    data->level_count) ||
                !slice_valid(move->event_offset, move->event_count,
                    data->event_ref_count)) return 0;
            uint32_t alternatives = move->level_count + move->event_count;
            for (uint8_t bit = 1; bit <= POKEMON_ACQUISITION_METHOD_LEVEL_UP_EGG;
                 bit <<= 1) alternatives += !!(move->method_flags & bit);
            if (alternatives == 0 || alternatives > data->max_sources_per_move) return 0;
            for (uint8_t i = 0; i < move->level_count; i++) {
                uint8_t level = data->levels[move->level_offset + i];
                if (level == 0 || level > 100 ||
                    (i && data->levels[move->level_offset + i - 1] >= level)) return 0;
            }
            for (uint8_t i = 0; i < move->event_count; i++) {
                uint16_t event = data->event_refs[move->event_offset + i];
                if (event == 0 || event > data->event_count ||
                    (i && data->event_refs[move->event_offset + i - 1] >= event)) return 0;
            }
            previous_move = move->move_id;
        }
        for (uint8_t i = 0; i < row->event_only_count; i++) {
            uint16_t event = data->event_only_refs[row->event_only_offset + i];
            if (event == 0 || event > data->event_count ||
                (i && data->event_only_refs[row->event_only_offset + i - 1] >= event)) return 0;
        }
        uint16_t cursor = (uint16_t)(species + 1);
        uint8_t depth = 0;
        while (cursor != 0) {
            if (++depth > data->max_lineage_depth) return 0;
            cursor = data->species[cursor - 1].parent_species_id;
        }
    }
    for (uint16_t event_index = 0; event_index < data->event_count; event_index++) {
        const PokemonAcquisitionEvent *event = &data->events[event_index];
        if (event->species_id == 0 || event->species_id > data->species_count ||
            event->ability_id > universe->identities[POKEMON_ADMISSION_ABILITY].count ||
            event->level > 100 || event->gender > 2 ||
            (event->flags & (uint8_t)~(POKEMON_ACQUISITION_EVENT_SHINY |
                POKEMON_ACQUISITION_EVENT_EMERALD_EGG |
                POKEMON_ACQUISITION_EVENT_SHINY_OPTIONAL)) ||
            ((event->flags & POKEMON_ACQUISITION_EVENT_SHINY) &&
                (event->flags & POKEMON_ACQUISITION_EVENT_SHINY_OPTIONAL)) ||
            !canonical_id_or_empty(event->nature_id) ||
            event->ability_slot > 2 ||
            event->move_count > POKEMON_ADMISSION_MAX_MOVES) return 0;
        for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT; stat++) {
            if (event->ivs[stat] > 31 && event->ivs[stat] != 255) return 0;
        }
        for (uint8_t move = 0; move < POKEMON_ADMISSION_MAX_MOVES; move++) {
            if ((move < event->move_count &&
                    (event->moves[move] == 0 || event->moves[move] > move_count)) ||
                (move >= event->move_count && event->moves[move] != 0)) return 0;
        }
        for (uint16_t prior = 0; prior < event_index; prior++) {
            if (data->events[prior].species_id == event->species_id &&
                data->events[prior].local_index == event->local_index) return 0;
        }
    }
    return 1;
}

uint8_t pokemon_acquisition_hidden_power_type(
    const PokemonAcquisitionData *data,
    const uint8_t ivs[POKEMON_ADMISSION_STAT_COUNT]
) {
    uint8_t parity = (ivs[POKEMON_ADMISSION_STAT_HP] & 1) |
        ((ivs[POKEMON_ADMISSION_STAT_ATK] & 1) << 1) |
        ((ivs[POKEMON_ADMISSION_STAT_DEF] & 1) << 2) |
        ((ivs[POKEMON_ADMISSION_STAT_SPE] & 1) << 3) |
        ((ivs[POKEMON_ADMISSION_STAT_SPA] & 1) << 4) |
        ((ivs[POKEMON_ADMISSION_STAT_SPD] & 1) << 5);
    return (uint8_t)((parity * (data->hidden_power_type_count - 1)) / 63 + 1);
}

static const PokemonAcquisitionMoveRow *find_move_row(
    const PokemonAcquisitionData *data,
    uint16_t species_id,
    uint16_t move_id
) {
    const PokemonAcquisitionSpecies *species = &data->species[species_id - 1];
    size_t lo = species->first_move_row;
    size_t hi = lo + species->move_row_count;
    while (lo < hi) {
        size_t mid = lo + (hi - lo) / 2;
        if (data->move_rows[mid].move_id < move_id) lo = mid + 1;
        else hi = mid;
    }
    if (lo < species->first_move_row + species->move_row_count &&
        data->move_rows[lo].move_id == move_id) return &data->move_rows[lo];
    return NULL;
}

static void learn_sources(
    const PokemonAcquisitionData *data,
    uint16_t species_id,
    uint16_t move_id,
    uint8_t level,
    int *non_egg,
    int *egg
) {
    uint16_t cursor = species_id;
    while (cursor != 0) {
        const PokemonAcquisitionMoveRow *row = find_move_row(data, cursor, move_id);
        if (row != NULL) {
            *non_egg |= !!(row->method_flags & (
                POKEMON_ACQUISITION_METHOD_MACHINE |
                POKEMON_ACQUISITION_METHOD_TUTOR |
                POKEMON_ACQUISITION_METHOD_RESTRICTED));
            *egg |= !!(row->method_flags & POKEMON_ACQUISITION_METHOD_EGG);
            for (uint8_t i = 0; i < row->level_count; i++) {
                *non_egg |= level >= data->levels[row->level_offset + i];
            }
        }
        cursor = data->species[cursor - 1].parent_species_id;
    }
}

static int egg_combo_possible(
    const PokemonAcquisitionData *data,
    uint16_t child_species_id,
    const uint16_t moves[POKEMON_ADMISSION_MAX_MOVES],
    uint8_t move_count,
    uint8_t depth
) {
    uint16_t hatch_species = child_species_id;
    while (data->species[hatch_species - 1].parent_species_id != 0) {
        hatch_species = data->species[hatch_species - 1].parent_species_id;
    }
    const PokemonAcquisitionSpecies *child = &data->species[hatch_species - 1];
    uint16_t child_groups = child->egg_group_mask & data->breeding_group_mask;
    if (!child->can_hatch || child_groups == 0) return 0;
    if (child_groups & data->unrestricted_egg_group_mask) return 1;
    for (uint16_t father_id = 1; father_id <= data->species_count; father_id++) {
        const PokemonAcquisitionSpecies *father = &data->species[father_id - 1];
        if (father->fixed_gender == POKEMON_ACQUISITION_GENDER_FEMALE ||
            father->fixed_gender == POKEMON_ACQUISITION_GENDER_NEUTER ||
            father_id == hatch_species ||
            !(father->egg_group_mask & child_groups & data->breeding_group_mask)) continue;
        uint16_t inherited[POKEMON_ADMISSION_MAX_MOVES] = {0};
        uint8_t inherited_count = 0;
        int possible = 1;
        for (uint8_t move = 0; move < move_count; move++) {
            int non_egg = 0, egg = 0;
            learn_sources(data, father_id, moves[move], 100, &non_egg, &egg);
            if (non_egg) continue;
            if (!egg) { possible = 0; break; }
            inherited[inherited_count++] = moves[move];
        }
        if (!possible) continue;
        if (inherited_count <= 1) return 1;
        if (depth == 0 && egg_combo_possible(
                data, father_id, inherited, inherited_count, 1)) return 1;
    }
    return 0;
}

static int event_matches(
    const PokemonAcquisitionData *data,
    const PokemonAdmissionUniverse *universe,
    uint16_t species_id,
    const PokemonAdmissionSetInput *input,
    uint16_t event_id,
    int underlevel
) {
    const PokemonAcquisitionEvent *event = &data->events[event_id - 1];
    const char *nature = input->nature_id && input->nature_id[0] ?
        input->nature_id : "serious";
    PokemonAcquisitionGender gender = input->gender;
    uint8_t fixed = data->species[species_id - 1].fixed_gender;
    if (fixed) gender = (PokemonAcquisitionGender)fixed;
    int shiny_legal = (event->flags & POKEMON_ACQUISITION_EVENT_SHINY_OPTIONAL) ||
        (!!(event->flags & POKEMON_ACQUISITION_EVENT_SHINY) == !!input->shiny);
    int legal = input->level >= event->level &&
        (!underlevel || event->species_id == species_id) &&
        (!event->gender || !gender || event->gender == gender) && shiny_legal &&
        (!event->nature_id[0] || strcmp(event->nature_id, nature) == 0);
    if (legal && event->ability_id && event->species_id == species_id) {
        legal = strcmp(input->ability_id,
            universe->identities[POKEMON_ADMISSION_ABILITY]
                .values[event->ability_id - 1].id) == 0;
    } else if (legal && event->ability_slot) {
        const PokemonAcquisitionSpecies *species = &data->species[species_id - 1];
        uint16_t expected = species->ability_ids[event->ability_slot - 1];
        if (!expected) expected = species->ability_ids[0];
        legal = expected && strcmp(input->ability_id,
            universe->identities[POKEMON_ADMISSION_ABILITY].values[expected - 1].id) == 0;
    }
    for (size_t stat = 0; stat < POKEMON_ADMISSION_STAT_COUNT && legal; stat++) {
        uint8_t iv = input->has_ivs ? input->ivs[stat] : 31;
        legal &= event->ivs[stat] == 255 || event->ivs[stat] == iv;
    }
    return legal;
}

PokemonAcquisitionDecision pokemon_acquisition_check(
    const PokemonAcquisitionData *data,
    const PokemonAdmissionUniverse *universe,
    const PokemonAdmissionFormatPolicy *policy,
    uint16_t species_id,
    const uint16_t moves[POKEMON_ADMISSION_MAX_MOVES],
    const PokemonAdmissionSetInput *input
) {
    typedef struct {
        uint8_t unrestricted;
        uint8_t restricted;
        uint8_t explicit_egg;
        uint8_t level_egg;
        uint8_t pomeg_egg;
        uint16_t events[32];
        uint8_t event_count;
    } MoveOptions;
    typedef struct {
        uint8_t origin; /* 0 unrestricted, 1 egg, 2 event */
        uint16_t event_id;
        uint16_t restricted_move;
        uint16_t egg_moves[POKEMON_ADMISSION_MAX_MOVES];
        uint8_t egg_move_count;
        uint8_t egg_requires_father;
        uint8_t pomeg_egg;
    } SearchState;

    if (data == NULL || universe == NULL || policy == NULL || input == NULL || species_id == 0 ||
        species_id > data->species_count) {
        PokemonAcquisitionDecision invalid = {0, 0, 0, 0};
        return invalid;
    }

    MoveOptions options[POKEMON_ADMISSION_MAX_MOVES] = {{0}};
    uint16_t source_moves[POKEMON_ADMISSION_MAX_MOVES] = {0};
    int sketch_unrestricted = 0;
    uint16_t sketch_cursor = species_id;
    while (sketch_cursor != 0) {
        const PokemonAcquisitionSpecies *species = &data->species[sketch_cursor - 1];
        for (uint32_t row_index = species->first_move_row;
             row_index < species->first_move_row + species->move_row_count; row_index++) {
            const PokemonAcquisitionMoveRow *row = &data->move_rows[row_index];
            if (row->move_id != data->sketch_move_id) continue;
            if (row->method_flags & (POKEMON_ACQUISITION_METHOD_MACHINE |
                    POKEMON_ACQUISITION_METHOD_TUTOR)) sketch_unrestricted = 1;
            for (uint8_t level = 0; level < row->level_count; level++) {
                if (input->level >= data->levels[row->level_offset + level]) {
                    sketch_unrestricted = 1;
                }
            }
        }
        sketch_cursor = species->parent_species_id;
    }
    for (uint8_t input_move = 0; input_move < input->move_count; input_move++) {
        uint16_t source_move = moves[input_move] == 0 ? 0 :
            data->move_source_ids[moves[input_move] - 1];
        source_moves[input_move] = source_move;
        if (source_move == 0) {
            PokemonAcquisitionDecision missing = {0, input_move, 0, 0};
            return missing;
        }
        uint16_t cursor = species_id;
        while (cursor != 0) {
            const PokemonAcquisitionSpecies *species = &data->species[cursor - 1];
            size_t lo = species->first_move_row;
            size_t hi = lo + species->move_row_count;
            while (lo < hi) {
                size_t mid = lo + (hi - lo) / 2;
                const PokemonAcquisitionMoveRow *row = &data->move_rows[mid];
                if (row->move_id < source_move) lo = mid + 1;
                else hi = mid;
            }
            if (lo < species->first_move_row + species->move_row_count &&
                data->move_rows[lo].move_id == source_move) {
                const PokemonAcquisitionMoveRow *row = &data->move_rows[lo];
                if (row->method_flags & (POKEMON_ACQUISITION_METHOD_MACHINE |
                        POKEMON_ACQUISITION_METHOD_TUTOR)) options[input_move].unrestricted = 1;
                if (row->method_flags & POKEMON_ACQUISITION_METHOD_RESTRICTED) {
                    options[input_move].restricted = 1;
                }
                if (row->method_flags & POKEMON_ACQUISITION_METHOD_EGG) {
                    options[input_move].explicit_egg = 1;
                }
                for (uint8_t level = 0; level < row->level_count; level++) {
                    if (input->level >= data->levels[row->level_offset + level]) {
                        options[input_move].unrestricted = 1;
                    } else {
                        if (policy->level_up_policy ==
                                POKEMON_ACQUISITION_LEVEL_UP_GEN3_POMEG &&
                            input->level >= policy->pomeg_minimum_level &&
                            species->can_hatch) {
                            options[input_move].pomeg_egg = 1;
                        }
                        if (row->method_flags &
                            POKEMON_ACQUISITION_METHOD_LEVEL_UP_EGG) {
                        /* The generated descriptor says this higher-level move
                         * can become an Eany acquisition source. */
                            options[input_move].level_egg = 1;
                        }
                    }
                }
                for (uint8_t event = 0; event < row->event_count; event++) {
                    uint16_t event_id = data->event_refs[row->event_offset + event];
                    int seen = 0;
                    for (uint8_t prior = 0; prior < options[input_move].event_count; prior++) {
                        seen |= options[input_move].events[prior] == event_id;
                    }
                    if (!seen && options[input_move].event_count < 32) {
                        options[input_move].events[options[input_move].event_count++] = event_id;
                    }
                }
            }
            cursor = species->parent_species_id;
        }
        if (sketch_unrestricted && data->move_sketchable[moves[input_move] - 1]) {
            options[input_move].unrestricted = 1;
        }
        if (!options[input_move].unrestricted && !options[input_move].restricted &&
            !options[input_move].explicit_egg && !options[input_move].level_egg &&
            !options[input_move].pomeg_egg &&
            options[input_move].event_count == 0) {
            PokemonAcquisitionDecision missing = {0, input_move, 0, 0};
            return missing;
        }
    }

    /* The bounded search is iterative over at most four domains. Each partial
     * state is unique by origin/restricted/egg product; 128 is generator-
     * independent and exceeds the 4 * (1 + 1 + 1 + 32) reachable products. */
    SearchState frontier[128] = {{0}};
    size_t frontier_count = 1;
    for (uint8_t move_index = 0; move_index < input->move_count; move_index++) {
        SearchState next[128];
        size_t next_count = 0;
#define PUSH_ALTERNATIVE(kind, event_value, restricted_value, add_egg, require_father) do { \
    for (size_t state_index = 0; state_index < frontier_count; state_index++) { \
        SearchState candidate = frontier[state_index]; \
        uint8_t requested_origin = (kind); \
        if (candidate.origin && requested_origin && candidate.origin != requested_origin) continue; \
        if (requested_origin == 2 && candidate.origin == 2 && \
            candidate.event_id != (event_value)) continue; \
        if (!candidate.origin) { candidate.origin = requested_origin; candidate.event_id = (event_value); } \
        if ((restricted_value) && candidate.restricted_move && \
            candidate.restricted_move != moves[move_index]) continue; \
        if (restricted_value) candidate.restricted_move = moves[move_index]; \
        if (add_egg) { \
            candidate.egg_moves[candidate.egg_move_count++] = source_moves[move_index]; \
            candidate.egg_requires_father |= (require_father); \
        } \
        int duplicate = 0; \
        for (size_t prior = 0; prior < next_count; prior++) { \
            duplicate |= memcmp(&next[prior], &candidate, sizeof candidate) == 0; \
        } \
        if (!duplicate && next_count < sizeof next / sizeof next[0]) next[next_count++] = candidate; \
    } \
} while (0)
        if (options[move_index].unrestricted) PUSH_ALTERNATIVE(0, 0, 0, 0, 0);
        if (options[move_index].restricted) PUSH_ALTERNATIVE(0, 0, 1, 0, 0);
        if (options[move_index].explicit_egg) PUSH_ALTERNATIVE(1, 0, 0, 1, 0);
        if (options[move_index].level_egg) PUSH_ALTERNATIVE(1, 0, 0, 1, 1);
        if (options[move_index].pomeg_egg) {
            for (size_t state_index = 0; state_index < frontier_count; state_index++) {
                SearchState candidate = frontier[state_index];
                if (candidate.origin == 2 &&
                    !(data->events[candidate.event_id - 1].flags &
                        POKEMON_ACQUISITION_EVENT_EMERALD_EGG)) continue;
                candidate.pomeg_egg = 1;
                int duplicate = 0;
                for (size_t prior = 0; prior < next_count; prior++) {
                    duplicate |= memcmp(&next[prior], &candidate,
                        sizeof candidate) == 0;
                }
                if (!duplicate && next_count < sizeof next / sizeof next[0]) {
                    next[next_count++] = candidate;
                }
            }
        }
        for (uint8_t event = 0; event < options[move_index].event_count; event++) {
            uint16_t event_id = options[move_index].events[event];
            for (size_t state_index = 0; state_index < frontier_count; state_index++) {
                SearchState candidate = frontier[state_index];
                if (candidate.pomeg_egg &&
                    !(data->events[event_id - 1].flags &
                        POKEMON_ACQUISITION_EVENT_EMERALD_EGG)) continue;
                if (candidate.origin && candidate.origin != 2) continue;
                if (candidate.origin == 2 && candidate.event_id != event_id) continue;
                candidate.origin = 2;
                candidate.event_id = event_id;
                int duplicate = 0;
                for (size_t prior = 0; prior < next_count; prior++) {
                    duplicate |= memcmp(&next[prior], &candidate,
                        sizeof candidate) == 0;
                }
                if (!duplicate && next_count < sizeof next / sizeof next[0]) {
                    next[next_count++] = candidate;
                }
            }
        }
#undef PUSH_ALTERNATIVE
        if (next_count == 0) {
            PokemonAcquisitionDecision incompatible = {0, move_index, 0, 0};
            return incompatible;
        }
        memcpy(frontier, next, next_count * sizeof next[0]);
        frontier_count = next_count;
    }

    uint8_t evolution_level = 0;
    for (uint16_t cursor = species_id; cursor != 0;
         cursor = data->species[cursor - 1].parent_species_id) {
        if (data->species[cursor - 1].evolution_level > evolution_level) {
            evolution_level = data->species[cursor - 1].evolution_level;
        }
    }
    const int underlevel = evolution_level != 0 && input->level < evolution_level;
    const PokemonAcquisitionSpecies *requested_species = &data->species[species_id - 1];
    for (size_t state_index = 0; state_index < frontier_count; state_index++) {
        const SearchState *state = &frontier[state_index];
        if (requested_species->event_only_count) {
            for (uint8_t event_index = 0;
                 event_index < requested_species->event_only_count; event_index++) {
                uint16_t event_id = data->event_only_refs[
                    requested_species->event_only_offset + event_index];
                if (state->origin == 1 ||
                    (state->origin == 2 && state->event_id != event_id)) continue;
                if (event_matches(data, universe, species_id, input, event_id, underlevel)) {
                    PokemonAcquisitionDecision accepted = {1, 0, 0, event_id};
                    return accepted;
                }
            }
            continue;
        }
        if (state->origin == 0 && !underlevel) {
            PokemonAcquisitionDecision legal = {1, 0, 0, 0};
            return legal;
        }
        if (state->origin == 2 && (!state->pomeg_egg ||
                (data->events[state->event_id - 1].flags &
                    POKEMON_ACQUISITION_EVENT_EMERALD_EGG))) {
            if (event_matches(data, universe, species_id, input, state->event_id, underlevel)) {
                PokemonAcquisitionDecision accepted = {1, 0, 0, state->event_id};
                return accepted;
            }
        }
        if (state->origin == 1 && !underlevel && input->level >= 5 &&
            (state->egg_move_count <= 1 && !state->egg_requires_father ? 1 :
                egg_combo_possible(data, species_id, state->egg_moves,
                    state->egg_move_count, 0))) {
            PokemonAcquisitionDecision accepted = {1, 0, 0, 0};
            return accepted;
        }
    }
    PokemonAcquisitionDecision rejected = {0,
        input->move_count ? (uint8_t)(input->move_count - 1) : 0,
        (uint8_t)(underlevel || requested_species->event_only_count != 0), 0};
    return rejected;
}
