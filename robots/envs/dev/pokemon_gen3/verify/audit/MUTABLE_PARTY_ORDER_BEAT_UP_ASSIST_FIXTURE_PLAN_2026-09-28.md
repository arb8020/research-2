# Mutable party order, Beat Up, and Assist fixture plan

Pinned Pokémon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is fixture design only. It changes no native code, generated data,
observer, feature map, or support classification.

## Source boundary

Pinned `sim/battle-actions.ts#switchIn` swaps the incoming Pokémon and outgoing
Pokémon inside `side.pokemon`:

```text
oldActive.position = pokemon.position
pokemon.position = active position
side.pokemon[pokemon.position] = pokemon
side.pokemon[oldActive.position] = oldActive
```

`Side.pokemon` is therefore current positional party order, not immutable team
order. Starting from `[A, B, C]`, these legal switches produce:

```text
switch B in       [B, A, C]
switch C in       [C, A, B]
switch A back     [A, C, B]
```

The verifier intentionally normalizes canonical Pokémon state back into
original roster order. The permutation remains observable through normalized
switch choices: on the last step Showdown source choice `switch 2` means A's
current position, while the stable native choice is `switch 1`, A's original
roster slot. This is already the established `source_choices` versus `choices`
adapter convention.

Two consumers read the mutable order directly:

- `data/mods/gen3/moves.ts#beatup` filters
  `pokemon.side.pokemon` in current order to contributors that are neither
  fainted nor statused. It then consumes that ordered array once per hit. Each
  contributor supplies its species base Attack; the defender supplies species
  base Defense. Gen 3 also changes Beat Up to `???` type and Special category.
- inherited `data/moves.ts#assist` iterates `target.side.pokemon` in current
  order, skips the user, appends every eligible move slot without deduplicating,
  samples the resulting vector, and re-enters the selected move.

Assist is banned as a submitted move by pinned Gen 3 OU (`banlist: Assist`). A
direct-Assist fixture is therefore illegal and must not be added. Gen 3 marks
Assist `metronome: 1`, so a legal Metronome user can call Assist. The Assist
fixtures below use that legal path.

## Common legal sets

Use level 100, Hardy nature, one HP EV, default IVs, and no items unless noted.
These sets were validated with pinned `TeamValidator.get('gen3ou')`:

- Smeargle / Own Tempo: Beat Up + Splash, or Metronome
- Machop / Guts: Bulk Up
- Alakazam / Synchronize: Recover
- Charmander / Blaze: Ember
- Rattata / Run Away: Tackle
- Tauros / Intimidate: Tackle or Rest
- Gengar / Levitate: Explosion
- Blissey / Natural Cure: Soft-Boiled + Protect

Use Blissey as the opposing passive target. Its HP keeps every multi-hit and
called-move scenario nonterminal.

## Fixture 1: permutation boundary

ID: `party-order-three-way-switch-roundtrip`

P1 original team: Smeargle, Machop, Alakazam. P2: Blissey.

```text
source_choices                 normalized choices
switch 2 / move 1              switch 2 / move 1
switch 3 / move 1              switch 3 / move 1
switch 2 / move 1              switch 1 / move 1
```

This is the smallest three-member sequence that distinguishes current party
order from original roster order after switching the original lead back in.
A two-member away/back sequence restores the original order and cannot expose
the invariant.

Assertions:

- legal switch targets remain exactly the two nonactive, nonfainted roster
  members after every step;
- the third Showdown source choice addresses current position 2 while the
  normalized choice addresses original roster slot 1;
- the final active Pokémon is original slot 1;
- deterministic replay preserves the source-to-normalized choice mapping.

No PRNG is required. This fixture proves the party-position permutation
boundary independently of Beat Up or Assist.

## Fixture 2: Beat Up consumes current party order

ID: `beat-up-current-party-order`

P1 original team: Smeargle (Beat Up + Splash), Machop, Alakazam. Perform the
same three-switch round trip, then use Beat Up:

```text
source_choices                 normalized choices
switch 2 / move 1              switch 2 / move 1
switch 3 / move 1              switch 3 / move 1
switch 2 / move 1              switch 1 / move 1
move 1   / move 1              move 1   / move 1
```

The contribution order must be Smeargle, Alakazam, Machop (`[A, C, B]`), not
original team order Smeargle, Machop, Alakazam. Their base Attack values are
20, 50, and 80, so equal damage rolls produce distinguishable ordered damage
events. `beatupnicknamesmod` suppresses contributor-name protocol messages in
Gen 3 OU; do not rely on nicknames as evidence.

Force and assert:

- one `move.accuracy` draw, range 100;
- three `move.critical` draws, range 16, all noncritical;
- three `move.damage_roll` draws, range 16, all equal;
- exactly three connected hits and the ordered HP deltas implied by base
  Attack 20 → 50 → 80 against Blissey's base Defense;
- no multihit-count selection draw: contributor count determines hit count.

This fixture proves ordered consumer behavior separately from contributor
eligibility.

## Fixture 3: Beat Up filters fainted and statused contributors

ID: `beat-up-fainted-statused-contributors`

P1 original team:

1. Smeargle: Beat Up
2. Gengar: Explosion
3. Machop: Bulk Up, initialized paralyzed
4. Tauros: Rest

P2: Blissey with Soft-Boiled and Protect.

Sequence:

```text
source_choices                 normalized choices
switch 2 / move 1              switch 2 / move 1
move 1   / move 2              move 1   / move 2
switch 2 / null                switch 1 / null
move 1   / move 1              move 1   / move 1
```

Gengar self-faints into Protect, then the forced replacement restores Smeargle.
At Beat Up resolution, Gengar is fainted and Machop is statused; only Smeargle
and Tauros contribute, in that order.

Force and assert one accuracy draw, two noncritical draws, and two equal damage
rolls. Assert exactly two hits with base-Attack contributions 20 then 100.
Assert that the fainted and statused party records remain in party order but
are absent from the contributor snapshot. This separates membership/filtering
from positional permutation and from multihit execution.

## Observer prerequisite for Assist

The current test-only observer labels Metronome's selection but not inherited
Assist's `this.sample(moves)`. Before adding the Assist fixtures, wrap only that
sample call in the observer patch with:

```text
verificationRandom('move.delegation.selection', () => this.sample(moves))
```

Do not sort or deduplicate the Assist vector. The vector's current party and
move-slot order is the behavior under test. After the observer change,
occurrence 1 is Metronome's selection and occurrence 2 is Assist's selection.
The pinned Gen 3 Metronome pool has range 336; Assist is index 257 (zero-based),
between Wish and Ingrain when sorted by move number.

Regenerate the observer checksum and prove patch reproducibility before these
fixtures enter the differential corpus.

## Fixture 4: legally reached Assist consumes current party order

ID: `assist-metronome-current-party-order`

P1 original team:

1. Smeargle: Metronome
2. Charmander: Ember
3. Rattata: Tackle

Perform the three-switch round trip from fixture 1, then use Metronome. Current
party order is Smeargle, Rattata, Charmander, so Assist's eligible vector is
`[Tackle, Ember]`; original team order would produce `[Ember, Tackle]`.

Force:

```text
move.delegation.selection occurrence 1: range 336, result 257  # Metronome -> Assist
move.delegation.selection occurrence 2: range 2,   result 0    # Assist -> Tackle
move.accuracy             occurrence 1: range 100, non-miss
move.critical             occurrence 1: range 16,  noncritical
move.damage_roll          occurrence 1: range 16,  fixed
```

Assert that the called move is Tackle, its PP is not deducted from Rattata, and
its ordinary hit pipeline owns the accuracy, critical, and damage-roll draws.
This distinguishes mutable party order from original team order through an
observable consumer.

## Fixture 5: Assist preserves duplicate move-slot weight

ID: `assist-metronome-duplicate-slot-weight`

P1 original team:

1. Smeargle: Metronome
2. Rattata: Tackle
3. Tauros: Tackle
4. Charmander: Ember

The legal Assist vector is `[Tackle, Tackle, Ember]`; duplicate move IDs remain
two selectable entries. Use Metronome twice against Soft-Boiled Blissey.

Force:

```text
occurrence 1: range 336, result 257  # Metronome -> Assist
occurrence 2: range 3,   result 1    # second Tackle slot
occurrence 3: range 336, result 257  # Metronome -> Assist
occurrence 4: range 3,   result 2    # Ember slot
```

Also force/assert each selected damaging move's accuracy, critical, damage-roll,
and Ember secondary draw. The range-three selections are the direct proof that
Assist weights move slots rather than unique move IDs. Assert Tackle on the
first turn and Ember on the second.

## Why five fixtures

- Fixture 1 proves party permutation without coupling it to a move family.
- Fixture 2 proves ordered Beat Up consumption.
- Fixture 3 proves Beat Up's faint/status eligibility snapshot.
- Fixture 4 proves legally reached Assist reads current positional order.
- Fixture 5 proves Assist preserves duplicate slot multiplicity and owns a
  separately labeled selection draw.

Combining these would save fixture count but obscure whether a divergence comes
from switch normalization, party mutation, eligibility, ordered multihit
execution, nested move delegation, or duplicate weighting. Five is the smallest
locally diagnosable basis under the current stable-boundary contract.

## Generator verification requirements

The future fixture generator should:

1. pin and verify the Showdown revision;
2. validate every exported team with `TeamValidator.get('gen3ou')`;
3. reject a direct Assist set as a generator invariant;
4. run every source-choice sequence against Showdown, including forced
   replacement with a `null` opponent choice;
5. assert the expected `side.pokemon` species order after each switch;
6. assert the exact Beat Up contributor snapshot or ordered per-hit damage;
7. assert the exact Assist candidate vector before sampling, including
   duplicates;
8. normalize fixtures through `normalizeCase`;
9. regenerate into an isolated output directory and byte-compare all JSON/team
   artifacts;
10. run the observer oracle after its Assist label patch, then require exact
    deterministic replay.

Passing these fixtures is evidence for the party-order and consumer boundaries,
not a support claim. Classification still requires the native abstraction,
focused C tests, generated-data mapping, differential evidence, and pinned
source mapping.
