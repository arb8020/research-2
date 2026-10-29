#pragma once

#include <stddef.h>

#include "pokemon.h"

/* Verifier-only compiled representation of one canonical JSON case. The
 * submitted battle runtime neither knows this type nor parses verifier data. */
typedef struct {
    const char *id;
    const char *source_file;
    const char *test_name;
    PokemonBattleInit init;
    const PokemonChoice (*choices)[POKEMON_SIDES];
    size_t choice_count;
} VerifyCase;
