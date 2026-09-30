# Active-move re-entry plan

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, resolved through
`Dex.forGen(3)`.

This note defines the shared native boundary needed by Gen 3 Magic Coat,
Mirror Move, and Snatch. It is an architecture plan, not evidence that those
descriptors are implemented. They must remain `unsupported` until the focused
and differential gates below pass.

## Semantic boundary in Showdown

Showdown has two materially different move entry points:

- `BattleActions.runMove` is the outer, selected-action path. It runs
  pre-action gates, deducts the selected move's PP, records `moveUsed`, and
  then calls `useMove` (`sim/battle-actions.ts:200-308`).
- `BattleActions.useMove` / `useMoveInner` is the inner execution path. It
  creates a fresh active move, resolves or accepts its target, runs move and
  hit events, accuracy, effects, and resulting state mutation, but does not
  repeat outer action gates or ordinary PP deduction
  (`sim/battle-actions.ts:355-490`).

All three Gen 3 mechanics in this plan re-enter through the **inner** path,
synchronously inside the current handler. They do not enqueue a new turn
action:

- Magic Coat's priority-2 `TryHit` handler clones the incoming move, marks the
  clone bounced, executes it from reflector to original source, and returns
  null to cancel the original (`data/moves.ts:10696-10724`).
- Mirror Move reads the target's most recent `attackedBy` record, checks both
  its Gen 3 exclusion list and that the recorded source still has the move,
  then calls `useMove` from the Mirror Move user with no explicit target
  (`data/mods/gen3/moves.ts:428-445`).
- Snatch's priority -1 `Any/PrepareHit` handler checks the `snatch` flag and
  source provenance, removes its own volatile before re-entry, executes the
  move from the snatcher with no explicit target, and returns null to cancel
  the original (`data/moves.ts:17118-17134`).

The current native engine has only `PokemonAction` (move slot or switch) and
executes a move directly from that selected slot. It has no active-move frame,
no called-move entry point, no attacked-by provenance, and its
`PokemonSourceEffectRef` can represent only a move. Extending
`PokemonAction` with reflection/snatch cases would therefore put synchronous
move semantics in the turn queue and would be the wrong boundary.

## Smallest honest native representation

Keep the turn queue unchanged. Add a separate fixed-capacity move-execution
stack whose top is the canonical active move visible to events.

```c
typedef enum {
    POKEMON_MOVE_ENTRY_SELECTED = 1,
    POKEMON_MOVE_ENTRY_CALLED,
} PokemonMoveEntryKind;

typedef enum {
    POKEMON_TARGET_REQUEST_RESOLVE = 1,
    POKEMON_TARGET_REQUEST_EXPLICIT,
} PokemonTargetRequestKind;

typedef struct {
    PokemonTargetRequestKind kind;
    PokemonEntityRef explicit_target; /* valid only for EXPLICIT */
} PokemonTargetRequest;

typedef struct {
    enum {
        POKEMON_EFFECT_REF_MOVE = 1,
        POKEMON_EFFECT_REF_CONDITION,
    } kind;
    uint16_t effect_id;
} PokemonEffectRef;

typedef struct {
    PokemonMoveEntryKind entry;
    uint16_t move_id;
    PokemonEntityRef user;
    PokemonTargetRequest target_request;
    PokemonEffectRef source_effect;
    uint8_t has_bounced;
    int8_t inherited_priority;
    uint32_t invocation_id;
    uint32_t parent_invocation_id;
} PokemonMoveInvocation;

typedef struct {
    PokemonMoveInvocation invocation;
    PokemonEntityRef resolved_target;
    PokemonMoveTarget target_mode;
    uint64_t flags;
    uint8_t type;
    uint8_t category;
    uint16_t base_power;
    uint8_t accuracy;
    uint8_t always_hit;
    int8_t priority;
    uint8_t outcome;
} PokemonActiveMoveFrame;
```

`PokemonEffectRef` above is deliberately broader than today's
move-only `PokemonSourceEffectRef`: Magic Coat and Snatch are installed
volatile-condition effects, while Mirror Move is a move effect. It should use
the same generated descriptor identity scheme as event owners rather than
Gen-3-specific move IDs. The distinct effect-kind enum is intentional because
today's `PokemonOwnerKind` describes installed holders and has no move arm; do
not encode Magic Coat or Snatch as fake moves in generic control flow.

The active frame is a mutable per-invocation projection of immutable move
data. Event handlers may modify this projection; generated move descriptors
remain immutable. Events receive an invocation/frame reference (or the top
frame), not a bare move descriptor. Every event source-effect copied into a
persistent trace remains an ID-based value, never a stack pointer.

The selected-action adapter constructs `ENTRY_SELECTED`, identifies the move
slot, runs outer gates, and owns the one base PP decrement. The shared inner
interpreter accepts a `PokemonMoveInvocation`; `ENTRY_CALLED` begins at the
equivalent of Showdown `useMoveInner`. Thus no call-site boolean combination
such as `deduct_pp=false, before_move=false, ...` is required.

## Stack and cycle policy

Use a compile-time `POKEMON_MOVE_FRAME_CAPACITY`, initially 8, independent of
the event-frame capacity. Push before target/event processing and pop on every
return path. Capacity exhaustion is an invariant/configuration failure, never
a silent failed move. The public step remains transactional on that failure so
partially removed volatiles or consumed draws cannot escape.

The number 8 is not the correctness argument. The generator/verifier must
also prove that the supported Gen 3 call graph fits:

- Magic Coat can repeat the same move only once because `has_bounced` is set
  before the child invocation.
- Snatch removes its installation before the child invocation and the child
  carries source effect `snatch`, either fact preventing re-steal.
- Gen 3 Mirror Move excludes Mirror Move itself and the other listed calling
  moves before invoking its child.

For the three-family slice, selected Mirror Move -> copied reflectable move ->
Magic Coat reflection is the deepest relevant chain (three active frames).
Keep spare capacity for later supported callers, but require a generated
maximum-depth/cycle audit whenever such a caller is enabled. A raw
`depth == 8` guard without the call-graph proof is only memory safety, not
semantic conformance.

## Ownership of observable semantics

### Source effect and lineage

Each child gets a fresh monotonically increasing `invocation_id` and its
parent's ID. Source effect is explicit:

- reflected child: installed Magic Coat condition;
- mirrored child: outer Mirror Move;
- snatched child: installed Snatch condition.

`has_bounced` belongs to the active invocation, not global battle state or the
immutable move. This makes the once-only reflection invariant local. Trace
records should include invocation ID, parent ID, entry kind, user, target,
move, source effect, and terminal outcome so differential failures identify
the first re-entry boundary.

### PP

The selected outer frame decrements its chosen slot once. The three child
invocations never deduct the child's move-slot PP and never require that the
new user knows the move. In pinned Gen 3, `useMoveInner` runs Pressure PP logic
only when there is no source effect (or for Pursuit); all three children have a
source effect, so they consume no additional PP. This policy belongs in the
Gen 3 generation operations/rules layer because later generations' generic
`battle-actions.ts` behavior differs.

Mirror Move's eligibility check is separate: the recorded attacker must still
have the recorded move. That test selects whether the call is legal; it does
not authorize charging that slot.

### Target

- Magic Coat supplies an explicit child target: the original move user.
- Mirror Move supplies no target. The child resolves a target from the copied
  move's own target mode, exactly where an ordinary inner move does.
- Snatch supplies no target. A stolen self move consequently resolves to the
  snatcher.

Target resolution therefore belongs in the inner interpreter, after a fresh
active frame exists. Do not reuse the parent's resolved target except through
the explicit Magic Coat request.

### Hit staging, accuracy, and PRNG

The child traverses the ordinary hit pipeline and owns all draws caused by
that execution. Draw labels add `invocation_id` (and retain the semantic label)
so equal labels in parent and child remain distinguishable and replayable.

In Gen 3, spread/single hit processing orders type immunity before `TryHit`,
then move-specific immunity, then accuracy
(`sim/battle-actions.ts:548-580`). Consequences:

- Magic Coat re-enters during `TryHit`; the original is null-cancelled and
  consumes no original accuracy draw. The reflected child owns its accuracy
  and later draws.
- Snatch re-enters even earlier, during `PrepareHit`; the original consumes no
  hit/accuracy draw. The stolen child owns all subsequent draws.
- Mirror Move first completes its own always-hit self action, then its called
  child independently owns target, accuracy, critical, damage, secondary, and
  handler-order draws.

Never advance the PRNG by guessed counts when cancelling the parent.

### Mirror Move provenance

Add a bounded per-Pokemon attacked-by history, not a single global
`last_move`. The minimal record for this family is:

```c
typedef struct {
    PokemonEntityRef source;
    uint16_t move_id;
    uint16_t damage;
    uint8_t damage_was_number;
    uint8_t this_turn;
} PokemonAttackRecord;
```

Append only at the native equivalent of Showdown `gotAttacked`, after a move
has reached `moveHit`; misses, immunities, Protect, reflected-away parents, and
Snatched-away parents must not create the record
(`data/mods/gen3/scripts.ts:465-504`, `sim/pokemon.ts:919-934`). Preserve the
most recent record across turns while its source remains active, set
`this_turn=false` at turn setup, remove records whose source is no longer
active, and clear the target's history on switch
(`sim/battle.ts:2328-2335`, `sim/pokemon.ts:1549-1557`). Mirror Move also needs
the source Pokemon's selected `lastMove` identity and current moveset check;
do not substitute `lastMoveUsed`, since called moves update the latter but not
`moveUsed` (`sim/pokemon.ts:912-929`).

The history capacity must cover all successful opposing attacks retained while
their sources remain active. For the current one-active-per-side runtime, one
latest record is observationally sufficient for `getLastAttackedBy`; encode
that as a generation/runtime geometry invariant. Expand to a fixed ring when
multi-active formats or other consumers require older records.

## Phased implementation order

1. **Frame substrate and proof hooks.** Broaden effect provenance, add the
   fixed stack, invocation traces, transactional overflow, and an inner
   interpreter entry. Route ordinary selected moves through outer -> inner
   without changing results. Differentially prove the existing corpus and
   exact draw labels before enabling a caller.
2. **Magic Coat.** Generate `reflectable`; install its duration-1 volatile;
   implement the priority-2 `TryHit` handler as `CALL_MOVE` plus parent null
   cancellation. Prove swapped target, one bounce, PP, handler order, and no
   parent accuracy draw.
3. **Attacked-by/last-move provenance and Mirror Move.** First prove lifecycle
   independently (hit/miss/block, turn boundary, switch). Then generate the
   Gen 3 exclusion predicate and invoke the recorded move through the same
   inner entry.
4. **Snatch.** Generate `snatch`; install its duration-1 volatile; implement
   `Any/PrepareHit` at priority -1. Remove the volatile before child push,
   attach Snatch source effect, and null-cancel the parent.
5. **Generated graph/capability gate.** Fail initialization if executable
   caller handlers, required flags, source-effect kinds, frame capacity, or
   attacked-by geometry are inconsistent. Only then reclassify affected
   descriptors.

Magic Coat precedes Mirror Move and Snatch because it exercises explicit
retargeting and parent cancellation with the smallest provenance surface.
Mirror Move then establishes persistent history. Snatch is last because it
combines `ANY` discovery, mutation-before-re-entry, and cancellation.

## Verification gates

Focused native tests must establish:

- selected -> inner routing is observationally unchanged;
- nested frame push/pop restores the parent and overflow rolls the complete
  battle back byte-for-byte;
- each parent/child trace and every PRNG draw has correct invocation lineage;
- Magic Coat swaps user/target, charges only original PP, bounces once, and
  cancels before parent accuracy;
- Protect priority 3 cancels before Magic Coat priority 2;
- Mirror Move accepts and rejects the exact Gen 3 eligibility cases, charges
  no copied PP, resolves a new target, and follows attacked-by lifecycle;
- Snatch removes itself before re-entry, steals only flagged moves, cannot
  steal its own child, and leaves an ineligible move untouched until expiry;
- capacity - 1, exact capacity, and capacity + 1 paths are explicit, with the
  last producing transactional failure and zero leaked draw/event/state
  mutation.

Differential cases must compare normalized legal choices, queue (which gains
no child action), ordered handler frames, invocation lineage, labeled draws,
events, canonical state, requests, and terminal result at every stable
boundary. Include at least one composed chain (Mirror Move -> reflectable move
-> Magic Coat), hit and miss seeds for called numeric-accuracy moves, switches
on both provenance source and target, and two same-turn eligible moves after a
single Snatch.

Passing only final boosts is insufficient: the defining contract includes
which frame owns PP, targeting, cancellation, handler order, and each PRNG
draw.
