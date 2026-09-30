# Uproar semantic family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
Format: `gen3ou` singles.

## Inventory closure

This family owns exactly seven currently unsupported records:

- move `uproar`;
- volatile condition `volatiles.uproar`;
- `move.uproar.onTryHit`;
- `move.uproar.condition.onStart`;
- `move.uproar.condition.onResidual`;
- `move.uproar.condition.onEnd`;
- `move.uproar.condition.onAnySetStatus`.

No record moves out of unsupported until its native boundary, focused test,
legal differential evidence, and source mapping all exist.

## Pinned Showdown boundary

The effective descriptor is resolved recursively through
`data/moves.ts#uproar`, the historical overrides in
`data/mods/gen5/moves.ts#uproar` and `data/mods/gen4/moves.ts#uproar`, and the
duration override in `data/mods/gen3/moves.ts#uproar`. The resulting Gen 3
move is a 50-power Normal physical move with numeric 100 accuracy. Its flags
are `protect`, `mirror`, `sound`, `metronome`, and `nosleeptalk`; notably it
does not bypass Substitute.

- after type immunity, global TryHit admission, and accuracy succeed, the
  move-owned TryHit callback wakes sleeping active Pokemon on both sides;
- the self volatile draws a uniform duration in `[2, 6)`;
- LockMove forces Uproar while the condition remains;
- Residual runs at order 10, sub-order 11, and its inherited fallback branch
  removes the lock if the holder's last move is Struggle;
- AnySetStatus globally rejects new sleep on either active;
- natural expiry dispatches End; forced switching and faint cleanup clear the
  condition silently without dispatching End.

The inherited Throat Chop branch is unreachable in Gen 3 OU because no legal
Gen 3 creator can install that later-generation condition. The resolved Dex
can still construct a generic `throatchop` condition identity, so the proof is
about the absence of a legal creation path, not the absence of an identity.
The inherited Struggle branch also appears unreachable through legal choices:
LockMove is resolved before the no-enabled-move fallback and locked executions
bypass ordinary PP deduction. Retain it as a focused constructed-state
invariant rather than claiming a legal differential scenario.

## Smallest native abstraction

Keep the condition as a generated descriptor over existing generic duration,
residual, LockMove, End, and teardown machinery. The missing reusable kernel
operations are:

- clear a generated major-status mask from living active Pokemon in canonical
  battlefield order;
- reuse the existing event-status-mask guard for SetStatus before ordinary
  null cancellation.

The global listener should use ordinary `ANY` handler discovery. Uproar IDs,
sleep IDs, duration bounds, and handler ownership belong in generated Gen 3
data or typed operands, not generic control flow.

## Branch-complete evidence basis

Legal differential cases must prove:

1. wake a sleeping foe after a faster foe uses Rest; a sleeping holder cannot
   legally select Uproar and Sleep Talk excludes it;
2. attempted new sleep on the holder and on the foe is rejected;
3. a non-sleep status passes through the same listener;
4. labeled duration draws at both endpoints, two and five;
5. locked continuation and natural expiry/End;
6. forced drag and faint cleanup remove the condition silently; voluntary
   switching is unavailable while LockMove is active;
7. miss, Protect, and Ghost immunity do not wake or install;
8. a sleeping target behind Substitute wakes before damage is intercepted;
9. Metronome-called Uproar fabricates a forced Uproar request even when the
   move is absent from the holder's slots;
10. status residual sub-order 6 precedes Uproar sub-order 11 without an early
    faint drain;
11. deterministic replay and recombination with existing Sleep Clause,
    Insomnia/Vital Spirit, and Sleep Talk behavior.

Focused native tests must separately prove global handler discovery order,
status rejection before mutation or sleep-duration PRNG, active wake order,
duration ownership, and malformed-bundle rejection.

Soundproof is not a legal differential branch in pinned `gen3ou`: every Gen 3
species that carries it is rejected by the format validator because Soundproof
is banned. The resolved source still establishes the sound-move immunity; this
family records that branch as validator-backed unreachable evidence rather
than fabricating an illegal fixture.

## Differential fixture set

The legal oracle corpus consists of these eleven cases:

- `uproar-wake-rest-duration2-expiry`;
- `uproar-duration5-rest-block`;
- `uproar-protect-no-install`;
- `uproar-ghost-sleeper-immunity`;
- `uproar-holder-sleep-nonsleep-recombination`;
- `uproar-forced-drag-silent-cleanup`;
- `uproar-poison-faint-residual-order`;
- `uproar-accuracy-miss-no-wake`;
- `uproar-substitute-wakes-before-intercept`;
- `metronome-uproar-absent-slot-lock`;
- `sleep-talk-excludes-uproar`.

Together they contribute 27 requested boundaries. The full normalized corpus
currently compares 2,693 boundaries exactly. The native focused test is
`test_uproar_global_status_and_lock_lifecycle`; it also covers the constructed
both-active sleep state, natural End dispatch, and atomic rejection of a
malformed generated wake-status mask.
