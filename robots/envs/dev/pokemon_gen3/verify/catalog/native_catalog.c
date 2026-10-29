#include "gen3_slice_data.h"

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>

static void json_string(const char *value) {
    putchar('"');
    for (; *value != '\0'; value++) {
        const unsigned char byte = (unsigned char)*value;
        if (byte == '"' || byte == '\\') putchar('\\');
        if (byte < 0x20) {
            printf("\\u%04x", byte);
        } else {
            putchar(byte);
        }
    }
    putchar('"');
}

static uint16_t calculated_stat(
    const PokemonSpeciesIdentity *species, size_t stat, uint8_t level,
    uint8_t iv, uint16_t ev
) {
    if (stat == 0 && species->max_hp_override != 0) {
        return species->max_hp_override;
    }
    const uint32_t effort = ev / 4;
    const uint32_t base = species->base_stats[stat];
    if (stat == 0) {
        return (uint16_t)(((2 * base + iv + effort + 100) * level) / 100 + 10);
    }
    return (uint16_t)(((2 * base + iv + effort) * level) / 100 + 5);
}

static void print_stat_vector(
    const PokemonSpeciesIdentity *species, uint8_t level, uint8_t iv, uint16_t ev
) {
    putchar('[');
    for (size_t stat = 0; stat < 6; stat++) {
        if (stat != 0) putchar(',');
        printf("%u", calculated_stat(species, stat, level, iv, ev));
    }
    putchar(']');
}

static void print_species(const PokemonSpeciesIdentity *value) {
    printf("{\"kind\":\"species\",\"catalog_id\":%u,\"source_num\":%u,"
           "\"executable_id\":%u,\"id\":", value->catalog_id,
           value->source_num, value->executable_id);
    json_string(value->id);
    fputs(",\"name\":", stdout);
    json_string(value->name);
    fputs(",\"tier\":", stdout);
    json_string(value->tier);
    fputs(",\"types\":[", stdout);
    for (size_t type = 0; type < value->type_count; type++) {
        if (type != 0) putchar(',');
        printf("%u", value->types[type]);
    }
    fputs("],\"base_stats\":[", stdout);
    for (size_t stat = 0; stat < 6; stat++) {
        if (stat != 0) putchar(',');
        printf("%u", value->base_stats[stat]);
    }
    printf("],\"max_hp_override\":%u,\"stat_vectors\":[",
           value->max_hp_override);
    print_stat_vector(value, 1, 0, 0);
    putchar(',');
    print_stat_vector(value, 50, 31, 0);
    putchar(',');
    print_stat_vector(value, 100, 31, 252);
    puts("]}");
}

static void print_move(const PokemonMoveIdentity *value) {
    printf("{\"kind\":\"move\",\"catalog_id\":%u,\"source_num\":%u,"
           "\"executable_id\":%u,\"id\":", value->catalog_id,
           value->source_num, value->executable_id);
    json_string(value->id);
    fputs(",\"name\":", stdout);
    json_string(value->name);
    printf(",\"type\":%u,\"category\":%u,\"base_power\":%u,"
           "\"accuracy\":%u,\"always_hits\":%u,\"priority\":%d,"
           "\"pp\":%u,\"max_pp\":[%u,%u,%u,%u],\"target\":%u,"
           "\"flags\":\"%" PRIu64 "\"}\n",
           value->type, value->category, value->base_power,
           value->accuracy.kind == POKEMON_ACCURACY_ALWAYS ? 0 :
               value->accuracy.percent,
           value->accuracy.kind == POKEMON_ACCURACY_ALWAYS,
           value->priority, value->pp,
           value->pp, value->pp * 6 / 5, value->pp * 7 / 5,
           value->pp * 8 / 5, value->target, value->flags);
}

static void print_named(const char *kind, const PokemonNamedIdentity *value) {
    printf("{\"kind\":\"");
    fputs(kind, stdout);
    printf("\",\"catalog_id\":%u,\"source_num\":%u,\"executable_id\":%u,"
           "\"id\":", value->catalog_id, value->source_num,
           value->executable_id);
    json_string(value->id);
    fputs(",\"name\":", stdout);
    json_string(value->name);
    puts("}");
}

int main(void) {
    const PokemonData *data = &POKEMON_GEN3_SLICE_DATA;
    for (size_t i = 0; i < data->species_catalog_count; i++) {
        print_species(&data->species_catalog[i]);
    }
    for (size_t i = 0; i < data->move_catalog_count; i++) {
        print_move(&data->move_catalog[i]);
    }
    for (size_t i = 0; i < data->ability_catalog_count; i++) {
        print_named("ability", &data->ability_catalog[i]);
    }
    for (size_t i = 0; i < data->item_catalog_count; i++) {
        print_named("item", &data->item_catalog[i]);
    }
    return 0;
}
