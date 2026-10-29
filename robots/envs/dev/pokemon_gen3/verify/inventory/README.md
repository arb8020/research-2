# Checkpoint 6 descriptor inventory contract

This directory defines the machine-checkable progress boundary for the frozen
Gen 3 OU inventory. It complements the semantic feature families in
`harbor/gen3ou-native/supported-features.json`: feature families describe
behavior, while this map proves that every frozen descriptor was considered.

The classification map is frozen and exhaustive over its generated universe.
Its universe is solely the
generated `gen3ou-inventory.json`; the recorded counts and common artifact
digest bind each generated inventory to that source. `classify.js`
deterministically emits exactly one evidence-bearing entry for every
descriptor. This freezes the progress denominator; it does not claim semantic
completion.

`CAPABILITY_DEPENDENCY_GRAPH.md` is the live work-selection view over the
current unsupported entries. It groups records by missing semantic capability,
records prerequisite edges, and requires a scored choice before another family
enters the kernel. Historical count/ranking documents are not a substitute for
regenerating that graph from this map.

The existing Harbor review manifest's 392/354/76/116 counts describe broad
generated data tables while its selectors say validator-reachable Gen 3 OU.
Those are not the same sets. The authoritative selector yields 369/345/70/104;
the descriptor-map denominator is derived from that generated reachability
closure rather than the broader tables. The same artifact now includes the 42
effective format rules and bans from the resolved Gen 3 OU rule table.

Each entry has exactly one classification:

- `implemented`: reachable executable semantics with generated/native
  boundaries, focused tests, and differential cases.
- `inert`: reachable immutable metadata with no callback behavior, still
  proven through construction/state tests and differential cases.
- `unreachable`: present in frozen source data but excluded by a reproducible
  validator, format, generation, or inheritance proof. It must not claim
  runtime evidence.
- `unsupported`: reachable behavior with a persistent counterexample or gap.
  This is useful progress accounting but always blocks completion.

Every entry names authoritative Showdown source, the generation/import seam,
the pinned revision, semantic feature IDs, and the evidence appropriate to its
classification. IDs are unique within their inventory. The validator rejects
unknown feature/case references and missing project paths.

## Coverage and anti-overfitting

Descriptor rotation requires every implemented or inert descriptor to be
reached, and every unsupported descriptor to retain a counterexample. Hidden
generation then measures pairwise effect/context coverage, three-way handler
ordering, action-to-residual-to-request sequences, and PRNG early-exit staging.
At least half of each hidden interaction set must be an exact tuple absent from
the public corpus. Team, seed, and choice-prefix hashes are also withheld.

Progress is reported separately for classification, authoritative source,
generation seam, native boundary or gap proof, focused evidence, differential
evidence, and hidden recombination. The weights total 100, but the score is not
a completion claim. Completion additionally requires a frozen exhaustive map,
no reachable `unsupported` entry, all recombination gates, and zero required
public/hidden semantic divergence.

The current generated denominator is 1,560 descriptors: 369 species/forms,
354 moves, 70 abilities, 104 items, 82 reachable conditions, 12 target modes,
42 effective format rules/bans, 514 callback-hook ownership records, and 13
simulator-only conditions. The format artifact also freezes inherited value
rules and team/level/move/EV constraints.

Run the dependency-free contract checks with:

```sh
node verify/inventory/test.js
node verify/inventory/validate.js verify/inventory/descriptor-map.json
```

The second command should currently report `schema_valid: true` and
`inventory_ready: true`. The map is exhaustive and has no reachable descriptor
classified `unsupported`. Overall completion remains an external conjunction
with observed semantic,
recombination, determinism, robustness, and performance gates.

Current evidence-driven classifications are 1093 `implemented`, 426 `inert`, 37
`unreachable`, and 0 `unsupported`. The exhaustive catalog differential
proves all 369 species/forms' static identities, types, stats, tiers, Shedinja
HP override, and calculated-stat vectors; this does not promote any move,
ability, or item behavior. Twenty-seven individually exercised format rules are
implemented: Species Clause, `Smeargle + Ingrain`, and the three Baton Pass
trapping bans for Block, Mean Look, and Spider Web, plus the nine resolved
atomic ability/item/move bans proven by the separate admission verifier, and
the Evasion Items/Moves aliases whose complete flattened child sets are
generated from the resolved RuleTable, and the generic Uber, Unobtainable,
and Nonexistent descriptor-tag bans, plus OHKO Clause as a generated move
predicate over exactly Fissure, Guillotine, Horn Drill, and Sheer Cold.
Accuracy Trap Clause uses the same generic fixed-capacity all-of interpreter:
five generated guaranteed-accuracy-drop moves must coexist with one of three
trapping moves or three trapping abilities. Probabilistic accuracy drops,
partial trapping, and either predicate alone are proven negative controls.
Speed Pass and One Boost Passer now execute in a distinct fixed-capacity team
admission phase. Generated policy predicates preserve Showdown's intentional
source lists across moves, items, and abilities; a generic anchored-cardinality
rule enforces both per-set source count and qualifying-passer team count.
EV Limit now executes through a generated stat-vector policy bound to the
resolved format manifest. The admission boundary normalizes omission separately
from an explicit six-stat vector, accepts each component in `0..255`, and
enforces the inclusive 510 total. It also preserves Showdown's adjacent
normalization checks: a zero total is rejected above level one but accepted at
level one. Those component and zero-total checks are evidence for the shared
stat boundary, not part of the denotation of EV Limit itself.
Obtainable Abilities now executes through a generic allowed-relation
interpreter. Build-time resolution flattens the pinned Gen 3 data into a CSR
table with 393 canonical species rows and 517 legal species/ability pairs;
the runtime contains no species or ability identity branches. Canonical-ID
normalization keeps unknown identities distinct from known disallowed pairs.
Focused bundle-shape and malformed-data tests plus seven shared differential
fixtures prove both legal ability slots, cross-species and modern-slot
rejection, rule precedence, and later-team-member diagnostics.
Obtainable Formes now executes through a generated guarded-rewrite program.
Its exact battle-only closure maps Castform-Sunny, Castform-Rainy, and
Castform-Snowy to base Castform after requiring Forecast. Admission and the
normalized set/team form one transactional product: output is committed only
after all rules succeed and remains unchanged on rejection. Selectable Deoxys
formes are not rewritten; the upstream scenario that selects among them is
Gen 3 OU-unreachable because those identities are banned as Uber. This native
boundary accepts and returns canonical IDs, so it does not claim preservation
of user-facing aliases or spelling.
Helping Hand's complete no-adjacent-ally behavior in
singles and Wing Attack's ordinary damage path are implemented. Eleven target
modes have native focused and differential evidence: `normal`, `self`, `all`,
`allAdjacent`, `allAdjacentFoes`, `allySide`, `adjacentAlly`, and `any`.
`randomNormal` is covered by locked/rampage semantics; Aromatherapy and Heal
Bell prove `allyTeam`; Counter and Mirror Coat prove `scripted`; Spikes proves
`foeSide` for the present singles shape. Endless Battle Clause, Standard AG,
and Standard now execute through the typed terminal policy described in
`ENDLESS_BATTLE_CLAUSE.md`. Obtainable Moves, Obtainable Misc, and their
Obtainable aggregate now
execute through the generated acquisition/source interpreter and transactional
admission boundary. Water
Absorb remains implemented with damaged-HP healing and full-HP cancellation
evidence. Damp's inherited `onAnyDamage` hook is unreachable in Gen 3 because
its sole source effect is the later-generation Aftermath ability. Guts now has
legal paralysis, sleep, freeze, poison, special-move, and item-ordering
recombinations. Rock Head includes the reachable Struggle exception. These
are gap measurements, not estimates of engineering effort; implementing one
generic handler can close many descriptors at once.

The screen-handler migration keeps those counts unchanged because Reflect,
Light Screen, and their callback records already had behavioral evidence. The
new implementation replaces the screen-specific damage loop with generated
`ModifyDamagePhase1` handlers and extends the exact corpus from 1,273 to 1,282
boundaries. The added cases cover attacker-side non-application, dual-screen
category routing, critical bypass, and tied-handler PRNG ordering.

The callback-free half-drain family adds Absorb, Mega Drain, and Leech Life to
the existing Giga Drain operation without changing the kernel. Flattened move
descriptors all point at the same `AfterDamage` one-half drain program. A
four-boundary rotation proves their inherited Gen 3 power, maximum PP,
physical/special split, damage-relative healing, state, and labeled PRNG. Dream
Eater's sleep predicate and Liquid Ooze's `TryHeal` callback are separate
semantic families and remain unsupported.

Sonic Boom and Dragon Rage use a typed fixed-literal damage formula whose
operand lives in the generated move descriptor. Natural type immunity is
resolved before the formula; resistance and weakness scaling are not applied
after it. The focused and differential evidence also proves accuracy staging,
the Gen 3 type-based category, and absence of critical and damage-roll draws.
The exact corpus is 1,291 boundaries.

Super Fang and Endeavor add two target-relative fixed-damage formulas. Super
Fang floors half of the target's current HP with a minimum of one. Endeavor
subtracts the source's current HP from the target's current HP, but its
generated inherited `Try` handler rejects an equal-or-higher source before
accuracy or PRNG consumption. Substitute fixtures prove both formulas use the
real target HP and only then cap damage to the substitute. Their moves and
Endeavor's two callback-owner records are implemented; the exact corpus is now
1,299 boundaries.

Psywave adds a generation-owned random damage-formula policy rather than a
move-specific resolver. Gen 3 supplies a uniform integer multiplier from 50
through 150; the kernel labels that owned draw `move.damage_formula`, multiplies
by the source level, floors, and clamps to at least one. Accuracy, Protect,
type immunity, and Substitute retain their existing gates: misses and Protect
do not draw the formula, while Substitute evaluates it exactly once. Focused
tests additionally cover Dark immunity without a formula draw. The move is
implemented after exact differential and replay agreement across 1,308
boundaries.

Hyper Beam adds the first synthetic forced-action lifecycle. A connected hit
installs the generated `mustrecharge` volatile, residual timing advances its
two-turn duration, `LockMove` projects the synthetic Recharge action and
suppresses switching, and priority-11 `BeforeMove` consumes the condition
without PP or last-move mutation. A miss does not install the condition. The
focused native lifecycle test and a legal two-turn differential fixture cover
request, queue, handler, condition, state, event, and PRNG boundaries exactly;
the corpus is now 1,311 boundaries. The protocol-only
`condition.mustrecharge.onStart` callback remains explicitly unsupported.

Sand Tomb closes the final legal Gen 3 member omitted from the generated
partial-trapping move product. It uses the existing source-owned volatile,
duration draw, exact residual damage, trapping request restriction, and source
switch cleanup without adding a kernel branch. A legal rotation fixture brings
the exact corpus to 1,314 boundaries.

Brick Break adds a generated move-owned `TryHit` program over one generic
selected-side condition-removal operation. Gen 3 data selects the source's
opposing side and removes Reflect before Light Screen. The operation runs after
admission and accuracy but before Substitute and damage, so immunity, Protect,
and misses preserve screens while a connected hit removes them before its own
damage is calculated. Five legal fixtures prove those gates and bring the
exact corpus to 1,332 boundaries without a move-ID branch or an owned PRNG
draw.

Leftovers is a generated item-owned Residual handler over the same generic
maximum-HP fraction operation used by Rain Dish. The resolved Gen 3 mod
inherits residual order 10/suborder 4 from Gen 4, rather than base data's
order 5. Focused tests prove floor, minimum-one, clamp, and full-HP behavior;
legal fixtures prove clamped healing and Leftovers suborder 4 preceding burn
suborder 6 at the shared order-10 residual boundary.
The exact corpus is now 1,336 boundaries.

Natural Cure adds the generic live-holder `SwitchOut` event at its Showdown
boundary, before ability/item End and volatile cleanup. A generated
ability-owned program clears the holder's complete major-status product
through the central status transaction; it does not branch on species or
ability identity. A legal burned-Starmie switch fixture proves handler,
condition, state, event, and PRNG boundaries, bringing the exact corpus to
1,338 boundaries. Fainted forced replacement deliberately skips `SwitchOut`.

Pressure adds one generic additive `DeductPP` relay after target resolution and
before `TryMove`. Selected moves own the base deduction; resolved opposing
targets contribute extra PP through generated ability handlers. Focused tests
cover self-target exclusion, immunity, Protect, foe-side moves, switching,
forced locked continuations, and successful Snatch. Four legal fixtures plus
the existing Snatch and switch-in cases prove both `onDeductPP` and `onStart`,
bringing the exact corpus to 1,348 boundaries. Snatch's exceptional call site
re-enters the same event instead of inspecting the Pressure ability ID.

Damp is a generated global `TryMove` handler over the move descriptor's
pre-hit self-faint timing. PP and Pressure staging remain before this event;
cancellation remains before self-faint, accuracy, critical-hit, and damage
draws. The generic kernel names neither Damp nor Explosion/Self-Destruct.

Flame Body is the first generated `DamagingHit` witness. The kernel dispatches
that target-owned event only after a connected real-target hit and after move
effects, never through Substitute. Its program composes the contact flag, a
labeled one-in-three draw, and the central status transaction; the exact corpus
now covers 1,367 decision boundaries. Static and Poison Point reuse the same
three-operation program with generated paralysis and poison operands; Steel
immunity remains inside the central status transaction after activation PRNG.
Effect Spore extends the same program family with a labeled one-in-ten
activation followed by one uniform three-way status-selection draw. Selection
precedes central status admission. Focused tests cover every selection value,
failed activation, and pre-existing-status rejection; four legal differential
fixtures bring the exact corpus to 1,383 boundaries.

Sleep now uses generated status-owner `Start`, `BeforeMove`, and `SwitchIn`
programs over one typed mutable payload: remaining duration and skipped sleep
turns. Early Bird is a generated operand of the generic advance operation;
Snore is an ordinary move with declarative `sleep_usable` data and a generated
status guard. Installation, waking, sleep-usable execution, switch restoration,
condition traces, and labeled duration PRNG all match the pinned oracle. Six
legal fixtures bring the exact deterministic corpus to 1,498 boundaries and
close Snore, Early Bird, the sleep condition, and its three lifecycle hooks.

Recoil effects now carry generated `PREVENTABLE | UNPREVENTABLE` metadata.
Ordinary recoil enters the existing generic Damage-handler pipeline, while
Gen 3 Struggle applies its quarter recoil without offering prevention. A legal
Rock Head holder exhausts Hyper Beam and then uses forced Struggle through the
ordinary request path; its 18 exact boundaries bring the corpus to 1,516 and
close Rock Head without a move-ID branch in the kernel.

Gen 3 Quick Claw is a typed generation policy, not an item callback: one
shared turn-start roll selects whether eligible holders receive the generation's
speed sentinel, while action priority remains the earlier ordering key. Exact
activation and failure cases expose both the labeled roll and resulting queue.
Shed Skin is a generated residual handler program with an explicit live-holder
guard, status predicate, labeled 33/100 draw, and generic status clear. Twelve
legal cases cover cure and preserve outcomes for burn, paralysis, poison,
Toxic, and freeze, plus no-status and KO-before-residual paths. Together with five Guts
recombination cases, these additions bring the deterministic exact corpus to
1,549 boundaries. The tagged fixture status payload now initializes both
sleep counters and Toxic's stage explicitly in Showdown and native state.

Speed Boost uses the same generic residual dispatcher and boost transaction as
other owners. A generation-neutral active-turn counter distinguishes initial
actives from same-turn switch-ins. Four exact fixtures cover first-turn
activation, delayed activation after switching, the `10/3` ordering before
Toxic's `10/6` residual, forced replacement cleanup, and the +6 stage cap.
They also exposed and fixed a duplicate post-switch Update and Showdown's
silent status cleanup when a fainted active is replaced. The exact corpus is
now 1,565 boundaries.

Twenty-five legal, recursively resolved Gen 3 held items have identity but no
effective callbacks. They are generated as executable zero-handler item rows,
not treated as missing behavior. Focused tests pass every identity through the
generic Trick transaction, and one legal differential case per item proves
the initial and post-swap canonical state against the pinned oracle. This adds
50 exact boundaries, bringing the deterministic corpus to 1,615, and moves
those descriptors from `unsupported` to `inert` without adding kernel control
flow.

Eruption and Water Spout share one generated live-source-HP base-power policy.
The generic kernel resolves `max(1, floor(150 * hp / max_hp))` before ordinary
BasePower handlers; neither move identity enters control flow. Focused tests
and four legal full/odd-half-HP cases add eight exact boundaries, bringing the
deterministic corpus to 1,623 and moving both move descriptors from
`unsupported` to `implemented`.

Nightmare is represented as an ordinary always-hit volatile-installing move
plus two generated condition handlers. Its Start handler requires sleep; its
resolved Gen 3 Residual handler runs at `10/7` and applies one quarter of the
holder's base maximum HP through the generic fractional-damage opcode. The
condition rule owns only structural lifetime facts (`noCopy` and removal when
sleep ends). Five legal cases cover awake rejection, damage while asleep,
natural-wake cleanup, switch cleanup, and Shed Skin's earlier `10/3` cure.
Those cases add 11 exact boundaries, bringing the deterministic corpus to
1,634 and moving the move, volatile, and two callback hooks from `unsupported`
to `implemented`. The pinned observer does not emit generic lifecycle rows for
Nightmare, so the differential contract proves installation and cleanup via
handler order, canonical volatile state, status state, damage events, and
labeled PRNG instead of synthesizing observer records.

Intimidate uses one generated opposing-active boost operation over the generic
directed `ChangeBoost`/`TryBoost` transaction. The Gen 3 descriptor supplies
Attack -1 and Substitute exclusion; neither the ability ID nor its name enters
kernel control flow. Four legal initial-entry cases prove both unequal-speed
orders and both outcomes of the tied `runSwitch` insertion draw. This source
audit also corrected an architectural false lead: Gen 3 inherits Gen 4's
single-entrant `runSwitch`, not the modern batched implementation. The same
fixtures exposed and fixed queue-tie PRNG staging before the post-start Update.

Trace adds a typed random-active-foe selector and a generic ability-replacement
transaction. The generation plugin explicitly controls whether the replacement
ability starts immediately; Gen 3 supplies false. A legal Porygon2 re-entry
case proves two singleton target draws, restoration of base Trace on switch,
and that copied Intimidate does not start. Together these two ability families
add eight exact boundaries, bringing the deterministic corpus to 1,642 and the
classification totals to 605 implemented, 396 inert, 16 unreachable, and 522
unsupported descriptors. A subsequent evidence audit promoted Arena Trap,
Magnet Pull, and their four Trap/MaybeTrap hooks without changing runtime
code: the existing four exact cases and focused hidden-trap request test already
cover those semantics. The current totals are therefore 611 implemented, 396
inert, 16 unreachable, and 516 unsupported descriptors.

Color Change introduces mutable effective typing as explicit battle state;
immutable species types remain generated data and switch cleanup restores them.
All type consumers—STAB, effectiveness and natural immunity, grounding, major
status immunity, trapping predicates, and damaging-weather immunity—read the
mutable product. The generated Gen 3 ability descriptor runs on each
`DamagingHit`, matching the inherited Gen 4 override rather than the modern
`AfterMoveSecondary` shape. Seven legal fixtures cover replacement, downstream
STAB and immunity, Toxic, Sandstorm, switch restoration, Substitute suppression,
and per-hit mutation during a forced five-hit move. These add 22 exact
boundaries, bringing the deterministic corpus to 1,664 and the classification
totals to 613 implemented, 396 inert, 16 unreachable, and 514 unsupported
descriptors.

Attract and Cute Charm share one generated volatile family rather than
move- or ability-specific kernel branches. Attract's move-owned
`TryImmunity` checks gender before accuracy while preserving Gen 3's accuracy
draw; its condition-owned `Start` admits only opposite binary genders,
`BeforeMove` performs the labeled action draw, and `Update` removes the
volatile when its recorded source leaves the active slot. Cute Charm's
`DamagingHit` handler composes the contact predicate, labeled one-in-three
activation draw, and that same source-attributed volatile transaction. Three
legal fixtures cover direct installation, same-gender rejection, and contact
activation. They add eight exact boundaries, bringing the deterministic corpus
to 1,672 and the classification totals to 621 implemented, 396 inert, 16
unreachable, and 506 unsupported descriptors. The inherited silent `onEnd`
callback remains unsupported rather than being inferred from lifecycle state.

Paralysis action denial is now a generated status-owner `BeforeMove` program:
priority 1, one labeled one-in-four draw, then a generic false return. The
kernel's former status-ID branch is gone; the existing generated `ModifySpe`
handler remains the separate speed half of paralysis. Focused tests prove
owner identity, ordering metadata, both outcomes, exact draw ownership, and
transactional rollback for a malformed chance operand. The existing legal
`status-paralysis-action` fixture proves two exact boundaries and promotes only
`condition.par.onBeforeMove`; the full paralysis condition remains unsupported
until its remaining hooks are closed. Classification totals are now 622
implemented, 396 inert, 16 unreachable, and 505 unsupported descriptors.

Burn, poison, and Toxic residual execution now enters through generated
condition-descriptor policies rather than status-ID branches. The observer
contract exposes discovery at order 10/suborder 6, condition-scoped damage,
and execution for all three. Four existing legal fixtures plus focused
rounding, cap, reset, and malformed-bundle tests promote their three
`onResidual` hooks. Ordinary poison's existing primary/secondary installation,
immunity, state, damage, and generated residual evidence also closes its
condition descriptor. Current totals are 626 implemented, 396 inert, 16
unreachable, and 501 unsupported descriptors. Burn and Toxic were already
condition-classified; their remaining callback rows stay explicit.

Rapid Spin adds one generated after-hit `REMOVE_VOLATILE` operation targeting
its user. The generic kernel routes it through the central volatile End/removal
transaction; neither the move ID nor its name appears in control flow. A legal
Bind-then-Rapid-Spin fixture proves connected-hit staging and exact partial-trap
cleanup, bringing the deterministic corpus to 1,675 boundaries and the totals
to 628 implemented, 396 inert, 16 unreachable, and 499 unsupported. This
promotes only the Gen 3 `self.onHit` partial-trap behavior. Leech Seed, Spikes,
and later-generation Rapid Spin callbacks remain explicit unsupported work.

Blast Burn, Frenzy Plant, and Hydro Cannon now join Hyper Beam as generated
producers of the shared `mustrecharge` condition. No kernel behavior changed:
the existing condition lifecycle still owns forced-choice projection, switch
restriction, priority-11 action denial, PP staging, and cleanup. Legal
Charizard, Venusaur, and Blastoise fixtures add nine exact boundaries, bringing
the deterministic corpus to 1,684 and the totals to 631 implemented, 396 inert,
16 unreachable, and 496 unsupported descriptors.

The damaging-secondary rotation now includes Sacred Fire, Blaze Kick, Poison
Tail, Luster Purge, Mist Ball, and Muddy Water with legal successful-effect
seeds. The generated one-effect pipeline was already sufficient; this adds
descriptor-level differential evidence without kernel changes. Weather
lifecycle evidence now also closes fourteen Hail/Rain/Sandstorm/Sun
`FieldStart`, `FieldResidual`, `FieldEnd`, and weather-damage ownership rows.
Sunny Day's separate freeze-immunity callback now has a legal reached-secondary
rejection fixture plus focused Cloud Nine suppression evidence. These cases
bring the expected deterministic corpus to 1,702 boundaries and the totals to
650 implemented, 396 inert, 16 unreachable, and 477 unsupported descriptors.

Extreme Speed adds one callback-free move descriptor and no kernel behavior.
Its legal Smeargle fixture proves that generated priority `+1` outruns a faster
Persian's ordinary action while retaining the shared accuracy, critical,
damage, and state pipeline. The corpus is expected to contain 1,704 boundaries;
classification is 651 implemented, 396 inert, 16 unreachable, and 476
unsupported.

The resolved callback-free identity audit adds 20 Gen 3 berries whose
`onEat: false` value is a non-executable sentinel, plus Illuminate, Pickup,
Run Away, and Stench after recursive mod inheritance removes their callbacks.
These identities install no handlers and consume no PRNG; legal fixtures prove
them through generic item transactions or ordinary turns. The exact,
deterministic corpus now contains 1,752 boundaries, and classification is 655
implemented, 416 inert, 16 unreachable, and 452 unsupported.

The singles `randomNormal` target mode is also closed without adding a target
RNG operation: Outrage, Petal Dance, and Thrash resolve the sole opposing
active through the ordinary foe pipeline while retaining the target mode in
the queue. Focused equivalence proves identical draws, events, and state to a
`normal` target under the same seed. Classification is therefore 656
implemented, 416 inert, 16 unreachable, and 451 unsupported; the corpus remains
1,752 boundaries.

Paralysis speed modification is generated as a status-owned `ModifySpe`
handler and the existing legal action fixture proves that quartering Persian's
Speed reverses its action order against Magikarp before the independent
one-in-four action check. This closes the previously omitted hook without a
runtime change: 657 implemented, 416 inert, 16 unreachable, and 450
unsupported.

Flail, Hyper Voice, and Vital Throw are admitted as generated move rows rather
than named runtime cases. Flail selects the same HP-bracket damage policy as
Reversal; Hyper Voice follows ordinary `allAdjacentFoes` singles routing; and
Vital Throw combines priority `-1` with `ALWAYS` accuracy. Eight legal Smeargle
fixtures add sixteen exact boundaries. The corpus is exact and deterministic
at 1,768 boundaries, with 660 implemented, 416 inert, 16 unreachable, and 447
unsupported descriptors. The verifier-only Showdown observer patch checksum
at that point was
`f8d1a7f13e37fec58001dec8bd0d8fb245fff2df22b0e1d72d5a9b89a0686cea`.

The inherited freeze `onAfterMoveSecondary` hook is unreachable in the frozen
Gen 3 format: generation now fails if any legal move resolves with
`thawsTarget`. This is an explicit reachability proof, not an implementation
claim. Totals become 660 implemented, 416 inert, 17 unreachable, and 446
unsupported.

Paralysis now owns its no-op/presentation `Start` boundary as a generated
status handler. A legal Static fixture proves ability-sourced installation,
ordered `DamagingHit` then `Start` dispatch, canonical status state, and zero
extra PRNG beyond Static's owned roll. Together with the existing speed and
action fixtures this closes the complete paralysis condition descriptor. The
exact deterministic corpus contains 1,770 boundaries; totals are 662
implemented, 416 inert, 17 unreachable, and 444 unsupported.

The species-conditioned stat-item family adds generic `ModifySpD` routing and
generated descriptors for Deep Sea Scale, Deep Sea Tooth, Light Ball, Macho
Brace, and Soul Dew. Legal positive and guard-control fixtures prove the four
reachable modifier branches. Soul Dew remains observable on legal non-Lati
holders: both callbacks are discovered and invoked, while the resolved Gen 3
OU bundle specializes their Latias/Latios-only positive branches to undefined
because those species are format-banned. Nine fixtures add 18 exact boundaries,
bringing the corpus to 1,788 boundaries and classification to 673 implemented,
416 inert, 17 unreachable, and 433 unsupported. The current verifier-only
observer patch checksum is
`4e588a54aa4648bc0c5f175cd92596e7d5d2f1878bc675223c82b2b10a91a19c`.

The ordinary real-HP damage commit now passes through the generic ordered
numeric `Damage` event after Substitute interception and before HP mutation.
False Swipe is the first generated source-effect witness: its declarative
program caps lethal damage to current HP minus one, including numeric zero at
one HP, without a move-name branch. Six legal differential fixtures add 13
exact boundaries and focused native coverage proves Substitute bypass. The
corpus is exact and deterministic at 1,801 boundaries; classification is 675
implemented, 416 inert, 17 unreachable, and 431 unsupported. The observer now
records source-effect identity so ordinary move damage remains distinct from
the exact Struggle-recoil bypass. Its checksum is
`b9f7c9e758591f839923f0630d6c3eb1ba5da7e821ea225ae0fbda8b4c529a54`.

Lansat Berry reuses the quarter-HP berry-consumption transaction and the
existing Focus Energy volatile lifecycle. Generated item data supplies the
volatile to install; the generic add-or-restart handler operation now admits
both ability-owned `TryHit` and item-owned `ItemEat` shapes while preserving
their distinct cancellation behavior. Three legal fixtures add six exact
boundaries, including duplicate Focus Energy consumption without reinstall.
The corpus now contains 1,807 boundaries; classification is 678 implemented,
416 inert, 17 unreachable, and 428 unsupported.

Mental Herb now follows the effective Gen 3 override inherited from Gen 4: its
ordered `Update` handler uses the item only when Attract is present, then ends
and removes Attract without berry semantics. The generic handler language owns
the volatile guard, held-item use transaction, and normal volatile removal;
generated data composes them without an item-name branch. Six legal fixtures
add 13 exact boundaries, including same-gender immunity, the Gen 3 Encore
exclusion, Cute Charm, and Recycle. The corpus now contains 1,820 boundaries;
classification is 681 implemented, 416 inert, 17 unreachable, and 425
unsupported.

Starf Berry extends that same quarter-HP transaction with a generated eligible
stat mask and one generic uniform-selection operation. The item-owned draw is
labeled separately, includes singleton samples, disappears for an empty
candidate set, and feeds the existing ChangeBoost/TryBoost path. Five seeded
fixtures rotate through Atk, Def, SpA, SpD, and Spe; a sixth proves the adjacent
threshold. Twelve exact boundaries bring the corpus to 1,832 boundaries and
classification to 684 implemented, 416 inert, 17 unreachable, and 422
unsupported. The verifier-only observer patch checksum is
`f8499699a5892bad81a586f529ed14d7b4922d6dfa4d53959ef509ee0f3dafeb`.

White Herb adds one reusable captured-negative-stage program at four generic
lifecycle boundaries: Start, any SwitchIn, AfterMove, and Residual. Item use
occurs between snapshot and mutation, matching the pinned Showdown staging;
positive stages are preserved and a missed self-drop does not consume the
item. Five legal fixtures cover connected and missed Overheat, both initial
Intimidate orderings, a later opposing switch, and a double-paralysis turn that
isolates Residual. Eleven exact boundaries bring the corpus to 1,843 boundaries and classification to 690 implemented, 416
inert, 18 unreachable, and 415 unsupported. The inherited `onAnyAfterMega`
callback is explicitly unreachable because Gen 3 has no Mega Evolution phase.
See `WHITE_HERB.md` for the source-to-kernel mapping.

Choice Band adds a generated priority-1 Attack relay and item-owned AfterMove
program over the existing descriptor-keyed choice-control lifecycle. The
indefinite Choice Lock captures the last executed move at Start, restricts the
next request at DisableMove, permits ordinary switching, clears through generic
switch cleanup, and removes itself when its required item is lost. The resolved
Gen 3 condition intentionally has no inherited BeforeMove callback. Four legal
fixtures cover connected damage, a miss, a status move, and switch reset. Their
14 exact boundaries bring the corpus to 1,857 and classification to 696
implemented, 416 inert, 18 unreachable, and 409 unsupported. See
`CHOICE_BAND.md`.

Aromatherapy and Heal Bell add the `allyTeam` execution boundary without a
move-name branch. Their generated move-owned Hit programs invoke one generic
team-major-status clear operation, which iterates the fixed-capacity party in
slot order and reuses the ordinary status-removal transaction. Aromatherapy is
silent per member; Heal Bell records its inherited silent cure effects.
Soundproof is banned by the resolved Gen 3 OU rule table, so this bundle
validly omits that unreachable exception while the generic opcode retains an
optional excluded-ability operand for other resolved bundles. Four legal
fixtures cover mixed active/bench statuses and clean-team no-ops. Their eight
exact boundaries bring the corpus to 1,865 and classification to 701
implemented, 416 inert, 18 unreachable, and 404 unsupported. See
`../cases/TEAM_STATUS_CURE_FIXTURES.md`.

Freeze now uses four generated status-owned lifecycle handlers rather than
phase-specific status branches. `BeforeMove` owns the labeled one-in-five thaw
draw, `ModifyMove` performs a defrost move's delayed cure, and `DamagingHit`
uses the immutable catalog type plus a living-holder guard. Three legal cases
prove random thaw, failed-thaw defrost, and the critical ordering in which a
successful Ember burn secondary is rejected before the target thaws. Focused
tests additionally prove later-flinch cancellation, lethal-hit non-cure, and
that dynamically Fire Weather Ball does not satisfy the base-type guard. Seven
exact boundaries bring the corpus to 1,872 and classification to 706
implemented, 416 inert, 18 unreachable, and 399 unsupported. The inherited
`onAfterMoveSecondary` hook remains explicitly unreachable. See
`FREEZE_LIFECYCLE.md`.

Oblivious and Role Play add generic volatile-Immunity and ability-transfer
boundaries. Generated programs own the Attract predicate, transfer admission,
and Update removal; the kernel owns ordered admission and one shared ability
replacement lifecycle. Four legal cases prove rejection before
`TryAddVolatile`, the Gen 3 Taunt negative, same-ability Role Play failure, and
the immediate post-hit Update that removes Attract after copying Oblivious.
Their nine exact boundaries bring the corpus to 1,881. They promote seven
inventory entries, bringing classification to 713 implemented, 416 inert, 18
unreachable, and 392 unsupported. See `OBLIVIOUS_ROLE_PLAY.md`.

Block, Mean Look, and Spider Web add one generated source-linked trapping
family. The generic kernel preserves Showdown's visible `trapped` condition and
normalizes the reachable internal `trapper` linked-status marker without
dropping its admission or effect-order boundary. Source switch/faint teardown,
duplicate installation, legal-choice restriction, and exact provenance are
shared semantics rather than move-specific branches. Seven exact boundaries
bring the corpus to 1,888. Nine unsupported entries and the formerly
misclassified unreachable `trapper` become implemented, bringing
classification to 723 implemented, 416 inert, 17 unreachable, and 383
unsupported. See `SOURCE_LINKED_TRAPPING.md`.

The bounded format validator already enforced the Block and Spider Web Baton
Pass bans through the same generated complex-set rule as Mean Look; focused
assertions now preserve all three operands. Separately, Gen 3 OU singles cannot
install Helping Hand's adjacent-ally condition, and Follow Me rejects in its
`onTry` callback before installing its slot condition when `activePerHalf` is
one. Those two conditions and five owned callbacks are therefore unreachable,
not unsupported. This evidence-only re-audit changes nine classifications
without changing runtime behavior or the 1,888-boundary corpus.

Metal Powder adds one generated `ModifyDef` owner binding and reuses the
existing species-guarded stat relay: an untransformed Ditto doubles Defense,
while a non-Ditto holder is unchanged. Two pinned differentials add four stable
boundaries, bringing the corpus to 1,892 and promoting the item plus its hook.
At that checkpoint Transform remained unsupported, so the Metal Powder claim
deliberately excluded transformed-Ditto suppression. The later Transform
family below now models that state explicitly.

Protect, Detect, and Endure now share one generated stalling-move operation.
Plugin condition rules explicitly declare the guard capability; the kernel
owns queue-aware admission, labeled `stall.success` draws, the shared counter
lifecycle, and failed-primary-effect termination. Protect supplies its ordered
TryHit handler, while Endure supplies a condition-owned Damage relay that caps
each ordinary connected hit at current HP minus one, including fixed damage
and every strike of a multihit move. Faint cleanup records remaining volatile
removals before terminal resolution. Four legal fixtures add 11 stable
boundaries, bringing the exact deterministic corpus to 1,987 and promoting two
moves, one condition, and thirteen callback ownership records.

Lock-On and Mind Reader now share one source-bound volatile product. The
generic handler interpreter owns duplicate admission, provenance matching,
literal-true Accuracy bypass, numeric-zero Invulnerability bypass, expiry, and
switch cleanup; neither move has a move-name branch in the kernel. Four legal
fixtures add 21 stable boundaries, bringing the exact deterministic corpus to
2,008 and promoting two moves, one condition, and six callback ownership
records. See `LOCK_ON_FAMILY.md`.

Wonder Guard is now a generated target-owned TryHit program over reusable
active-move category, type, and target-effectiveness predicates. Status,
self-targeted, and typeless moves bypass the gate; neutral and resisted damage
is rejected; super-effective damage continues through the ordinary hit
pipeline. Two legal fixtures add eight stable boundaries, bringing the exact
deterministic corpus to 2,016 and promoting the ability plus its callback.
See `WONDER_GUARD_FAMILY.md`.

Focus Band is now an item-owned ordered Damage handler whose generated program
owns the 1/10 draw, ordinary-move damage guard, and real-HP cap. Three legal
fixtures prove successful lethal survival, failed activation, and Showdown's
observable draw-before-lethality staging on nonlethal damage. They add six
stable boundaries, bringing the exact deterministic corpus to 2,022 and
promoting the item plus its callback. See `FOCUS_BAND_FAMILY.md`.

Burn, poison, and Toxic now expose their resolved status-owner Start handlers,
and Toxic resets its stage through a generated SwitchIn program rather than a
switch-action branch. The hazard recombination proves Showdown's
`EntryHazard -> SwitchIn reset -> residual` staging. One new legal fixture adds
four stable boundaries, bringing the exact deterministic corpus to 2,026 and
promoting four lifecycle callbacks. See `MAJOR_STATUS_LIFECYCLE.md`.

Leppa Berry now uses generated item-owned Update and Eat programs over a
generic stable PP-slot selector and capped restoration operation. Two legal
fixtures prove exact +10 restoration, non-first-slot selection, first-zero
precedence, clamping, and immediate activation after Trick. They add 35 stable
boundaries, bringing the exact deterministic corpus to 2,061 and promoting
the item plus its two callbacks. See `LEPPA_BERRY_FAMILY.md`.

King's Rock now uses a generated 130-move eligibility tag and an item-owned
`ModifyMove` program which appends a bounded flinch secondary to the active
move frame. Five legal fixtures prove successful and failed rolls, Shield Dust
filtering before PRNG consumption, and one roll per connected Arm Thrust hit.
The explicit Serene Grace recombination uses a roll of 18 to distinguish the
correct doubled 20% chance from an incorrect 10% implementation. The five
fixtures add ten stable boundaries, bringing the exact deterministic corpus to
2,071 and promoting the item plus its callback. See
`KINGS_ROCK_FAMILY.md`.

Shell Bell now enters through the ordered `AfterMoveSecondarySelf` event. The
active move frame carries actual opposing HP damage, so the generic generated
heal operation naturally caps overkill, aggregates multihit damage, and
excludes Substitute damage. Four legal fixtures add eight stable boundaries,
bringing the exact deterministic corpus to 2,079 and promoting the item plus
its callback. Classification is 812 implemented, 416 inert, 24 unreachable,
and 287 unsupported descriptors. See `SHELL_BELL_FAMILY.md`.

Fake Out now uses a canonical selected-move-action counter distinct from
active turns. It increments before `BeforeMove`, resets on switch-in, and feeds
one generated move-owned `Try` program; its flinch remains an ordinary
secondary. Three legal fixtures add eleven stable boundaries, bringing the
exact deterministic corpus to 2,090 and classification to 814 implemented,
416 inert, 24 unreachable, and 285 unsupported descriptors. See
`FAKE_OUT_FAMILY.md`.

Return and Frustration now read immutable normalized happiness through typed
base-power policies. The ABI distinguishes explicit zero from omission,
initialization canonicalizes the latter to 255, and Ocean observations expose
the value. Six legal fixtures add twelve stable boundaries, bringing the exact
deterministic corpus to 2,102 and classification to 816 implemented, 416
inert, 24 unreachable, and 283 unsupported descriptors. See
`HAPPINESS_POWER_FAMILY.md`.

A pinned inheritance/topology audit reclassifies Helping Hand's orphaned
`TryHit` and Toxic's two uninstalled nested callbacks as unreachable, and
Splash's Gravity-only/log-only callbacks as inert. No runtime behavior or
corpus size changes. Classification becomes 816 implemented, 418 inert, 27
unreachable, and 278 unsupported descriptors. See
`SINGLES_REACHABILITY_AUDIT.md`.

Pay Day is generated as an ordinary 40-power Normal physical move. Its
inherited `onHit` emits protocol text only and is inert at the canonical-state
boundary. Three legal fixtures cover connection, Protect, and Substitute,
bringing the exact corpus to 2,108 boundaries and classification to 817
implemented, 419 inert, 27 unreachable, and 276 unsupported descriptors. See
`PAY_DAY_FAMILY.md`.

Follow Me now uses the generic move-owned `Try` dispatcher with a generated
`RETURN_FALSE` program. In Gen 3 OU singles the inherited callback rejects
after PP deduction because there is one active per half; the Gen 3 slot
condition and redirect hooks cannot be installed. One legal fixture brings the
exact corpus to 2,110 boundaries and classification to 819 implemented, 419
inert, 27 unreachable, and 274 unsupported descriptors. See
`FOLLOW_ME_SINGLES.md`.

Lightning Rod's sole effective Gen 3 callback is a foe-target redirect, and
Showdown does not dispatch `RedirectTarget` when `activePerHalf` is one. The
ability identity is therefore inert and the callback unreachable for this
singles feature map. Two legal fixtures bring the exact corpus to 2,114
boundaries. A classifier-order audit at this point also corrected four earlier
callback-free abilities (`Illuminate`, `Pickup`, `Run Away`, and `Stench`)
from `implemented` to `inert`; this is a label correction with no runtime or
corpus change. Current classification is 815 implemented, 424 inert, 28
unreachable, and 272 unsupported descriptors. See
`LIGHTNING_ROD_SINGLES.md`.

The personal-move construction slice adds normalized IVs, a typed
generation-owned profile, generated move-local mutation, and ordinary
base-power consumption without a move-ID branch in the kernel. Six legal
Hidden Power fixtures cover formula endpoints, mixed-bit type construction,
the Gen 3 category split, effectiveness/immunity, and Counter/Mirror Coat's
exceptional identity-based routing. The exact corpus is now 2,147 boundaries;
classification is 821 implemented, 424 inert, 31 unreachable, and 263
unsupported descriptors. See `HIDDEN_POWER_FAMILY.md`.

The delayed-slot slice closes Future Sight, Doom Desire, and Wish through one
fixed-capacity slot-condition lifecycle. Six legal fixtures cover shared-key
collision, immutable damage snapshots, switching occupants, protection and
Endure interaction, delayed misses, lethal terminal resolution, and forced
replacement after residual completion. The exact corpus is now 2,172
boundaries; classification is 831 implemented, 424 inert, 30 unreachable, and
261 unsupported descriptors. See `DELAYED_SLOT_FAMILY.md`.

Snatch's generated duration-one condition and ordered `AnyPrepareHit` program
now have complete source, native, focused, and differential mappings. Nine
legal cases cover eligible and ineligible moves, expiry, called-move reentry,
Pressure ownership, healing, weather recovery, boosts, and Focus Energy. The
exact corpus is 2,174 boundaries; classification is 835 implemented, 424
inert, 30 unreachable, and 257 unsupported descriptors. See
`SNATCH_FAMILY.md`.

The retaliation slice closes Counter and Mirror Coat through one preparation,
damage-provenance, and state-derived fixed-damage family. Fifteen legal cases
cover class selection, failures, immunity, Substitute, multihit overwrite,
self-faint, Weather Ball's resolved category, delayed Future Sight provenance,
and overkill/forced replacement. A focused internal relay test proves capture
uses requested damage before real-HP capping. The exact corpus is 2,191
boundaries; classification is 843 implemented, 424 inert, 30 unreachable, and
249 unsupported descriptors after also reconciling the duplicated
`volatiles.trapper` inventory identity with its already-proven normalized
source-linked marker. See `RETALIATION_FAMILY.md` and
`SOURCE_LINKED_TRAPPING.md`.

The generic drag transaction closes Roar and Whirlwind through one generated
force-switch effect and a typed switch cause. Generated Ingrain and Suction
Cups handlers then prove ordered DragOut cancellation, Ingrain trapping and
residual healing, and ordinary volatile/ability owner discovery without
mechanic IDs in the kernel. Seven legal cases add 16 stable boundaries; the
complete corpus is exact at 2,207 boundaries with deterministic replay.
Classification was 853 implemented, 424 inert, 30 unreachable, and 239
unsupported at the drag checkpoint. Pursuit now closes four additional records
through generic queued-action interception, leaving Baton Pass as the remaining
switch-transfer family. The exact corpus is 2,219 boundaries. See
`native/DRAG_TRANSACTION_SPIKE.md` and `native/PURSUIT_INTERCEPTION_PLAN.md`.

The mutable move-slot slice closes Mimic, Sketch, and their two inherited
`onHit` hooks through one generated copy operation over explicit current/base
slot products. Mimic is temporary and restores its spent base slot; Sketch is
persistent and carries subsequent PP use through switching. The exact corpus
is 2,382 boundaries with byte-identical oracle and native replay. See
`MUTABLE_MOVE_SLOT_COPY.md`.

Regenerate the classification map after evidence changes with:

```sh
node verify/inventory/classify.js
```

## Authoritative Showdown extraction

`gen3ou-inventory.json` is the generated legal/reachable source inventory from
the pinned Showdown revision. Regenerate it with:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/pinned/showdown \
  node verify/inventory/generate.js verify/inventory/gen3ou-inventory.json
```

Showdown's own `TeamValidator` determines legal species, moves, abilities, and
items. Conditions and hooks come from effective descriptors, embedded
conditions, declarative references, every balanced condition-API call, direct
condition-container deletions, runtime format rules, and fixed-point traversal
of newly referenced global Conditions.

Move reachability has two boundaries. `TeamValidator` first derives moves that
can occur on a submitted Gen 3 OU set. If that set contains Metronome, the
inventory then includes every move admitted by the pinned effective
`metronome.onHit` predicate; simulator-forced Struggle is included independently.
Each generated move records whether it is submitted-set reachable, delegated by
Metronome, or simulator-forced. Descriptor, condition, and callback extraction
runs over this runtime closure, not only over submitted moves. The fixed closure
gate is:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown \
  node verify/inventory/test-runtime-move-closure.js
```

The frozen counts are 369 species, 354 moves, 70 abilities, 104 items, 6
nonvolatile statuses, 62 volatile conditions, 5 side conditions, 4 weather
states, 2 pseudo-weather conditions, 3 slot conditions, 12 target modes, 514
callback-hook ownership records, 42 effective format rules/bans, 16 reviewed
dynamic condition-ID arguments, 131 condition mutation calls, 7 direct
condition-container deletes, 23 traversed global Conditions, and 13
simulator-only effective condition records. This bucket means
the condition is not referenced as a primary condition ID; `trapper` is the
reviewed exception reached through the fourth `linkedStatus` argument to
`addVolatile`. The artifact
SHA-256 is
`8811be98cbbf6e0faa82f651b9fb8e7c77dd2f339e9e9db1a5d1b635419c2dd7`.

`cp5-provisional` means only that the identifier exists in the current native
slice. It is not a claim that every interaction involving the identifier is
implemented. Dynamically shaped condition calls have finite reviewed
resolutions in the generator, which fails if a call is added, removed, or no
longer matches that review. The frozen artifact has zero unresolved dynamic
condition calls or deletions. `test-condition-extractor.js` proves the balanced
scanner's API argument contract; `gen3-condition-completeness-audit.js`
independently proves the production result against the pinned oracle.
The separate generic-runtime audit parses all pinned `sim/**/*.ts` condition
API calls and direct owner-store mutations into the reviewed 95-row
`runtime-condition-paths.json` v2 ledger. Run its fail-closed gates with:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown \
  node verify/inventory/test-condition-completeness.js

# Individual component gates:
node verify/inventory/test-condition-extractor.js
node verify/inventory/test-runtime-condition-review.js
POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown \
  node verify/inventory/test-runtime-condition-paths.js
POKEMON_SHOWDOWN_DIR=/path/to/clean/pinned/showdown \
  node verify/inventory/test-condition-integration.js
```

These audits correct and protect the inventory denominator; they do not
promote any support classification.

Fly is intentionally still unclassified. Two exact differential cases cover
its charge/release marker, airborne `Invulnerability` rejection, residual
ordering, and Protect interaction. Two additional legal cases are retained as
pending evidence: release onto a switching target and a Thunder-induced
paralysis abort currently fail at native staging boundaries. The inherited
Fly-condition `onSourceModifyDamage` behavior for Gust and Twister is also
unsupported, so the implemented sub-hooks are not promoted into a whole-move
support claim.

The Charge family closes one move, one volatile, and six callback-owner
records through generated programs and the generic lifecycle/event kernel.
Crucially, its source mapping follows the fully resolved Gen 3 mod chain:
Gen 3 keeps the Electric-only BasePower callback but inherits Gen 8's cleanup
override, so every non-Charge move consumes the volatile. Six legal fixtures
cover Start, Restart, BasePower, AfterMove, MoveAborted, End, ordinary and
status moves, switch cleanup, and zero-HP faint cleanup. The complete corpus
matches the pinned oracle at 2,240 boundaries with byte-identical replay. See
`CHARGE_FAMILY.md`.

The locked-ramp family closes Rollout, Ice Ball, Defense Curl, their three
reachable volatile identities, and seven reachable callback-owner records
through one generated policy and the generic event/lifecycle kernel. Four
flattened records are classified unreachable: `rolloutstorage`, its
`onBasePower` hook, and the two `onAfterMove` producers which require a
later-generation connected non-contact hit. Six legal fixtures add 40 stable
boundaries. The complete 2,481-boundary corpus matches the pinned oracle with
byte-identical oracle and native replay. Classification at that checkpoint was
970 implemented, 424 inert, 37 unreachable, and 129 unsupported descriptors. See
`LOCKED_RAMP_FAMILY.md`.

The Stockpile family adds one generated bounded counter and ordinary Try,
BasePower, Hit, and AfterMove programs for Stockpile, Spit Up, and Swallow.
Twelve legal fixtures prove the three layers, cap failure, dynamic power,
immunity and called-move cleanup, Snatch staging, switch cleanup, exact healing,
and full-HP zero-delta cleanup. The complete 2,522-boundary corpus matches the
pinned oracle with byte-identical oracle and native replay. Current
classification is 982 implemented, 424 inert, 37 unreachable, and 117
unsupported descriptors. See `STOCKPILE_FAMILY.md`.

The Baton Pass family adds one generic move-driven switch continuation and a
generated boost/volatile transfer policy. Twelve legal fixtures cover boost
transfer, no-bench failure, retained action execution, and every Block/Mean
Look/Spider Web plus Bind/Clamp/Fire Spin/Sand Tomb/Whirlpool/Wrap trapping
rotation. While adding those rotations, the verifier exposed and the kernel
corrected the generic ordering between primary move effects, the move hit
callback, and global `Hit` dispatch. The complete 2,567-boundary corpus matches
the pinned oracle with byte-identical replay. Current classification is 985
implemented, 424 inert, 37 unreachable, and 114 unsupported descriptors. See
`BATON_PASS_BOUNDARY_AUDIT.md`.

The Conversion 2 family adds canonical resolved invoked-move history and one
generation-parameterized type-response operation. Six legal fixtures cover
no-history failure, exact Normal-response ordering, singleton selection,
switch cleanup, Weather Ball's resolved type, and Sleep Talk child provenance;
focused native tests cover Struggle's catalog override and Gen 3's already-held
type rule; a seventh fixture reaches Struggle legally through Torment and proves
its Normal override. The full 2,592-boundary corpus matches the pinned oracle
with byte-identical replay.
Current classification is 987 implemented, 424 inert, 37 unreachable, and 112
unsupported descriptors. See `CONVERSION_2_FAMILY.md`.

The Rage family adds one generated persistent handler-driven condition. Its
ordinary move effect installs the volatile only after a connected hit; generic
condition handlers reject status moves, boost Attack once per damaging hit,
and remove Rage at priority 100 before the holder's next move. Focused native
tests and two legal fixtures prove install, miss staging, multihit reaction,
status rejection, teardown/reinstallation, and switch cleanup. The corpus is
now 2,599 stable boundaries. Current classification is 992 implemented, 424
inert, 37 unreachable, and 107 unsupported descriptors. See `RAGE_FAMILY.md`.

The Minimize family reuses the ordinary boost/effect pipeline and generic
persistent-condition dispatch. The resolved Gen 3 inheritance chain supplies
a `+1` evasion boost, disables the later-generation accuracy callback, and
retains a no-op Restart plus a flagged-move `onSourceModifyDamage` callback.
One legal Metronome fixture and a focused native test prove installation,
restart, the generated move-flag guard, the exact 2x damage relay, and unchanged
PRNG staging. The complete 2,603-boundary corpus matches the pinned oracle and
both oracle and native replays are byte-identical to their repeats. Current
classification is 996 implemented, 424 inert, 37 unreachable, and 103
unsupported descriptors. See `MINIMIZE_FAMILY.md`.

The Spite family adds one generic generated target-PP mutation operation. Its
handler owns the Gen 3 uniform reduction draw before checking the target's
selected-move history and current slot, then clamps the deduction at zero.
Focused tests prove successful deduction, draw-before-failure staging, and
clamping; a legal Pressure/Heal Bell fixture proves the public state and trace
contract. The complete corpus and deterministic replay match the pinned oracle
at 2,606 boundaries. Current classification is 998 implemented, 424 inert, 37
unreachable, and 101 unsupported descriptors. See `SPITE_FAMILY.md`.

Camouflage and Conversion add one reusable current-slot type-overlay boundary.
Generated programs either provide a literal type or sample eligible types from
the holder's current mutable move slots; the kernel owns candidate filtering,
duplicate-slot weighting, labeled PRNG, failure, replacement, and switch
restoration. Focused tests and two legal differential fixtures add five exact
boundaries. Current classification is 1002 implemented, 424 inert, 37
unreachable, and 97 unsupported descriptors. See
`CURRENT_SLOT_TYPE_OVERLAYS.md`.

The Focus Punch family adds a generated prepared-action condition rather than
a move-pair resolver. An order-5 pre-turn action installs it before switches;
ordered condition handlers mark non-status hits, reject flinch admission, and
cancel the later move attempt after ordinary PP deduction. The same work fixes
the generic Substitute boundary so intercepted damage does not discover
target-owned `Hit` handlers. Focused tests and five legal differential fixtures
match pinned Showdown across 11 stable boundaries; the complete 2,622-boundary
corpus and deterministic replay remain exact. Current classification is
1008 implemented, 424 inert, 37 unreachable, and 91 unsupported descriptors.
See `FOCUS_PUNCH_FAMILY.md`.

Destiny Bond and Grudge add one source-sensitive faint-response boundary.
Generated volatile handlers receive the exact queued faint source and move
effect before teardown; generic operations either queue the opposing source's
faint or zero the living source's matching last-move PP. Thirteen legal cases
cover direct, indirect, Future Sight, Doom Desire, source-fainted,
BeforeMove, MoveAborted, and consecutive-refresh branches. They also exposed
and fixed the generic delayed-hit phase order: the post-spread Update occurs
after faint draining. Current classification is 1020 implemented, 424 inert,
37 unreachable, and 79 unsupported descriptors. See
`DESTINY_BOND_GRUDGE_FAMILY.md`.

Uproar closes seven further descriptor/hook records through generated global
status, lock, duration, and teardown handlers. Eleven legal fixtures preserve
the complete differential corpus at 2,693 exact boundaries. Classification is
1026 implemented, 424 inert, 37 unreachable, and 72 unsupported descriptors.

Imprison closes the remaining foe-scoped legal-choice family through one
generated persistent volatile and identity-free move-sharing operations. Five
legal fixtures add 12 exact boundaries, including admission failure, queued
cancellation, all-shared Struggle, and both switch directions. Classification
is now 1033 implemented, 424 inert, 37 unreachable, and 66 unsupported
descriptors. See `IMPRISON_FAMILY.md`.

Triple Kick and Twineedle close the specialized per-hit family through two
generated descriptor policies: repeat accuracy and hit-index base power.
Ordinary per-hit secondary execution is shared with the existing effect
pipeline. Four legal fixtures add eight exact boundaries covering all-hit,
later-hit miss, poison application, and poison immunity. Classification is
now 1035 implemented, 424 inert, 37 unreachable, and 64 unsupported
descriptors. See `SPECIALIZED_MULTIHIT_FAMILY.md`.

Secret Power resolves to an ordinary generated 70-power Normal physical move
with a 30% paralysis secondary in Gen 3. Its inherited `onModifyMove` callback
is still discovered and traced, but is an identity transformation in every
reachable terrain-free Gen 3 OU state. A focused descriptor test and two legal
differential fixtures cover both secondary outcomes. Classification is now
1036 implemented, 425 inert, 37 unreachable, and 62 unsupported descriptors.
See `SECRET_POWER_FAMILY.md`.

Present generalizes the existing weighted-power machinery into a generated
weighted move-outcome sum type: damage with a selected power, or a target
maximum-HP fractional heal. The selection lives only in the invocation frame;
the immutable descriptor and generic hit-admission pipeline remain shared.
Ten legal fixtures cover every outcome, misses, immunity, Protect, full HP,
and both Gen 3 Substitute interactions across 20 exact boundaries. Contrary
to later engine behavior, pinned Gen 3 inherits a Substitute handler that
blocks the healing branch despite Present setting `infiltrates`.
Classification is now 1038 implemented, 425 inert, 37 unreachable, and 60
unsupported descriptors; the complete corpus contains 2,737 stable boundaries.
See `PRESENT_FAMILY.md`.

Curse establishes generated invocation profiles without a move-identity branch
in the kernel. Effective Ghost typing selects an opponent-targeted persistent
condition, duplicate guard, and half-maximum-HP payment; the non-Ghost profile
retargets the invocation to its user and applies the ordinary Attack, Defense,
and Speed changes. Seven legal fixtures cover profile selection, Substitute,
Protect, duplicate rejection, same-turn residual damage, and independent
source/target switching. Focused native tests additionally prove handler trace
ordering and zero PRNG consumption. The complete differential corpus and both
replays match the pinned oracle at 2,767 stable boundaries; sanitizer,
random-play, Ocean-adapter, and admission gates pass. Classification is now
1049 implemented, 426 inert, 37 unreachable, and 48 unsupported descriptors.

Truant is represented as generated ability handlers over a typed,
Pokémon-owned Boolean state rather than the inherited modern volatile. Initial
SwitchIn normalizes Showdown's turn-zero setup boundary; BeforeMove cancels on
the stored phase; order-27 Residual toggles it. Eight legal fixtures prove
opening alternation, voluntary switch entry, post-residual forced replacement,
recharge, both sleep/wake phases, and two-turn move failure. Focused invariants
reject invalid setup and Boolean-state bits,
and the native, random-play, Ocean, admission, ASan/UBSan, complete
differential, and deterministic replay gates pass. The corpus contains 2,801
stable boundaries. Classification is now 1054 implemented, 426 inert, 37
unreachable, and 43 unsupported descriptors.

Pain Split adds one generic atomic bilateral direct-HP assignment operation.
It snapshots both current HP values, floors their shared average with a
minimum of one, and independently clamps each assignment to that Pokémon's
maximum HP. The operation deliberately bypasses damage, healing, fainting,
provenance, and PRNG channels. Six legal fixtures cover odd rounding, both
maximum-HP clamps, Protect, Substitute, and an equal-HP zero delta. The corpus
contains 2,813 stable boundaries, and classification is now 1056 implemented,
426 inert, 37 unreachable, and 41 unsupported descriptors.

Double Team and Memento close two further move records without move-identity
branches in the kernel. Double Team is an ordinary generated evasion boost,
reached legally through Metronome. Memento adds the typed `IF_HIT` self-faint
timing: a successful primary hit queues the user faint, while Protect and
Substitute cancel before that payment. Clear Body and saturated negative
stages do not cancel it, and the selected-action `AfterMove` boundary remains
before faint drain so White Herb composes normally. One Metronome fixture and
six legal Memento fixtures cover the boost, cancellation, ability filter,
item ordering, forced replacement, terminal result, and PRNG staging. The
corpus contains 2,827 stable boundaries, and classification is now 1058
implemented, 426 inert, 37 unreachable, and 39 unsupported descriptors.

Jump Kick and High Jump Kick close one reusable failed-attempt family rather
than two move-specific resolvers. Generated move descriptors select a typed
hypothetical-damage-to-source policy; the generic kernel owns MoveFail
dispatch, the fresh critical and damage-roll draws, the generated one-half
scale and minimum, the target-max-HP cap, ordinary Damage relay, and faint
queueing. Five legal fixtures cover an accuracy miss with lethal capped crash,
Protect, raw Ghost immunity, Foresight-negated immunity, Dig invulnerability,
and cancellation after a faster target self-faints. The corpus contains 2,839
stable boundaries, and classification is now 1062 implemented, 426 inert, 37
unreachable, and 35 unsupported descriptors.

Revenge closes the first target-specific recent-damage base-power guard through
two generic handler operations: match a positive current-turn `attackedBy`
record against the resolved target, then multiply the unsigned base-power relay
directly. Six legal fixtures distinguish missing, positive, fixed, zero,
stale, and replacement-target provenance. They add 15 stable boundaries; the
corpus contains 2,854 boundaries, and classification is now 1063 implemented,
426 inert, 37 unreachable, and 34 unsupported descriptors. See
`REVENGE_FAMILY.md`.

Dream Eater closes one move and its `TryImmunity` hook through a generated
predicate program requiring sleep and rejecting Substitute. The Gen 3 plugin
selects deferred-immunity hit staging: immunity is discovered before accuracy,
accuracy is still consumed, target `TryHit` may mask the pending rejection, and
the rejection is then reported before damage. Liquid Ooze's inherited Dream
Eater exception is a generated source-effect guard over the existing generic
drain handler. Seven legal fixtures cover awake rejection, ordinary drain,
full-HP healing, Liquid Ooze, Dark immunity, Protect, and Substitute. They add
16 stable boundaries; the corpus contains 2,870 boundaries, and classification
is now 1065 implemented, 426 inert, 37 unreachable, and 32 unsupported
descriptors. See `DREAM_EATER_FAMILY.md`.

Tri Attack closes one move and its callback hook through a generated immutable
three-status distribution and one generic sampled-status secondary operation.
The normal hit pipeline owns accuracy, critical, and damage; the existing
generation policy owns Serene Grace; ModifySecondaries owns Shield Dust; and
ordinary status admission owns existing-status rejection. Eleven legal
fixtures cover all three outcomes, failed and doubled secondary gates,
Shield Dust, Substitute, Protect, type immunity, rejection, and lethal damage.
They add 23 stable boundaries; the corpus contains 2,893 boundaries, and
classification is now 1067 implemented, 426 inert, 37 unreachable, and 30
unsupported descriptors. See `TRI_ATTACK_FAMILY.md`.

Forecast closes the remaining three ability-lifecycle records in node L. A
generated immutable form policy and two handlers drive a generic mutable
current-species overlay. The kernel now distinguishes single-owner event
delegation from ordered field-wide `eachEvent` dispatch, so weather changes and
their labeled PRNG draws compose with Cloud Nine, switching, replacement, and
expiry without a Forecast branch. Four legal fixtures add 24 stable boundaries;
the complete 2,917-boundary differential corpus and deterministic replay are
exact. Classification is now 1,070 implemented, 426 inert, 37 unreachable, and
27 unsupported descriptors. See `FORECAST_FAMILY.md`.

Low Kick adds canonical generated species weight and one generic
target-current-species weight bracket policy. The kernel interprets a validated
generation-owned table rather than naming the move or Gen 3 thresholds. Focused
tests cover both sides of every threshold, malformed-bundle atomicity, and
immunity staging; seven legal fixtures cover all six powers and Ghost immunity.
The complete 2,931-boundary corpus and deterministic replay are exact.
Classification is now 1,071 implemented, 426 inert, 37 unreachable, and 26
unsupported descriptors. See `LOW_KICK_FAMILY.md`.

Transform closes the mutable battle-profile family through a generated policy
and one generic profile-copy transaction. Live species/types/weight, non-HP
stored stats, boosts, moves and PP, Hidden Power profile, ability, and
current-turn speed staging are copied; switching and faint cleanup restore the
complete base profile. Five legal fixtures add 17 stable boundaries, bringing
the corpus to 2,948. Classification is now 1,073 implemented, 426 inert, 37
unreachable, and 24 unsupported descriptors. See `TRANSFORM_FAMILY.md`.

Smelling Salts and Belly Drum close the typed-formula/atomic-mutation node.
Smelling Salts uses generated target-status data at the pre-BasePower callback
stage rather than fabricating an event handler, and its target cure is skipped
when Substitute replaces the target with null. Belly Drum uses one generic
thresholded HP-cost/max-stage transaction. Seven legal fixtures add 16 stable
boundaries; the complete 2,964-boundary corpus and deterministic replay are
exact. Classification is now 1,077 implemented, 426 inert, 37 unreachable,
and 20 unsupported descriptors. See `ATOMIC_FORMULA_FAMILY.md`.

Mutable party order and delegated move execution close Assist, Metronome,
Beat Up, Beat Up's temporary condition, and five callbacks through two generic
operations: candidate-pool child invocation and a dynamic party-hit plan. Six
legal fixtures add 18 stable boundaries. Classification is now 1,086
implemented, 426 inert, 37 unreachable, and 11 unsupported descriptors; the
remaining unsupported records are format/rule surfaces. See
`PARTY_ORDER_DELEGATION_FAMILY.md`.

The resolved format-policy pass closes Switch Priority Clause Mod through the
existing generic speed-ordered switch queue and records HP Percentage, Cancel,
and Beat Up Nicknames as typed protocol policies outside canonical atomic
battle mutation. Nickname Clause then adds generated species display/base
metadata to the cold admission bundle, bounded UTF-8 normalization with
Showdown's UTF-16 length rule, same-family canonicalization, cross-species
impersonation rejection, and exact case-sensitive team uniqueness. Eleven
focused admission scenarios agree with pinned TeamValidator, including forms,
Unicode length, sanitation, defaults, duplicate ordering, and transactional
failure. Classification is now 1,087 implemented, 426 inert, 37 unreachable,
and 6 unsupported descriptors.

The obtainability provenance slice promotes Obtainable Moves, Obtainable Misc,
and their Obtainable aggregate after exact agreement on 136 pinned
TeamValidator fixtures, 1,925 exhaustive legal single-egg pairs, and 1,250
seeded recombinations. Classification is now 1,090 implemented, 426 inert, 37
unreachable, and 3 unsupported descriptors.

The terminal-policy slice closes the final three records: Endless Battle
Clause and the two resolved aggregate rules, Standard AG and Standard. The
generic kernel evaluates staleness only at the next-turn boundary after request
projection and before any next-turn PRNG. Generated item and ability traits
identify restorative-item cycles; mutable state distinguishes internal,
external, pending, and switch-scoped staleness. A 101-turn legal differential
case proves the complete natural Recycle/Skill Swap path and exact terminal
winner with no fixture state injection. Focused tests prove the strict turn
threshold, internal-only negative, legal-switch escape, unique-cycler loss,
two-cycler tie, independent universal turn cap, malformed-policy rollback, and
zero post-terminal PRNG consumption. Classification is now 1,093 implemented,
426 inert, 37 unreachable, and 0 unsupported descriptors. The complete
3,084-boundary corpus agrees exactly with the pinned oracle. See
`ENDLESS_BATTLE_CLAUSE.md`.
