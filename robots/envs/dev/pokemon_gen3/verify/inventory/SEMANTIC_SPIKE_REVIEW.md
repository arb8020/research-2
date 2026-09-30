# Checkpoint 6 isolated semantic spike review

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The outer Pokémon source directory is untracked, so a Git worktree would omit
it. Each lane therefore used a private copied Git repository with a committed
baseline, a separate pinned Showdown checkout, and a separate verifier output
directory. No spike changed integration-generated data, observer patches,
JSONL output, native IDs, or the shared Showdown checkout. Passing a spike is
design evidence, never a support claim.

## Integration decisions

### Side-condition lifecycle

Spike: `/private/tmp/pokemon-screen-lifecycle-spike`, commit
`4f31dee4575a79933751c436599a8dcdd01e3ded`.

Light Screen and Reflect already share an honest generic lifecycle. Their
remaining architectural leak is damage code branching on condition kind and a
literal half modifier. Integrate them as generated side-owner `ModifyDamage`
handlers with declarative category, critical-hit, and battle-geometry guards.
Do not keep the spike's parallel generation table.

### Partial trapping and switch legality

Spike: `/private/tmp/pokemon-partial-trap-spike.7mz58u`, commit
`d3e64eb`.

The source-bound volatile lifecycle is sound. `TrapPokemon` currently mutates
the request directly, which crosses the event/request boundary. Port the typed
switch-restriction buffer and pure atomic switch-choice reducer first; only
then make `TrapPokemon` emit `DISALLOW_ALL`. Lifecycle damage and switch
legality remain separate semantics.

### Always-hit accuracy

Spike: `/private/tmp/gen3-always-hit-spike.q412gC/project`, commit
`07e572abe9ae01c002bb0bd5e11913f3df5b6725`.

Showdown's resolved descriptor is the sum type `true | number`; numeric 100 is
not always-hit. The `native/` kernel already models the correct
`ALWAYS | PERCENT(n)` distinction, stages and draws only the numeric variant,
and validates illegal encodings. Do not port the spike's second type. Future
work should remove the old engine's zero sentinel and prove conditional
numeric-to-always transitions such as rain Thunder and Lock-On separately.

### Pre-resolution self-faint

Spike: `/private/tmp/pokemon-self-faint-spike.088u9G`, commit
`f222529`.

Current self-destruct staging is largely correct: PP and TryMove precede the
self-faint; a successful self-destruct queues the user faint before immunity,
accuracy, Protect, critical, and damage; Gen 3 singles cancels remaining
actions. Replace the ambiguous cancellation boolean with a validated typed
faint-action policy. Do not claim the family fully proved until Damp,
source-only action cancellation, Defense staging, and Pressure are covered.

### Later-family ranking

The next bounded families after choice control are:

1. low-HP type abilities (`Blaze`, `Overgrow`, `Swarm`, `Torrent`) to earn
   declarative holder-HP and move-type guards over one ordered `BasePower`
   modifier event;
2. contact-response abilities to earn generic post-damage `DamagingHit`
   dispatch and owned probability;
3. constant/current-HP/difference damage formulas for Dragon Rage, Sonic
   Boom, Super Fang, and Endeavor.

The inventory extractor is correct here: Gen 3 inherits the Gen 4 ability
overrides, which explicitly remove `onModifyAtk`/`onModifySpA` and install
priority-2 `onBasePower` callbacks. Earlier notes claiming stat-relay hooks
were based on the wrong inheritance boundary and must not guide implementation.

## Dependency order

1. Finish Disable, Encore, and Torment on the now-proven choice-control
   boundary; Taunt is the exact vertical witness.
2. Port the pure switch-choice reducer independently of partial-trap lifecycle.
3. Convert screens to generated `ModifyDamage` handlers.
4. Type the self-faint queue-cancellation policy and add the missing proof
cases before changing its support claim.

### Torment request restriction

Audit: `/private/tmp/gen3-torment-audit.q7Qg8b/project`, baseline commit
`0665863`; independent pinned oracle checkout
`/private/tmp/gen3-torment-audit.q7Qg8b/showdown`.

Torment is deliberately smaller than the other choice-control conditions. It
has no duration, stored move, residual, queued-action guard, or PRNG operation.
Its sole behavioral policy is request-time
`DISABLE_LAST_NONFALLBACK`: read the holder's current `lastMove` whenever a
request is built. Consequently a faster Torment does not cancel the slower
move already in the queue, and a one-move set cycles
`move -> queued move -> Struggle -> move -> Struggle`. Switching bulk-clears
the volatile and `lastMove` without running End. The integration slice uses
this reducer operation. The five-boundary `choice-torment-cycle` differential
now proves queued-move preservation, request-time Struggle alternation, PP
ownership, and persistent Torment discovery. Classification remains
conservative until the switch-clear/no-End boundary is also proved.

The first isolated Torment oracle fixture exposed a prerequisite outside the
condition itself: Gen 3 Struggle starts as Normal data but its resolved
`ModifyMove` callback changes it to typeless. Without that callback, native
incorrectly applied STAB and produced 26 damage/6 recoil instead of the
fixture's 17/4. The kernel now has a reusable generated
`SET_ACTIVE_MOVE_TYPE` handler operation, and Struggle binds it at
`ModifyMove`. The resolved plugin additionally identifies `???` as a
non-interacting type: the generic kernel omits the observable immunity
decision but retains Gen 3's ordinary 100% accuracy draw. Exact differential
evidence is 17 damage and 4 recoil, with no Pound PP consumption during the
fallback action.

### Disable and Encore Start transactions

Disable spike: `/private/tmp/pokemon-disable-spike`, commit
`5855a94cae4136d6bde21df0e5efb54854e5c868`.

Encore spike: `/private/tmp/pokemon-encore-spike.SJ8uKJ`, commit `e0a293d`.

Both conditions sample duration before Start and therefore require one generic
atomic transaction: reserve capacity, draw, tentatively install, dispatch
Start, and either commit lifecycle evidence or roll back while retaining the
draw/handler evidence. The resolved pinned Dex shows that both Disable and
Encore increment their sampled duration when the target already acted;
end-of-turn residual ticking accounts for the queued-target offset. Disable
draws from `[2,6)` and Encore from `[3,7)`. Both capture the last usable move,
while Encore also
rejects descriptors carrying `failencore`. Disable's ordinary move has a
separate pre-duration TryHit predicate requiring a non-fallback last move;
that staging check does not replace Start's authoritative PP revalidation.

The integration API now represents the queue-relative duration law and
condition-owned PRNG labels explicitly. The generic installer transaction,
Disable data/policy, request filter, queued-action guard, and early admission
predicate are wired. Do not port either spike's temporary condition-name
checks. Three differential cases now prove both queue-relative duration
branches, queued-action rejection, request restriction, duration expiry/End,
and switch cleanup without End. The native focused suite additionally proves
failed-Start rollback and non-rewound effect order. Remaining proof is an
observable generated move-self form of Disable's TryHit admission and a
failed-Start differential using symmetric verifier-owned initial PP.

The independent Encore residual spike at commit
`ef88b230747d04da77ebf0c020104d5a283f59b9` confirmed that no new queue kind is
needed. Existing duration-bearing volatile residual work owns order 10,
sub-order 14, and duration decrement; an owner handler only checks stored-move
usability, dispatches End, and removes the exact installation. Its
owner-discovery design is integrated with residual work keyed by descriptor,
installation generation, and effect order, collision-checked synthetic handler
identities, and exact End/removal.

Encore is now serialized as resolved Gen 3 data and proved by three pinned
differential cases: failed Start followed by a pre-action override,
post-action duration adjustment followed by switch clearing without End, and
natural PP exhaustion followed by residual End/removal. These add 15 exact
boundaries; the complete corpus is exact at 1,183 boundaries and both oracle
and native replay are byte-identical. Focused native coverage additionally
proves selected-versus-executed PP ownership, request restriction, the two
queue-relative duration branches, and the zero-PP early-end path. The
classification map remains unchanged until the broader choice-control family
review is complete.

Disable's remaining admission boundary is now generated rather than encoded
as a move ID or a bespoke move-data policy. The resolved plugin emits a
move-owned `TryHit` descriptor whose one-operation program requires a
non-fallback target `lastMove`; the generic kernel dispatches it through the
same move-self event path used by other resolved move callbacks. The pinned
observer now exposes move-owned `TryHit` single-event execution.

Start revalidation uses an explicit three-way move-slot state: absent,
present with zero PP, or present with usable PP. This preserves Showdown's
otherwise surprising distinction: Disable rejects only a matching zero-PP
slot, while an absent slot is admitted; Encore requires a present usable slot.
Two new differential cases prove no-`lastMove` admission failure without a
duration draw and natural 16-use PP exhaustion followed by duration sampling,
Start rejection, and atomic rollback. Target `TryHit` remains after the Gen 3
accuracy draw in the native staging proven by the existing miss/Protect
corpus; move-owned `TryHit` follows target interception. The complete corpus
is exact at 1,203 boundaries. Support classification remains unchanged until
the serialized family review.
5. Repair the starter-ability inventory source boundary, then begin the
   low-HP guard family.

The integration owner must port these changes selectively and rerun the full
differential, replay, generator, random/Ocean, sanitizer, and inventory gates
after each support-classification change.

### Choice-control family closure

The Disable, Encore, Taunt, and Torment family is now classified from one
descriptor-keyed choice-control kernel. Seven final recombination fixtures
cover duplicate Disable and Encore without a duplicate duration draw, Protect
prevention, Substitute bypass, a type-immune attack retained as Disable's
`lastMove`, and Taunt/Torment switch clearing without End. Together with the
earlier lifecycle fixtures, focused tests, and generated move-owned Disable
`TryHit`, these close 19 previously unsupported Disable/Encore/Torment records;
Taunt's earlier classification now has the same switch-boundary evidence.

The complete differential corpus is exact at 1,225 boundaries. Oracle and
native replays are byte-identical, and the fresh ASan/UBSan verifier artifact
also contains and matches all 1,225 boundaries. The descriptor map remains
structurally complete at 1,539 records and now reports 671 unsupported records.

### Mist side-condition slice

Mist is now a generated side-owned condition, not a move-specific resolver.
The generic side lifecycle installs it for five turns, refuses duplicate
installation without refresh, persists across switches, and removes it at the
resolved Gen 3 residual boundary. Its `TryBoost` descriptor reuses the same
two-operation program as Clear Body: guard source-not-target, then delete every
negative field from the boost product. Positive, zero, and self-sourced fields
remain intact.

The pinned source audit exposed a mod-inheritance detail: Gen 3 inherits the
Gen 4 Mist residual-order override, so the resolved order is 3; handler and
residual sub-order remain 4. The generator asserts this resolved shape instead
of copying the base move table's order 26.

`mist-lifecycle-filter` proves installation, external Smokescreen filtering,
duplicate non-refresh, all five residual ticks, expiry, and the first
unprotected drop. Focused native coverage proves mixed-product filtering and
self-source bypass. The full corpus is exact at 1,232 boundaries, deterministic
oracle/native replay is byte-identical, ASan/UBSan matches all 1,232 records,
and random/Ocean tests pass. The map remains structurally complete at 1,539
records and now reports 666 unsupported records.

### Starter low-HP BasePower ability slice

Blaze, Overgrow, Swarm, and Torrent now share one generated three-operation
program: guard holder HP at or below one third, guard the active move type,
then chain a 1.5x Q12 modifier. The generic damage path runs one ordered
`BasePower` event containing both holder-owned ability handlers and move-owned
handlers; Solar Beam remains an exceptional move handler without creating a
second event boundary.

Six focused differential cases prove the exact floor threshold, above-threshold
identity, type mismatch, all four matching types, and composition with
Charcoal. The full corpus is exact at 1,244 boundaries. The descriptor map
remains structurally complete at 1,539 records and now reports 658 unsupported
records.

### Safeguard admission foundation (not yet a support claim)

Safeguard now uses the generic five-turn side-condition lifecycle, with the
resolved Gen 3 residual order/sub-order `4/4`. Major-status installation now
dispatches the typed `SetStatus` event before mutation and before sleep-duration
PRNG; confusion admission reuses the existing `TryAddVolatile` boundary. Both
callbacks are generated side-owned handler programs guarded by source/target
provenance. The status program also carries the pinned Yawn source-effect
exemption as generated data.

Focused native tests prove installation, duplicate non-refresh, external
major-status cancellation, external confusion cancellation, self-confusion
bypass, and cancellation before status mutation. `SetStatus` now discovers
Safeguard, format clauses, and ability callbacks into one ordered handler list;
the ordering PRNG therefore belongs to the actual tied slice rather than a
guessed handler count. Focused clause tests also prove Showdown's allied-source
exemption, including a different team slot, and ability-owned immunity is no
longer reported as natural typing.

The seven-boundary `safeguard-lifecycle-status-confusion` differential proves
installation, switch persistence, Toxic and Confuse Ray interception, exact
expiry, and post-expiry confusion. The complete 1,251-boundary corpus and both
oracle/native replays are exact. This remains deliberately short of a support
classification change: honest Yawn coverage requires Yawn's own volatile
lifecycle. Infiltrating moves are not a reachable Gen 3 concern, but the
generated provenance guard remains the correct reusable boundary for a later
generation plugin.

### Yawn delayed-status closure

Yawn now closes that boundary through the common condition installer rather
than a move-specific turn branch. Generated data supplies an always-hit move,
the target-status admission predicate, a fixed two-tick volatile at residual
order/sub-order `10/19`, explicit Start/End handlers, and an End program that
attempts sleep using the installed condition's recorded source. Insomnia and
Vital Spirit reject the semantic Yawn volatile through ordinary
`TryAddVolatile` ability handlers; Safeguard rejects admission but deliberately
permits Yawn-owned `SetStatus` at expiry, matching pinned Showdown provenance.

Focused tests cover successful delay/expiry, no accuracy draw, exact sleep
duration staging, existing-status rejection, ability rejection, Safeguard
admission rejection, and the later-Safeguard expiry bypass. Four differential
cases independently prove those boundaries, including handler order and the
ability-owned immunity event. The complete corpus is exact at 1,260 boundaries,
with deterministic oracle and native replay. Yawn and Safeguard are therefore
classified as supported; this is a claim about the explicit feature map, not
exhaustive enumeration of battle states.

### Spikes and entry-hazard boundary

Spikes is a durationless side-owned condition interpreted by generated Start,
Restart, and EntryHazard programs. The kernel contributes only generic owner
counter mutation, groundedness through type data and the ability ground-
immunity capability, and counter-indexed max-HP fraction damage. Generic
control flow contains no Spikes or move-name branch.

Focused tests prove layer installation, the three-layer cap, durationless
state invariants, and exact layer-three damage. Two differentials prove all
`3/24`, `4/24`, and `6/24` fractions, Flying and Levitate exclusion,
switch-before-hazard ordering, capped restart failure, and hazard KO followed
by one-sided forced replacement. The full corpus is exact at 1,273 boundaries
and native replay is byte-identical. Spikes, its three owned hooks, and the
singles `foeSide` target are classified as supported. Rapid Spin removal and
later-generation grounding overrides such as Ingrain remain separate.

### Reflect and Light Screen damage handlers

Reflect and Light Screen now enter the ordinary damage pipeline through two
generated `ModifyDamagePhase1` descriptors. Both programs guard source and
target identity, side ownership, move category, and critical state before
chaining the singles Q12 modifier `2048`. The generic kernel contains no
screen ID or move-name branch.

The dual-screen fixture exposed a generic ordering error. Native discovery had
used condition installation order for every event. Showdown uses installation
order only for SwitchIn and redirect callbacks, so two screen callbacks tie
and consume `event.modifydamagephase1.handler_order`. The kernel now keeps
installation order for owner liveness but excludes it from other event sort
keys.

`screen-attacker-side-no-effect` proves that a screen on the attacker's side
does not reduce outgoing damage. `screen-dual-category-routing` proves both
category guards, both critical bypasses, and tied-handler ordering. The full
corpus is exact at 1,282 boundaries. Oracle and native replays are
byte-identical, and ASan and UBSan match the same 1,282 boundaries. Doubles
screen scaling and later-generation infiltration remain outside Gen 3 OU.

### Callback-free half-drain descriptors

Absorb, Mega Drain, Giga Drain, and Leech Life are one declarative family in
the pinned resolved Gen 3 data: an ordinary damaging move plus `drain: [1, 2]`.
The generator validates that shape and emits the existing generic
`DamageRelative` operation at `AfterDamage`; the kernel has no move identity
branch. Focused tests verify every flattened descriptor, including Gen 3
maximum PP and the type-based physical/special category.

`drain-family-rotation` exercises the three newly admitted descriptors through
one legal Smeargle set and matches Showdown at four stable boundaries. Dream
Eater is excluded because its sleep-only `TryImmunity` predicate is additional
semantics. Liquid Ooze is separate because it changes the generic heal
transaction through `TryHeal`.

The complete corpus remains exact at 1,286 boundaries. Oracle and native
replays are byte-identical, and ASan and UBSan match the same boundaries.

### Literal fixed damage

Pinned `BattleActions#getDamage` checks natural immunity before returning a
numeric `move.damage`, and returns before ordinary base-power and effectiveness
arithmetic. The native kernel now represents that boundary as
`POKEMON_DAMAGE_FIXED_LITERAL` with a generated descriptor operand. It does not
reuse `power`, branch on move identity, or consume critical and damage-roll
draws.

`fixed-literal-sonic-boom` proves numeric accuracy, exact 20 damage, switch
retargeting, and Normal immunity. `fixed-literal-dragon-rage` proves exact 40
damage against a Dragon-resistant Steel target. The full 1,291-boundary corpus,
both deterministic replays, and ASan/UBSan are exact.

### Target-relative fixed damage

Super Fang and Endeavor are descriptor-selected formulas over current battle
state, not base-power moves. The generation policy resolves floor-half target
HP with minimum one, or target HP minus source HP. The generic hit pipeline
still owns accuracy, natural immunity, protection, Substitute interception,
damage application, and tracing.

Endeavor additionally inherits an early Gen 3 `Try` callback. A generated
move-owned program enforces `source.hp < target.hp` before invulnerability,
accuracy, protection, or any PRNG draw. It is intentionally not deferred into
formula evaluation. `target-relative-formulas` proves the odd half, HP
equalization, and no-draw equality failure. `target-relative-substitute` proves
formula evaluation against real HP before the common Substitute cap. The full
1,299-boundary differential, deterministic replays, and ASan/UBSan are exact.
The test-only observer now records numeric damage callbacks generically; its
pinned patch checksum is
`b8055d17489c24fae1c9d803acdf2e2b2ab29b6a87d286313423d81fefc9c164`.

### Residual status identity and Shed Skin

Residual discovery snapshots the installed status identity, generation, and
ordering keys. Execution revalidates that identity before applying captured
status work. This matches Showdown's stale-owner check and prevents poison,
burn, or toxic damage captured before a same-residual-phase cure from running
after the status is gone.

Shed Skin is a generated ability-owned Residual program at the effective Gen 3
order 10/suborder 3. It guards holder liveness and status presence, owns one
labeled 33/100 draw, and invokes the shared major-status removal operation.
Twelve legal fixtures cover successful and failed cures for burn, paralysis,
poison, Toxic, and freeze, plus the no-status/no-draw and
KO-before-residual/no-draw paths. Toxic fixtures carry an explicit tagged
initial stage, so its residual increment and damage are real oracle behavior
rather than an uninitialized observer artifact. Shed Skin and its Residual
hook are classified implemented; sleep already has independent lifecycle
coverage through the shared clear operation.

The switch lifecycle also now suppresses incoming ability/item Start handlers
when entry hazards faint the incoming Pokemon. This is covered by a focused
Pressure-plus-Spikes regression.

Freeze BeforeMove staging now always consumes its labeled 1/5 thaw draw. A
successful draw cures before move execution; after a failed draw, an ordinary
move is blocked while a defrost move proceeds and cures at the later
ModifyMove-equivalent boundary. Focused tests cover both draw outcomes. Fire-
hit thaw now consults the immutable generated move descriptor rather than an
actively modified move type; a focused sunny Weather Ball case proves that
becoming Fire dynamically does not thaw the target. The remaining freeze work
is explicit: sunny-weather admission immunity and moving target thaw into the
ordered DamagingHit handler.

The complete corpus is exact at 1,397 boundaries. Oracle and native replay are
byte-identical. The deterministic generator, inventory contract, event
vocabulary, native/random/Ocean suites, and ASan/UBSan semantic comparison all
pass. Leak detection is unavailable in this platform's AddressSanitizer
runtime, so that option was disabled rather than treated as evidence. The
current observer patch checksum is
`a2fedbc5447519b847fc5d538399b70a07db9d8f5ac05f578b0d7055d9dce805`.

### Explicit elemental heal interception

Water Absorb no longer asks its caller to infer whether healing succeeded from
an HP delta. The handler invokes the shared `TryHeal` transaction, receives an
explicit `APPLIED | FAILED` result, and attaches immunity presentation to the
subsequent null cancellation. Healing, cancellation, and protocol presentation
are therefore separate semantic facts.

Volt Absorb reuses that operation with generated predicates for active
Electric type, source/target inequality, and the Gen 3 Thunder Wave exclusion.
No ability or move ID appears in generic control flow. Three legal cases prove
injured healing, full-HP immunity, Thunder Wave fallthrough, post-accuracy
handler staging, and the absence of critical/damage randomness after
interception. The pinned Gen 3 `tryMoveHit` override—not the modern generic
`trySpreadMoveHit` pipeline—is authoritative for this ordering.

The expanded corpus is exact at 1,403 boundaries, with byte-identical oracle
and native replay.

### Defender-owned base-power modifiers

Thick Fat follows the effective inherited Gen 4 override used by Gen 3: one
defender-owned `BasePower` handler at priority 1, guarding the active move's
Fire or Ice type and chaining Q12 `0.5`. It is not implemented as separate
Attack and Special Attack branches, and it owns no randomness. A focused test
proves FOE-scope discovery, active-type routing, and odd base-power rounding.
Three legal differential fixtures cover Fire, Ice, and type-mismatch paths.

This exposed and corrected a verifier assumption: a defender-owned
`onSourceBasePower` handler has a different holder from the attacker-rooted
relay result, so those records cannot be correlated by holder identity. The
expanded corpus is exact at 1,409 boundaries.

### Defender-owned Defense modifiers and Marvel Scale

`ModifyDef` is now a generic defender-owned numeric relay in the damage
pipeline. Its Gen 3 staging is explicit: critical-hit suppression of positive
Defense stages, then the remaining Defense stage, then ordered `ModifyDef`
handlers, then the Self-Destruct/Explosion Defense divisor. An empty event is
an identity operation and emits no synthetic relay trace. The alternate proof
plugin remains compatible because a bundle that does not advertise the event
uses that identity behavior.

Marvel Scale is generated data over that boundary: a target-owned handler at
priority 6/suborder 7 guards for any major status and chains the Defense relay
by Q12 `1.5`. Neither the kernel nor damage control flow names Milotic or
Marvel Scale. Focused tests prove inactive and active paths, positive-stage
ordering, critical stage bypass followed by the ability modifier, and
Explosion ordering.

Five legal differential fixtures cover physical control, status activation,
special non-routing, a forced critical, and persistence across switching.
They expand the exact corpus to 1,420 stable boundaries; oracle and native
replays are byte-identical. The observer records `ModifyDef` as a generic
numeric modifier event. Its current pinned patch checksum is
`7abda7d71cb4e42969e7c87b838194b49ff60317ba3d9017d2825d9f7b6696ae`.

Metal Powder remains unsupported. The pinned Gen 3 callback requires an
untransformed current Ditto and modifies only physical Defense. Implementing
that honestly first requires explicit Transform identity/lifecycle state; a
species/item special case at the damage call site would cross the semantic
boundary.

### Holder-status predicates and Facade

Facade is the first user-major-status predicate over the generic BasePower
relay. The interpreter operation accepts a generated status bit mask and reads
the discovered handler holder; it rejects zero, `NONE`, and unknown bits before
mutation. Gen 3 data supplies burn, Toxic, paralysis, regular poison, and
freeze, deliberately excluding sleep, followed by Q12 `2.0`. Generic control
flow does not name Facade or any individual status.

Focused tests cover every native major status plus fail-before-mutation mask
validation. Legal clean and paralyzed Smeargle fixtures prove the inactive and
active Showdown paths. The complete differential now matches 1,424 stable
boundaries, and both oracle and native replays are byte-identical.

### Move-owned Hit callbacks and Refresh

Move-owned `singleEvent('Hit')` is now a typed boolean-or-null boundary kept
separate from the holder-wide `runEvent('Hit')` notification. A generated
required-status-mask operation returns false for an inapplicable callback;
the existing central status-clear transaction owns mutation and lifecycle
tracing. The kernel names neither Refresh nor any concrete status.

Focused tests cover no status, sleep, freeze, burn, paralysis, poison, and
Toxic without PRNG consumption. Four legal differential fixtures cover clean
failure and burn, poison, and Toxic cures. The observer now records move-owned
`Hit` callbacks, and the complete corpus matches at 1,432 stable boundaries
with byte-identical oracle and native replay. Refresh and its `onHit` hook move
the inventory to 559 implemented, 371 inert, 16 unreachable, and 593
unsupported descriptors.

### Atomic boost-stage products and Psych Up

The resolved Gen 3 descriptor inherits the boosts-only Gen 5 callback through
Gen 4; it does not use the modern base callback that also copies critical-stage
volatiles. Psych Up therefore atomically replaces the user's seven-stage boost
product from its target without dispatching `ChangeBoost`, `TryBoost`, or
ordinary boost effects. One generated operation performs that fixed-size copy
at the typed move-owned `Hit` boundary. Generic control flow names no move or
generation-specific ID.

Focused tests prove complete replacement, target preservation, invariant
validity, and zero PRNG. Three legal cases prove mixed-stage overwrite,
Substitute bypass, and simultaneous Protect plus Ghost-type recombination.
They also establish callback-only foe-targeted `attackedBy` provenance. The
full corpus and both deterministic replays match at 1,443 boundaries. Psych Up
and `move.psychup.onHit` move the inventory to 561 implemented, 371 inert, 16
unreachable, and 591 unsupported descriptors.

The next descriptor batch adds two callback-free generated families without
move-identity branches in the kernel. Overheat, Psycho Boost, and Superpower
use a typed post-hit self-drop phase: one labeled chance draw owns one atomic
sparse boost product, including Superpower's paired Attack/Defense drop.
Submission, Take Down, and Volt Tackle reuse the existing damage-relative
recoil operation with resolved ratios 1/4, 1/4, and 1/3. Their focused tests,
generated-source assertions, and exact rotation differentials move the frozen
inventory to 567 implemented, 371 inert, 16 unreachable, and 585 unsupported.

Haze adds the distinct move-owned `HitField` boundary rather than pretending a
field effect is an ordinary target `Hit`. One generated program clears the
complete seven-stage products of every living active through a topology-checked
fixed-capacity iterator. Exact fixtures cover two nonzero products, Substitute
and Protect bypass, Pressure PP staging, and the neutral-product callback. Haze
and `move.haze.onHitField` move the inventory to 569 implemented, 371 inert, 16
unreachable, and 583 unsupported descriptors.

Generated sleep `Start` is now a status-owned lifecycle program rather than a
hardcoded status side effect. The resolved Gen 3 bundle binds `slp.onStart` to
one labeled uniform `[2,6)` duration draw; the generic lifecycle dispatcher
owns validation, capacity preflight, provisional installation, and exact
rollback. The alternate proof plugin changes the interval through data while
using the same kernel. Exact sleep, Yawn, and Effect Spore differentials move
the inventory to 570 implemented, 371 inert, 16 unreachable, and 582
unsupported descriptors. This classifies only `condition.slp.onStart`, not the
broader sleep `BeforeMove`/`SwitchIn` lifecycle.

Rest is the first consumer of direct major-status replacement. Its generated
`Try` program rejects an already-sleeping or full-HP holder and consults
generated status-immunity data for sleep-blocking abilities. Its generated
`Hit` program runs the ordinary sleep `Start` transaction (including the
labeled duration draw), overwrites the typed sleep counter to three, and heals
to maximum. Exact fixtures cover a clean success, full-HP rejection, Insomnia,
and toxic replacement/removal ordering. `move:rest`, `move.rest.onTry`, and
`move.rest.onHit` move the inventory to 573 implemented, 371 inert, 16
unreachable, and 579 unsupported descriptors.

Synchronize is a generated `AfterSetStatus` owner, not an ability branch. Its
program guards self-source, admits only burn/poison/toxic/paralysis, rewrites
toxic to ordinary poison in generation data, and reuses ordinary nested status
admission for occupied slots and natural immunity. Exact fixtures cover burn,
sleep exclusion, toxic normalization, source immunity, and occupied source
state. `ability:synchronize` and `ability.synchronize.onAfterSetStatus` move
the inventory to 575 implemented, 371 inert, 16 unreachable, and 577
unsupported descriptors.

The status-ability rotation now initializes incompatible poison, paralysis,
burn, and freeze states and observes their removal at Showdown's `Update`
boundary before status reapplication. This supplies descriptor-specific
differential evidence for Immunity, Limber, Water Veil, and Magma Armor over
the existing generated `cure_on_update` policy. The sleep variants remain
unsupported because the current fixture schema cannot represent a valid
nonzero native sleep counter without changing the observable initial state.
The newly proven Immunity, Limber, and Water Veil `onUpdate` hooks move the
inventory to 578 implemented, 371 inert, 16 unreachable, and 574 unsupported
descriptors.

Ancient Power and Silver Wind now preserve Showdown's secondary-object
ownership explicitly: five generated boost effects share one nonzero product
key and therefore one labeled chance draw. A generated ability policy scales
that product's chance for Serene Grace; Shield Dust is still discovered at
`ModifySecondaries` but retains self-only products. Exact legal fixtures prove
the 10--19 Serene Grace/control split, all-five-or-none mutation, Silver Wind,
and Shield Dust handler visibility. The two moves, Serene Grace, and its
`onModifyMove` hook move the inventory to 582 implemented, 371 inert, 16
unreachable, and 570 unsupported descriptors.

## Zig and Rust kernel decision gate

### Active-ABI audit correction (2026-09-25)

Both reduced prototypes pass their own focused tests, C smoke tests, and
synthetic shared fixture projection, but **neither clears the migration gate**.
They export a legacy-shaped `gen3_battle_turn` over private 528/532-byte states;
they do not implement the active 22,064-byte `PokemonBattle` surface
(`pokemon_battle_init`, `pokemon_battle_request`, `pokemon_battle_step`, and
`pokemon_battle_view`). Their shared TSV was not emitted by the pinned
Showdown observer and is therefore not differential evidence.

The isolated audits are Zig commit `9313055d9433e01dcfb80bef903285918f9ea3e8`
and Rust commits `e588d05` plus `cac2bc4`. Zig again passed 4/4 ReleaseSafe
tests, dynamic/static C smoke, and the C-edge ASan/UBSan check at about 41.8 ns
per reduced transition. Rust passed 8/8 tests, C FFI, Clippy with warnings
denied, and the C-edge ASan/UBSan check at a 42.3 million transitions/second
median. These remain microbenchmarks of reduced kernels.

An honest second rung must generate one shared ABI/data schema, populate the
unchanged active view and traces, and replay an observer-produced accepted
case. A wrapper that calls the C transition is not evidence for a Zig or Rust
kernel. Until that rung exists, the demonstrated local sum-type/ownership gains
do not offset a second toolchain, schema, and debugging surface. Continue the C
kernel; do not merge either spike or alter supported-feature claims.

The language spikes remain isolated and are not part of the submitted runtime:

- Zig worktree `pokemon-zig-kernel-cp6`, commit `ae28817`;
- Rust worktree `pokemon-rust-kernel-cp6`, commit `8889bc9`.

Both preserve the encoded two-choice C call shape, normalize it to closed
choice/action sum types, use fixed queues, expose an explicit
`immune | missed | connected` hit result, validate a bounded plugin before
mutation, order typed handlers, and label every Showdown-compatible PRNG draw.
They execute the same three persisted semantic fixtures and six shared PRNG
vectors exactly through C callers.

Zig demonstrates the smaller interop surface: a 532-byte reduced state, no
allocator or language runtime, a 50,904-byte dylib, and a 42.2 ns median for
the reduced transition on this Apple Silicon host. Rust demonstrates the
stronger ownership boundary: private enums plus unique `&mut` mutation and
caller-owned aligned storage, with a 528-byte reduced state and 34.8--60.7
million reduced transitions/s. Its linked smoke binary is 1.4 MB and its
static archive is 17 MB. These are ABI-overhead microbenchmarks, not Ocean
batch or complete-battle benchmarks.

Both languages make several illegal internal states unrepresentable, but raw
C actions and generated numeric IDs still require boundary validation. Both
also add a second build/debug surface and require one generated schema to emit
coherent C-facing and language-native data. Neither prototype exercises the
full canonical state, requests, forced replacement, rollback, or the complete
differential corpus. The dominant long-tail cost remains encoding and proving
handler semantics, not queue syntax.

Decision: continue the C kernel. The demonstrated type-safety improvement is
real but does not yet outweigh migration and dual-toolchain complexity or
prove higher long-tail velocity. A Zig reconsideration would require roughly
1--2 engineer-weeks for a decision-quality generated-data/Ocean benchmark and
6--10 weeks to migrate current semantics. Rust would require roughly 2--3
weeks for the same second rung, 8--12 weeks to migrate, and 2--4 weeks of
dual-run soak. No rewrite or supported-feature reclassification is authorized
by these spikes.

### Two-turn producer and semi-invulnerability family

All eight Gen 3 charge producers now share one generated descriptor and one
generic charge/lock/release lifecycle. The immutable move descriptor carries
separate semi-invulnerable reachability and double-damage masks; the kernel
therefore composes Gust/Twister/Sky Uppercut/Thunder with airborne targets,
Earthquake with underground targets, and Surf with underwater targets without
move-pair branches. Bounce doubles through `BasePower`; Fly, Dig, and Dive use
the distinct final `ModifyDamage` event after STAB/type staging and before the
damage roll. Skull Bash's charge-time Defense boost is descriptor data and is
applied exactly once.

Weather residual damage now preserves Showdown's boundary: natural type
immunity short-circuits first, followed by the target-owned ordered `Immunity`
event, followed by damage. The event carries a generated condition descriptor
key rather than a Gen 3 ID. Dig and Dive marker handlers return false only when
that key resolves through the plugin to Sandstorm or Hail. This boundary can
also accept later ability/item weather-immunity handlers without changing the
weather loop.

Focused validation proves every generated reachability/doubling mask and
atomically rejects unknown bits, double masks outside the hit mask, duplicate
weather descriptor identities, and missing weather identities. Differential
recombination covers Fly+Twister, Bounce+Gust, Bounce+Sky Uppercut,
Dig+Earthquake, Dive+Surf, all four Dig/Dive Sandstorm/Hail immunities, and a
Fly negative weather control. The complete corpus and deterministic replay are
exact at 1,946 boundaries; native/random/Ocean and ASan/UBSan gates pass.

The inventory is now 759 implemented, 416 inert, 24 unreachable, and 340
unsupported descriptors. Dig remains unsupported as a complete move and
marker condition despite its individually proven hooks: reachable Magnitude
composition still requires Magnitude's generated weighted-power `ModifyMove`
program and labeled draw. This conservative classification prevents the
Earthquake fixture from standing in for the unimplemented operand.

### Weighted active-move power and Magnitude closure

Magnitude closes that remaining composition through one generic interpreter
operation, not a named resolver. Generated data defines a weighted distribution
of `{weight, power, message}` products; the move-owned `ModifyMove` handler
samples it with the labeled `move.power_variant` draw and mutates only the
active move frame. The ordinary hit pipeline then owns accuracy, immunity,
critical, damage, and secondary staging. `UseMoveMessage` is a separate
move-self event, matching Showdown's callback boundary without placing message
text in the battle kernel.

A focused native test proves all seven weighted outcomes and atomic rejection
of an invalid distribution. Seven legal differential fixtures force Magnitude
levels 4 through 10, and an eighth recombines level 7 with Dig's underground
double-damage handler. The complete corpus and both deterministic replays are
exact at 1,963 boundaries. This evidence promotes Magnitude, both owned hooks,
Dig, and the Dig condition: the inventory is now 764 implemented, 416 inert,
24 unreachable, and 335 unsupported descriptors.

### Ambient sport conditions and `AnyBasePower`

Mud Sport and Water Sport are ordinary indefinite user volatiles plus one
generated `AnyBasePower` handler each. The generic event discovery path visits
both active sides for `ANY` scope; the handler program guards Electric or Fire
move type and chains a Q12 one-half modifier. No move-name branch or field
pseudo-weather state is involved. Independent holders therefore compose
through the ordinary modifier relay, and generic switch cleanup removes the
outgoing holder's effect.

The generation capability layout now reserves the low 48 bits for condition
families and places kernel services above that range. Plugin ABI version 2 and
compile-time disjointness assertions prevent the former condition/service bit
alias from recurring. Required-rule validation spans the complete advertised
condition capability domain and rejects incomplete bundles before mutation.

Focused native tests prove matching and nonmatching types, same-side and
opposing-side holders, two-holder quarter-power composition, and switch
cleanup. Four differential fixtures reproduce those boundaries against the
pinned oracle. The observer projects sport lifecycle and BasePower modifier
records, including exact Q12 accumulation. The complete corpus and both
deterministic replays are exact at 1,976 boundaries; native, randomized legal
play, Ocean, and ASan/UBSan gates pass. The inventory is now 772 implemented,
416 inert, 24 unreachable, and 327 unsupported descriptors.

### Stored-damage action memory and Bide

Bide closes through three reusable boundaries rather than a move-pair
resolver: a typed direct pre-use program, an explicit stored-damage condition
payload, and a generated constructed-hit template. The direct program models
Showdown's `beforeMoveCallback` at its actual location after `BeforeMove` and
before PP commitment or move announcement; it is deliberately absent from
event-handler discovery. Condition programs own initialization, requested-
damage accumulation, last-source replacement, release, abort cleanup, and
End. The generic hit pipeline owns immunity, Protect, Substitute, accuracy,
damage, fainting, and retargeting.

Nine legal fixtures prove additive and zero-damage paths, protection,
Substitute, Ghost immunity, inactive and fainted source retargeting, forced
drag cleanup, paralysis abort, exact labeled PRNG staging, and deterministic
replay. Focused native tests prove the single PP commitment, silent forced
middle action, release damage, absence of critical/damage-roll draws, and
fail-fast pre-use bundle validation. The full differential and both replays
match at 2,416 boundaries; random legal play, Ocean, admission, focused native,
and ASan/UBSan runs pass. The inventory is now 950 implemented, 424 inert, 33
unreachable, and 153 unsupported descriptors. Exactly seven records move:
the Bide move, its volatile, and five reachable condition callbacks.
