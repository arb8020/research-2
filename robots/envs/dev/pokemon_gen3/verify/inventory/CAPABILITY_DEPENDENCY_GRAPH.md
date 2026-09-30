# Unsupported-capability dependency graph

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is the live work-selection contract for the 0 records classified
`unsupported` in `descriptor-map.json`. Unsupported records are evidence obligations,
not individual implementation tasks. `unsupported-ownership.js` reads this same map,
assigns every unsupported `(kind, id)` exactly once, and fails on an overlap,
or omission. Pass `--list` to audit every assignment.

| Kind | Records |
| --- | ---: |
| move | 0 |
| ability | 0 |
| condition | 0 |
| format rule | 0 |
| target mode | 0 |
| event-hook ownership | 0 |
| **Total** | **0** |

No unsupported item, species, or simulator-only-condition records remain in
this snapshot. A hook and its owner often depend on the same operation, so raw
record counts must never be treated as engineering estimates.

## Graph

An arrow means that the left capability is a prerequisite for the right one.
The capability table below is a disjoint admission partition: every live
unsupported record has exactly one primary owner. A record may still appear
in another node's recombination proof, but never in its closure count. This
prevents an attractive narrative from substituting for a mechanically
checkable work queue.

```text
resolved legality universe + flattened rule aliases
    -> team/set validation and bans
    -> legal submitted sets -> runtime move-delegation closure

typed condition payloads + complete lifecycle
    -> ramping/locked move state machines
    -> damage/action memory -> Counter/Mirror Coat/Bide -> Revenge/Pursuit
    -> ability-owned state -> Flash Fire/Truant
    -> implemented delayed-slot lifecycle -> retaliation recombination

typed damage/source provenance
    -> scripted target resolution -> Counter/Mirror Coat
    -> source-sensitive faint effects and retaliation families

typed action queue + switch/request suspension
    -> drag transaction -> Roar/Whirlwind/Suction Cups/Ingrain
    -> switch interception -> Pursuit
    -> state transfer -> Baton Pass
    -> implemented delayed-slot suspension and replacement

active move frame + bounded child invocation
    -> called-move selection -> Assist/Metronome/Nature Power/Sleep Talk/Snatch
    -> active-move mutation -> Hidden Power/Present/Secret Power/Tri Attack
    -> runtime overlays -> Transform/Conversion/Camouflage/Mimic/Sketch

canonical typed mutations
    -> atomic HP/stat transactions
    -> PP mutation
    -> heal interception -> Liquid Ooze

weather lifecycle + mutable form overlay -> completed Forecast projection
event ordering + labeled PRNG -> every probabilistic/stateful node above
```

## Capability nodes

No live missing semantic boundary remains. The table retains completed nodes as
an architectural and verification history; it is not a queue for new work.

| Node | Records | Capability | Direct basis and downstream mechanics | Important prerequisites |
| --- | ---: | --- | --- | --- |
| A | 0 | completed resolved aggregate format aliases | `standardag` and `standard` are complete after their flattened terminal-policy child closed | C; flattened RuleTable identity and conjunctive child support |
| B | 0 | completed typed condition/status lifecycle | Curse, Rage, recharge, Sleep Talk admission, Sleep Clause, Freeze Clause, and Uproar are complete | typed payloads; Start/Restart/Update/Residual/End and teardown |
| C | 0 | completed terminal policy | `endlessbattleclause`, persistent/pending/volatile staleness, legal-switch escape, cycle-owner resolution, and the independent turn cap are complete | terminal policy and staleness ownership |
| D | 0 | completed protocol/presentation adapters | HP percentage, cancellation, and Beat Up nickname behavior are typed policies outside canonical atomic battle mutation | explicit observable-contract decision |
| E | 0 | completed bounded move-local state machines | Imprison, Destiny Bond, Grudge, Focus Punch, Minimize, Bide, Fury Cutter, Rollout/Ice Ball/Defense Curl, and the Stockpile family are complete | B plus action-attempt, damage/faint provenance, and interruption/reset rules |
| F | 0 | completed damage provenance and scripted retaliation | Counter, Mirror Coat, both volatile owners and `Damage` hooks, and `scripted` target are implemented | typed condition payload; damage/source capture; delayed-hit recombination |
| G | 0 | completed delayed-slot work | Future Sight, Doom Desire, Wish, both slot conditions, and six hooks are now implemented | queue suspension, slot identity, immutable effect snapshot, replacement/terminal ordering |
| H | 0 | completed switching and state transfer | Baton Pass, generic dragging, and Pursuit interception are complete | C, passable-state policy and action provenance |
| I | 0 | active-move construction and runtime overlays | Beat Up, Transform, Tri Attack, Present, Secret Power, Conversion, Camouflage, and Conversion 2 are complete through generated active-move, party-hit, profile-copy, status-distribution, or current-slot policies | active frame, finite generated policies, mutable overlays |
| J | 0 | child invocation and moveset mutation | Assist, Metronome, Sleep Talk, Mimic, and Sketch are complete | bounded re-entry, candidate sets, PP ownership, rollback |
| K | 0 | completed typed formulas and atomic mutations | Smelling Salts, Belly Drum, Low Kick, Dream Eater, Revenge, the Gen 3 OHKO/Sturdy family, Spite, Pain Split, Double Team, Memento, and the Jump Kick family are complete | canonical HP/stat/PP transactions and source history |
| L | 0 | completed ability lifecycle and relational handlers | Forecast, Truant, Plus/Minus, and Skill Swap are complete | B/H where applicable, weather, typed stat relays, ability replacement/end |
| M | 0 | completed specialized per-hit sequencing | Triple Kick and Twineedle use generated repeat-accuracy, hit-index power, and per-hit secondary policies | per-hit accuracy/damage/effect staging |
| N | 0 | completed declarative rejection | Teleport's inherited constant `onTry: false` is implemented as a generated move-owned rejection program | generic move-owned rejection program |
| **Total** | **0** |  |  |  |

B is a planning cluster, not one implementation batch. Select independently
among ordinary volatile lifecycle, source-linked residual lifecycle,
type/immunity overlays, status admission/update, and cleanup/recharge hook
completion. Bide's seven-record accumulated-damage/action-memory machine is
complete through a generated direct pre-use program, stored-damage payload,
and constructed-hit template. Destiny Bond and Grudge still belong to
source-sensitive faint/action provenance, not merely to “bounded state.”

Teleport is not switching infrastructure. The three presentation/protocol
rules in D likewise must not be used to justify battle-kernel machinery.

## Selection rule

First reject a candidate whose prerequisites are absent. Score each eligible
node from 0 to 5 on:

- architectural uncertainty removed: 35%;
- downstream distinct families unlocked: 30%;
- verification affordability, where 5 is cheapest: 20%;
- direct proven closure, logarithmically/cap normalized: 15%.

Subtract 0.5 for material ABI/state growth and 0.5 for an oracle-observability
gap unless the slice directly resolves that gap. Every score needs a written
evidence basis; the decimals rank choices but do not claim measurement
precision.

| Candidate | Uncertainty | Unlocks | Verification | Closure | Penalty | Score |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| F: retaliation provenance (completed) | 4 | 5 | 4 | 3 | 0 | **4.15** |
| A: validation universe | 5 | 5 | 1 | 5 | -0.5 | **3.70** |
| H: switch/drag/transfer | 5 | 5 | 1 | 4 | -0.5 | **3.55** |
| J: child/dynamic moves | 3 | 4 | 2 | 3 | 0 | **3.10** |

The B slice is complete: Sleep Clause and Freeze Clause share a
generated, format-selected status-clause policy table and ordinary generated
`SetStatus` handlers. The policies preserve their real distinction—Sleep
Clause ignores fainted members and tracks opponent provenance; Freeze Clause
blocks on any existing team freeze—without named status checks in the generic
kernel. Recharge `onStart` is retained as a generated, unbound zero-program
descriptor because its only denotation is protocol presentation; Sleep Talk's
inherited Choice Lock/Encore `TryHit` guard is an ordinary generated move-owned
admission handler. Curse adds data-selected invocation profiles: effective
Ghost typing selects the opponent-targeted persistent condition and maximum-HP
payment, while the other profile retargets the same move frame to the user and
applies ordinary boosts. Seven legal fixtures cover selection, duplicate
rejection, Substitute interception, Protect non-interaction, residual timing,
and independent source/target teardown. L's Pokémon-owned ability phase-state
slice is now complete. Truant is expressed by generated SwitchIn, BeforeMove,
and order-27 Residual handlers over a typed Pokémon-owned Boolean bit; the
inherited empty `volatiles.truant` descriptor has no runtime owner. Three legal
fixtures prove opening alternation, voluntary switch entry, post-residual
forced replacement, recharge, both sleep/wake phases, and two-turn move
failure. Forecast completes L through a generated form-policy descriptor over
the generic mutable current-species overlay. Separating single-owner event
delegation from ordered field-wide `eachEvent` dispatch preserves Cloud Nine's
Gen 3 Start/End asymmetry and labels WeatherChange ordering PRNG. Transform
then extends that overlay into a generated full battle-profile copy and raises
the exact corpus to 2,948 boundaries. The kernel contains no Truant, Forecast,
or Transform identity branch. See `FORECAST_FAMILY.md` and
`TRANSFORM_FAMILY.md`.

## Selected battle-kernel slices

The completed source-sensitive faint-response slice shared by Destiny Bond and
Grudge closed 12 records in E. Retaliation and Bide
already established typed move/source provenance, action-attempt events, and
queued fainting; Spite established move-slot PP mutation. This slice therefore
tests the remaining architectural fact directly: a fainting holder's volatile
handlers must discover the exact source and source effect before teardown.
Destiny Bond queues a secondary faint only for an opposing, non-delayed move;
Grudge atomically zeros the living source's matching last-move slot. Their
`BeforeMove`, `MoveAborted`, and consecutive-use cleanup remain distinct
lifetime boundaries. The implementation uses generic `Faint` dispatch and
generated guards/mutations, with no move-identity branches in faint draining.

The dependency-free declarative-rejection node is complete. Resolved Gen 3
Teleport inherits a literal-false `onTry`; generated data binds that denotation
to the generic cancellable move-owned `Try` dispatcher. One legal differential
case and a focused native test prove PP/last-move staging, absence of hit and
accuracy work, continuation of the opposing action, and zero Teleport-owned
PRNG. No switch behavior or move-ID branch was added to the kernel.

The relational-stat subset of L is complete. Generated Plus and Minus handlers
use the generic living-active-ability guard followed by the ordinary ordered
Special Attack scalar relay; the kernel contains no Plus/Minus identity branch.
Four legal cases prove both directions, the matching-ability negative case,
and the physical-category control against the pinned oracle. See
`PLUS_MINUS_FAMILY.md`.

The OHKO subset of K is complete. Fissure, Guillotine, Horn Drill, and the
Gen 3 form of Sheer Cold use one typed OHKO policy, one generation-owned
accuracy rule, and the generic current-target-HP damage formula. Sturdy is a
generated ordered `TryHit` handler rather than a move/ability identity branch.
Seven direct legal fixtures plus a legal Metronome/Fissure selection prove the
level gate, miss, deferred natural immunity, Substitute interception,
Lock-On, Sturdy cancellation, Gen 3 Sheer Cold versus Ice, faint/replacement,
terminal state, and exact PRNG ownership. The full 2,305-boundary differential
and deterministic replay gate is exact. Metronome itself remains unsupported
until its complete generated candidate pool is executable.

The Perish Song subset of B is complete. One generated field callback applies
a generated countdown condition through generic per-active admission; generic
Residual and End programs own decrement and fainting. Two legal fixtures prove
duplicate/no-restart behavior, Protect recombination, switch cleanup,
simultaneous Gen 3 terminal resolution, and forced replacement across 11 exact
boundaries. Soundproof is banned by the pinned Gen 3 OU format, so its upstream
regression remains a focused constructed-state obligation rather than an
illegal differential case. See `PERISH_SONG_FAMILY.md`.

Swagger's runtime record is complete without a named resolver. Direct team
submission remains banned, but legal Metronome delegation reaches a generated
90-percent descriptor whose ordered primary program boosts Attack and then
attempts confusion. Four exact fixtures cover hit, miss, Own Tempo, Safeguard,
and subsequent self-hit staging. The format-rule ban remains independently
unsupported admission work. See `SWAGGER_CALLED_FAMILY.md`.

A previously selected slice was source-linked residual transfer, witnessed by
Leech Seed, Liquid Ooze, and Rapid Spin cleanup.  It was selected from the
live 239-record graph after independent audits of condition lifecycle,
admission validation, and downstream unlocks.  The slice tests the missing
composition of battlefield-position provenance, actual-damage-to-heal relay,
`SourceTryHeal`, deferred faint staging, and cleanup after ordinary versus
Substitute damage.  Its nine-record closure remains provisional until the full
evidence gate passes; see `SOURCE_LINKED_RESIDUAL_PLAN.md`.

Admission validation remains a separate generated, non-hot-path track.  It is
required for Checkpoint 6 but must not distort the battle kernel or be inferred
from the already-filtered legal/reachable catalog.

F was selected first: typed damage/source provenance plus scripted
Counter/Mirror Coat retaliation. It did not win by count. It was the cheapest test of whether the
existing `last_attacked_by`, move-invocation frames, source/effect references,
condition storage, and damage traces compose into one honest state transition.
It also unlocks Bide, Revenge, Pursuit, and source-sensitive faint effects.

The generic preparation queue, typed condition payload, damage-class guard,
capture operation, and state-derived fixed-damage formula pass focused native
tests. Fifteen legal differential cases cover physical and special capture,
wrong class, no-history miss, incoming and response type immunity, Substitute,
per-hit overwrite, Gen 3 self-faint/forced-replacement cancellation, resolved
Weather Ball category, delayed Future Sight provenance, and overkill followed
by forced replacement. A focused internal event test proves that the `Damage`
handler captures requested damage before real-HP clamping. The two moves, two
volatile owners, two reachable `Damage` hooks, and `scripted` target are now
implemented. Showdown does not dispatch either `RedirectTarget` hook in
singles, so those two records remain classified unreachable.

The completed I/Hidden Power slice did not merely implement one named move: it
establishes per-Pokemon move construction as immutable set
data normalized by a typed generation policy, applied through generated
move-owned handlers, and consumed at the ordinary base-power boundary. Gen 3
Hidden Power's exceptional physical routing, delayed/current-hit recombination,
resolved Weather Ball category, and the pre-HP-cap relay are also retaliation
evidence. That recombination proof is now complete; future damage-provenance
families must reuse this boundary rather than reopening Counter/Mirror Coat.

Run A, the resolved validation universe, as a separate non-hot-path design
track. It has high leverage but should not distort the battle kernel or infer
admission behavior from a catalog that already excludes illegal moves.

After retaliation closure, independent source audits split both leading
candidates more honestly. A is not one implementation family: format
composition/provenance, input normalization, atomic and complex bans,
learnset/source intersection, Sturdy/OHKO reachability, and runtime Freeze
Clause cross different boundaries. Freeze Clause is therefore owned by B,
while A remains a separate generated `PokemonAdmissionBundle` and non-hot-path
validator track. That bundle is now explicitly bound to the resolved runtime
plugin and format. Its first completed slice covers the nine atomic ability,
item, and move bans; every non-banned input still returns `INCOMPLETE`. The
already-filtered battle catalog cannot prove arbitrary team admission.

H likewise decomposes into three ordered slices. Generic drag/phazing is now
complete: one switch transaction parameterized by cause, ordered `DragOut`
cancellation, one labeled uniform bench selection, and generated force-switch,
Ingrain, and Suction Cups descriptors serve Roar and Whirlwind through the same
path. Seven legal fixtures and focused tests prove all ten reclassified
records. Pursuit is now also complete through target-bound pre-turn intent,
exact queued-action claim, ordered `BeforeSwitchOut`, and continuation of the
preselected switch after an interception faint. The full 2,219-boundary corpus
and deterministic replay remain exact. Baton Pass follows last because it
additionally requires mid-turn request suspension and explicit copyable-state
transfer.
The source-linked `trapper` identity was already implemented and has now been
removed from H as duplicated classification debt rather than counted as new
switch infrastructure.

Delayed slot work is complete. It closed 11 records: three moves, two slot
conditions, and six hooks. Six legal fixtures prove slot identity versus
occupant identity, source persistence after switching, immutable damage
snapshots, multi-turn replay, residual ordering, terminal resolution, and
forced replacement. The executable ownership helper also repairs the previous
hand-maintained table's arithmetic defect: Bide, Destiny Bond, and Grudge are
owned by E; Ingrain's full switch/drag surface is owned by H; and all remaining
condition-lifecycle records are owned by B.

## Iteration and evidence gate

For every selected node:

1. inspect its complete pinned-Showdown control flow;
2. define the smallest generic state/operation/generated descriptor that owns
   the semantics;
3. select a branch-complete compact basis, including every ordering and PRNG
   site;
4. prove focused invariants and boundary-by-boundary differential agreement;
5. recombine with already-supported mechanics to expose hidden coupling;
6. reclassify only records individually covered by source, focused, rotation,
   differential, replay, and rollback evidence;
7. regenerate this graph from the new live map before choosing again.

Primary ownership is executable in `unsupported-ownership.js`. Classification
and ownership remain separate decisions: `classify.js` determines support and
the helper partitions only its unsupported output. A graph refresh must run
both scripts; the ownership helper asserts exact coverage of the live set.

No move-specific resolver is justified merely because a named move is the
first witness. The fixed-capacity C/Ocean ABI and validated generation-plugin
boundary remain constraints of every node.
