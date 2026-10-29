# Generation boundary

The native battle kernel owns control flow; a generation plugin owns arithmetic
or policy whose answer changes between generations. Generated data owns facts
about individual species, moves, abilities, items, and type matchups.

## Ownership map

| Owner | Responsibilities |
| --- | --- |
| `pokemon.c` | Choice validation, action queues, requests and phases, targeting, handler discovery, immunity/accuracy/TryHit staging, effect execution, hit loops, faint and replacement draining, residual work scheduling, tracing, capacity checks, and atomic rollback. |
| `PokemonGeneration` / `gen3_rules.c` | Cross-move arithmetic and policy shared by the generation: base damage, critical rules, nonstandard damage formulas, residual formulas, condition/stall policy, Toxic stage cap, and weather-damage staging. |
| generated `gen3_slice_data.c` | Species/types/weights, flattened move descriptors (including per-weather move mutation policy), immutable weather-form and target-weight power policies, effect programs, abilities/items/handlers, the type chart, and the resolved format manifest/RuleTable. |
| Ocean adapter | Stable vectorized reset/step/observation/action surface only; it does not decide battle semantics. |
| `PokemonFormat` target rules | Format-specific normalization from immutable move target modes to explicit execution targets and capability gaps. |
| generated event vocabulary and handler programs | The complete frozen event-name/algebra/ordering contract, plus bounded declarative programs for executable ability/item handlers. |

The kernel calls a rule hook at the semantic operation that owns it. The hook
returns a value; queueing, mutation, events, PRNG ownership, and traces remain
visible in the kernel. This avoids hiding the state machine behind callbacks.

This corresponds to Showdown's resolved bundle boundary without reproducing its
runtime inheritance machinery:

- `PokemonData` is the bounded `GenerationData`: immutable identity catalogs,
  executable descriptor tables, handler spans, effects, and type facts.
- `PokemonGeneration` contains `GenerationRules` (condition/stall policy) and
  the small typed `GenerationOps` arithmetic surface.
- `weather_damage_stage` selects where generic `WeatherModifyDamage` dispatch
  occurs relative to the final base-damage floor and `+2`. Gen 3 declares the
  pre-offset stage from its `scripts.ts` override; another generation can
  select the post-offset stage without changing handler discovery.
- `PokemonFormatManifest` is the separate `Format` boundary: game type,
  cardinality, level/move limits, and a typed resolved RuleTable.

The generator flattens the pinned effective Gen 3 source once. There is no
runtime inheritance, object merging, generation switch, or callback bag.

## Format selection and resolved bundles

Showdown selects a generation through the format rather than accepting its
parts independently. `[Gen 3] OU` names `mod: 'gen3'` in
`config/formats.ts`; `Dex.forFormat` selects that mod, and the `Battle`
constructor obtains the mod's generation, effective data, and recursively
resolved RuleTable together (`sim/dex.ts`, `sim/battle.ts`, and
`sim/dex-formats.ts`). A mod's `scripts.ts` declares its parent and generation.
`ModdedDex.loadData` resolves table inheritance and runs the mod initializer;
for Gen 3, that initializer derives physical/special move categories by type
before a battle exists (`data/mods/gen3/scripts.ts`).

The native equivalent should therefore expose one immutable resolved selection:

```text
format -> { generation data, generation rules/ops, runtime format, rule manifest }
```

This is a compatibility boundary, not a request for Showdown-style runtime
inheritance. Generation and mod inheritance remain generator concerns, and the
emitted C tables contain only the flattened result. Battle initialization must
validate that every selected component has the same generation/bundle identity
before it mutates state or consumes PRNG. The public format selection should
also link the legality `PokemonFormatManifest` to the battle-time
`PokemonFormat`; accepting those two independently would permit an OU legality
manifest to be paired accidentally with another target geometry or game type.

`PokemonBattleInit` accepts one `PokemonResolvedBundle`. Every component carries
the same nonzero opaque plugin fingerprint, kernel capability ABI version, and
capability bitset. Initialization validates exact agreement across rules, data,
runtime geometry, policy, and manifest—including the policy's manifest pointer—
before constructing battle state or consuming PRNG. Equal numeric generations
are intentionally insufficient: same-generation components from different
flattened plugins fail closed.

The capability bitset names coarse kernel subsystems—singles geometry and
targeting, event dispatch, handler programs, effect programs, damage/critical/
multihit policy, condition rules, and format policy—and separately states which
semantic condition families the plugin provides. These are intentionally
subsystem capabilities, not a claim that every interpreter opcode has its own
negotiated ABI bit. Nonempty event, handler, or effect tables require their
subsystem bit. The base runtime capabilities are mandatory; each declared
condition family must have exactly one well-formed rule and each rule must be
declared. Unknown capability bits, ABI versions, and rule kinds are rejected. The test-only
generation-99 proof plugin exercises this boundary with different critical,
multihit, rounding, and duration policies through the same kernel. It is a
contract test, not a supported game generation.

## Event interpreter boundary

The kernel represents event evaluation with a typed event ID, the generated
relay algebra, an explicit relay sum type, owner references, and a bounded
frame stack. It discovers handler bindings from the target's current ability
and item, orders them according to the event specification, and interprets a
fixed opcode program. Programs may guard on typed move or damage context,
compose Q12 numeric modifiers, heal, or return an ordinary typed relay value.
`null`, `false`, and `undefined` remain distinct values; the caller interprets
their meaning at the event boundary rather than encoding TryHit or Damage
semantics in the interpreter.

The generated table contains all 69 frozen event specifications, but only
Damage, ModifyAtk, and TryHit are currently marked executable. Unsupported
events, mismatched relay/context variants, exceptional native handler IDs, and
malformed programs fail closed before mutation or PRNG. Program and trace/event
capacity are conservatively preflighted before execution. Water Absorb, Guts,
Black Belt, and Rock Head now use declarative programs; Levitate remains an
immutable type-immunity capability rather than an event callback.

This is deliberately not yet a claim of complete Showdown event execution.
Discovery currently covers active-holder ability/item scopes. Snapshot/stale
holder checks, ordinary tied-handler shuffle, left-to-right synthetic proofs,
nested dispatch opcodes, redirect early exit, and the remaining holder scopes
belong to later bounded family gates.

## Target and request boundary

Executable and catalog move descriptors retain the same 12 immutable target
modes found in the frozen Gen 3 OU inventory. The singles format normalizes
them before queue execution into an explicit target algebra: absent, user,
foe, field, user side, user team, foe side, or scripted provenance. Queue
actions retain the descriptor mode, resolved target, and relative target
location. The public Ocean action stays compact because Gen 3 OU singles has
only one active slot per side and therefore no player target choice.

`normal`, `any`, `randomNormal`, `allAdjacent`, and `allAdjacentFoes` resolve
to the sole foe without a targeting PRNG call. `adjacentAlly` resolves to an
absent target: it remains selectable, spends PP, and fails without mutating a
Pokémon. `self`, `allySide`, and field-wide `all` retain distinct owners.
Team-wide effects, foe-side conditions, and scripted damage-source provenance
are typed unsupported capabilities until their corresponding state/effect
families exist. An executable descriptor requiring one is rejected before
battle initialization can mutate state or consume PRNG.

## Identity catalog versus executable descriptors

`PokemonData` deliberately has two immutable layers:

- the frozen Gen 3 OU catalog contains all 369 species/forms, 354 moves, 70
  abilities, 104 items, and 82 reachable conditions selected by the
  authoritative pinned inventory;
- the executable tables contain only descriptors whose bounded semantics the
  native interpreter currently implements.

Catalog records have their own dense `catalog_id`, the normalized Showdown ID
and display name, source number, static facts, and an `executable_id`. An
`executable_id` of zero is a hard unsupported marker. Merely finding an identity
in the complete catalog never makes it legal to construct a native battle set.
Battle initialization continues to resolve only through executable tables and
fails closed for absent descriptors.

Conditions use the same distinction explicitly. Their dense generated
`catalog_id` is the descriptor identity used by handler ownership. A separate
`domain` records whether the identity is a status, volatile, side condition,
weather, pseudo-weather, or slot condition. `semantic_kind` maps only the
currently executable identities into the kernel's compact state enums and is
zero for the rest. The former seven-value hand enum was therefore a semantic
mapping, not an authoritative condition catalog, and has been removed.

Legality uses a separate `PokemonCatalogSet` / `PokemonCatalogTeam` product
type whose identities are catalog IDs. This avoids confusing catalog identity
with the executable IDs accepted by the trusted battle initializer. The
validator is deliberately outside the hot path and returns
`ACCEPTED_BOUNDED`, not a claim of full Showdown legality.

The current frozen catalog is the OU legal/reachable battle inventory, not the
universe of every illegal Gen 3 descriptor. Rules such as the Uber tag and bans
whose operand is absent from that inventory are retained as
`UNSUPPORTED_ADMISSION_UNIVERSE`; rules requiring fields absent from
`PokemonCatalogSet` are retained as `UNSUPPORTED_SET_FIELDS`. Both contribute
to the result's `unsupported_rule_count`. A future full legality gate must
generate a distinct admission-universe catalog rather than treating an absent
illegal identity as an ordinary unknown or silently accepting it.

The generator verifies the frozen inventory digest, revision, counts, ordering,
and every record against the pinned resolved Showdown bundle. It emits no giant
handwritten identity enums; catalog IDs are deterministic inventory positions.

## Current plugin surface

- `base_damage`: generation damage arithmetic before common staged modifiers.
- a critical-stage-to-chance function and critical damage multiplier. Moves
  supply only their generated base stage; the kernel owns the ordered
  `ModifyCritRatio` and cancellable `CriticalHit` event boundaries.
- `resolve_damage_formula`: the tagged fixed-level and HP-bracket alternatives
  to standard base power.
- `residual_damage`: Sand, burn, and escalating Toxic arithmetic.
- a fixed table of tagged condition rules: supported condition durations,
  residual order/suborder, and whether speed participates in ordering.
- Protect's stall denominator policy: initial value, multiplier, and cap.
- Toxic stage cap and the bounded end-turn draw policy.

Condition rules are data rather than callbacks. The generic runtime looks up a
tagged record when it creates a condition or residual work item, then performs
the ordinary lifecycle operation itself. Duplicate, missing, undeclared, or
malformed rule records reject the generation plugin at battle initialization.
Validation does not equate a plugin with the current Gen 3 array length:
requirements follow its explicit capability bits.

Weather Ball, Thunder, and Solar Beam are not generation-wide rules. Their
effective Gen 3 callbacks are flattened into each generated move descriptor as
a five-entry effective-weather policy. Generic handlers interpret flags for
type/category, accuracy/always-hit, Q12 power, charge skipping, and protocol
target suppression. `PokemonGeneration` therefore contains no move-specific
policy tables, and the interpreter contains no move-ID or move-name branch.

Invalid or incomplete generation plugins are rejected at battle initialization.
The runtime never guesses a default generation rule.

## Migration order

1. Keep CP1–CP5 behavior fixed while moving already-proven arithmetic into the
   typed hooks above.
2. ~~Move Protect stall policy, condition durations, and residual ordering into
   explicit rule data.~~ Implemented with `PokemonConditionRule` and
   `PokemonStallPolicy`.
3. Represent generation-specific damage-stage behavior (burn, Reflect, critical
   bypass) as ordered rule descriptors while leaving discovery and relay tracing
   in the kernel.
4. Add exceptional handlers only when source evidence shows that declarative
   descriptors cannot express the mechanic.

Do not move queues, phases, generic effect interpretation, or trace emission into
generation callbacks. Doing so would duplicate the state machine per generation
and make ordering impossible to inspect locally.
