# Endless Battle Clause terminal policy

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Pinned Showdown evaluates Endless Battle Clause in `Battle.nextTurn` after the
turn increment and trapped-state discovery, but before the next request and its
PRNG work. It is distinct from Showdown's universal turn cap. The clause does
nothing through turn 100. It then requires both active sides to be stale, at
least one through an external source, and does not activate if both sides can
switch to a living non-stale party member.

When the clause activates, Showdown inspects the initially submitted sets. A
side is a cycle owner when its initial held item is a restorative berry and its
initial ability or moveset can restore that item through Harvest, Pickup, or
Recycle. Exactly one cycle owner loses; otherwise the battle ties. The native
policy intentionally preserves the pinned party-scan behavior rather than
inventing a cleaner rule.

Staleness is mutable battle state, not item metadata:

- restorative item consumption commits pending staleness to persistent
  staleness;
- item acquisition stages internal pending staleness;
- losing the held item clears pending staleness;
- an opposing Skill Swap marks external, switch-scoped staleness;
- switching clears only switch-scoped staleness.

## Native ownership

- `PokemonTerminalPolicy` in `native/pokemon.h` is the resolved format-policy
  input.
- Generated item and ability semantic flags describe restorative items and
  item-cycling capabilities without exposing Gen 3 IDs to the kernel.
- `native/pokemon_kernel/move.inc` owns next-turn bookkeeping and generic
  terminal-policy evaluation.
- `native/pokemon_kernel/condition_install.inc` owns staleness transitions at
  item consumption and opposing Skill Swap.
- `native/pokemon_kernel/switch.inc` owns switch-scoped teardown.
- `native/pokemon_kernel/api.inc` enforces the order: bookkeeping, request/trap
  projection, terminal policy, then nonterminal next-turn PRNG.

Bundle validation rejects malformed terminal policies before mutation or PRNG
consumption. The Ocean ABI remains fixed-capacity and heap-free.

## Evidence

`native/test_pokemon.c` proves the threshold, internal-only negative, legal
escape, unique and dual cycle-owner outcomes, universal turn cap, atomic bundle
rejection, and post-terminal PRNG staging. The generated data tests cover the
restorative and cycle-owner traits.

`verify/cases/derived/endless-battle-recycle-skill-swap-winner.json` is a legal
101-turn scenario with natural PP exhaustion and recycling. It injects no
battle state and agrees with pinned Showdown at all 102 stable boundaries,
including the terminal result. The verifier projection exposes persistent,
pending, and volatile staleness so agreement is checked before the winner alone
could hide an earlier divergence.

The complete 3,084-boundary differential corpus also agrees exactly. Its newly
visible staleness fields caught and forced two generic repairs: item theft now
uses the common take/set acquisition boundary, and forced-replacement turn
resumption now uses the same request/terminal/PRNG staging as every other
next-turn entry.

The descriptor map binds this evidence to `endlessbattleclause`, `standardag`,
and `standard`. The latter two are supported only because their flattened child
rules, including this terminal policy, are all supported.
