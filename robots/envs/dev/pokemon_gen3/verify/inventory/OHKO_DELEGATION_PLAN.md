# Called-move and Gen 3 OHKO capability plan

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

## Honest closure boundary

Legal Gen 3 OU can reach Fissure, Guillotine, Horn Drill, and Sheer Cold through
Metronome even though OHKO Clause rejects those four moves on submitted sets.
That makes their runtime semantics required. It does **not** make Metronome
implemented: its resolved candidate pool contains 336 moves, and forced OHKO
fixtures prove only one delegation path through that pool.

The first slice may close exactly:

- `move:fissure`, `move:guillotine`, `move:horndrill`, `move:sheercold`;
- `ability:sturdy`;
- `event_hook:ability.sturdy.onTryHit`.

`move:metronome` and `event_hook:move.metronome.onHit` remain unsupported until
every generated candidate is executable or the supported contract defines and
verifies a different complete pool.

## Pinned Showdown control flow

- Effective Gen 3 Metronome is inherited from
  `data/mods/gen4/moves.ts:833`: enumerate resolved moves with the Metronome
  flag, sort by move number, sample once, then call `actions.useMove`.
- The pinned resolved pool has 336 candidates. Metronome owns the submitted
  move's PP and BeforeMove work. The called move owns its own targeting,
  mutation, accuracy, TryHit, hit, and effect pipeline without spending its PP.
- Gen 3 hit staging is `data/mods/gen3/scripts.ts:300-388`.
- Gen 3 OHKO damage is current target HP in
  `sim/battle-actions.ts#getDamage`, not maximum HP and not ordinary fixed
  damage.
- Gen 3 Sturdy is the OHKO-only `onTryHit` cancellation inherited from the base
  ability. `data/mods/gen4/abilities.ts:452` removes the modern full-HP survival
  callback.

## Native semantic operations

1. Immutable generated call pool `{offset,count}` over catalog move IDs, plus a
   move-owned `CALL_MOVE_FROM_POOL` effect. One labeled selection draw chooses
   an index; the selected executable descriptor re-enters the existing bounded
   `PokemonMoveInvocation` path as `POKEMON_MOVE_ENTRY_CALLED`.
2. Typed move data `ohko = NONE | ANY | EXCLUDED_TYPE(type)` and a
   generation-owned OHKO accuracy policy. The kernel branches on the sum type,
   never a move ID. All four resolved Gen 3 OHKO moves are `ANY`; the excluded
   type variant exists for later-generation plugins rather than Gen 3 data.
3. A `TARGET_CURRENT_HP` damage formula. Substitute intercepts the requested
   current-real-HP amount before real HP mutation; the formula consumes no
   critical or damage-roll draw.
4. A generated Sturdy `TryHit` program: guard that the active move is OHKO,
   then return null. No generic Sturdy identity branch and no modern survival
   behavior.

Pool validation must prove catalog identity coherence, bounded offsets, stable
ordering, and non-recursive selection. Executability remains a separate support
fact: selecting a catalog-only unsupported candidate must fail honestly, and
therefore Metronome remains outside the supported feature map.

## Exact staging and PRNG

1. Metronome selection: one `move.delegation.selection` draw over 336 sorted
   candidates.
2. If source level is lower than target level, report OHKO immunity without an
   accuracy draw. Pinned Gen 3 resolves Sheer Cold as `ohko: true`; its later
   Ice-type exclusion does not apply.
3. Otherwise accuracy is `30 + source_level - target_level`; accuracy/evasion
   boosts are bypassed, but the ordinary Accuracy event still runs. Consume one
   `move.accuracy` draw over 100.
4. Natural type immunity is discovered before accuracy but resolved afterward.
   It therefore still consumes the OHKO accuracy draw. A miss against a
   naturally immune target reports immunity, matching pinned Gen 3 ordering.
5. On an accuracy pass, Sturdy's target `TryHit` handler cancels before deferred
   natural immunity and before damage. No critical, damage-roll, or secondary
   draw occurs.
6. A connected OHKO requests exactly the target's current real HP. Existing
   faint, forced-replacement, and terminal machinery owns the resulting state
   transition.

## Verification basis

- equal-level hit and forced replacement;
- lower-level no-draw immunity;
- forced miss;
- accuracy/evasion boost bypass;
- Fissure versus Flying: accuracy draw then natural immunity;
- Sturdy cancellation after a passing accuracy draw;
- low-current-HP target behind a healthier Substitute, proving current-HP
  damage leaves Substitute HP;
- Substitute break without real faint;
- terminal real-HP knockout;
- Sheer Cold versus Ice: ordinary Gen 3 OHKO staging (no typed exclusion);
- deterministic replay with separate delegation-selection and accuracy labels;
- focused invalid-pool atomicity and called-move PP-ownership tests.

Implementation order is data types and generator assertions, plugin validation,
generic pool selection/re-entry, typed OHKO policy/current-HP formula, generated
Sturdy handler, focused tests, legal differential cases, full replay/sanitizer
gates, then reclassification of only the six proven records.
