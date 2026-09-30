# Gen 3 move-choice control family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is the source-derived implementation contract for Disable, Encore, Taunt,
and Torment. The family is implemented and classified from focused,
differential, replay, random, Ocean, and sanitizer evidence: four moves, four
volatile conditions, and seventeen callback-owner records.

## Integration status

The shared normalization foundation and all four vertical slices are
implemented and classified. The live
request path now resolves an explicit sum of
selectable slots, a hard-locked synthetic move, or the generation plugin's
fallback move. Its pure reducer composes PP filtering with typed equal,
unequal, category, and last-nonfallback restrictions. Actions retain selected
move identity and distinguish selected-slot, forced, and fallback execution.

The generation plugin also owns a validated, descriptor-keyed choice-control
policy vocabulary, and volatile state has a generic stored-move payload.
Request-time policies are discovered from installed owners through the generic
`DisableMove` event, ordered by priority and installation order, traced, and
then passed into the reducer. `OverrideAction` and `BeforeMove` are distinct
ordered event boundaries. Override changes executed identity, target
resolution, PP ownership, and last-move state without changing queued priority
or selected identity; guards cancel before PP. Taunt now uses generated
move/lifecycle data plus descriptor-keyed `DisableMove` and `BeforeMove`
policies. Its focused test and three-boundary differential prove queued
cancellation before PP, request filtering, Start and End handlers,
fixed-duration residual work, choice restoration, state, events, and exact
PRNG. Disable, Encore, and Torment use generated descriptors and
descriptor-keyed policies over the same kernel. The complete corpus has 1,225
stable boundaries, including duplicate admission, Protect, Substitute,
type-immune last-move capture, PP exhaustion, and switch-clear/no-End cases.

## Authoritative control flow

The effective move and condition descriptors are in `data/moves.ts`, with Gen
3 overrides in `data/mods/gen3/moves.ts`. Request-time disabling is owned by
`sim/battle.ts`'s turn/request preparation and `Pokemon#getMoves` in
`sim/pokemon.ts`. Execution-time replacement and cancellation are owned by
`BattleActions#runMove` in `sim/battle-actions.ts`.

The four conditions are one choice-control family, not one kind of lock:

| Condition | Request reduction | Already-queued action | Duration |
| --- | --- | --- | --- |
| Disable | remove the stored last move | `BeforeMove`, priority 7, rejects the stored move before PP | uniform `[2, 6)`; decrement once on Start when the target still has a queued action |
| Encore | retain only the stored last move | `OverrideAction` replaces the selected move while preserving the selected action's queue priority | uniform `[3, 7)`; increment once on Start when the target has already moved; end early at zero stored-move PP |
| Taunt | remove Status-category moves | inherited `BeforeMove` rejects a queued Status move | fixed 2 turns |
| Torment | remove `lastMove`, except Struggle | unchanged | indefinite |

Gen 3 Taunt sets inherited `onBeforeMovePriority` to `undefined`; it does not
remove the inherited `onBeforeMove` callback. Its queued-action guard therefore
runs at default priority zero. All four effects permit switching and clear on
ordinary switch. Disable, Encore, and Torment are `noCopy`; Taunt is not.

All four moves are protectable and bypass Substitute. They are ordinary Status
moves and do not acquire type immunity. A duplicate volatile has no Restart
handler, so reapplication fails without replacing state or drawing a second
duration.

## Native semantic model

The kernel should normalize a submitted move choice before queue construction:

```text
NormalizedMoveChoice =
    SelectedSlot { slot, selected_move_id }
  | ForcedMove  { move_id }
  | Fallback    { move_id = struggle }
```

`PokemonAction` must retain `selected_move_id`. At execution, an ordered
`OverrideAction` event derives `executed_move_id`; target resolution and PP
deduction use the executed move, while action priority remains the priority of
the originally selected move. Re-reading only a slot at execution cannot
represent Encore honestly.

Request projection builds one move-choice product containing each slot's move,
PP availability, category, and disabled state. Ordered `DisableMove` handlers
reduce that product. The public legal mask and choice validation are projections
of this single result. If every move is unavailable, projection exposes exactly
one synthetic Struggle choice. An attempted illegal slot is never silently
converted to Struggle.

Each installed choice-control volatile stores a bounded `stored_move_id` when
required. Generated condition policy selects reusable operations:

- disable the move equal to stored state;
- disable every move unequal to stored state;
- disable a move category;
- disable the last non-fallback move;
- override execution with stored state;
- reject a queued move equal to stored state;
- reject a queued category;
- remove the owner when its stored move is absent or out of PP.

The kernel owns move-set reduction, action normalization, event ordering,
volatile lifecycle, rollback, and request projection. The resolved generation
plugin owns duration laws, queue-relative Start adjustment, category and
fallback policies, handler bindings, and the declarative operations attached to
each condition. Generic control flow must not compare move or condition names.

## PRNG and staging

Disable consumes accuracy before its duration draw. Its Gen 3 duration draw is
uniform over `[2, 6)`. Encore's is uniform over `[3, 7)`. Miss, Protect,
failed admission, and duplicate admission consume no duration draw. Taunt and
Torment consume none. The verifier observer should label the two draws
`condition.disable.duration` and `condition.encore.duration` without changing
the pinned random stream.

The important action sequence is:

```text
request DisableMove reduction
  -> choices normalize
  -> queue orders using selected move priority
  -> faster choice-control move installs volatile
  -> slower action runs OverrideAction / BeforeMove
  -> executed move owns target and PP
  -> residual duration and early-end work
  -> next request uses the same DisableMove reducer
```

## Required proof

Focused native tests must cover reduction composition, explicit fallback,
illegal-choice rejection, queue-relative duration adjustment, stored-move
capture, execution override with inherited priority, cancellation before PP,
zero-PP early end, duplicate no-redraw, switch cleanup, invalid policy/plugin
rejection, and atomic capacity failure.

The minimum differential matrix is:

1. Disable fails without `lastMove`, then cancels an already-queued stored move.
2. Encore rewrites a queued different move while retaining selected priority.
3. Taunt cancels a queued Status move and produces a Struggle-only request.
4. Torment disables a consecutive move, then exempts Struggle on the following request.
5. Encore ends when its stored move reaches zero PP.
6. Duplicate Disable or Encore does not redraw duration.
7. Protect prevents installation.
8. Substitute does not prevent installation.
9. A type-immune attack still becomes `lastMove` and can be disabled.
10. Switching removes the condition and clears last-move state.

Persist actions, requests, queue, handler order, condition lifecycle, canonical
state, and labeled PRNG at every boundary.

## Integration order

1. Add the choice-product and normalized-choice types plus plugin validation.
2. Implement one pure reducer and use it for request projection and validation.
3. Retain selected move identity in queued actions; add ordered
   `OverrideAction` execution.
4. Add stored-move volatile state and generic Start/BeforeMove/Residual policy
   operations.
5. Generate the four resolved descriptors and bindings.
6. Add focused tests, observer labels, differential fixtures, and classification.
7. Run the complete corpus, replay, generator, random/Ocean, sanitizer, and
   invariant gates before changing support claims.
