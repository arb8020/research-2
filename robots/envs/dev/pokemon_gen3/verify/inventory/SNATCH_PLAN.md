# Gen 3 Snatch implementation and verification plan

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, resolved through
`Dex.forGen(3)`.

This is an implementation audit, not evidence that Snatch is supported. Keep
the move, volatile, and hooks `unsupported` until every gate below passes.

## Effective pinned semantics

The important source fact is the inheritance chain. Gen 3 declares
`inherit: 'gen4'` in `data/mods/gen3/scripts.ts`; it does **not** use the base
modern Snatch callback. The effective descriptor is the Gen 4 override in
`data/mods/gen4/moves.ts` merged over `data/moves.ts`:

- Snatch is an always-hit, priority `+4`, self-targeting status move with 10
  base PP and `volatileStatus: 'snatch'`.
- Its effective flags are exactly `bypasssub`, `noassist`, and `failcopycat`.
  In particular, the effective move has neither `snatch` nor `mustpressure`.
- The installed volatile has duration 1 and records the move user as its
  `source` and the selected Snatch move as its installation `sourceEffect`.
- `condition.onAnyPrepareHit` has priority `-1`. It reads the volatile state's
  source as the snatcher. In Gen 3 the Sky Drop, Z, and Max guards are inert;
  the live eligibility predicate is the incoming active move's generated
  `snatch` flag.
- On an eligible move, the handler removes its own Snatch installation,
  announces activation, performs the special successful-Snatch Pressure
  check, synchronously calls the ordinary inner move executor as the
  snatcher with no explicit target, and returns `null` to cancel the stolen
  parent invocation.
- Unlike the modern base callback, the inherited Gen 4 callback has no
  `move.sourceEffect === 'snatch'` guard. A move called by one snatcher can be
  stolen by another installed snatcher.

The effective Gen 3 dex has 44 flagged moves: Charge, Recover, Stockpile,
Aromatherapy, Camouflage, Growth, Heal Bell, Ingrain, Light Screen, Minimize,
Mist, Moonlight, Morning Sun, Psych Up, Reflect, Safeguard, Substitute,
Swallow, Synthesis, Tail Glow, Acid Armor, Barrier, Swords Dance, Howl,
Meditate, Refresh, Sharpen, Milk Drink, Rest, Slack Off, Soft-Boiled, Agility,
Amnesia, Belly Drum, Bulk Up, Calm Mind, Cosmic Power, Defense Curl, Double
Team, Dragon Dance, Focus Energy, Harden, Iron Defense, and Withdraw. Generate
the predicate from the flag; do not encode this list in control flow. Format
admission may make some members unreachable, but must not change move data.

Authoritative boundaries are `data/mods/gen3/scripts.ts` (parent mod),
`data/mods/gen4/moves.ts` (effective Snatch override), `data/moves.ts`
(inherited base fields), `sim/pokemon.ts::addVolatile/getMoveTargets`,
`sim/battle.ts::findEventHandlers/runEvent/fieldEvent`, and the Gen 3 inherited
`useMove` implementation in `data/mods/gen3/scripts.ts`.

## Ordering, re-entry, PP, and lifetime

`PrepareHit` is an ordinary event. `onAnyPrepareHit` is discovered on every
active holder on both sides and sorted by order, priority, holder speed,
sub-order, and effect order; exact ties consume the normal labeled handler
ordering PRNG draws. Therefore the fastest installed snatcher intercepts
first. It removes itself before pushing the child. The child discovers the
remaining installations anew, so a chain continues from fastest to slowest;
the slowest remaining snatcher ultimately executes the move. Each enclosing
handler then returns `null`, cancelling its own parent. With `N` installed
snatchers, there are exactly `N` called frames and `N` removals; no condition
can intercept twice.

The production singles geometry has at most two active holders, and two
ordinary selected Snatch actions cannot steal each other because Snatch lacks
the eligibility flag. Still, the generic event/inner-execution boundary must
implement the chain honestly for verifier-injected states and future
multi-active formats. Capacity proof is structural: maximum additional depth
is the number of installed Snatch volatiles at discovery time, bounded by
active slots, because removal precedes the child push. Check the complete
move-caller graph in addition to the local bound. Capacity exhaustion must
roll the public step back byte-for-byte, including removals, PP, traces, and
draws.

PP has two distinct owners:

1. The victim already paid one PP for its selected outer action. The called
   child is an inner `useMove`, so it pays no PP for the copied move and need
   not know that move.
2. A selected Snatch pays its own base PP normally. Only when it successfully
   intercepts, the callback runs `DeductPP` against the Pokemon from whom that
   particular invocation was stolen. If that holder's effective Pressure
   returns 1, one extra PP is deducted from the snatcher's **Snatch slot**,
   identified by the installation state's original `sourceEffect`. An
   ineligible/expired Snatch incurs no extra PP. In a chain this check happens
   independently at every edge, against the immediately stolen-from user.

The called invocation's public source effect is the installed condition
`snatch` (Showdown's ambient handler effect), while the persistent volatile
also retains its installation source and selected-move source effect for the
Pressure deduction. These are different facts and must not be collapsed.
Target resolution is fresh inside the child. Every currently flagged move is
self-targeting, so the final child targets the final snatcher. The parent
stops at `PrepareHit`: it owns no later accuracy/effect/PRNG work.

If never triggered, duration 1 is decremented by `fieldEvent('Residual')` and
the volatile is removed before executing a residual callback. Switching also
clears it through ordinary volatile teardown. Its `onStart` is only the
single-turn announcement; it has no state mutation beyond installation.

## Minimal native implementation atop the current stack

Reuse `PokemonMoveInvocation` and `invoke_move_inner`; do not enqueue a new
turn action and do not add a Snatch resolver. Required changes are:

1. Add the Snatch semantic volatile/rule mapping and generate its duration-1
   primary installation plus the `ANY / PrepareHit / priority -1` binding.
   Enable `PrepareHit`'s boolean-or-null algebra.
2. Add declarative operations (or one narrowly typed generation operation)
   for: guard active move flag; remove the **discovered handler owner's**
   installation; perform successful-Snatch PP adjustment from installation
   provenance; call the current active move with holder as user and a resolve
   target request; return null.
3. Generalize handler execution to use `PokemonHandlerRef.owner` /
   `holder_side,holder_slot` for owner mutation and called-user identity.
   The current interpreter commonly addresses `input->target_side/slot`;
   that is wrong for an `ANY` handler because the event target is the victim
   while the owner is the snatcher.
4. Persist volatile installation `source` and `sourceEffect` as ID/entity
   values. The child invocation gets
   `{kind=CONDITION,id=snatch-condition}`; successful Pressure deduction uses
   the installation's `{kind=MOVE,id=snatch-move}` to find the selected slot.
5. Preflight frame, invocation-trace, handler, event, condition-trace, PP, and
   draw capacity for the whole nested operation, or rely on the existing
   transactional public-step copy with explicit overflow tests. Never leave a
   removed installation behind after a failed child push.

Do not add the modern source-effect guard, `mustpressure`, a fixed guessed
depth, or a direct target swap. Those would implement a different generation.

## Focused proof obligations

- install/expiry/switch removal and failed duplicate installation;
- eligible single- and multi-stat boosts move wholly to the snatcher;
- all 44 effective eligibility bits match the pinned flattened dex, with an
  ineligible self move leaving Snatch installed until residual expiry;
- victim selected PP is charged once; copied-move PP is unchanged; Snatch base
  PP is charged once; successful Pressure charges one additional Snatch PP;
  failed/ineligible interception does not;
- handler trace identifies `ANY / PrepareHit`, the snatcher as holder, the
  original user as source/target of the parent event, and priority `-1`;
- remove occurs before child start; parent null-cancels before accuracy and
  owns no subsequent random draw;
- child has fresh invocation/parent IDs, `CALLED` entry, condition source
  effect, resolved self target, and owns all downstream events/draws;
- two installed snatchers of different speed prove fastest-to-slowest
  interception and slowest final user; a speed tie proves exact handler-order
  draw count and replay; each installation and Pressure edge is consumed once;
- capacity-minus-one, exact-capacity, and capacity-plus-one nested chains,
  with byte-identical rollback on overflow.

## Differential and observer contract

Add oracle cases for Howl and Calm Mind steals, ineligible move then expiry,
Pressure success/failure, switching before trigger, and a multiple-snatcher
fixture. The verifier may use a doubles oracle fixture for naturally reachable
multiple snatchers even though the submitted Ocean ABI is singles; the native
focused test may construct the equivalent bounded installed state.

The test-only observer must expose enough causal structure to compare, at the
first boundary:

- condition add, residual discovery/decrement/removal, trigger removal, and
  holder/source/source-effect identities;
- ordered `PrepareHit` discovery and execution, including labeled tie draws;
- invocation start/end with ID, parent ID, selected/called kind, user, target,
  move, source-effect kind/ID, and result;
- base and successful-Snatch PP deductions with charged move/slot and Pressure
  owner;
- cancellation kind (`null`, not `false`) and the absence of parent
  accuracy/effect draws after interception;
- canonical boosts/HP/PP/volatiles, legal choices, request, queue (no child
  action), and terminal state at every stable boundary.

Only after focused tests, exact differential cases, deterministic replay,
random/Ocean regression, and sanitizers pass should `move:snatch`,
`volatiles.snatch`, `move.snatch.condition.onStart`, and
`move.snatch.condition.onAnyPrepareHit` be reclassified.

## Current implementation evidence (not yet classification evidence)

The native kernel now has the reusable owner-directed PrepareHit re-entry
boundary, installation provenance, successful Pressure PP adjustment, and
fixed-capacity transactional rollback inherited from the public step. Focused
tests prove one snatcher and an injected two-installation chain; the legal
Showdown differential proves Howl theft both with and without Pressure. The
corpus is currently 237 exact stable boundaries.

Two live Snatch installations are unreachable in Gen 3 OU singles through
ordinary choices: there are only two active actions, Snatch itself lacks the
`snatch` flag, and its duration-one installation expires in the same turn.
The injected native chain is therefore a generic-kernel/future-multi-active
proof, not a claimed reachable singles differential. A doubles oracle fixture
would be the honest independent proof if this generic topology is promoted.

Keep the Snatch descriptors unsupported for now. Focused evidence now covers
Calm Mind, ineligible expiry, duplicate non-refresh, equal-key tie ordering
and replay, detailed native invocation/owner/cancellation/PP assertions, and
transactional invocation-frame, event-frame, and volatile-capacity failures;
the Calm Mind differential brings the combined corpus to 282 exact stable
boundaries. Remaining obligations are the full 44-bit eligibility audit,
explicit switch teardown if a reachable Gen 3 path is found, richer
oracle-side invocation and PP-cause records, and an exact-capacity-success
chain in addition to the proven overflow rollback.
