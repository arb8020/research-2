# Baton Pass boundary audit

Pinned Pokemon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is the bounded implementation and verification record for the native
Baton Pass family. A state-copy helper alone was not accepted as evidence: the
proved boundary also includes the mid-turn request, retained queued work,
move-caused switching, trapping relations, and no-replacement failure.

## Owned inventory records

The frozen inventory has exactly three records owned directly by this family:

- `move:batonpass`;
- `event_hook:move.batonpass.onHit`;
- `event_hook:move.batonpass.self.onHit`.

## Implementation status

The native kernel now represents Baton Pass as a generated move-driven switch
policy, not as move-ID control flow. A successful move suspends the retained
action queue, projects a one-sided replacement request, runs the ordinary
switch lifecycle, and transfers boost stages plus every resolved condition
whose generated rule is copyable. The replacement resumes the same turn.

Focused native evidence covers queue retention, request/phase ownership,
copyable Focus Energy, non-copyable Stockpile, linked trapping, outgoing
cleanup, no-bench failure, and invariant preservation. Exact differential
evidence covers boost transfer, no-bench failure, queue resumption, and all
nine legal source/partial trapping rotations. All fixtures pass the complete
corpus and the regenerated descriptor map classifies exactly these three
records as implemented.

The runtime-registration census has nine additional proven regression
instances. They are test obligations rather than nine more inventory records:

| Upstream source | Required native case keys |
| --- | --- |
| `test/sim/misc/trapmoves.js:28-38` | `upstream-block-28`, `upstream-meanlook-28`, `upstream-spiderweb-28` |
| `test/sim/misc/trapmoves.js:143-153` | `upstream-bind-143`, `upstream-clamp-143`, `upstream-firespin-143`, `upstream-sandtomb-143`, `upstream-whirlpool-143`, `upstream-wrap-143` |

The three Gen 3 OU same-set bans (`Baton Pass + Block`, `Baton Pass + Mean
Look`, and `Baton Pass + Spider Web`) and the Speed/One Boost Passer clauses
are already admission obligations. They do not implement runtime Baton Pass
and must not be counted again as records closed by this slice.

## Showdown control flow

The semantic path is compositional rather than move-name dispatch:

1. The resolved move descriptor declares `selfSwitch: 'copyvolatile'`
   (`data/moves.ts:1092-1114`). Its target `onHit` rejects the move when
   `canSwitch` is false; its nested self `onHit` sets
   `skipBeforeSwitchOutEventFlag` so this switch never dispatches that event.
2. Generic move-hit completion observes `selfSwitch`, verifies that a living
   replacement exists, and sets `source.switchFlag` (`sim/battle-actions.ts:
   1311-1334`). Trapping does not participate in this admission check.
3. Generic action completion sees that flag, observes the skip flag, creates
   a switch request, and returns without discarding the remaining action queue
   (`sim/battle.ts:2854-2935`). This is also why queued Pursuit does not
   intercept Baton Pass; it later executes against an inactive target.
4. The switch request requires a choice only from the flagged side; the other
   side has no request (`sim/battle.ts:1416-1431`, `sim/side.ts:1090-1107`).
   This is a requested move-driven switch, not a faint replacement and not an
   ordinary voluntary switch from a move request.
5. The accepted `instaswitch` enters generic `switchIn`. The source move's
   string-valued `selfSwitch` selects the transfer mode; `BeforeSwitchOut` is
   skipped by descriptor policy; ability/item `End` and queued-action
   cancellation retain their ordinary ordering (`sim/battle-actions.ts:
   72-117`).
6. `copyVolatileFrom` clears the incoming Pokemon's transient product, copies
   all boost stages, shallow-copies every volatile whose resolved condition
   does not say `noCopy`, retargets each copied state to the incoming Pokemon,
   repairs linked relations when present, clears the outgoing product, and
   dispatches each copied condition's `Copy` callback in insertion order
   (`sim/pokemon.ts:1247-1268`).
7. `runSwitch`/entry work executes and the suspended queue resumes. Thus an
   opposing move selected at turn start can execute against the incoming
   Pokemon before residual and the next request.

This also explains the nine trapping cases. A known trap removes ordinary
switch choices from a move request, but it does not prevent a move from
setting `switchFlag`. In the resolved Gen 3 Dex, the Gen 4 mod explicitly
overrides both `trapped` and `trapper` to `noCopy: false`; partial trapping is
also copyable. The modern base conditions are not authoritative here. Thus
both trap families permit the request and transfer their live relation.

## State-transfer product

The native operation should be a typed switch transfer policy, not a Baton
Pass branch in the switch function. For `COPY_VOLATILES`, transfer:

- all seven boost stages exactly;
- each `PokemonVolatileState` whose resolved `PokemonConditionRule.no_copy`
  is false, including its descriptor identity, duration, counter, typed
  payload, source/effect provenance, and insertion/effect order;
- relation endpoints, replacing references to the outgoing holder with the
  incoming holder where a copied state has a linked counterpart;
- an explicit generic `Copy` lifecycle dispatch for copied descriptors.

Do not transfer HP, major status, PP, item, ability, last-move/action history,
or other per-Pokemon persistent state. Ordinary switch cleanup still resets
the outgoing boosts, temporary moves/types/ability, attack history, and all
remaining volatiles. No-copy filtering must come from flattened condition
data. The implementation must not enumerate `substitute`, `focusenergy`,
`leechseed`, or trapping identities in generic switch control flow.

Before enabling the move, regenerate `no_copy` from the resolved pinned Dex
for every generated condition. The current `PokemonConditionRule` already has
the field, but several rows are hand-populated as zero; relying on those rows
without an exhaustive generated-data test would silently over-transfer state.

## Native boundary gap

The existing kernel already has most adjacent pieces: typed switch actions,
ordered `BeforeSwitchOut`/`SwitchOut`, Pursuit interception, run-switch entry
work, forced-replacement suspension, generic volatile payloads, and
descriptor-level `no_copy` storage. The missing boundary is specifically a
move-driven switch continuation:

- `compile_choices` currently begins by clearing `battle->queue`; a Baton
  Pass replacement step must instead preserve the already-selected opponent
  action and insert/execute only the requested switch.
- `POKEMON_REQUEST_SWITCH` and `POKEMON_PHASE_FORCED_REPLACEMENT` currently
  imply a faint replacement. The request needs an explicit reason/mode so a
  move-driven switch cannot acquire forced-replacement ordering or semantics.
- `PokemonSwitchCause` needs a move-driven cause, while the action (or bounded
  pending-switch product) needs the resolved transfer policy and source move.
- turn suspension needs a distinct `MID_ACTION_SWITCH` state. Completing the
  replacement must resume the retained queue; it must not add `beforeTurn`,
  rebuild either player's choice, or start residual early.
- the switch transaction needs an explicit generated BeforeSwitchOut policy.
  This is generic descriptor provenance corresponding to Showdown's
  `skipBeforeSwitchOutEventFlag`, not a Baton Pass branch.
- failure when no living inactive teammate exists must leave no pending
  switch, consume no switch-selection PRNG, and allow the ordinary post-action
  turn path. The move's PP and move event still occur.

A compact product is sufficient, for example:

```text
PendingMoveSwitch {
    side, outgoing_slot, source_move_id,
    transfer_policy, before_switch_out_complete
}
```

It is valid only while the request mode is `MOVE_DRIVEN`, exactly one side is
required in singles, the retained queue contains only previously normalized
actions, and the referenced outgoing Pokemon is still the active living
holder. These are invariants, not recovery cases.

## Smallest legal differential basis

Use legal Gen 3 OU sets and preserve the upstream semantic assertion rather
than its modern teams/abilities. A generated fixture family can share one
scenario shape while rotating every descriptor binding.

1. **Three full-trap rotations:** Block, Mean Look, Spider Web. On turn one a
   slower legal Smeargle establishes the trap after the faster Baton Pass user
   acts. On turn two the trapped user selects Baton Pass while the opponent
   selects a visible damaging move. Assert: ordinary switch mask was empty;
   Baton Pass remained selectable; a one-sided mid-turn switch request was
   emitted; replacement copied the resolved Gen 3 `trapped` relation; the retained damaging
   action hit the incoming Pokemon; residual/next-turn transition followed
   only after that action.
2. **Six partial-trap rotations:** Bind, Clamp, Fire Spin, Sand Tomb,
   Whirlpool, Wrap, using the same ordering. Force the initial accuracy and
   duration draws. Assert the same request/queue facts, plus exact copied
   `partiallytrapped` descriptor, remaining duration, source provenance and
   residual damage on the incoming Pokemon. Its next ordinary switch request
   must still be restricted while Baton Pass remains a legal move choice.
3. **Transfer-product fixture:** establish at least one boost, Substitute with
   non-full HP, Focus Energy, and opponent-owned Leech Seed, then Baton Pass.
   Assert exact payload/provenance transfer and outgoing cleanup. Add one
   reachable `noCopy` condition such as Torment or Attract and assert its
   absence on the recipient. This is the differential proof for the generic
   product rather than just trapping.
4. **No replacement fixture:** a one-Pokemon legal team selects Baton Pass.
   Assert failure without a switch request, queue loss, state transfer, or
   switch-selection draw. This ports `test/sim/moves/batonpass.js:30-46` for
   the reachable singles branch.
5. **BeforeSwitchOut/faint fixture:** focused C construction installs a
   handler capable of fainting the passer at that boundary. Assert one
   dispatch, cancellation of the move-driven request, ordinary faint
   replacement/terminal behavior, and invariant preservation. This is an
   internal ordering proof; it need not invent an illegal Gen 3 OU team.

The nine descriptor rotations cannot be collapsed into one shared C unit:
each generated move binding needs oracle evidence. The transfer-product and
no-replacement scenarios need not be repeated nine times.

## Focused native proofs

Add unit tests below the differential layer for facts difficult to isolate via
the public fixture surface:

- complete table-driven `no_copy` agreement between generated conditions and
  resolved Showdown data;
- capacity preflight: destination/trace capacity failure leaves battle state,
  queue, and PRNG unchanged;
- payload-preserving copies for every native volatile payload variant;
- stable insertion order and one `Copy` dispatch per transferred condition;
- linked-relation retargeting and teardown of every skipped/no-copy relation;
- exact queue snapshot before request and after replacement;
- action source identity and target re-resolution against the incoming active;
- pass followed by opponent KO, pass after opponent faint, and terminal/no-
  replacement interactions;
- replay identity across the mid-turn request boundary.

The observer must expose the retained queue, request reason, switch cause,
condition-copy lifecycle, and transferred payload/provenance. If its current
canonical projection loses any of these distinctions, extend it only after
the kernel/API shape is settled.

## Dependency and merge order

1. **Data audit first:** generate and validate all condition `no_copy` facts;
   define a generation-neutral move self-switch/transfer enum. This may touch
   the generator and generated bundle but not queue behavior.
2. **Kernel continuation:** add request reason, pending move-switch product,
   suspension invariant, and retained-queue resume. Prove it with a synthetic
   transfer policy before enabling Baton Pass data.
3. **Generic transfer transaction:** preflight, copy boosts/copyable volatile
   products, repair relations, run `Copy`, then perform ordinary outgoing
   cleanup. Reuse the existing switch/run-switch pipeline.
4. **Resolved Baton Pass binding:** generate `onHit`, nested self `onHit`, and
   `COPY_VOLATILES` data; no move-ID branch. Add failure and transfer focused
   tests.
5. **Observer and fixtures:** add the transfer/no-replacement cases, then the
   three plus six trapping rotations. Update the runtime census only after
   every named case is exact.
6. **Classification last:** reclassify only the three direct inventory records
   after native boundary, focused tests, differential cases, source mapping,
   replay, sanitizer/random/Ocean, and complete-corpus gates pass.

## Overlap and conflict notes

- This work overlaps the central `pokemon.h`/`pokemon.c` switch/request state
  machine, generated move/condition data, observer projection, native ID map,
  fixture Makefile, and classification. Keep those serialized in the
  integration worktree.
- Do not reuse the faint-replacement flag for move-driven switching; doing so
  loses queue ownership and creates false residual/before-turn transitions.
- Do not make all source-linked conditions noncopyable. Leech Seed and partial
  trapping deliberately retain their original source; `noCopy` is a property
  of each resolved condition.
- Do not derive copying from whether a volatile is currently “supported.” The
  generated policy is authoritative, and every newly implemented condition
  must automatically enter the same transfer operation.
- Do not encode the nine trapping move IDs in Baton Pass logic. They are
  descriptor-rotation evidence for two already-general relation families.
