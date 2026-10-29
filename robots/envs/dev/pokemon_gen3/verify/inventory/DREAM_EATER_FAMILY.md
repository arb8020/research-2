# Dream Eater deferred-immunity family

The oracle is Pokémon Showdown revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`. This family proves the
reachable Gen 3 OU `move:dreameater` descriptor and
`event_hook:move.dreameater.onTryImmunity` inventory record.

## Authoritative semantics

- `data/mods/gen3/scripts.ts#tryMoveHit` is the authoritative Gen 3 hit
  pipeline. It determines natural and move-owned `TryImmunity` rejection,
  still performs the labeled accuracy check, then runs target `TryHit`. A
  pending immunity is reported after the accuracy stage, including when the
  accuracy check itself misses. Target `TryHit` runs only after an accuracy
  pass and can mask that pending immunity by blocking the move first. Thus an
  immune Dream Eater consumes one accuracy draw but no critical-hit or
  damage-roll draw; Protect can win over the pending immunity after that same
  accuracy draw.
- `data/mods/gen3/scripts.ts#Scripts.inherit` resolves Gen 3 through Gen 4.
  `data/moves.ts#dreameater` supplies the 100-power, 100-accuracy Psychic
  special move and one-half drain metadata, while
  `data/mods/gen4/moves.ts#dreameater` supplies the effective Gen 3
  `onTryImmunity`: the target must be asleep and must not have Substitute.
- `sim/battle.ts#damage` computes Gen 3 drain as at least one HP and otherwise
  `floor(actualDamage / 2)`. `sim/battle.ts#heal` runs `TryHeal` even when the
  recipient is already at full HP.
- `data/mods/gen4/abilities.ts#liquidooze` is the inherited Gen 3 Liquid Ooze
  handler. It explicitly excludes Dream Eater from drain reversal.

## Native boundary

`tools/generate_slice_data.js` verifies the resolved oracle shapes and emits
the immutable move, handler, and effect programs in
`native/gen3_slice_data.c`. Dream Eater's generated `TryImmunity` program
composes two generic predicates:

1. require the target's major status to be sleep;
2. require the target not to own the Substitute volatile.

`native/pokemon.h` defines those typed operations and `native/pokemon.c`
validates and interprets them. The generic hit pipeline records a rejected
move handler as a pending immunity, owns the accuracy draw, runs target
`TryHit` only on an accuracy pass, and then resolves the pending result unless
`TryHit` already blocked the move. On an accuracy miss, the pending immunity
is reported instead of the miss. Critical and damage-roll draws remain inside
admitted damage calculation.

The Liquid Ooze exception is data, not a Dream Eater branch in generic
control flow. Its generated `TryHeal` program begins with
`POKEMON_HANDLER_OP_GUARD_SOURCE_EFFECT_NOT`, whose operand encodes the
resolved Gen 3 Dream Eater move descriptor, before the generic immediate
damage and numeric-zero return operations.

This preserves the generation-plugin boundary: Gen 3 supplies flattened move
data, owner bindings, predicate programs, and the Liquid Ooze exception;
`native/pokemon.c` supplies only generation-neutral event dispatch, staged hit
resolution, drain/heal operations, and program interpretation. A later
generation can emit different resolved descriptors or programs without a
generation or move-name check in the kernel.

Bundle validation checks the new volatile predicate's event, owner, route,
operand, and program extent before mutation or PRNG consumption. The focused
atomic-rejection case deliberately corrupts that operand.

## Evidence

Focused native test:

- `native/test_pokemon.c#test_dream_eater_move_immunity_is_deferred_after_accuracy`

It checks the generated descriptor and both predicate operations, awake
rejection, a connected sleeping-target hit and drain, sleeping Substitute
rejection, exact accuracy/critical/damage-roll staging, and atomic rejection
of a malformed resolved bundle.

Seven legality-validated differential fixtures contribute 16 stable
boundaries:

- `dream-eater-awake-rejection`
- `dream-eater-sleeping-target`
- `dream-eater-full-hp-user`
- `dream-eater-liquid-ooze-exception`
- `dream-eater-dark-immunity`
- `dream-eater-protect`
- `dream-eater-substitute`

Together they distinguish an awake target, an admitted sleeping target,
full-HP drain, the Liquid Ooze exception, natural Psychic immunity, target
`TryHit` protection, and the conjunction of sleep with no Substitute. The
fixtures compare normalized choices, queues, handler order, canonical state,
events, and labeled PRNG consumption against the pinned oracle.

## Nonclaims

This evidence does not claim exhaustive enumeration of Dream Eater battle
states, correctness of every draining move or `TryImmunity` handler, support
for Comatose or post-Gen-3 mechanics, implementation of another generation,
complete-battle coverage, performance hardening, or release readiness. It
promotes only the two frozen Gen 3 OU inventory records named above; broader
runtime claims remain governed by the complete feature map and corpus gates.
