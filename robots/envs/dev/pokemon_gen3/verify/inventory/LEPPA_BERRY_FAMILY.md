# Gen 3 Leppa Berry family

The pinned Gen 3 mod inherits Leppa Berry from `data/items.ts`. Its `Update`
callback consumes the held berry when any live move slot has exactly zero PP.
Its `Eat` callback then rescans slots in declaration order, selects the first
zero-PP slot or otherwise the first depleted slot, and restores ten PP capped
at the generated maximum. Gen 3 has no reachable Ripen modifier and Leppa
owns no PRNG.

Generated data binds Leppa to two ordinary item handlers. The generic kernel
provides a zero-PP predicate, the existing eat-item transaction, and stable
first-eligible PP restoration. Item identity, amount, callback order, and
bindings remain in the resolved generation plugin; the kernel contains no
Leppa branch and needs no extra state capacity.

Focused evidence is
`native/test_pokemon.c#test_leppa_berry_pp_transaction`. The legal differential
cases `leppa-exact-ten-nonfirst` and
`leppa-delayed-acquisition-first-zero` prove post-deduction activation, exact
restoration, clamping, stable selection, and immediate Update after item
acquisition against Pokémon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
