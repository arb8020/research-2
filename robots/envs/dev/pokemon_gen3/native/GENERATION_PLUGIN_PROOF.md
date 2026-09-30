# Resolved generation plugin boundary

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This document fixes the boundary between format selection, generated generation
data, generation policy, and the generic native battle kernel. It uses Pokemon
Showdown's mod architecture as the semantic reference, but does not reproduce
Showdown's dynamic TypeScript loading or callback replacement at runtime.

The native construction rule is:

```text
format selection
    -> build-time recursive mod and RuleTable resolution
    -> immutable flattened data + typed generation policy
    -> one validated resolved plugin bundle
    -> generic fixed-capacity PokemonBattle kernel
```

The bundle is the unit of compatibility. A generation number is metadata; it
is not a sufficient compatibility identity.

## Source model

`[Gen 3] OU` selects `mod: 'gen3'` and supplies its direct rules and bans in
`config/formats.ts:4282-4286`. `Dex.forFormat` reads the format's `mod` and
returns the corresponding data-loaded `ModdedDex` (`sim/dex.ts:176-180`). A
Showdown battle does not independently choose a data set, scripts object, and
rule table. Its constructor performs this sequence (`sim/battle.ts:414-432`):

1. resolve one format;
2. obtain one `Dex` with `Dex.forFormat(format)`;
3. read `gen` from that `Dex`;
4. resolve the format's `RuleTable` through that `Dex`; and
5. install the resolved scripts, followed by explicit format overrides.

The constructor then creates the field, sides, PRNG, queue, and action runner
from that coherent selection (`sim/battle.ts:440-460`). Effective rule event
handlers are also installed from the same resolved table
(`sim/battle.ts:522-535`). This is the coherence property the native bundle
must preserve.

### Mod data resolution

The source tables that participate in mod resolution are enumerated in
`sim/dex.ts:47-68`: abilities, rulesets, formats data, items, learnsets, moves,
natures, species, scripts, conditions, type data, and related generated data.
`ModdedDex.loadData` implements the recursive resolution
(`sim/dex.ts:604-683`):

- `Scripts.inherit` selects the parent mod (`sim/dex.ts:611-624`). The pinned
  mainline chain for Gen 3 is Gen 3 -> Gen 4 -> Gen 5 -> Gen 6 -> Gen 7 ->
  Gen 8; it is not a direct merge with the current base generation.
- An omitted table may reuse the resolved parent table
  (`sim/dex.ts:638-645`). A native generator must nevertheless emit a complete
  immutable result rather than preserve this aliasing as runtime inheritance.
- An absent child entry inherits the parent entry (`sim/dex.ts:646-652`).
- A child entry equal to `null` deletes the inherited entry
  (`sim/dex.ts:647-650`).
- An entry with `inherit: true` shallowly overlays its fields on the parent
  entry (`sim/dex.ts:653-669`). The embedded move `condition` object has one
  additional nested overlay rule (`sim/dex.ts:658-665`).
- A callback explicitly assigned `undefined` replaces an inherited callback
  with no callback. Gen 3 Bide does this for `onAfterSetStatus`
  (`data/mods/gen3/moves.ts:57-64`); Gen 3 Lightning Rod does it before adding a
  differently scoped redirect handler (`data/mods/gen3/abilities.ts:87-96`).
- `init` is deliberately captured before inheritance and only the selected
  mod's local initializer is invoked after its data cache is installed
  (`sim/dex.ts:611-614,674-680`). Parent transformations are already present in
  resolved parent data; parent initializers are not replayed as inherited child
  callbacks.

The last point matters for Gen 3. Its local initializer derives the
physical/special category of every damaging move from its type
(`data/mods/gen3/scripts.ts:1-15`). Generated C must contain this post-init
result. Category derivation is not a runtime kernel branch and is not a typed
generation callback.

Partial data overrides and algorithm overrides are distinct. For example,
Gen 3 changes only Absorb's PP and Acid's secondary descriptor
(`data/mods/gen3/moves.ts:6-17`), while its scripts replace algorithms such as
action speed and staged damage (`data/mods/gen3/scripts.ts:16-136`). Showdown
can install resolved `pokemon`, `actions`, `queue`, `field`, and `side` script
namespaces dynamically (`sim/pokemon.ts:309-318`,
`sim/battle-actions.ts:52-57`, and `sim/battle-queue.ts:133-141`). Native code
must instead represent only genuine algorithmic differences as typed policy
or operation fields. An override that exposes a reusable operation belongs in
the generic kernel; an arbitrary callback dictionary does not belong in the
native plugin.

### RuleTable resolution

Rule resolution is a separate recursive operation, but it is performed by the
format-selected `Dex`. At its top level, `getRuleTable` redirects resolution to
the format's mod (`sim/dex-formats.ts:738-748`). It then:

- combines direct rules, bans, restrictions, unbans, and custom rules
  (`sim/dex-formats.ts:751-763`);
- applies repeals before recursive expansion (`sim/dex-formats.ts:771-781`);
- validates ordinary, value, and complex rules and their conflicts
  (`sim/dex-formats.ts:790-902`);
- recursively merges sub-rules, including multiple inheritance, complex bans,
  and unique validator hooks (`sim/dex-formats.ts:903-961`); and
- resolves numeric values, invokes rule validators, and caches the effective
  table (`sim/dex-formats.ts:965-991`).

Gen 3's `Standard` rule is itself a recursive ruleset
(`data/mods/gen3/rulesets.ts:1-10`). Therefore the native format manifest must
describe the effective resolved RuleTable, not only the five rule names and
ban list written directly on `[Gen 3] OU`.

## Native mapping

| Pokemon Showdown | Native runtime | Native owner |
| --- | --- | --- |
| `ModdedDex` after recursive inheritance and local `init` | flattened immutable `PokemonData` | generator and generated `gen3_slice_data.c` |
| generation `Scripts` overrides | typed `PokemonGeneration` policies and reusable kernel operations | generated/static generation plugin plus `pokemon.c` |
| move, ability, item, and condition callbacks | generated handler descriptors, owner bindings, and bounded effect programs | `PokemonData`; interpreted by `pokemon.c` |
| resolved `RuleTable` | `PokemonFormatManifest` plus battle-time `PokemonFormatPolicy` | generated format data and format selection |
| format-selected Dex and rules | one validated `PokemonResolvedBundle` (the resolved generation plugin) | format registry / battle initialization boundary |
| generic `Battle` | generic fixed-capacity `PokemonBattle` | `pokemon.c` |

The resolved plugin contains, directly or transitively:

- flattened species, moves, abilities, items, conditions, and type data;
- generated handler/effect programs and owner-binding indexes;
- typed formulas, staging policies, probability distributions, and condition
  policies for genuine generation-level algorithm differences;
- runtime format geometry and the effective format/rule manifest; and
- an explicit set of kernel capabilities required to interpret the bundle.

The generic kernel continues to own choice normalization, action queues,
handler discovery and ordering, requests and phases, move invocation, hit
loops, switching, faint draining, residual scheduling, tracing, PRNG ownership,
capacity preflight, rollback, and terminal resolution. The Ocean adapter
continues to expose reset, step, observations, actions, and vectorized storage;
it neither selects mechanics nor interprets handlers.

## Bundle invariants

`PokemonResolvedBundle` is currently the native aggregation point
(`native/pokemon.h:1000-1011`), and `pokemon_battle_init` validates it before
constructing the next battle or copying its seed (`native/pokemon.c:6944-6987`).
The enforced boundary must satisfy all of the following invariants:

1. **One selection identity.** Data, rules, handlers, format geometry, policy,
   and manifest carry or are covered by one immutable plugin identity. Matching
   `generation` bytes alone is insufficient: two separately generated bundles
   for the same generation must not be mixable.
2. **One resolved format identity.** The policy and runtime geometry are the
   ones selected by the manifest. A manifest pointer check alone does not prove
   that independently supplied geometry belongs to that format.
3. **Explicit kernel contract.** A versioned capability set states every
   operation the plugin requires. Unknown capabilities, missing required
   capabilities, and handlers requiring an undeclared kernel operation reject
   the bundle.
4. **Closed internal references.** Descriptor IDs, handler spans, program spans,
   event specifications, owner-binding spans, condition mappings, and type IDs
   are in range and refer only to members of the same plugin identity.
5. **Complete typed policy.** Every required function, finite distribution,
   staging selector, and condition policy is present and structurally valid.
   The kernel never supplies a guessed default.
6. **Validation is atomic.** Every bundle, capability, reference, format, and
   initial-team check that can fail does so before mutation, trace emission, or
   PRNG consumption. Failure leaves the destination battle byte-for-byte
   unchanged.
7. **Selection is stable.** A battle retains the validated resolved plugin for
   its lifetime. Its components cannot be substituted independently after
   initialization.

These are construction invariants, not hot-path compatibility checks. Once
initialization succeeds, the kernel operates on trusted immutable tables.

## Alternate proof plugin

The proof plugin is synthetic test data, not another game generation. It exists
only to demonstrate that the abstraction changes behavior through data and
typed policy while preserving one kernel.

It should reuse the smallest shared descriptor set needed by the fixtures and
deliberately differ from Gen 3 in four independent dimensions:

1. critical-hit probability;
2. ranged multihit outcome distribution;
3. damage rounding or modifier staging; and
4. one condition-duration policy.

Each fixture runs through the same public initialization, choice, queue, and
step functions against both plugins. Assertions cover the normalized choices,
queue and event trace, resulting canonical state, request/phase, and labeled
PRNG calls. A fixture changing one policy must differ only at that policy's
semantic boundary and its downstream consequences. In particular, tests must
show whether the changed policy consumes the same draw with a different
interpretation or intentionally changes draw ownership; an unlabeled final-HP
comparison is not sufficient proof.

Negative fixtures independently mix or corrupt:

- generation data versus generation policy;
- handler/program tables versus their data catalogs;
- runtime geometry versus format policy and manifest;
- same-generation components with different plugin identities;
- required capability versions and bits;
- required function pointers and finite distributions;
- handler, owner-binding, event, condition, and type-table spans; and
- post-flattening callback presence, replacement, and deletion expectations.

Every negative fixture snapshots the destination battle and PRNG/trace cursor,
calls initialization, expects `POKEMON_INVALID_CONFIGURATION`, and proves that
neither snapshot changed. The callback-flattening tests are generator tests:
they verify effective emitted records for inherited, deleted, overridden, and
post-init-derived values rather than attempting TypeScript inheritance at
runtime.

The existing Gen 3 focused, random, sanitizer, Ocean, replay, and exact
differential suites remain mandatory after the proof plugin is added. The
synthetic tests prove the abstraction boundary; only the pinned Showdown corpus
proves that the Gen 3 instance still has the intended behavior.

## Out of scope

This checkpoint does not select the next real generation and does not implement
a second incomplete game. It also does not add runtime mod inheritance, a
dynamic loader, JavaScript or Node to the submitted runtime, arbitrary callback
dictionaries, heap allocation, or generation/name/move-ID switches in generic
control flow. A later real generation must arrive as another independently
flattened and validated plugin using this same boundary.
