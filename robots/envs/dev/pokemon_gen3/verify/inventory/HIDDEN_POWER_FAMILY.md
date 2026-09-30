# Hidden Power and personal move construction

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Hidden Power is the first witness for a reusable per-Pokemon move-construction
boundary. It is not resolved by a move-ID branch in the battle kernel.

## Showdown control flow

- `sim/teams.ts` imports explicit IVs and normalizes typed Hidden Power names.
- `sim/team-validator.ts` validates the requested type against the set IVs.
- `sim/pokemon.ts` derives `hpType` and `hpPower` during Pokemon construction.
- `sim/dex.ts` owns the generation formula.
- `data/mods/gen3/moves.ts` applies the derived type and Gen 3 category in the
  move-local `onModifyMove`; inherited base-power construction reads
  `hpPower`.
- `data/mods/gen3/scripts.ts` dispatches `ModifyMove`, not a separate
  `ModifyType` phase. The flattened `onModifyType` record is therefore
  unreachable in Gen 3 OU execution.

The IV bit order is HP, Attack, Defense, Speed, Special Attack, Special
Defense. Type uses the low bit of each IV; power uses the next bit and ranges
from 30 through 70. Gen 3 category follows the type split.

## Native boundary

`PokemonSet` retains normalized IVs as immutable set data. At battle
construction, the resolved generation plugin derives one bounded
`PokemonPersonalMoveProfile {kind, type, category, power}`. Generated move data
selects the opaque profile kind. A move-owned `ModifyMove` program applies its
type and category to the active move frame; the generic base-power stage reads
its power. Type immunity, accuracy, critical hit, damage roll, STAB,
effectiveness, items, and abilities then use the ordinary pipeline.

This division keeps the formula and physical/special split generation-owned,
keeps the kernel free of Hidden Power IDs, and gives eventual Transform-like
overlays a visible mutable profile boundary.

## Evidence

Focused native vectors prove Fighting/Dark 30/70 endpoints, Ground and
Electric mixed-bit construction, category selection, default-IV
normalization, invalid-IV atomic rejection, generated handler dispatch, type
immunity, and exact early-exit PRNG staging.

Six legal differential fixtures prove:

- Dark 70 special construction and Psychic effectiveness;
- Dark 30 minimum power;
- Ground 70 physical construction, STAB, and fourfold effectiveness;
- Counter accepts Hidden Power through its Gen 3 retaliation class despite
  the constructed special category;
- Mirror Coat rejects the same move identity;
- constructed Electric type stops at Ground immunity after accuracy, without
  critical or damage-roll consumption.

The complete corpus matches the pinned oracle at 2,147 stable boundaries and
replays deterministically. Inventory promotion is limited to `hiddenpower`
and `move.hiddenpower.onModifyMove`; `move.hiddenpower.onModifyType` is
classified unreachable rather than implemented.
