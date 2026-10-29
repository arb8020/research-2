# Gen 3 Wonder Guard family

The pinned Gen 3 Dex inherits Wonder Guard's effective callback from
`data/mods/gen4/abilities.ts`. It bypasses self-targeted moves, status moves,
and active typeless moves; every other hit is admitted only when its type is
super-effective against the current target. Gen 3 Struggle therefore bypasses
through the inherited active-move type mutation to `???`, not through a
Struggle-specific branch.

Native data supplies one target-owned TryHit program and the existing
fail-Role-Play ability capability. The generic interpreter supplies category
and type masks plus a target-effectiveness requirement on the neutral=4 type
product scale. The kernel contains no Wonder Guard or Shedinja identity check.
This work also makes self-targeted status actions traverse target-owned TryHit
discovery; generated predicates, rather than target topology, decide whether a
handler applies.

Focused evidence is
`native/test_pokemon.c#test_wonder_guard_generic_effectiveness_gate`.
`wonder-guard-effectiveness` and `wonder-guard-bypass-and-order` cover neutral
rejection, super-effective admission, status and typeless bypass, Protect
ordering, natural type immunity, labeled PRNG staging, and Role Play rejection.
They add eight exact pinned-Showdown boundaries.
