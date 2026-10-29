# Passive held-item identity closure

Oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This family covers identity only. It is the intersection of the frozen legal
Gen 3 OU item inventory with the recursively resolved `Dex.forGen(3)` items
whose effective `on*` callback set is empty, excluding Quick Claw because its
Gen 3 turn-speed policy is supported separately.

The exact closure is Master, Ultra, Great, Poke, Net, Dive, Nest, Repeat,
Timer, Luxury, Premier, and Friend Ball; Sun, Moon, Fire, Thunder, Water, and
Leaf Stone; Root, Claw, Helix, and Dome Fossil; Old Amber; Dragon Scale; and
Up-Grade. Unobtainable callback-free items are outside the frozen legal
inventory and are not included.

Authoritative boundaries are `data/items.ts`, `data/mods/gen3/items.ts`, and
the recursive mod resolution in `sim/dex.ts`. Generic item exchange is defined
by Trick in `data/moves.ts` and executed by `sim/battle-actions.ts`.

Native integration appends 25 zero-handler `PokemonItemData` rows and maps the
existing catalog identities to their Showdown numeric IDs. It adds no branch
to `pokemon.c`. `native/test_pokemon.c#test_trick_item_swap_family` proves that
every identity swaps through the existing transaction with fresh holder
generation and effect-order state. The `passive-item-*` legal differential
cases prove initial and post-Trick canonical state and exact PRNG staging.

The descriptors are classified `inert`, not `implemented`: the claim is that
their identity participates correctly in generic item operations, not that an
absent callback has been replaced with behavior.
