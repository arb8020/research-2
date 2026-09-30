# Gen 3 native-slice oracle case

This is the verifier-owned, complete two-Pokemon battle used to compare the
independent native runtime with pinned Pokemon Showdown. The exported teams are
ordinary Showdown inputs: player 1 is level 100 and player 2 is level 1 so both
forced replacement and victory occur without mutating Showdown state.

For the preserved complete regression, `oracle.js` emits six JSONL records: the initial move request, two further move
requests, a forced `wait/switch` request, the post-replacement move request, and
the terminal result. Each record contains legal and submitted choices, the
sorted action queue, canonical fixed-team-order state, typed protocol events,
and all PRNG observations since the
preceding boundary. Switch choices and active slots use original team order,
not Showdown's mutable internal party order. Fainted status is represented by
`fainted: true` plus `status: null`.

Checkpoint 2 boundaries also include `immunity` and `handlers`. `immunity`
records the pre-accuracy natural/grounding decision: none, natural type, or
Levitate ability. In Gen 3 that decision occurs before accuracy; the accuracy
draw is nevertheless consumed, and immunity takes precedence if the draw
would also miss. `handlers` contains discovered `TryHit` handlers. Water Absorb
is the first supported entry. Levitate does not appear there because Showdown
implements it in `Pokemon#isGrounded`, not as an event callback.

Checkpoint 3 boundaries add `modifiers`. For `ModifyAtk`, each executed handler
records the unchanged relay value and the Q12 accumulator before and after the
handler, followed by one relay-result record. The combined Guts plus Black
Belt case must read 4096 -> 6144 -> 6758, not two independently rounded Attack
updates. A separate `damage-stage` record describes Gen 3's direct burn check:
2048/4096 when applied, or the explicit `guts` suppression reason. Burn is not
reported as a handler.

Native modifier, relay-result, and damage-stage records carry one monotonic
semantic sequence. The driver merges those fixed-capacity storage arrays by
that tag before projecting them. The nonlethal item-only case executes two
actions in one boundary and proves this chronological merge against Showdown's
single observation stream. It also supplies an independent matched damage
comparison: 115 without Black Belt and 127 with it.

Cases may supply `normalized[].status: "brn"` as canonical initial fixture
state. The oracle installs it after normal team construction and updates the
initial decision snapshot without simulating acquisition or emitting protocol;
the generated native initializer supplies the identical state. Checkpoint 5
separately covers Ember burn acquisition and its application-turn residual;
the initial-state path itself emits no acquisition event.

Cases may also supply `normalized[].initial_hp` from 1 through max HP. Omission
means full HP. The oracle updates the initial canonical snapshot and the native
initializer receives the identical value; this is fixture state, not a
simulated damage history, and cannot represent an initially fainted Pokemon.

The observer patch labels draws at their semantic owners: `team.gender`,
`queue.tie`, `move.accuracy`, `move.critical`, `move.damage_roll`, and
`turn.quick_claw`. Checkpoint 4 adds `stall.success` and
`field_event.residual.handler_order`. The latter is consumed only when
Showdown shuffles equal-key residual handlers; the focused corpus otherwise
uses unequal speeds.
Checkpoint 5 adds `move.secondary` and `move.multihit_count`. Each connected
multi-hit continues to own its ordinary critical and damage-roll draws;
fixed-level damage consumes neither.
The projection removes observer-internal sequence numbers and converts Gen 5
PRNG seed strings to four-element integer arrays.

Run against the pinned, built, observer-patched checkout:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  node verify/slice/oracle.js verify/cases/regressions/gen3-singles2-complete.json
```

The pinned revision is `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

`verify/cases/compile-c.js` compiles the imported, regression, and derived
normalized cases into a
verifier-only header. The generic `native.c` driver can run every compiled case
or one named case; choice exhaustion is a valid nonterminal stopping point.
It links only the self-contained C runtime and emits the same boundary schema,
including each case ID. Its PRNG records deliberately omit Showdown's
internal trace sequence number and use semantic owner labels; the oracle
projection must likewise discard `sequence`, convert seed strings to four-
element integer arrays, and emit the same semantic labels before comparison.

Build and run the native side without Node or Python:

```sh
make -C verify/slice test
verify/slice/native
verify/slice/native decisions-switch-targets
```

Strictly compare every emitted field and boundary against the oracle:

```sh
make -C verify/slice differential \
  POKEMON_SHOWDOWN_DIR=/path/to/pinned-observer-patched-pokemon-showdown
```

`compare.js` rejects missing or extra fields and reports the first differing
JSON path, including its boundary number. The current command compares 14
stable boundaries across four Checkpoint 1 cases plus 14 boundaries across
seven Checkpoint 2 cases plus ten boundaries across five Checkpoint 3 cases
plus 54 boundaries across 15 Checkpoint 4 cases and 106 boundaries across 37
Checkpoint 5 cases (198 total across 68 cases),
then repeats both oracle and native runs and requires byte-identical JSONL.

Canonical Pokémon state distinguishes the selected outer `last_move` from
`last_move_used: {move, resolved_type}`, the most recently invoked move after
active-move modification. Called moves replace that product and switching
clears it. This is observable because generation mechanics such as Conversion
2 consume it.

Checkpoint 4 canonical state adds tagged status state, sorted volatile state,
sorted side-condition state, and weather state. Its lifecycle projection
records apply, increment, reset, expire, and remove transitions. Residual
records expose discovery and execution separately, including scope, condition
ID, ordering keys, holder, duration/counter before and after, and damage. The
supported residual keys are Sandstorm order 8, Toxic order 10/suborder 6, and
the duration work for Reflect and Protect/stall. Residual fainting is drained
before the next stable request, so the combined case ends at `wait/switch`
rather than advancing the turn.

Compiled cases preserve actual team cardinality per side. Formats with maximum
team sizes one, two, and three are present in this corpus, while requests and
canonical state iterate only each side's supplied members. This is distinct
from the runtime's fixed capacity and permits asymmetric one-versus-two
verification cases without dummy Pokemon.

Checkpoint 5 `effects` records cover signed boost/status operations,
damage-relative recoil/drain and prevention, multi-hit plan/per-hit/result,
and fixed/variable damage-formula resolution. Protocol projection includes
the final multi-hit count after the last damage and before faint/win events.
The cases prove exact actual-damage fractions, Rock Head prevention, secondary
roll staging, Bone Rush two/five-hit and early-stop behavior, exact-level
damage, and every Gen 3 Reversal bracket.

The observer projects discovered callback-handler lists only for the supported
`TryHit` boundary. Water Absorb proves discovery and cancellation. Natural
Flying immunity and Levitate grounding are compared through the separate
immunity projection; emitting a fabricated Levitate handler would be semantic
disagreement. Bone Rush now covers both non-connection staging and the generic
multi-hit loop.

The modifier observer covers the implemented relay families, including
`ModifyAtk`, `ModifySpA`, `BasePower`, weather damage, and the screen-owned
`ModifyDamagePhase1` event. It records each handler's Q12 transition and one
final relay result. The direct burn stage remains a separate trace.

The condition observer is likewise bounded. It proves Toxic, move-started
Sandstorm, Protect/stall, Reflect, Light Screen, and the later documented
condition families. It does not claim regular poison, arbitrary condition
callbacks, or unsupported weather and side-condition interactions.

The corpus is not uniformly a ladder-team corpus. All Checkpoint 4/5 sources
and the repaired Persian/Scratch derived cases validate as Gen 3 OU. Twelve
inherited Checkpoint 0--3 source files remain simulator-mechanic fixtures
outside that claim, principally because of zero-EV sentinels and legacy
evolution-level regression data.

Checkpoint 6 must freeze and classify the reachable Gen 3 OU descriptor and
event inventory, then add source-linked focused and recombined evidence for
each supported entry. Passing these 198 boundaries does not complete that
inventory.

The Checkpoint 6 observer additionally includes `snatch` in its test-only
condition lifecycle allowlist and projects `PrepareHit` handler discovery.
The Snatch/Howl and Snatch/Calm Mind cases compare ordinary theft and the
successful Pressure edge, including canonical PP and boosts. The direct-boost
rotation then covers all 34 declarative descriptors in nine fresh battles,
plus product filtering, queue-order, and exact accuracy-threshold
recombinations. Together with the prior corpus this is 311 stable boundaries.
These observer additions are evidence only and do not run in the submitted
native environment.

The Gen 3 type-boost item slice adds 15 pinned recombinations and 33 stable
boundaries. Nine cases exercise every newly supported item whose guarded type
has a damaging move in the current executable move catalog: Metal Coat,
Sharp Beak, Silk Scarf, Soft Sand, Black Glasses, Charcoal, Miracle Seed,
Mystic Water, and Sea Incense. Black Belt remains covered by the earlier
physical baseline. Focused cases also prove a type mismatch, cancellation by
Water Absorb and Protect before the damage-stat relay, damage into Substitute,
a forced critical hit, and item persistence across switch-out/switch-in. At
that point the corpus had 344 stable boundaries. Items whose guarded type had
no executable damaging move were left to a later move-catalog slice.

The ordinary constant-power attack rotation adds 16 callback-free move
descriptors and 32 stable boundaries. It also supplies matching differential
evidence for Hard Stone, SilverPowder, and Dragon Fang. The corpus is now 376
stable boundaries. Hyper Voice remains fail-closed because every legal Gen 3
learner requires an ability outside the current admissible capability set;
the five remaining uncredited type items require attacks with additional
secondary, fixed-damage, or exceptional semantics.

Switch choices in this schema name fixed team slots. Showdown mutates its
internal party positions when switching, so the oracle adapter must translate
its request-local `switch N` commands back to the original team order. For
example, after Persian switches to Alakazam, Showdown's next `switch 2` denotes
the original-slot-1 Persian and is canonically `switch 1` here.

Equal-speed startup is intentionally not normalized away. Showdown randomizes
tied ordering in startup event passes before it builds the first action queue.
Until the native event interpreter owns those passes, the corresponding
differential scenario is rejected rather than consuming guessed PRNG frames.

The Charge family extends the exact corpus to 2,240 stable boundaries. Its
six fixtures prove the resolved Gen 3 inheritance chain rather than the base
move file in isolation: Electric-only power modification coexists with Gen
8-derived cleanup after every non-Charge move. Start/Restart/End lifecycle,
AfterMove and MoveAborted dispatch, ordinary/status consumption, and silent
switch/faint clearing all compare exactly and replay deterministically.
