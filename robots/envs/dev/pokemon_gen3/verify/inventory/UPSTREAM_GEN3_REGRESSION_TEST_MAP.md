# Pinned Showdown Gen 3 OU regression-test audit

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

Audited trees:

- Showdown: `/private/tmp/pokemon-lockon-clean/test/sim`, plus the matching
  Gen 3 data/mod sources.
- Native: `native/test_pokemon.c`, `verify/cases/derived`, and
  `verify/inventory/descriptor-map.json`.

This is a test-evidence map, not a support claim. A green upstream test is only
portable when its assertion matches Gen 3 source semantics. A native descriptor
remains unsupported until source mapping, native boundary, focused test, and
differential evidence all exist.

This narrative predates the reviewed canonical projection. For exhaustive
per-assertion dispositions use `verify/upstream-tests/gen3ou-test-map.json`;
the tables below remain useful historical detail but are not authoritative
when they disagree with that artifact.

## Applicability rule

1. **G3-explicit**: the upstream test actually constructs `common.gen(3)` (or
   validates `gen3ou`). These are exhaustively listed below.
2. **G3-source-applicable**: the tested entity exists in the frozen Gen 3 OU
   inventory, but the upstream scenario runs a later generation. These tests
   are candidate assertions only; compare the relevant Gen 3 override and
   inherited source before porting.
3. **Format-unreachable**: Doubles/Triples/FFA, team-preview, or a clause-banned
   entity cannot occur in the current Gen 3 OU singles runtime contract. Keep a
   focused constructed-state test only if it protects a generic kernel
   invariant.
4. **Out of runtime contract**: Showdown's parser, private logs, undo protocol,
   and full learnset/event legality belong to verifier/admission tooling unless
   the native contract is deliberately expanded.

## Exhaustive G3-explicit runtime map

Every row is at the pinned revision above.

| Upstream test | Boundary / assertion | Current native evidence | Disposition |
|---|---|---|---|
| `test/sim/abilities/flashfire.js:65`, frozen Gen 3 holder | Frozen-status suppression of Flash Fire | `test_flash_fire_generated_lifecycle`; six `flash-fire-*` differential cases, including frozen fallthrough plus independent activation/repeat/boost evidence | **Covered** at pinned revision. The upstream assertion proves suppression; the added cases separately prove activation, immunity, ordering, persistence, cleanup, and the 1.5× modifier. |
| `test/sim/abilities/magnetpull.js:56`, “prevent Steel-type allies from switching” | Gen 3 global trap discovery in Doubles, including ally | singles native tests `test_hidden_trap_rejection_updates_only_request`; fixtures `magnet-pull-steel-flying-block`, `magnet-pull-nonsteel-escape` | Upstream scenario is **format-unreachable** (Doubles). Existing singles evidence is appropriate for Gen 3 OU; optional C constructed-state test only if multi-slot kernel becomes supported. |
| `test/sim/abilities/thickfat.js:27`, “halve Fire/Ice damage in past generations even with type item” | source base-power modification and modifier composition | `test_thick_fat_source_base_power`; `thick-fat-firepunch`, `thick-fat-icepunch`, `thick-fat-psychic` | **Partial**: add one recombination fixture with Never-Melt Ice/Charcoal to cover the upstream composition assertion. |
| `test/sim/items/quickclaw.js:30`, “Gen 3 causes Speed ties with every holder when activated” | pre-turn shared priority bracket; activation PRNG; tie PRNG | `test_shared_turn_speed_item_policy`; `quick-claw-activation`, `quick-claw-failure` | **Partial**: current two fixtures prove activation/failure, but the upstream assertion specifically needs two holders of unequal natural Speed becoming a tie and a labeled `queue.tie` draw. Add differential case. |
| `test/sim/items/sitrusberry.js:69`, “not activate in same turn put below 50% by status” | residual discovery snapshot/order; status damage then deferred berry check | `test_fixed_heal_berry_transaction`; `berry-sitrus-threshold`, `berry-sitrus-rain-dish-order` | **Gap**: add poison/burn crossing threshold at residual and prove consumption is deferred to next residual pass. Existing cases do not prove this upstream regression. |
| `test/sim/misc/faint-order.js:26`, “turn ends in Gen 3” | Explosion self-faint; forced replacement request terminates remaining turn work | generic switching/faint tests and self-destruct fixture family | **Needs exact port** unless an existing self-destruct case demonstrates the foe's queued action is skipped and the replacement request occurs before a new turn. Differential observable. |
| `test/sim/misc/ohko.js:38`, “deal damage equal to target HP” | Gen 3 OHKO damage semantics | Direct submission is banned by OHKO Clause, but legal Metronome can delegate to an OHKO move | **Runtime-reachable gap**. Add forced Metronome differential coverage for level/accuracy staging, current-HP damage, type immunity, Substitute, Sturdy, and labeled draws. |
| `test/sim/moves/brickbreak.js:97`, “break foe Reflect when used against ally” | Gen 3 Doubles target/side resolution | `test_move_owned_try_hit_removes_selected_side_conditions`; five singles Brick Break fixtures | **Format-unreachable** (Doubles). Singles contract already proves screen removal gates; do not port scenario. |
| `test/sim/moves/conversion2.js:13,67`, Conversion 2 resistance and Gen 3 already-held type behavior | resolved invoked-move provenance; ordered resistant/immune candidate construction; labeled random selection; Gen 3 duplicate-type rule | `conversion2-dragon-singleton`, `conversion2-normal-{ghost-switch-reset,rock,steel}`, `conversion2-weather-ball`, `conversion2-sleep-talk`; focused `test_conversion_2_resolved_last_move_response` and plugin validation | **Covered** at the native contract. Public differential cases prove legal observable behavior; focused C constructs the already-held-type and Struggle states without claiming support for Conversion or Imprison. |
| `test/sim/moves/followme.js:88`, “redirection persists after KO/replacement” | Gen 3 Doubles slot condition lifetime | singles rejection test and `follow-me-singles-try-rejection` | **Format-unreachable** for Gen 3 OU. Current inert/rejection classification is correct only for singles. This test is useful future multi-slot evidence, not current support evidence. |
| `test/sim/moves/furycutter.js:34`, “double power after each successful hit (Gen 3)” | source-bound volatile, success-only counter, BP progression | descriptor **unsupported** | **P0 new differential + focused C**. Basis must include hit, miss/immune interruption, switch reset, and cap. |
| `test/sim/moves/glare.js:27`, “Gen 3 does not ignore natural type immunity” | status-move type immunity before status transaction | `test_primary_major_status_family`; `status-primary-rotation` | **Partial**: rotation proves ordinary paralysis but not Glare-vs-Ground immunity. Add a focused differential case; do not infer this assertion from generic status evidence. |
| `test/sim/moves/haze.js:202`, “does not remove Focus Energy in Gen 3” | field hit clears boost product but preserves unrelated volatile | `test_haze_field_hit_and_pressure_targeting`; four Haze fixtures, none named Focus Energy | **Gap**: add Haze + Focus Energy differential fixture; current `haze-both-products` is not evidence for volatile preservation unless inspected and explicitly mapped. |
| `test/sim/moves/pursuit.js:240`, “continue the switch” | intercept selected switch, pre-switch hit, surviving target still switches | descriptor **unsupported** | **P0 new differential + focused C**; includes action rewrite/order and switch continuation. |
| `test/sim/moves/pursuit.js:251`, “only activate on targeted opponent” | Doubles target identity | no native evidence | **Format-unreachable** (Doubles); retain as future multi-slot test, not Gen 3 OU gap. |
| `test/sim/moves/pursuit.js:269`, “do not activate on switching foe when targeting ally” | Doubles target identity | no native evidence | **Format-unreachable** (Doubles). |
| `test/sim/moves/weatherball.js:50`, “special form does not trigger Counter” | active move category mutation; retaliation provenance | `test_weather_ball_active_frame_mutation`; `weather-ball-category` and other Weather Ball fixtures; retaliation fixtures | **Likely covered but mapping too indirect**. Confirm `weather-ball-category` includes Counter rejection; otherwise add recombination. |
| `test/sim/moves/weatherball.js:58`, “special form triggers Mirror Coat” | same, positive special retaliation | same | **Likely covered but must inspect/add exact recombination**. |
| `test/sim/moves/weatherball.js:66`, “physical form does not trigger Mirror Coat” | Gen 3 type-based category under weather | same | **Likely covered but must inspect/add exact recombination**. |
| `test/sim/moves/weatherball.js:74`, “physical form triggers Counter” | same, positive physical retaliation | same | **Likely covered but must inspect/add exact recombination**. One four-turn/case matrix can prove all four rows. |

### G3-explicit source test whose name is broader than its execution

`test/sim/moves/camouflage.js:75` says “Gen 3-4”, but the body only runs Gen 4
and Gen 5. It is not direct Gen 3 execution evidence. Camouflage remains
unsupported; source inspection is required before porting the Gen 3 assertion
(Normal conversion and failure if Normal is already either type).

## Team-validator tests

- `test/sim/team-validator/breeding.js` contains nine `gen3ou` legality
  assertions (egg groups, event/tutor combinations, and Pomeg Glitch Clause).
- `test/sim/team-validator/formes.js:22` covers Gen 3 Deoxys formes in Ubers,
  not OU runtime behavior.
- `test/sim/team-validator/misc.js` has Gen 3-era legality checks but not the
  native battle transition contract.

These are **out of the current native runtime contract** if teams are normalized
and admitted by the verifier. Record them in a separate `team_admission` map;
do not silently use battle-kernel success as learnset/obtainability proof. If
Harbor requires native team validation later, that is a distinct capability.

## G3-source-applicable upstream files

The following upstream test files have names matching descriptors in the
frozen Gen 3 inventory. Their individual tests run modern generations unless
listed in the explicit table, so each assertion needs source adjudication.
The exhaustive per-`it()` AST census is checked in as
`verify/inventory/gen3-source-applicable.tsv` (548 tests plus header). Its
adjudications are conservative structural triage, not completed semantic
proof: 287 assertion shapes requiring Gen 3 source proof, 138 explicitly
different-generation/not-direct cases, 85 multi-slot-unreachable cases, 25
post-Gen-3-unreachable cases, and 13 explicit single-slot Gen 3 cases.

### Moves

`batonpass`, `bellydrum`, `bide`, `brickbreak`, `camouflage`, `charge`,
`conversion2`, `counter`, `curse`, `destinybond`, `disable`, `encore`,
`explosion`, `fakeout`, `focuspunch`, `followme`, `foresight`, `furycutter`,
`futuresight`, `glare`, `haze`, `healbell`, `highjumpkick`, `hyperbeam`,
`hypervoice`, `imprison`, `ingrain`, `knockoff`, `leechseed`, `lockon`,
`memento`, `mirrormove`, `nightmare`, `painsplit`, `perishsong`, `psychup`,
`pursuit`, `rage`, `rapidspin`, `recycle`, `rollout`, `skillswap`, `sleeptalk`,
`smellingsalts`, `snatch`, `spikes`, `spite`, `stockpile`, `substitute`,
`taunt`, `teleport`, `thief`, `thrash`, `thunderwave`, `toxic`, `transform`,
`trick`, `uproar`, `weatherball`, `wish`, `yawn`.

### Abilities

`arenatrap`, `battlearmor`, `clearbody`, `cloudnine`, `colorchange`, `damp`,
`flashfire`, `immunity`, `intimidate`, `levitate`, `lightningrod`,
`liquidooze`, `magnetpull`, `naturalcure`, `owntempo`, `pickup`, `pressure`,
`rockhead`, `roughskin`, `serenegrace`, `shellarmor`, `shielddust`,
`stickyhold`, `sturdy`, `suctioncups`, `synchronize`, `thickfat`, `trace`,
`truant`, `wonderguard`.

### Items

`lansatberry`, `leftovers`, `leppaberry`, `lumberry`, `mail`, `quickclaw`,
`shellbell`, `sitrusberry`, `whiteherb`.

The TSV is generated from the TypeScript AST rather than filename matching, so
generation/game-type declarations from later tests cannot leak into earlier
tests. Every row still needs one of `same_semantics`, `different_semantics`,
`format_unreachable`, or `not_in_contract`, backed by Showdown source, before
it can become support evidence.

Pinned `test/random-battles/all-gens.js` expands Gen 3 as
`gen3randombattle`. Those tests prove Random Battle set-data/generator
invariants (valid sets, move count, configured-move reachability, and team
generation), not `gen3ou` admission or full-battle simulation. Native
randomized full battles are therefore independent local evidence, not a port
of that upstream suite.

## Core simulator tests relevant by boundary

These are not Gen 3 conformance oracles as written (most create the current
generation), but their assertions define reusable kernel proof obligations:

| Upstream area | Portable boundary | Native evidence / gap |
|---|---|---|
| `test/sim/choice-parser.js` and `test/sim/decisions.js` | normalize move/switch choices, wait for both players, reject illegal forced choices, Struggle, trapped-switch rejection | native request/choice reducer, atomic rejection, Struggle, hidden trap tests exist. Parser strings, undo, private logs, team preview, Doubles/Triples are outside ABI contract. |
| `test/sim/events.js` | multiple handlers and priority ordering; invalid callback rejection | event interpreter, tie ordering, discovery D1-D3, plugin validation tests exist. Keep C-only because handler internals are not fully observable through ABI. |
| `test/sim/misc/accuracy.js` | fixed-point modifier rounding and speed-ordered modifiers | shared fractional accuracy tests exist; add exact modifier-chain rounding case if no current case proves half-down. |
| `test/sim/misc/critical.js` | self-hit cannot crit | critical and typed synthetic self-hit tests exist, but add/assert zero critical PRNG consumption on confusion self-hit if not explicit. |
| `test/sim/misc/faint-order.js` | stop/drain points and winner checks after each damage owner | general faint/terminal tests exist; delayed-slot winner check remains a required futuremove case. |
| `test/sim/misc/prng.js` | deterministic seed replay and exact primitive distributions | deterministic replay exists. Distribution sanity belongs C-only/plugin tests; labeled semantic call-site agreement is stronger than upstream's generic PRNG statistics. |
| `test/sim/misc/recoil.js` | recoil based on actual damage | recoil family and terminal tests exist. |
| `test/sim/misc/statuses.js` | burn, paralysis, toxic, freeze lifecycle | substantial native focused/differential families exist. Each modern assertion still needs Gen 3 source adjudication; modern burn residual (1/16) matches Gen 3, modern paralysis speed (1/2) does not. |
| `test/sim/misc/state.js` | deterministic serialization/replay | native canonical state + deterministic replay replace JS object serialization; add ABI round-trip only if serialization is an exposed contract. |
| `test/sim/misc/statusmoves.js` | natural immunity ordering | modern blanket status-move behavior does not directly prove Gen 3; use move-specific Gen 3 source (Glare is a demonstrated counterexample). |
| `test/sim/misc/turn-order.js` | switch/action ordering and speed-tie randomness | native action ordering/tie tests exist; Mega/Dynamax and multi-slot cases are unreachable. |
| `test/sim/misc/weather.js` | damage stage, duration, residual order, expiry before delayed attacks | weather focused/differential evidence exists; expiry-before-futuremove becomes a required delayed-slot recombination. |

## Future Sight and Wish: omission-sensitive map

Neither upstream file runs Gen 3 directly, so copying its expected numbers or
modern modifiers would be wrong. Still, these scenario shapes reveal the slot
condition proof obligations that the inventory extractor missed.

### `test/sim/moves/futuresight.js`

Port to Gen 3 after reading Gen 3/Gen 4 inherited source:

- slot-key duplicate rejection (`:31`);
- slot survives source/target switching and applies to the current occupant;
- duration advances and expires even with a fainted/empty occupant (`:88`,
  `:405` scenario shapes);
- expiry bypasses Protect (`:13` shape), clears Protect/Endure, performs the
  delayed accuracy draw, and then drains faint/winner work;
- target screen/weather ordering at cast versus expiry (`:236` and
  `test/sim/misc/weather.js:63` are useful recombination shapes).

Do **not** port modern Dark immunity, Terrain, Life Orb, Protean, Unaware, or
live-stat assertions without Gen 3 source proof. Gen 3 Future Sight/Doom Desire
use a cast-time fixed-damage snapshot and an expiry-time accuracy check in the
pinned implementation; that is a distinct assertion from modern tests.

### `test/sim/moves/wish.js`

Portable scenario shapes:

- slot ownership transfers healing to replacement (`:13`);
- duration progresses through a fainted/empty slot and is consumed as a no-op
  (`:31`, `:64`).

Do **not** port the modern “half of user's max HP” amount. Pinned Gen 3 heals
half of the **current recipient's** `baseMaxhp`. Add a Gen 3 differential with
unequal-max-HP switch recipient so the distinction is observable.

## Prioritized gaps discovered by this audit

1. **P0 unsupported explicit regressions**: Conversion 2 duplicate-type
   behavior and Fury Cutter progression. Flash Fire frozen suppression and
   Pursuit interception/continued switch now have focused and differential
   evidence.
2. **Closed delayed-slot family**: the native boundary and six exact differential
   cases cover the shared Future Sight/Doom Desire key, slot ownership
   across switching, cast-time snapshot, expiry accuracy/PRNG, Protect/Endure
   removal, Wish/Future ordering, fainted-occupant no-draw consumption, and
   delayed-hit forced replacement and terminal/winner resolution. Wish's
   fainted/empty `onEnd` guard is unreachable in legal Gen 3 OU singles for the
   ordering reasons recorded in `DELAYED_SLOT_FAMILY.md`.
3. **P1 false-positive coverage holes**: Quick Claw induced tie, Sitrus
   residual deferral, Glare natural Ground immunity, Haze preserving Focus
   Energy, and the four Weather Ball retaliation/category assertions.
4. **P1 generic boundary recombinations**: Thick Fat + type item; weather or
   screen expiry around futuremove; confusion self-hit consumes no critical
   draw; exact accuracy modifier rounding.
5. **P2 contract separation**: generate a separate admission/validator test
   map instead of treating Showdown's breeding/form legality tests as battle
   runtime obligations.

## Proposed project artifact schema

Add generated `verify/upstream-tests/gen3ou-test-map.json` plus a checked-in
human summary. One record per upstream `it()`:

```json
{
  "oracle_revision": "6e71625b9e6cffeda268b548ae7f43a7643fc3f0",
  "source_file": "test/sim/items/quickclaw.js",
  "test_name": "[Gen 3] causes Speed ties with every holder when activated",
  "applicability": "g3-explicit",
  "showdown_semantic_sources": ["data/mods/gen3/items.ts"],
  "features": ["queue.priority-bracket", "queue.tie", "prng.turn.quick_claw"],
  "boundaries": ["queue", "events", "prng", "state"],
  "native_tests": ["native/test_pokemon.c#test_shared_turn_speed_item_policy"],
  "differential_cases": ["quick-claw-activation", "quick-claw-failure"],
  "random_scenarios": [],
  "coverage": "partial",
  "required_case": "quick-claw-induced-speed-tie",
  "evidence_note": "Activation is covered; induced tie and tie draw are not."
}
```

Validation rules should reject records without pinned revision, adjudication,
source evidence for non-explicit tests, and a concrete reason for `irrelevant`
or `unreachable`. It should also cross-check referenced native symbols and
fixture IDs. Classification code may consume this map only after all four proof
links exist; it must not infer support merely from `coverage: complete`.
