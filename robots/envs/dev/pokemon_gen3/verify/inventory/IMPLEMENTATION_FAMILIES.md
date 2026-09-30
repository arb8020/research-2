# Checkpoint 6 implementation families

This is the implementation order for the 1,463 reachable descriptors currently
classified `unsupported`. It is a work plan, not a claim of support. The source
of truth for membership and counts remains `gen3ou-inventory.json` plus
`descriptor-map.json` at Showdown revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Counting model

The unsupported denominator is:

| Descriptor kind | Count | What completing it means |
| --- | ---: | --- |
| species/form | 348 | Generated immutable identity, typing, base stats, gender and form data construct the same canonical state. |
| move | 320 | Static move data and every reachable attached behavior are supported. |
| ability | 66 | Static ability identity and every reachable attached behavior are supported. |
| item | 103 | Static item identity and every reachable attached behavior are supported. |
| condition | 71 | The condition has bounded state, lifecycle rules and all reachable behavior. |
| format rule | 42 | Team/battle normalization enforces the resolved rule or ban. |
| target mode | 10 | Choice normalization, legal masks and runtime target resolution agree. |
| callback-hook ownership | 505 | This exact owner/event binding is discovered, ordered and dispatched with evidence. |
| **Total** | **1,463** | |

The 505 hook records are not 505 separate algorithms. They are conformance
obligations layered on the move, ability, item and condition descriptors. For
example, implementing a generic fraction-heal operation can close many item
descriptors and their `onResidual`/`onEat` ownership records, but each record
still needs a focused or rotated differential witness. Progress reporting must
keep descriptor closure and hook-ownership closure separate so it neither
double-counts engineering work nor loses event-discovery coverage.

The frozen hook records partition by runtime boundary as follows. These counts
are an audit partition of 505, not an implementation estimate:

| Event boundary | Hook records | Examples of shared semantics |
| --- | ---: | --- |
| lifecycle and phase entry/exit | 132 | start/end/restart/update, switch, prepare/abort/after-move |
| typed relay modifiers | 84 | stat, power, accuracy, critical, move/type and secondary modification |
| mutation, hit and item operations | 147 | damage/heal, status/boost, eat/take item, primary/secondary hit |
| choice and move gating | 49 | before/try move, disabled/locked moves, override action, PP |
| targeting, immunity and switch control | 30 | redirect, invulnerability, trapping, drag immunity |
| residual, weather and field phases | 51 | residual and field/weather start/end/modification |
| small remaining protocol seams | 10 | add-volatile gates, stall, failure, post-mega compatibility hook |

## Generation boundary

Follow Showdown's useful abstraction, but resolve it at build time. Showdown's
`ModdedDex` selects a mod from a format and materializes tables by inheriting
from `parentMod`; individual dex tables reuse or override parent records. Our
generator should perform the same resolution against the pinned source, then
emit one immutable `PokemonGeneration` plugin. The C runtime does not implement
inheritance and never loads Showdown.

The generic fixed-capacity kernel owns:

- canonical mutable battle state and invariant checks;
- choice normalization, action/faint queues, sorting and phase/request flow;
- event-source discovery, handler ordering, relay threading and trace emission;
- generic target, hit and mutation primitives;
- explicit PRNG operations at their semantic call sites;
- atomic rejection of unsupported or capacity-exceeding transitions.

The generated generation plugin owns:

- resolved species, move, ability, item, condition and type-chart data;
- typed rules for generation-dependent arithmetic, ordering and policy;
- compact declarative effect programs and event bindings;
- IDs for the few named native handlers required by irreducible behavior.

An exceptional handler is justified by stateful semantics, not by a proper
name. `Earthquake` is ordinary Ground damage; its interaction with `Dig` is a
named exception. Conversely, Counter/Mirror Coat's remembered damage and
source targeting, Transform's state copy and Metronome's move selection earn
dedicated handlers. No handler may encode a pair of chosen moves.

## Dependency and leverage order

Each row is a closure gate. A later family may be prototyped earlier, but it
cannot be marked implemented while an earlier boundary it relies on is only
approximated.

| Order | Family | Boundary and representation | Typical coverage | Required proof |
| ---: | --- | --- | --- | --- |
| 0 | Resolved generation image | Build-time `ModdedDex`-like inheritance resolution; generated stable IDs and lookup tables; plugin validation. No runtime mechanics. | 348 species plus static portions of all moves, abilities, items, types and conditions. | Regenerate byte-identically; construct every legal set; compare calculated stats, types, PP and normalized identities; reject a deliberately incomplete plugin. |
| 1 | Format and team normalization | Gen-neutral validator consumes typed generated rule records; Gen 3 supplies resolved clauses, bans and numeric constraints. | 42 format rules. | Import representative Showdown validator tests; rotate every rule/ban; differential accepted/rejected teams and normalized sets. |
| 2 | Target and request algebra | Kernel choice/action sum types and target resolver; plugin supplies legal target-mode descriptors and format cardinality. | 10 target modes, singles now and doubles-capable shape later. | Legal-mask and normalized-choice agreement for move/switch/forced replacement; invalid targets reject before mutation or PRNG; recombine with faint and redirection. |
| 3 | Complete event vocabulary | Kernel event IDs, holder/source discovery, priority/order/suborder sorting, typed relay values and handler result algebra. Plugin binds owners to declarative programs/handler IDs. | Infrastructure for all 505 hooks. | Synthetic discovery/order unit tests for every holder class; exact Showdown structural trace; tied ordering and early-exit PRNG tests; capacity rejection. |
| 4 | Canonical mutation primitives | Kernel-only HP, PP, status, boosts, volatile/side/field condition and item mutation coupled to typed events. Conditions use bounded tagged payloads. | Common effects across moves, conditions, berries and abilities. | Boundary tests for success, no-effect, fail and silent-fail; invariant after every primitive; differential protocol/state order. |
| 5 | Relay modifier algebra | Ordered fixed-point/stat relays and generated predicates for holder/source/target/weather/status/type. Gen plugin supplies rounding and critical-bypass policy. | 84 modifier hooks: Choice Band/type items, Guts, Huge/Pure Power, screens, weather, speed, accuracy, crit ratio. | Focused one-modifier tests, order-sensitive three-handler tests, critical bypass, overflow/rounding vectors and exact trace. |
| 6 | Ordinary move execution | Generic preflight -> PP -> target/immunity -> accuracy -> TryHit -> crit/damage -> primary/secondary -> post-hit -> faint drain. Declarative programs cover damage, status, boosts, heal, recoil/drain, multihit and common flags. | Most of 320 moves and many hit/mutation hooks. | Table-rotate all ordinary moves; forced hit/miss/crit/secondary/multihit; immunity must consume no later draws; pairwise move × ability/item/status/weather contexts. |
| 7 | Status and volatile lifecycle | Generic add/start/restart/duration/before-move/residual/end; Gen 3 typed condition policies and payload layouts. | Six statuses and common volatile families: confusion, flinch, recharge, partial trap, lock, disable/encore/taunt/torment, substitute. | Each lifecycle transition, switch clearing/preservation, reapplication, simultaneous expiries, immobilization PRNG, action -> residual -> request sequences. |
| 8 | Items and consumption | Generic trigger predicates, consume/eat/restore/cure/boost operations, item removal and ownership rules; named state only where needed. | Berries, Leftovers/Shell Bell, White Herb, Choice lock, stat/type items, Focus Band, Thick Club/Light Ball/DeepSea items, Mail/Sticky Hold. | Rotate every item; threshold edge cases; item × status/boost/weather; consume exactly once; ordered competing triggers; forced probabilistic outcomes. |
| 9 | Abilities and switch lifecycle | Generated ordered bindings plus generic immunity, absorb, contact proc, stat/weather/status and switch operations. | Most 66 abilities and 87 ability-owned hooks. | Rotate every ability; switch-in/out/update order; ability suppression/holder faint cases where reachable; contact chance labels; ability × move/type/status/item recombinations. |
| 10 | Weather, side and field conditions | Generic field/side condition lifecycle and residual scheduling; Gen 3 duration, damage, immunity and modifier records. | Rain, sun, sand, hail; Reflect/Light Screen, Safeguard, Mist, Spikes; Mud/Water Sport. | Start/restart/end, duration and residual order; weather × ability × move; switch into hazards including faint/forced replacement; terminal during residual. |
| 11 | Switching control and delayed work | Kernel queue operations for trapping, phazing, Baton Pass, Pursuit interception, forced replacement and delayed attacks/heals. Plugin supplies descriptors/policies. | Mean Look family, Arena Trap/Magnet Pull, Roar/Whirlwind, Baton Pass, Pursuit, Future Sight/Doom Desire, Wish. | Queue snapshots before/after suspension; target/source preservation; switch/faint races; request/legal-mask agreement; deterministic replay. |
| 12 | Stateful move families | Small reusable state machines or named handlers selected by generated descriptors. | two-turn moves, charge/recharge, Protect/Endure stall, ramping moves, stockpile family, Bide, Counter/Mirror Coat, Focus Punch, Destiny Bond/Grudge/Perish Song. | Focused source-linked test per state machine; interruption/switch/faint paths; exact action/event/residual order and labeled draws; cross-family recombination. |
| 13 | Transformative and move-selection exceptions | Named handlers where declarative operations cannot honestly express copying or selecting executable descriptors. | Transform, Conversion/Camouflage, Mimic/Sketch, Metronome/Sleep Talk/Mirror Move/Nature Power, Role Play/Skill Swap/Trick/Recycle. | Full before/after canonical state; legal choices and PP; copied-state cleanup on switch; selection PRNG labels; unsupported selection rejects atomically. |
| 14 | Remaining named damage exceptions | Tagged formulas first; native handler only for memory or unusual multi-actor semantics. | fixed/level/HP damage, Endeavor/Pain Split, Beat Up, Present/Magnitude, OHKO rules, Explosion/Self-Destruct, False Swipe, High Jump Kick crash. | Exhaustive formula boundary vectors; party-participation cases; damage/faint ordering; forced rolls; interactions with Substitute, immunity and prevention handlers. |
| 15 | Inventory closure and anti-overfitting | Update descriptor evidence only after semantics pass; minimize and persist failures. | Every still-unsupported descriptor and all 505 ownership records. | Zero reachable `unsupported`; every owner/event binding observed; hidden unseen teams/seeds/choices; pairwise context, three-way handler, phase-sequence and PRNG-early-exit gates. |

## Evidence rule per family

A family is not complete merely because its opcode exists. For every descriptor
closed by a family, classification needs all of:

1. authoritative source symbol at the pinned revision;
2. generated Gen 3 record and a generic kernel boundary, or a justified named
   handler;
3. a focused test derived from the relevant Showdown mechanic test or source;
4. at least one exact differential boundary case;
5. rotation evidence for every descriptor sharing the implementation;
6. recombination evidence appropriate to the boundary;
7. deterministic repeat with identical trace and final PRNG state.

The minimum recombination matrix is not a Cartesian explosion. Use
coverage-guided pairwise combinations for effect × context, targeted three-way
cases for ordered handlers, explicit action -> residual -> request phase
sequences, and one early-exit case at every random boundary. Persist the first
divergence and minimized choices plus resulting state.

## How to keep the plan honest

- Generate family membership from resolved descriptors and hook bindings; do
  not maintain a second handwritten inventory.
- Treat unclassified callback bodies as unsupported. Similar hook names do not
  prove similar denotation.
- Let ordinary descriptors select generic operations. Do not add
  `resolve_<move>` functions for ordinary named moves.
- Keep discovery, ordering, mutation, queues and PRNG ownership visible in the
  kernel; a generation callback may answer a typed policy question but must not
  hide control flow.
- Preserve CP1--CP5 traces as regression evidence throughout. Deleting an old
  path is safe only when every reaching corpus transition traverses the new
  family and remains exact.
