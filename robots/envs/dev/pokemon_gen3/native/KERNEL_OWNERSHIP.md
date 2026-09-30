# Kernel ownership split

`pokemon.c` remains the single translation-unit facade so this first split is
behavior preserving. Ordered implementation fragments expose navigation and
ownership without manufacturing a broad internal API around dependencies that
are not yet one-way.

| Fragment | Current owner |
|---|---|
| `catalog_choice.inc` | resolved plugin lookup, catalog validation, and normalized choice products |
| `condition_install.inc` | condition admission/installation and direct owner lifecycle primitives |
| `choice_queue.inc` | request projection, choice validation, action construction and ordering |
| `event.inc` | handler discovery, ordering, relay dispatch, and generated handler programs |
| `move.inc` | move invocation, targeting, hit/damage/effect pipeline, and child delegation |
| `switch.inc` | committed switch transition |
| `residual.inc` | residual work, delayed actions, and constructed residual hits |
| `bundle_validation.inc` | resolved generation-plugin coherence and capacity validation |
| `api.inc` | initialization, public step/request/view API, invariants, and rollback boundary |

The fragments deliberately preserve original function order and static
linkage. `#line` directives retain original assertion locations. Event,
condition, faint, move, and switch code still have cyclic implementation
dependencies; hiding those behind a giant `pokemon_internal.h` would make the
boundary look cleaner without making it truer.

Separate object files are a later earned refactor. Start with bundle validation
and introduce one internal declaration at a time only where dependency
direction is demonstrably one-way. Every extraction must retain public ABI and
layout, compare the preprocessed token stream where applicable, pass native and
randomized tests, and preserve the complete differential/replay corpus.
