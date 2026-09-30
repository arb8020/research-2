#include "pokemon.h"


#include <assert.h>
#include <limits.h>
#include <string.h>

#include "pokemon_kernel/prng.h"

/* A singles step may contain two complete five-hit actions. Each action owns
 * one plan and one result record in addition to its per-hit records. */
_Static_assert(POKEMON_HIT_TRACE_CAPACITY >= 2u * (5u + 2u),
    "hit trace capacity must hold the maximum singles step");
_Static_assert(POKEMON_DRAW_CAPACITY >= 27u,
    "draw capacity must hold two five-hit actions and turn framing");
_Static_assert(POKEMON_DAMAGE_FORMULA_TRACE_CAPACITY >= 2u,
    "damage formula trace capacity must hold both singles actions");

/*
 * The kernel remains one translation unit. These ordered implementation
 * fragments expose ownership boundaries without changing linkage, function
 * order, or the public ABI.
 */
#include "pokemon_kernel/catalog_choice.inc"
#include "pokemon_kernel/condition_install.inc"
#include "pokemon_kernel/choice_queue.inc"
#include "pokemon_kernel/event.inc"
#include "pokemon_kernel/move.inc"
#include "pokemon_kernel/switch.inc"
#include "pokemon_kernel/residual.inc"
#include "pokemon_kernel/bundle_validation.inc"
#include "pokemon_kernel/api.inc"
