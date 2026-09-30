# Recharge initialization and Sleep Talk admission audit

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This read-only audit covers the remaining condition-lifecycle records in the
live unsupported inventory other than Curse. It distinguishes inventory
records from semantic families: neither record requires another condition
state machine.

## Exact unsupported records

There are exactly two relevant records in `descriptor-map.json`:

| Inventory record | Effective owner | Missing denotation |
| --- | --- | --- |
| `condition.mustrecharge.onStart` | shared `mustrecharge` volatile | emit the recharge-start notification after successful installation |
| `move.sleeptalk.onTryHit` | Sleep Talk | reject while the user owns either Choice Lock or Encore |

The first record is one of B's eight live records. The second is not a typed
condition-lifecycle record: both conditions already exist and are proven. It
is a move-owned admission orphan and should be owned by the move admission or
child-invocation cluster. Thus B's mechanically correct remainder is Curse's
seven records plus `condition.mustrecharge.onStart`; the graph prose should not
count Sleep Talk toward B.

## Recharge initialization

### Showdown control flow

`data/conditions.ts:364-378` defines one resolved condition:

- duration 2;
- `onLockMove: 'recharge'`, which makes `Pokemon#getMoves` return the synthetic
  Recharge choice (`sim/pokemon.ts:965-973`);
- priority-11 `onBeforeMove`, which emits `cant`, removes `mustrecharge`, also
  removes `truant`, and returns `null`;
- `onStart`, whose only effect is the protocol notification
  `this.add('-mustrecharge', pokemon)`.

The four legal Gen 3 producers are Hyper Beam, Blast Burn, Frenzy Plant, and
Hydro Cannon. Their resolved self effect reaches the ordinary
`BattleActions#runMoveEffects` volatile installation path
(`sim/battle-actions.ts:1207,1257-1259`). There is no additional initialization
state or PRNG in `onStart`.

### Existing native coverage and exact gap

The native runtime already has the complete behavioral condition product:

- all four generated move descriptors apply the same after-move
  `POKEMON_EFFECT_ADD_VOLATILE`;
- the generated condition rule supplies duration and forced synthetic choice;
- request projection forbids switching and exposes Recharge;
- the generated priority-11 `BeforeMove` handler consumes the condition without
  another PP deduction;
- `test_recharge_synthetic_hard_lock_lifecycle` covers all four producers,
  connected installation, forced request, consumption, miss/no-installation,
  PP ownership, and last-move preservation;
- `recharge-connected`, `recharge-blast-burn`,
  `recharge-frenzy-plant`, and `recharge-hydro-cannon` are legal differential
  evidence.

The sole gap is descriptor ownership for the protocol-only Start callback. The
smallest honest closure is a generated, zero-program `Start` descriptor owned
by the `mustrecharge` condition, deliberately left unbound from semantic
dispatch. The pinned observer proves that its only denotation,
`-mustrecharge`, is outside the canonical native event projection; binding the
descriptor caused native to invent a structural handler record absent from the
oracle. The kernel therefore gains neither a recharge branch nor new state.

### Proof basis

The focused assertion requires the generated Start descriptor, exact condition
owner/route, zero program length, and absence of an owner binding. The existing
four producer fixtures prove condition installation, request projection, and
zero extra draws. Do not create one case per producer: the focused test already
proves all producers share this condition.

## Sleep Talk inherited admission

### Showdown control flow

The effective Gen 3 descriptor composes two inherited layers:

- `data/mods/gen3/moves.ts:526-547` replaces `onHit` with the current-slot
  selector: exclude `nosleeptalk` and charge moves, sample uniformly, reject a
  selected zero-PP slot, and invoke the selected move without child PP;
- `data/mods/gen4/moves.ts:1207-1211` supplies the still-inherited `onTryHit`:
  `!pokemon.volatiles['choicelock'] && !pokemon.volatiles['encore']`.

The existing generator source-shape assertion checks Gen 3 `onTry` and `onHit`
but does not assert this inherited `onTryHit`. The native descriptor therefore
has generated Try and Hit handlers but no TryHit owner.

Choice Lock and Encore are not dependencies to implement. The native runtime
already represents both as ordinary typed volatiles, validates their payloads,
projects their request restrictions, and clears them on switch. What is missing
is a reusable move-program predicate meaning “reject when the discovered holder
owns any volatile in this generated set.” It should be a generated mask or
bounded list operand, not a Sleep Talk, Choice Band, or Encore identity test in
generic control flow.

One handler program should preserve Showdown's one-callback structure:

```text
TryHit(Sleep Talk, source owner)
  -> reject if source owns any of { Choice Lock, Encore }
  -> otherwise undefined success
```

Splitting it into two generated handlers would reproduce the boolean result
but lie about handler discovery and ordering. No PRNG belongs to this predicate.
Rejection occurs before `onHit`, so it consumes no `move.called_slot` draw and
never invokes a child. Normal parent PP staging remains owned by the generic
move pipeline.

### Existing native coverage and exact gap

`test_generated_current_slot_move_delegation` and the three core Sleep Talk
fixtures already prove sleep admission, eligible-slot sampling, no-candidate
failure, zero-PP selection, child provenance, child PP ownership, and invalid
plugin rejection. `sleep-talk-excludes-uproar` additionally proves resolved
eligibility flags. None proves the inherited Choice Lock/Encore TryHit gate.

The minimum legal differential basis is:

1. **Choice Lock:** an already-sleeping legal Choice Band user successfully
   uses Sleep Talk once, acquiring Choice Lock; on the next forced Sleep Talk,
   parent PP follows ordinary pre-hit staging, TryHit rejects, there is no
   called-slot draw, no child action, and the turn continues normally.
2. **Encore:** an already-sleeping Sleep Talk user acts and is legally Encored;
   the following forced/overridden Sleep Talk reaches the same TryHit rejection
   with no called-slot draw or child action.
3. **Negative recombination:** ordinary sleeping Sleep Talk with neither
   volatile still reaches the existing selector exactly. This can reuse
   `sleep-talk-current-slot-call` rather than adding a third fixture.

A focused test should also construct each volatile independently and together,
assert one discovered Sleep Talk TryHit handler, identical false result for
either/both, zero mutation/draws, and invalid operand rejection before battle
mutation.

## Dependencies and merge order

1. Close `condition.mustrecharge.onStart` first or in the same generator batch.
   It requires generated data and focused/structural evidence only; no kernel
   capability is missing.
2. Close `move.sleeptalk.onTryHit` next. Reuse existing Choice Lock/Encore state
   and add at most one generic volatile-set rejection operation plus one
   generated handler and owner binding.
3. Regenerate once, run the focused cases and full differential/replay,
   sanitizer, random, Ocean, generator-current, and classification gates, then
   reclassify only these two records.
4. Implement Curse afterward. Curse is a seven-record dual-path mechanic with
   type-dependent targeting, boost mutation, HP cost, and a persistent
   source-bound residual condition. It is substantially more architectural
   work, and neither orphan depends on it.

Closing both orphans before Curse reduces false coupling in node B and finishes
two already-built semantic families at minimal verification cost. It does not
justify any broader condition-lifecycle support claim.
