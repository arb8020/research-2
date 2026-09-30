#ifndef POKEMON_TEST_PLUGIN_H
#define POKEMON_TEST_PLUGIN_H

#include "pokemon.h"

#define POKEMON_TEST_PLUGIN_FINGERPRINT UINT64_C(0x54455354504c5547)

/* Rebinds an otherwise valid test fixture to a deliberately non-production
 * rules/data/format bundle.  This proves the kernel boundary; it is not a
 * claim about any real Pokemon generation. */
void pokemon_test_plugin_rebind(PokemonBattleInit *init);

#endif
