# Showdown generation boundary audit

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## The useful abstraction

Showdown does not construct a battle from an independently chosen generation,
data set, and format. A format selects a mod (`[Gen 3] OU` selects `gen3`), and
`Battle` resolves that selection into one coherent object graph:

```text
format
  -> modded Dex (effective generation data + generation scripts)
  -> recursively flattened RuleTable
  -> battle state machine
```

The relevant source boundaries are:

- `config/formats.ts:4283`: `[Gen 3] OU` declares `mod: 'gen3'` and its rules.
- `sim/dex.ts:166-180`: `forGen` and `forFormat` select a `ModdedDex`.
- `sim/dex.ts:490-672`: `loadData` recursively inherits tables, applies explicit
  entry overrides/deletions, sets `gen`, and runs the mod initializer.
- `data/mods/gen3/scripts.ts:1-20`: Gen 3 inherits Gen 4, declares `gen: 3`, and
  derives the pre-split physical/special move category in `init`.
- `sim/dex-formats.ts:739-990`: `getRuleTable` recursively resolves rules,
  bans, repeals, values, conflicts, and complex bans into one effective table.
- `sim/battle.ts:400-441`: the constructor obtains the Dex and RuleTable from
  the format, installs generation/format script overrides, then constructs the
  ordinary queue/actions/state-machine objects.

The semantic shape worth copying is therefore **selection followed by
resolution**: a public format identity resolves atomically to effective data,
generation mechanics, runtime geometry, and effective rules. The generic
battle machine consumes only that resolved product.

Our `PokemonResolvedBundle` already has the right top-level shape:

```text
PokemonResolvedBundle = {
  PokemonData,
  PokemonGeneration,
  PokemonFormat,
  PokemonFormatManifest
}
```

`pokemon_battle_init` also correctly rejects mixed-generation components
before state mutation or PRNG consumption. Keep queue construction, phase
transitions, handler discovery, and effect interpretation in `pokemon.c`;
put only genuinely generation-dependent policy/arithmetic in
`PokemonGeneration`; keep descriptor facts in generated `PokemonData`.

## Adaptation for static C and Ocean

Do not copy Showdown's runtime inheritance, dynamic object merge, mutable
callback dictionaries, filesystem mod discovery, or per-battle method
replacement. They solve dynamic TypeScript loading, not battle semantics, and
would obscure ownership and impede fixed-capacity vectorization.

Instead, reproduce their *effective result* at generation time:

1. resolve the pinned mod inheritance and format RuleTable in the verifier;
2. emit immutable, generation-local C descriptors and small typed rule hooks;
3. bind compatible components in one immutable resolved bundle;
4. let each Ocean instance contain only mutable battle state and fixed-capacity
   work stacks.

This preserves Showdown's important distinction: mod/generation selects
mechanics and data, while format/rules select legality and battle policy.

## Corrected boundary mismatch

`PokemonFormat` previously mixed two different axes. Its team size,
`active_per_side`, and target normalization describe runtime geometry, while
`sleep_clause` and `freeze_clause` are effective format rules. Consequently
the constants named `POKEMON_SINGLES_{1,2,3,6}_FORMAT` were not reusable singles
formats: all silently meant clause-enabled Gen 3 singles. That differs from
Showdown, where the same Gen 3 mod can run formats with different resolved
RuleTables.

The native boundary now makes this invariant explicit:

- geometry/target topology remains in a reusable runtime-format record;
- battle-policy flags are generated from the resolved format
  manifest/RuleTable;
- `PokemonResolvedBundle` binds geometry, policy, and manifest together, and
  initialization verifies policy-to-manifest identity as well as generation.

This is a boundary correction, not a request for a generic runtime rule
language. The two booleans remain compact typed fields in
`PokemonFormatPolicy`, rather than a supposedly generic singles geometry
record.

The existing `manifest->game_type == SINGLES` and `active_per_side == 1`
checks are an honest current capability restriction. They should remain
fail-closed until doubles/VGC queue and targeting semantics exist, rather than
being generalized structurally ahead of those semantics.
