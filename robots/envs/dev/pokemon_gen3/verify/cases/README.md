# Shared differential case format

This directory owns the build-time contract between imported Pokémon Showdown
scenarios, the instrumented Showdown oracle, and the native C driver. It is not
linked into the submitted runtime.

`case.schema.json` is the reviewable shape. `normalize.js` is the executable
validator: it rejects unknown fields, unsupported features, the wrong oracle
revision, malformed choices, and invalid forced outcomes. It emits fields and
feature lists in a fixed order, so normalizing the same input twice must be
byte-identical.

An accepted case preserves two representations of each team at one explicit
boundary:

- `source` names the original Showdown export used by the oracle;
- `normalized` records the immutable IDs and calculated stats consumed by C.

Each normalized member also carries `gender` as `"M"`, `"F"`, `"N"`, or
`null`. `null` preserves an omitted Showdown team field: battle construction
resolves it with one labeled `team.gender` draw. Explicit genders consume no
randomness, and the resolved value is part of canonical battle state.

An optional `initial_hp` supplies verifier-owned canonical mutable state. It
must be in `1..maxHP`; omission means max HP, and zero/fainted initialization
is rejected. The oracle amends the initial decision snapshot and the generated
native initializer receives the same value. This isolates formulas such as
Reversal without inventing a prior battle history.

The adapter must derive both from the imported scenario and pinned Showdown. A
human-written native fixture is not an alternative source of truth. Build-time
code may compile the normalized case into a C initializer; battle-step code
must not parse JSON or depend on Node, Python, or Showdown.

Version 1 requires unique species within each team because its canonical state
uses species identity to recover fixed team order after Showdown switches.
Cases with duplicate species fail normalization until a later schema adds a
stable set identity.

`forced_outcomes` records an imported test's semantic PRNG controls when they
can be represented by the pinned seeded stream. Each entry identifies the
semantic draw label, its one-based occurrence, range, and result. An adapter
must reject a test whose monkey-patching or callback-based randomness cannot be
faithfully converted; it must not silently replace that control with a guessed
seed.

The inventory is separate from cases. Every examined Showdown test has exactly
one `accepted` or `rejected` entry. Rejections name a stable reason code and a
plain-language explanation; absence from the inventory is not a rejection.

Checkpoint 1's frozen corpus contains four cases:

- one literal Showdown test import for request-local switch targets;
- one preserved six-boundary differential regression;
- one source-linked ordinary accuracy-miss case;
- one source-linked critical-hit and damage-roll case.

The latter two are marked `showdown-derived`, not imported tests. The inventory
rejects Showdown's Gen 3 Quick Claw tie test because it requires item handlers,
sleep, and direct oracle-state mutation. A separate derived equal-speed attempt
also exposed startup event-ordering draws before the action queue, which cannot
be represented honestly until the native event interpreter exists. Queue-tie
behavior remains covered by the focused native test.

Checkpoint 2 adds seven source-linked, recombined cases:

- grounded, Flying, and Levitate targets for Earthquake;
- the same three grounding states with a forced Bone Rush accuracy failure,
  proving that Gen 3 determines immunity before accuracy, still consumes the
  accuracy draw, and reports immunity rather than miss when both apply;
- Surf into full-HP Water Absorb, exercising actual `TryHit` handler discovery
  and cancellation.

These are `showdown-derived` cases, not claims that identical fixtures occur in
the upstream test suite. Levitate is observed at Showdown's `isGrounded` /
`runImmunity` boundary and is not represented as a callback handler. Bone Rush
multi-hit execution is deliberately unreachable and remains unsupported.
Together with the four Checkpoint 1 cases, the compiled corpus contains eleven
cases and 28 stable boundaries. Checkpoint 2 is not complete merely because
the cases exist: both drivers must agree on every boundary and replay
byte-identically against the pinned observer-patched oracle.

Checkpoint 3 adds five source-linked, recombined cases:

- an unstatused Guts baseline, proving the discovered handler leaves the relay
  modifier at 4096;
- an item-only nonlethal Black Belt turn, independently changing matched
  damage from 115 to 127 and allowing both queued actions to execute;
- an ordinary burned physical attacker, proving the direct 2048/4096 burn
  damage stage;
- a burned Guts attacker, proving the 6144/4096 Attack modifier and burn
  suppression;
- burned Guts plus Black Belt on a Fighting move, proving ordered composition
  from Q12 4096 to 6144 to 6758 before a single relay application.

These cases are `showdown-derived`. They use `normalized[].status: "brn"` as
explicit canonical initial mutable state. The oracle installs that state after
team construction, initializes Showdown's status state, and amends the already
captured initial boundary; it does not simulate status acquisition or emit a
status event. The native initializer receives the same state. Only `null` and
`"brn"` are accepted by version 1, and burn acquisition and residual damage
remain unsupported.

The item-only case also guards trace chronology: sequence-tagged modifier
records from the first and second actions must remain interleaved by execution
order when projected, rather than being grouped by native storage kind.

The complete frozen corpus now contains 16 cases and 38 stable boundaries.
Checkpoint 3 proves only Guts and Black Belt at `ModifyAtk` plus the direct Gen
3 burn stage. It does not claim Choice Band, all relay events, all handlers,
all items, or general status support; those are explicit long-tail work for the
later lifecycle, generic-effect, and inventory checkpoints.

Checkpoint 4 adds 15 source-linked, recombined cases and 54 stable boundaries:

- Toxic ramping, switch-in counter reset, and separate Poison- and Steel-type
  immunity cases;
- move-started Sandstorm duration/expiry and natural weather immunity;
- Protect's first block, forced consecutive success then failure, reset after
  a non-stalling move, and reset after switching;
- matched Reflect baseline/halving and critical baseline/bypass pairs, plus
  five-turn duration and switch persistence;
- a combined Sandstorm-before-Toxic residual sequence ending in knockout and
  a forced-replacement request.

Every source team is accepted by pinned Showdown's Gen 3 OU validator. The
cases avoid speed ties except where randomness is itself under test. Protect's
seeded consecutive draws are labeled `stall.success`: range 2 result 0, then
range 4 result 1. The Reflect pairs hold the defender, attacker, and damage
roll constant: ordinary damage is 22 versus 11, while critical damage remains
49 with or without Reflect.

Version 1 now supports explicit per-side team cardinality in the compiled
initializer. A case can therefore use one member on one side and two on the
other without inventing placeholder sets. The chosen singles format records
the maximum team size for that case; canonical state and legal switches use
each side's actual size.

At the Checkpoint 4 gate, the frozen corpus contained 31 cases and 92 stable
boundaries.
Checkpoint 4 does not imply general statuses, weather, volatiles, or side
conditions: only Toxic, move-started Sandstorm, Protect/stall, and Reflect are
in the supported condition lifecycle slice. The feature map and case
provenance make those limits explicit.

Checkpoint 5 adds 37 source-linked cases and 106 stable boundaries in four
slices:

- signed self/foe boosts, downstream damage, cap/failure/switch reset, and
  damage-plus-secondary status/boost success, failure, block, and immunity;
- actual-damage-based recoil/drain, Rock Head prevention, healing clamp and
  overkill, no-followup paths, and recoil faint/request/terminal ordering;
- Bone Rush two/five-hit selection, per-hit evidence, early knockout, and no
  hit-count draw before a connecting hit;
- exact-level Seismic Toss/Night Shade plus their type immunities, and all six
  Gen 3 Reversal HP brackets.

The corresponding effect records expose boost/status changes,
damage-relative basis, multi-hit plan/hit/result, and fixed/variable formula
resolution. Forced evidence uses `move.secondary`, `move.multihit_count`, and
the ordinary per-hit accuracy/critical/damage-roll labels. The complete frozen
corpus is now 68 cases and 198 stable boundaries.

Checkpoint 6 target normalization adds two legal source-backed cases. Helping
Hand proves that `adjacentAlly` remains selectable in singles, spends PP, has
an absent target, mutates no ally, and consumes no targeting PRNG. Wing Attack
proves that `any` resolves to the sole foe without a targeting draw and then
uses the ordinary hit pipeline. The corpus is now 70 cases and 202 stable
boundaries. Native focused tests additionally assert the normalized queue
mode, resolution, and relative target location; the current Showdown observer
queue schema does not expose those structural fields, so the differential
contract proves them through choices, target events, state, and PRNG instead
of projecting guessed metadata.

Checkpoint 6 handler-program verification adds a damaged-target Water Absorb
case alongside the retained full-HP case. With max HP 401 and initial HP 201,
the pinned oracle heals exactly `floor(401 / 4) = 100` HP, emits a heal event,
and cancels Surf after its accuracy draw without emitting a generic immunity
event. At full HP the same handler cannot heal, emits immunity, and still
cancels the hit. The corpus is therefore 71 cases and 204 stable boundaries.

The structural observer exposes ordered `TryHit` discovery and its Water
Absorb owner, but not the callback's raw `null` return value. Differential
state/events prove the resulting heal-versus-immunity behavior; the native
focused event-interpreter test owns the typed `POKEMON_EVENT_CANCEL_NULL`
assertion until Gate 3 adds generic per-handler result records.

Checkpoint 6 `TryBoost` verification adds legal holders for Clear Body,
White Smoke, and Hyper Cutter and recombines each with Growl. The cases prove
that all-negative and Attack-specific filters remove the externally sourced
Attack drop without consuming handler-order randomness. A Keen Eye case proves
that its accuracy-only filter preserves Growl's Attack drop, while the retained
successful Steel Wing case exercises the source-equals-target bypass for a
positive self boost. These four new cases bring the corpus to 76 cases and 214
stable boundaries.

The Gen 3 type-boost held-item slice adds 15 deterministic, source-linked
cases. Nine cover every new item with a matching damaging move in the current
executable catalog: Metal Coat, Sharp Beak, Silk Scarf, Soft Sand, Black
Glasses, Charcoal, Miracle Seed, Mystic Water, and Sea Incense. Existing Black
Belt evidence supplies the tenth executable pair. Six recombinations cover a
mismatched move type, Water Absorb and Protect cancellation before the damage
modifier, Substitute damage, a forced critical, and persistence across a
switch cycle. This adds 33 stable boundaries; guarded types without an
executable damaging move are not represented by fake fixtures.

All Checkpoint 4 and 5 team sources, and the repaired Persian/Scratch derived
cases, pass the pinned Gen 3 OU validator. This is not true of the entire
historical corpus: 12 inherited Checkpoint 0--3 source files are intentionally
retained as simulator-mechanic fixtures outside the ladder-legality claim.
Most use Showdown's zero-EV sentinel, while the preserved complete regression
also contains legacy set/evolution-level data. Do not describe all 68 cases as
ladder-legal.

Checkpoint 6 must inventory every reachable descriptor and classify it as
implemented, inert, unreachable, or unsupported, then map supported entries to
source, native boundary, focused evidence, and recombined differential cases.
A finite CP5 corpus is not that inventory.

`verify_case.h` is the C-side verifier ABI. A generated header owns static
choice arrays and `VerifyCase` values containing the normalized
`PokemonBattleInit`. This keeps provenance available to the driver while the
generic runtime remains ignorant of JSON and verifier concerns.

`compile-c.js CASE.json [CASE.json ...] ID_MAP.json` emits one header containing
uniquely prefixed choice arrays plus `VERIFY_CASES` and `VERIFY_CASE_COUNT`. The
ID map supplies `data_symbol`, `generation_symbol`, a `format_symbols` map keyed
by team size, and exact
numeric maps named `species`, `moves`, `abilities`, and `items`. Missing IDs are
hard errors. This explicit input prevents the verifier from guessing that an
unknown descriptor is ID zero.

At oracle startup, `oracle.js` reconstructs every source team through pinned
Showdown and compares species, level, gender presence, ability, item, moves,
and calculated stats with `normalized`. A hand-edited native initializer that
drifts from the source export therefore fails before battle comparison.

Run the contract tests with:

```sh
node verify/cases/test-normalize.js
```

`generate-white-herb-cases.js` emits the legal White Herb lifecycle rotation.
It covers connected and missed post-move self-drops, both initial Intimidate
orderings, any-SwitchIn activation, and an isolated Residual activation after
two explicitly seeded full-paralysis results.

`generate-freeze-lifecycle-cases.js` emits three validator-checked Gen 3 OU
cases for the resolved freeze status. They force a successful one-in-five thaw,
a failed thaw followed by Flame Wheel's delayed defrost cure, and a successful
Ember burn-secondary roll against an already frozen target. The last case
proves that the burn is rejected before `DamagingHit` thaws the target. The
owned thaw draw is normalized as `status.freeze.before_move` and must be
reproduced exactly from the case seed.

`generate-oblivious-cases.js` emits four validator-checked cases for volatile
Immunity and ability transfer. They cover direct Attract rejection, the Gen 3
Taunt negative, a forced successful attraction action followed by Role Play
and immediate Oblivious Update, and same-ability Role Play rejection. The
forced attraction draw is labeled `condition.attract.action`; Role Play itself
must add no PRNG consumption.

`generate-source-trap-cases.js` emits three validator-checked cases for Block,
Mean Look, and Spider Web. They cover exact source-linked installation,
voluntary-switch restriction, source-switch release, handler ordering, source
provenance, and the absence of intrinsic PRNG consumption. Together they add
seven stable boundaries.

`generate-stat-item-cases.js` also emits the Metal Powder positive and species-
guard cases. They prove the generated `ModifyDef` handler doubles an
untransformed Ditto's Defense and leaves a non-Ditto holder unchanged, adding
four stable boundaries. Transform itself remains outside the supported feature
map.

`generate-charge-cases.js` emits six legal Gen 3 OU cases from the resolved
mod semantics. They cover Electric power doubling without a Special Defense
boost, any-non-Charge-move cleanup, Electric status cleanup, Restart,
MoveAborted after forced full paralysis, silent switch cleanup, and silent
zero-HP faint cleanup. Together they add 21 stable boundaries.

`generate-imprison-cases.js` emits five legal Gen 3 OU cases for foe-scoped
move sharing. The verifier normalizes Showdown's singles-only
`maybeDisabled` request to the actual selectable move set from the pinned
engine's hidden move state, which is the full-information action mask consumed
by Ocean. The cases cover failed admission, stale queued-action cancellation,
all-shared Struggle, source-switch teardown, and restriction reprojection after
a foe switch. They add 12 stable boundaries without mechanic-owned PRNG.

`generate-specialized-multihit-cases.js` emits four legal cases for the
per-hit interpreter boundary shared by Triple Kick and Twineedle. They cover
repeat accuracy, hit-index power, later-hit miss termination, per-hit poison
draws, and failed poison application. The fixtures preserve effect ordering
inside the hit loop and add eight stable boundaries.

`generate-secret-power-cases.js` emits two legal cases for Secret Power's
resolved terrain-free Gen 3 descriptor. They force the 30% paralysis
secondary to succeed and fail while preserving the inherited no-op
`ModifyMove` handler in the observable handler trace. Together they add four
stable boundaries.

`generate-present-cases.js` emits ten legal cases for the weighted
damage-or-heal resolution boundary. The cases force every weighted outcome and
cover miss, Ghost immunity, Protect, full-HP failure, Gen 3's Substitute block
of healing, and ordinary Substitute interception of damage. They add 20 stable
boundaries with the selection labeled `move.resolution_variant`.
