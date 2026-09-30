# Stockpile family: one bounded counter, three declarative moves

The Gen 3 Stockpile family is implemented as one generated bounded-counter
condition plus ordinary move-owned handlers. It is not a resolver for the
three move names.

## Pinned Showdown semantics

At revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`:

- `data/mods/gen3/moves.ts#stockpile` replaces modern defensive boosts with an
  indefinite, `noCopy` counter whose Start value is one and whose Restart
  value caps at three;
- `data/moves.ts#spitup` requires that counter, uses `layers * 100` BasePower,
  and removes the condition in `AfterMove`, including after immunity;
- the resolved Gen 3 `swallow` inherits `data/mods/gen4/moves.ts#swallow`, so
  it requires Stockpile even when called through Snatch; its inherited Hit
  callback heals one quarter, one half, or all maximum HP and then removes the
  condition;
- `sim/battle-actions.ts#runMove` runs `AfterMove` once at the selected-action
  boundary using the final active move. A called Spit Up therefore owns that
  event after the caller's Hit processing, not at each nested invocation.

These resolved Gen 3 semantics contradict the modern upstream tests for
Stockpile stat boosts and for a Snatched Swallow healing a snatcher without
Stockpile. The native cases port the Gen 3 denotation, not those modern
assertions.

## Native boundary

Generated data supplies the three move descriptors, Stockpile condition
identity, ordered handler programs, and the immutable three-entry Q12 heal
policy. The generic kernel supplies:

1. bounded condition Start/Restart counters and switch cleanup;
2. move-owned `Try` predicates over installed condition state;
3. numeric BasePower relay from a counter;
4. counter-indexed healing with Gen 3 modifier rounding;
5. generic volatile removal and condition End dispatch;
6. selected-action `AfterMove` ownership by the final called move;
7. Snatch re-entry before the called move's own `Try` predicate.

The generated condition rule carries `no_copy = 1`. The focused test proves
that policy bit and its validated descriptor identity; Baton Pass remains a
separate unsupported transfer family and must consult the same generic rule
when implemented.

## Verification

Focused native evidence:

- `test_stockpile_counter_power_and_heal_family` proves counter values and
  cap, absence of modern Defense/Special Defense boosts, dynamic Spit Up
  damage, exact odd-HP heal rounding, cleanup, resolved move target, `noCopy`,
  and invariants;
- `test_counter_heal_policy_validation_is_atomic` proves malformed generated
  heal policies fail before mutation or PRNG consumption.

Pinned-oracle differential evidence:

- `stockpile-cap-spit-up`, `stockpile-switch-clears`
- `spit-up-immune-consumes`, `spit-up-without-stockpile`
- `swallow-layer-1`, `swallow-layer-2`, `swallow-layer-3`, and
  `swallow-full-hp-cleanup`, `swallow-without-stockpile`
- `metronome-spit-up-after-move`
- `snatch-stockpile-transfer`, `snatch-swallow-gen3-rejection`

The family promotes exactly twelve inventory records: three moves, the
Stockpile volatile, and eight move/condition callback owners. No Baton Pass or
other transfer-mechanic claim follows from this slice. The complete corpus
matches the pinned oracle at 2,522 stable boundaries, and both oracle and
native replays are byte-identical.
