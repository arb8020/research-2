# Gen 3 OU target-mode contract

Oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format `gen3ou`. This document
classifies the 12 target strings present in the frozen reachable move catalog.
It is deliberately a singles contract; it does not claim that singles-shaped
representations are sufficient for doubles or triples.

## Shared control flow

Showdown separates four decisions which the native implementation must not
collapse conceptually:

1. A move request exposes the resolved move target. Only `normal`, `any`, and
   `adjacentAlly` among the frozen 12 are player-choosable
   (`sim/battle-actions.ts:3,1568-1570`). `Side.chooseMove` accepts an omitted
   location in singles, requires one only when there are at least two active
   slots, rejects invalid locations, and rejects a supplied location for every
   non-choosable mode (`sim/side.ts:647-661`).
2. Locations are relative to the user: positive locations are foes and
   negative locations are allies (`sim/pokemon.ts:772-790`). With one active
   slot per half, `+1` is the opposing active and `-1` is the user. Location
   `0` means unspecified (`sim/battle.ts:3063-3094`).
3. Queue resolution fills an unspecified target location from
   `getRandomTarget` and records `originalTarget`
   (`sim/battle-queue.ts:258-269`). In singles, this function returns the user
   for `self`/`all`/`allySide`/`allyTeam`, `null` for `adjacentAlly`, and the
   sole opposing active for every other frozen mode
   (`sim/battle.ts:3154-3173`). **No targeting PRNG call occurs for any mode in
   singles.** The word “random” in `randomNormal` therefore does not imply a
   draw when only one foe can be selected.
4. `Pokemon.getMoveTargets` expands the representative target into Pokémon
   targets or side/field context (`sim/pokemon.ts:793-863`). The Gen 3 override
   then distinguishes field/side dispatch, spread iteration, and ordinary
   single-target resolution (`data/mods/gen3/scripts.ts:222-264,301-315`).

The authoritative prose definitions are in `sim/dex-moves.ts:5-25`.

## Exact singles table

“Current native” distinguishes the complete immutable catalog target enum from
the executable target model. All 12 identities are preserved in
`PokemonCatalogMoveTarget`; the resolved execution algebra includes `FOE`,
`SELF`, `USER_SIDE`, `USER_TEAM`, and `FIELD` (`native/pokemon.h`). The
executor otherwise assumes one opposing active up front
(`native/pokemon.c:1344-1357`). “Representable” below means the target-routing
semantics can be expressed honestly now; it does not mean every move using the
mode is implemented.

| Frozen mode | Reachable moves | Player target / valid singles location | Singles resolution | Required observable contract | Current native |
|---|---:|---|---|---|---|
| `adjacentAlly` | 1 (`helpinghand`) | Choosable, but there is no legal ally. Omitted `0` is accepted during choice normalization; explicit `-1` denotes self and ultimately produces no target, not self-targeting. | `getRandomTarget` returns `null`; move emits no-target/fails. No PRNG. | Choice remains syntactically legal, PP/action staging follows Showdown, target is absent, no ally state changes. | **No.** There is no absent-target executable variant; mapping to `SELF` would be wrong. |
| `all` | 8 | Not choosable; only `0`. | Representative target is user; dispatch is `TryHitField`, once. In singles the target expansion is user + foe, but field effects are not two ordinary hits. No PRNG. | Field event ordering and field/weather/pseudo-weather state; for Pokémon-wide effects such as Haze or Perish Song, both active Pokémon receive the effect through the move's semantics. | **Partial.** `FIELD` represents Sandstorm-like field state, but not the full family of all-Pokémon effects. |
| `allAdjacent` | 5 | Not choosable; only `0`. | Adjacent allies plus adjacent foes; in singles this is exactly the opposing active. One target means `spreadHit` is false, so no spread modifier. No PRNG. | One foe target, ordinary immunity/accuracy/damage staging; move-specific self-destruction remains a separate effect. | **Yes for routing** as `FOE`; family mechanics remain unsupported. |
| `allAdjacentFoes` | 22 | Not choosable; only `0`. | All adjacent foes; in singles exactly the opposing active. One target means no spread modifier. No PRNG. | Same single-foe hit observables as `normal`, while retaining the descriptor so a future multi-active format can expand it. | **Yes for singles routing** as `FOE`; do not erase the catalog mode. |
| `allySide` | 4 | Not choosable; only `0`. | Representative target is user; dispatch is `TryHitSide` for the user's side. No PRNG. | User-side condition state, handler order, duration and failure if already present; no Pokémon accuracy/immunity pipeline unless the move says so. | **Yes** as `USER_SIDE` for existing side-condition programs. |
| `allyTeam` | 2 | Not choosable; only `0`. | Representative target is user; dispatch is `TryHitSide`. `aromatherapy`/`healbell` semantics affect all unfainted team members, including the bench. No PRNG. | Every eligible team member's status and emitted cures, in Showdown order; not merely the active Pokémon. | **Yes** as `USER_TEAM`. Generated Hit programs invoke deterministic living-party iteration and the generic status-clear transaction. |
| `any` | 10 | Choosable. In singles `+1` is the only non-self target; omission `0` auto-selects it. `-1` is invalid/self. | Sole opposing active. No PRNG. | Normal single-target pipeline and `target_side/slot`; no extra choice dimension is needed in the singles ABI. | **Yes for singles routing** as `FOE`. |
| `foeSide` | 1 (`spikes`) | Not choosable; only `0`. | Representative target is the foe, then `TryHitSide` dispatches against the foe side. Spikes carries `mustpressure`, so the opposing active is also the Pressure target even though there is no ordinary Pokémon hit. No targeting PRNG. | Foe-side condition state, Pressure PP deduction, and later switch-in effects; no ordinary Pokémon damage pipeline. | **Yes for the present singles shape.** Spikes proves opponent-side addressing, Pressure target construction, layer restart/cap, and later entry effects. |
| `normal` | 231 | Choosable. In singles `+1` is the foe; omission `0` auto-selects it. Explicit self is rejected during target resolution (`sim/battle.ts:3120-3127`). | Sole opposing active; a fainted/unavailable target is re-resolved before execution (`sim/pokemon.ts:823-850`). No PRNG in singles. | Normal target, retarget/no-target behavior, immunity → accuracy → hit/effects, and exact target trace. | **Yes for the present singles shape** as `FOE`; retarget staging still needs differential coverage. |
| `randomNormal` | 4 | Not choosable; supplying a location is rejected. | Sole opposing active. `getTarget` intentionally bypasses a supplied location (`sim/battle.ts:3128-3151`). No targeting PRNG in singles. | Legal choice has no target; target trace is foe; only mechanic-owned randomness (for example duration/lock), never a fake target draw. | **Yes for singles routing** as `FOE`, but normalization must preserve “not choosable” and PRNG labels. |
| `scripted` | 2 (`counter`, `mirrorcoat`) | Not choosable; only `0`. | Initial singles representative is the foe, but Gen 3 records the damaging source slot and redirects to it (`data/mods/gen3/moves.ts:163-181,407-425`). No targeting PRNG. | Last qualifying damage/source provenance, redirection/failure, doubled damage, and target trace. | **No.** `FOE` alone cannot represent source-provenance targeting or its failure cases. |
| `self` | 55 | Not choosable; only `0`; an explicit location is rejected. | User. No PRNG. | User-target event/effect state, including failure and accuracy rules specific to the move; never foe immunity. | **Yes for routing** as `SELF`. |

## ABI consequence

For Gen 3 OU singles, `PokemonChoice { kind, slot }` is sufficient for the
player-facing action because every target choice collapses to the sole foe and
all other modes forbid a player-selected target. This is a property of the
format, not of the generic kernel. A future doubles/VGC format must extend the
normalized move choice with a relative target-location sum/product field;
reinterpreting the existing `slot` would conflate move selection with target
selection.

The executable descriptor should therefore retain a generation-neutral target
mode even where several modes currently route to the same singles endpoint.
The mode owns target expansion and target-choice legality; generation rules and
move effect programs own what happens after that expansion. In particular,
`all`, `allyTeam`, `foeSide`, and `scripted` must not be encoded as named-move
branches, and `randomNormal` must not consume a guessed PRNG frame in singles.

## Differential gates

A target-mode family is conformant only when focused cases prove:

- normalized legal choices, including rejection of an explicit target for
  non-choosable modes;
- resolved queue `targetLoc`/original target and the corresponding native
  target side/slot or field/side scope;
- zero targeting PRNG records for all 12 modes in singles;
- no-target behavior for `adjacentAlly`;
- one-hit, no-spread-modifier behavior for both adjacent spread modes;
- distinct user-side, foe-side, team, and field state mutations;
- Counter/Mirror Coat source provenance and redirection; and
- deterministic replay of choices, targets, events, state and PRNG labels.

At minimum, anti-overfitting cases should recombine each target family with a
faster foe, a switch before execution, a fainted intended target, Protect or an
immunity where applicable, and a residual/forced-replacement boundary.
