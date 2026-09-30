# Gen 3 Shell Bell family

Pinned Gen 3 Showdown implements Shell Bell in `data/items.ts` as an
item-owned `AfterMoveSecondarySelf` handler with priority -1. It reads the
completed move's `totalDamage`, skips zero damage, and heals the holder by
one eighth of that damage with a minimum of one. `totalDamage` is actual HP
removed from opposing Pokemon: overkill is capped, multihit damage is summed,
and damage absorbed by Substitute is excluded.

The native kernel keeps that aggregate on the bounded active-move frame and
dispatches the ordinary ordered event after the move body completes. The
generated Shell Bell program applies a generic fraction-of-move-damage heal;
neither the item ID nor move IDs appear in generic control flow. Recoil has
already resolved at this boundary, so a holder which fainted from recoil is
not revived. Showdown's additional `!forceSwitchFlag` guard is pinned by the
generator. It cannot coincide with positive move damage in Gen 3: the only
forced-switch moves are the zero-damage Roar and Whirlwind, so the native
bundle requires no otherwise-dead mutable flag. The operation owns no PRNG.

Focused evidence is
`native/test_pokemon.c#test_shell_bell_actual_move_damage_transaction`. It
proves single-hit and multihit aggregation, Substitute exclusion, overkill
capping, full-HP behavior, and recoil-before-heal ordering. Legal differential
cases `shell-bell-single-hit`, `shell-bell-multihit-aggregate`,
`shell-bell-overkill-cap`, and `shell-bell-substitute-zero` prove the same
observable state and handler boundary against Pokemon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
