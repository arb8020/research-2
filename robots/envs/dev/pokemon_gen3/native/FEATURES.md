# Slice feature map

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
The frozen differential corpus is under `verify/cases/`; the original
`verify/slice/case.json` survives as provenance for the converted regression.
Focused native cases are in `native/test_pokemon.c`.

| Supported feature | Authoritative Showdown boundary | Native boundary | Focused evidence |
|---|---|---|---|
| Omitted team gender | `sim/pokemon.ts` constructor fallback | `pokemon_battle_init`, `POKEMON_DRAW_TEAM_GENDER` | explicit gender consumes no draw; omitted gender resolves once in team construction order |
| Choice validation and requests | `sim/side.ts`, `sim/battle.ts` request/choice flow | `validate_choice`, `project_request` | illegal choice is atomic; move/wait/switch/terminal requests |
| Action construction and ordering | `sim/battle-queue.ts` | `compile_choices`, `queue_sort`, `last_queue` | priority, voluntary and forced switches; queue speed ties are implemented and unit-tested, but excluded from the differential feature map until startup event ties are modeled |
| Type interaction and natural immunity | `sim/dex.ts`, `data/mods/gen3/scripts.ts` | `type_multiplier`, hit resolution | Normal into Ghost; immunity is determined before accuracy, accuracy is consumed, and immunity wins over a miss |
| Grounding and Levitate | `sim/pokemon.ts` `isGrounded` | generated ability grounding capability | Grounded, Flying, and Levitate causes remain distinct; Levitate is not fabricated as an event handler |
| Scoped `TryHit` handlers | `sim/battle.ts` handler ordering; `data/abilities.ts` Water Absorb | bounded descriptor discovery/order/dispatch and handler trace | full-HP Water Absorb cancels Water damage; discovery capacity fails atomically; Levitate is not in this handler set |
| `ModifyAtk` relay modifiers | `sim/battle.ts` event ordering and `chainModify`; `data/abilities.ts` Guts; `data/items.ts` Black Belt | shared ability/item descriptor discovery, ordered Q12 accumulator, single relay application; sequence-tagged trace merge | unstatused baseline, item-only nonlethal two-action turn, burned Guts, and burned Guts plus Black Belt; matched damage 115 -> 127 for Black Belt and exact 4096 -> 6144 -> 6758 combined accumulator chain |
| Gen 3 type-boost held-item programs | `data/mods/gen3/items.ts` category-specific `onModifyAtk`/`onModifySpA` overrides | generated `(item,event,type,Q12)` bindings over the common numeric relay interpreter; category selects the observable event | all 17 new native programs rotate matching and nonmatching types; real physical and special damage paths, exact 4505/4096 rounding (4300/4096 for Sea Incense), and switch persistence; descriptor credit remains per-item |
| Holder-status BasePower predicates | `data/moves.ts` `Facade.onBasePower` | generated status mask plus generic discovered-holder guard and Q12 BasePower relay | every major-status variant, sleep exclusion, invalid-mask atomic rejection, and exact clean/paralyzed differential paths |
| Move-owned `Hit` callbacks | `sim/battle-actions.ts` move `singleEvent('Hit')` followed by holder-wide `runEvent('Hit')`; `data/moves.ts` `Refresh.onHit` | typed boolean-or-null move callback, generated required-status mask, then the shared status-clear transaction and ordinary `Hit` dispatch | direct coverage of every major status and no-status failure; exact clean-fail, burn, poison, and Toxic differential paths with labeled zero additional PRNG |
| Atomic boost-stage product copy | resolved Gen 3 `Psych Up.onHit` inherited from `data/mods/gen5/moves.ts` through Gen 4 | one generated move-owned `Hit` operation copies all seven stages directly from event target to source, bypassing boost events | exact mixed positive/negative overwrite, Substitute bypass, Protect bypass, Ghost target, Pressure, `attackedBy`, and zero additional PRNG |
| Item mutation and gating | `sim/pokemon.ts` `takeItem`/`setItem`; effective Gen 3 Thief, Covet, Knock Off, Recycle, Trick, Sticky Hold, and Mail descriptors | generated move effect programs plus generic take/set/recycle/direct-knock/swap transactions; generated ability and item take policies; explicit Knock Off slot lockout | focused transaction/state tests and exact differential cases for transfer, Mail gates, Sticky Hold immunity, Knock Off lockout, consumed-berry Recycle, sequential Trick rollback, empty holders, Protect, misses, and fresh installs; no item-operation PRNG |
| Callback-free constant-power attacks | flattened `data/moves.ts` records at the pinned Gen 3 mod | generated `PokemonMoveData` interpreted by the common hit/damage pipeline | 16-descriptor focused rotation and 32 exact differential boundaries; Hyper Voice remains fail-closed because no legal learner has an admissible ability |
| Gen 3 burn damage stage | `data/mods/gen3/scripts.ts` `modifyDamage` | explicit post-base-damage burn stage | ordinary burn applies 2048/4096; Guts suppresses the stage without representing burn as a handler |
| Toxic status lifecycle | `sim/pokemon.ts` status application; inherited Gen 3 condition ordering | tagged status, status-immunity check, residual work, switch-in lifecycle | 85%-accuracy application, Poison/Steel immunity, escalating damage, switch-in reset, order 10/suborder 6 |
| Move-started Sandstorm | `sim/field.ts`; inherited Gen 3 condition ordering | tagged weather and residual work | duration five, four ticks, expiry before the fifth, Ground/Rock/Steel immunity, order 8 |
| Weather-projected forms and event fan-out | `data/abilities.ts#forecast`; inherited Gen 3 Cloud Nine; `sim/field.ts` `setWeather`/`clearWeather`/`effectiveWeather`; `sim/battle.ts` `singleEvent`/`eachEvent` | generated `PokemonWeatherFormPolicy`, mutable current-species overlay, distinct single-owner and field-wide event operations, and `POKEMON_DRAW_EACH_EVENT_WEATHER_CHANGE_ACTIVE_ORDER` | four Forecast fixtures cover all weather forms, replacement/expiry, switch reset/re-entry, Cloud Nine's Gen 3 Start/End asymmetry, equal-speed ordering, and 24 exact boundaries; malformed form bundles and transformed-state guard are focused-tested |
| Protect/stall volatile | `data/moves.ts`; inherited Gen 4/5 `stall` condition | fixed-capacity tagged volatile and `POKEMON_DRAW_STALL_SUCCESS` | first block; forced 1/2 success then 1/4 failure; reset after Scratch or switching |
| Magic Coat reflection | effective Gen 3 descriptor inherited through `data/mods/gen4/moves.ts`; `sim/battle-actions.ts` selected `runMove` vs called `useMove` | fixed-capacity active-move invocation stack and declarative volatile-owned `TryHit` program | reflector consumes its volatile, calls a fresh bounced child with explicit target/source provenance, charges only selected PP, and matches both owned accuracy draws |
| Mirror Move provenance and call | `data/mods/gen3/moves.ts` `mirrormove.onHit`; `sim/pokemon.ts` `moveUsed`, `gotAttacked`, and `getLastAttackedBy` | per-Pokemon selected `last_move_id`, bounded singles `PokemonAttackRecord`, and declarative `CALL_LAST_ATTACK_MOVE` effect over the same invocation stack | copies a foe-targeted boost as a called move with fresh target resolution and no copied PP; no-history/current-moveset failures, turn retention, multihit final-damage, Substitute numeric-zero, faint, and switch lifecycle are projected against the oracle |
| Reflect and Light Screen | inherited `data/mods/gen4/moves.ts` screen conditions | descriptor-owned side-condition lifecycle plus reusable physical/special screen operation at Gen 3 damage Phase 1 | distinct generated identities and residual order, five-turn duration, physical/special category selection, switch persistence, critical bypass, and exact pinned differential damage |
| Move-owned side-condition removal | Gen 3 `brickbreak.onTryHit` in `data/mods/gen3/moves.ts` | generated move-owned `TryHit` program plus generic selected-side condition removal transaction | Reflect then Light Screen removal before damage and Substitute; immunity, Protect, and miss preserve both conditions; no removal-owned PRNG |
| Leftovers residual healing | inherited Gen 4 Leftovers override plus `data/items.ts` heal callback | generated item-owned Residual descriptor using generic `HEAL_MAX_HP_FRACTION(16)` | inherited order 10/suborder 4, floor/minimum-one/clamp behavior, Leftovers-before-burn ordering, and no intrinsic PRNG |
| Switch-out ability effects | inherited Gen 4 Natural Cure override and `sim/battle-actions.ts` switch staging | generic live-holder `SwitchOut` event plus generated `CLEAR_MAJOR_STATUS` ability program | cure precedes ability/item End, volatile cleanup, and replacement switch; status-free no-op and no intrinsic PRNG |
| Pressure PP deduction | Gen 3 `useMove` target construction; inherited Gen 4 Pressure and Snatch overrides | generic target-resolved additive `DeductPP` relay, selected-invocation PP ownership, and generated Pressure handler | ordinary hits, misses, immunity, Protect, foe-side targets, switch timing, called/locked suppression, and successful-Snatch re-entry; no intrinsic PRNG |
| Damp move prevention | inherited `Damp.onAnyTryMove`; Gen 3 `useMove` TryMove-before-self-faint staging | generic global `TryMove` discovery plus a generated guard over typed `self_faint_timing` | Explosion, Self-Destruct, and ordinary-move passthrough; PP spent before cancellation and no hit-pipeline PRNG |
| Contact-response abilities | Gen 3 `onDamagingHit`; `sim/battle-actions.ts` post-effect staging | generic target-owned `DamagingHit` event plus generated contact/chance/status programs | Flame Body, Static, and Poison Point; activation success/failure, Substitute exclusion, non-contact passthrough, and post-draw type immunity |
| Safeguard and Yawn | `data/moves.ts`; inherited Gen 4 Yawn condition | generated side/volatile descriptors and ordered `TryHit`, `TryAddVolatile`, `SetStatus`, Start, and End programs over the generic condition/status transactions | five-turn Safeguard admission gate; two-tick Yawn at residual `10/19`; existing-status and Insomnia rejection; recorded-source sleep; later-Safeguard expiry bypass; exact labeled PRNG staging |
| Partial trapping | inherited Gen 4 duration/order plus Gen 5 source-bound residual and base `TrapPokemon` condition callbacks | generated move descriptors install one source-owned volatile; generic condition duration, handler discovery, legal-choice restriction, and residual programs own the lifecycle | Bind, Clamp, Fire Spin, Whirlpool, Wrap, and Sand Tomb rotate through one implementation; exact labeled 3--6 turn draw, trapped legal choices, source switch cleanup, and no post-switch damage |
| Source-linked trapping | `Pokemon.addVolatile` linked-status transaction; Block, Mean Look, Spider Web; `trapped`/`trapper` conditions | generated Hit/Start/TrapPokemon programs plus generic hidden-counterpart admission, shared effect-order identity, source-owned teardown, and request restriction | all three moves, exact linked `TryAddVolatile` discovery, duplicate no-relink, source switch release, provenance, and zero intrinsic PRNG |
| Pre-hit self-faint and faint draining | Gen 3 `useMove` `selfdestruct: "always"`; `Pokemon#faint`; `Battle#faintMessages`; Gen 3 `getDamage` Defense halving | descriptor-selected pre-hit enqueue, battle-owned fixed-capacity FIFO faint queue, outer-action drain, and typed generation Defense divisor/action-cancellation policies | Explosion and Self-Destruct cover Protect, miss, Ghost immunity, Substitute, survivable damage, simultaneous replacement, FIFO double faint, and terminal tie |
| Negative boost filtering | inherited `onTryBoost` callbacks for Clear Body, White Smoke, Hyper Cutter, and Keen Eye | one mutable boost-product relay plus generated `DROP_ALL_NEGATIVE_BOOSTS` / `DROP_NEGATIVE_BOOST_STAT` programs | mixed-product focused tests and differential negative, positive, unrelated-stat, and Tickle partial-filter cases |
| Residual lifecycle | `sim/battle.ts` `fieldEvent('Residual')` and faint queue | fixed-capacity sorted `PokemonResidualWork` and lifecycle trace | Sandstorm before Toxic; duration/counter transitions; residual knockout suspends at forced replacement |
| Signed boosts and secondaries | `sim/battle-actions.ts`; move secondary descriptors | generic primary/self/secondary effect execution | Bulk Up/Growl, caps/failure/reset, Ember burn and Steel Wing Defense success/failure, block/immunity without a secondary draw |
| Recoil and drain | move recoil/drain tuples; Rock Head `Damage` event | damage-relative effect descriptor and ordered prevention handler | actual-damage basis, floor rounding, healing clamp, overkill, no-followup paths, and recoil faint ordering |
| Multi-hit loop | `data/mods/gen3/scripts.ts` | requested-hit loop and typed plan/hit/result trace | Bone Rush forced two/five hits, per-hit crit/roll/damage, early KO, and no premature count draw |
| Fixed and variable damage | `sim/battle-actions.ts`; Gen 3 Reversal callback | damage-formula descriptor and typed formula trace | exact Seismic Toss/Night Shade level damage and immunity; Reversal 20/40/80/100/150/200 brackets |
| Target-weight base power | `data/moves.ts#lowkick.basePowerCallback`; `sim/pokemon.ts#getWeight` | generated species hectogram mass plus validated `PokemonWeightPowerPolicy`, interpreted by generic current-species target lookup | every threshold edge, malformed-policy atomic rejection, immunity before critical/damage draws, six legal power fixtures plus Ghost immunity |
| Mutable battle-profile copy | `data/moves.ts#transform`; `sim/pokemon.ts#transformInto`, `setSpecies`, and `clearVolatile` | generated `PokemonTransformPolicy` and Hit program over generic current-profile copy, typed species-stat recalculation, and complete base-profile restoration | focused atomicity/reset test plus five legal fixtures covering Substitute, Hidden Power, re-transform, target rejection, copied ability, switching, Forecast, and exact PRNG staging |
| Target-status power and atomic self-cost formulas | `data/moves.ts#smellingsalts`; `data/mods/gen3/moves.ts#bellydrum`; `sim/battle-actions.ts#runMoveEffects` | generated target-status power predicate before BasePower events; generated Hit programs over generic status-clear and thresholded HP-cost/max-stage transactions; Substitute-null target staging | focused malformed-bundle atomicity plus seven legal fixtures covering clean/paralyzed power, cure, Substitute preservation, odd/even HP cost, threshold failure, and boost-cap failure |
| Random fixed-damage formulas | Psywave `damageCallback` in `data/moves.ts`; inherited Gen 3 80% accuracy | generated formula tag plus generation-owned inclusive multiplier policy and `POKEMON_DRAW_DAMAGE_FORMULA` | level scaling, floor/minimum-one rule, miss and Protect early exits, Dark immunity, Substitute interception, and exact labeled draw staging |
| Accuracy | `data/mods/gen3/scripts.ts` | explicit `ALWAYS | PERCENT(n)` move-data sum type carried through `ModifyAccuracy` and `Accuracy` | numeric misses stop later draws; all six boolean-accuracy moves skip stage math and the accuracy draw without bypassing immunity or later hit staging |
| Critical hit and damage roll | `sim/battle-actions.ts`, `sim/battle.ts`; Gen 3 damage in `data/mods/gen3/scripts.ts` | hit resolution, `gen3_base_damage` | exact critical damage and labeled draw staging |
| High-critical move descriptors | `sim/battle-actions.ts`; resolved Gen 3 move data | generated critical stage -> `ModifyCritRatio` -> generation-owned chance -> `CriticalHit` gate | all ten non-charge ratio-2 moves, exact 1/8 draw range, crit/noncrit rotation, secondary and singles-target coverage |
| PP, HP, faint, action cancellation | `sim/battle-actions.ts`, `sim/battle.ts` faint queue | `execute_move`, `cancel_side_actions` | knockout cancels the fainted side's queued move |
| Voluntary/forced switch and turn suspension | `sim/battle.ts`, `sim/battle-queue.ts` | `execute_switch`, phase/request transitions | forced replacement does not advance the turn early |
| Terminal result | `sim/battle.ts` win/tie resolution | `finish_battle` | winner and terminal request |
| Gen 3 next-turn Quick Claw roll | `sim/battle.ts` next-turn setup | `begin_next_turn`, `POKEMON_DRAW_END_TURN` | initial/new-turn draw, none during suspended turn |
| Deterministic replay | `sim/prng.ts` | embedded four-word seed and labeled draw trace | identical battle/view replay from init+choices+seed |

The generated immutable data comes from `tools/generate_slice_data.js`, which
refuses any other Showdown revision. The bounded inventory additionally routes
Bulk Up, Growl, Splash, Ember, Steel Wing, Body Slam, Double-Edge, Giga Drain,
Seismic Toss, Night Shade, and Reversal through generic operations. Bone Rush
now exercises the generic multi-hit loop as well as miss/immunity staging.
Thief/Covet transfer, Knock Off removal and Gen 3 slot lockout, Recycle, Sticky
Hold, Mail, and Trick are supported. Water Absorb, Guts, Rock
Head, the boost filters, and the 18 generated type-boost items are supported
callback-handler families. Burn is supported as explicit initial state,
Ember acquisition, its direct physical-damage stage, and residual damage.
Toxic, move-started Sandstorm, Protect/stall, Reflect, Light Screen, partial
trapping, and source-linked trapping are the supported condition lifecycles. No general item, status, weather,
volatile, or side-condition support is claimed. Showdown handler discovery for
other event families is not falsely equated with an empty native list.
The runtime accepts one coherent generation plugin bundle. Rules, generated
data, target geometry, format policy, manifest, and the resolved bundle carry
the same opaque fingerprint, capability ABI version, and declared subsystem
plus condition-family capabilities; any mismatch rejects before state
construction or PRNG. Capabilities are honest coarse interpreter boundaries,
not one bit per opcode. A
test-only generation-99 proof plugin runs the same kernel with different
critical odds, multihit outcomes, damage/fraction rounding, and condition
duration. Equal numeric generation fields cannot make foreign components
compatible.
The current `TryHit` discovery scope is the target ability. Water Absorb proves
one real callback path, while comparator tests cover distinct ordering keys.
The dual-screen differential proves simultaneous handler discovery and
Showdown's PRNG shuffle for exact handler-key ties.

Checkpoint 3 adds one compositional `ModifyAtk` example with two simultaneous
handlers: Guts precedes Black Belt under Showdown's ordering keys, accumulating
Q12 modifiers 4096 -> 6144 -> 6758 before one application to the relay value.
The item-only nonlethal case independently changes matched damage from 115 to
127 and executes both queued moves. Its sequence-tagged records prove the
serialized modifier trace preserves cross-action chronology.
Checkpoint 6 extends the same common item path to all Gen 3 type-boost items.
Physical types retain `ModifyAtk`; special types dispatch distinct
`ModifySpA`. This initial type-boost rotation did not claim unrelated stat
items. Later Checkpoint 6 families add Light Ball, Deep Sea Tooth, and Metal
Powder through generated species predicates, and Choice Band through the common `ModifyAtk`
relay plus an item-owned AfterMove/choice-control lifecycle. Descriptor-map credit remains
per-item and conservative: an item stays `unsupported` until a matching-type
pinned battle differential exists, even though the generated family rotation
already passes focused native tests.

Metal Powder's generated `ModifyDef` program doubles Defense only for an
untransformed Ditto holder; the now-supported transformed state takes the
existing declarative rejection path.

The scalar owner-handler family reuses the same ordered relay interpreter for
Compound Eyes, Guts, Huge Power, Hustle, Pure Power, and Thick Club. Generated
programs carry the Q12 multiplier and declarative status, physical-type, or
Cubone/Marowak holder guards. Hustle's Attack callback is deliberately a
direct, immediately rounded relay update; its accuracy callback and the other
families chain normally. `ModifyAccuracy` preserves Showdown's three distinct
inputs: integral numbers are modified, fractional staged values invoke and
trace handlers without changing the value, and boolean always-hit values
invoke handlers without consuming an accuracy draw. Focused tests cover all
major-status predicates and the 101 -> 151 -> 166 Hustle/item rounding witness;
the pinned differential corpus covers the seven hooks across 1050 boundaries.

Checkpoint 4 stores each condition at its natural owner: status on a Pokemon,
volatiles on a Pokemon, side conditions on a side, and weather on the field.
Residual work is discovered into a fixed-capacity queue and sorted by Showdown
ordering keys. In the supported interaction, Sandstorm order 8 runs before
Toxic order 10/suborder 6. Lifecycle and residual records use the same
monotonic semantic sequence as the other trace families.

The initializer carries the actual team size for each side. The current corpus
selects singles formats with maxima of one, two, or three members and includes
asymmetric teams; state iteration and legal switching use the per-side size.
Battle storage capacity remains six members per side.

Explicit omissions after Checkpoint 4 include regular poison, status curing
and Natural Cure behavior, Sand Stream/Sand Veil, weather replacement or
suppression, Detect/Endure, doubles screen scaling,
and general condition callbacks. Their descriptors may appear only as inert
set metadata where required by a legal fixture.

Checkpoint 5 adds typed effect records for boosts/status, damage-relative
recoil/drain, multi-hit plan/hit/result, and fixed/variable damage formulas.
Its additional PRNG labels are `move.secondary` and
`move.multihit_count`. Each connected multi-hit owns its critical and damage
roll; fixed-level damage owns neither. Verifier inputs may set canonical
`initial_hp` from 1 through max HP (default max HP) to isolate an HP bracket
without inventing prior battle history.

Sonic Boom and Dragon Rage use a separate descriptor-parameterized literal
damage formula. The hit pipeline still owns targeting, protection, accuracy,
and natural immunity; connected literal damage bypasses ordinary power,
critical, random roll, STAB, and resistance/weakness scaling.

Super Fang and Endeavor use target-relative fixed-damage formulas over mutable
current HP. Formula resolution occurs after the ordinary hit gates and before
the common Substitute/HP application boundary. Endeavor's inherited early
`Try` predicate is a generated move-owned handler, so an equal-or-higher source
fails before accuracy and consumes no draw. These are reusable formula and
handler boundaries; generic control flow contains neither move ID.

Checkpoint 6 extends that same loop to the thirteen callback-free ordinary
multi-hit descriptors. Numeric Showdown data is retained as a fixed count and
does not consume `move.multihit_count`; ranged `[2,5]` data selects through the
immutable Gen 3 outcome table `{2,2,2,3,3,3,4,5}`. The generic kernel knows
only fixed versus generation-distributed counts. Twineedle and Triple Kick are
not part of this family because they add poison and escalating per-hit power.

The frozen CP5 corpus contains 68 cases and 198 stable boundaries. It proves
the listed families, not arbitrary effect programs, every move sharing a
family, Substitute/Counter-style interactions, targeting/redirection, or
inventory completeness. Those remain Checkpoint 6 work.

All Checkpoint 4/5 source teams and the repaired Persian/Scratch derived cases
validate as Gen 3 OU. Twelve inherited Checkpoint 0--3 sources are retained as
simulator-mechanic fixtures outside that ladder-legality claim, chiefly because
of zero-EV sentinels and legacy evolution-level regression data.

The current Checkpoint 6 slice includes Spikes through the generic side-
condition/event interpreter. Generated Start/Restart/EntryHazard programs own
the layer payload and handler identity; the kernel supplies reusable
groundedness and fraction-damage operations. Switch entry runs EntryHazard,
then SwitchIn, then ability/item Start, stopping for faint replacement at each
boundary. Exact oracle fixtures cover three layers, the cap, all Gen 3
fractions, Flying/Levitate exclusion, and entry-hazard KO. Rapid Spin removal
is not part of this family.

Effect Spore reuses the generic `DamagingHit` interpreter. Its generated
program owns the contact guard, one-in-ten activation, and uniform selection
of sleep, paralysis, or poison; the kernel routes the selected value through
the same central status transaction used by moves and other abilities. Both
draws have distinct semantic labels, and no Effect Spore ID appears in generic
control flow.

Rough Skin uses the same `DamagingHit` boundary with a generated contact guard
and one reusable source-directed fraction-damage operation. Damage is
`floor(attacker base max HP / 16)`, with the central minimum-one rule and the
ability holder retained as provenance. The ordinary damage/faint transaction
stops a multi-hit plan if the response faints its source. The pinned
differential fixture also preserves Showdown's explicit handler order of one;
no Rough Skin ID appears in generic control flow.

Switch requests now separate public candidate actions from omniscient
definitive legality. Hidden ability traps therefore leave a switch visible
until the choice attempt; rejection updates only trap disclosure and the
request mask, without advancing battle state or PRNG, and the caller may retry
with a move. Forced replacement bypasses voluntary restrictions. This is the
generic request/choice transaction boundary; Arena Trap and Magnet Pull remain
unclassified until generated hypothetical-ability `maybeTrapped` discovery,
`cantUndo` exposure, and rejected-attempt differential observation are also
covered.

Reflect and Light Screen use generated side-owned `ModifyDamagePhase1`
handlers. The generic event interpreter orders all applicable handlers,
threads one Q12 accumulator through them, and applies the result once. The
generated programs own the side, category, and critical guards. Gen 3 OU uses
the singles modifier only. Doubles scaling belongs to a format plugin that can
state and test multi-active geometry.

Absorb, Mega Drain, Giga Drain, and Leech Life share one generated
damage-relative half-drain program. The descriptor owns power, type, category,
PP, and the drain fraction; the generic `AfterDamage` interpreter owns healing
from actual damage. Dream Eater and Liquid Ooze are not included in this
callback-free family.

Fly now exercises the generic two-turn lock with a distinct generated marker
descriptor. Marker duration is data, so duration-bearing semi-invulnerability
markers participate in the ordinary residual queue without a move-name branch.
`Invulnerability` dispatch is a generic target-owned event, and bypass is a
declarative move semantic (Thunder currently supplies the airborne bypass).
The exact supported slice covers charging, ordinary airborne rejection,
release, and Protect. Fly remains unclassified overall: its Gust/Twister
double-damage hook is not implemented, and the retained switch-target and
paralysis-abort fixtures currently expose unresolved staging failures.

Post-hit self drops are represented by a distinct typed phase rather than by
ordinary self secondaries. The generic interpreter consumes one labeled draw
for the complete sparse product, then performs one boost transaction. Overheat,
Psycho Boost, and Superpower use this boundary; Superpower's two stat changes
cannot be split by guards or event ordering. Submission, Take Down, and Volt
Tackle require no new kernel behavior: generated descriptors route their
resolved recoil fractions through the existing damage-relative after-move
operation.

Haze is a typed move-owned field callback. Its generated program enumerates the
current format's living active topology and clears each complete boost-stage
product directly, matching Showdown's `HitField` boundary without synthesizing
ChangeBoost/TryBoost events. Target-all resolution remains responsible for
Pressure before the callback; wider active geometries fail closed until their
format topology is represented.

Aromatherapy and Heal Bell exercise a resolved `USER_TEAM` target through
generated move-owned Hit programs. One generic team-major-status operation
prevalidates fixed trace capacity, walks living party slots deterministically,
and delegates each removal to the existing status transaction, including
linked Nightmare cleanup. Heal Bell's per-member cure traces and Aromatherapy's
silent clears are descriptor operands. The Gen 3 OU bundle omits Heal Bell's
Soundproof exclusion because the resolved format bans Soundproof; the opcode
still supports an optional excluded ability for another validated bundle.

Freeze is likewise a generated status-owner lifecycle. Its Start, BeforeMove,
ModifyMove, and DamagingHit handlers compose a labeled one-in-five thaw draw,
a typed defrost predicate, an immutable base-move-type predicate, a
living-holder guard, and the shared status-clear transaction. Generic control
flow contains no freeze, Fire-move, or defrost-move ID. The ordering matches
Showdown: later BeforeMove cancellation prevents the delayed defrost cure;
secondaries precede DamagingHit thaw; fainted holders cannot thaw; and a move
that becomes Fire dynamically does not pass the immutable-type predicate.

Oblivious uses the generic volatile-admission pipeline: duplicate/restart,
ordered `Immunity`, then `TryAddVolatile`. Its generated program rejects only
Attract, while the inherited legal-Gen-3 `TryHit` remains an observed no-op and
its generated `Update` removes an existing Attract. Role Play is a generated
move callback over a shared ability-replacement transaction. Admission checks
same identity and typed ability-policy flags; replacement runs old `End`,
changes the complete ability state, and runs copied `Start` only where the
generation policy requires it. Role Play consumes no target-selection PRNG.

Block, Mean Look, and Spider Web use one generated Hit program that installs a
source-linked condition. The generation plugin names both `trapped` and its
hidden `trapper` counterpart; the kernel owns admission, effect-order identity,
duplicate reuse, request restriction, and source switch/faint teardown. The
canonical view exposes only the visible relation with source provenance, while
the hidden helper's real event-discovery boundary remains observable.

Assist, Metronome, and Beat Up share the generic delegated-move machinery.
The battle state stores mutable party order as a permutation of fixed team
slots. Generated pools enumerate callable moves in that order, so duplicates
retain their weight and selection remains a single labeled draw. Beat Up uses
a generated party-hit plan whose contributors supply per-hit stats; ordinary
accuracy, immunity, critical, damage, effects, and faint draining remain in
the common hit pipeline. The generation plugin supplies the non-interacting
type policy rather than the kernel naming Beat Up or Gen 3.
