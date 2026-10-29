# Historical next-family rankings

This file preserves earlier ranking decisions and their inventory snapshots;
it is not the live work queue. The authoritative current partition is
`CAPABILITY_DEPENDENCY_GRAPH.md`, mechanically checked by
`unsupported-ownership.js`. At revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0` that graph owns exactly 91
unsupported records. The next selected family is the source-sensitive
faint-response boundary shared by Destiny Bond and Grudge (12 records).

## Snapshot after self-faint and evidence closure

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This snapshot had 658 unsupported records after choice control, Mist, and the
four starter low-HP abilities. This
superseded the older historical snapshots below. Mist now uses the generic
side-condition lifecycle plus a generated `TryBoost` filter; Safeguard and
Spikes remain separate semantic families despite sharing side ownership.

| Rank | Semantic family | Direct obligations | Boundary earned |
| ---: | --- | ---: | --- |
| 1 | Safeguard and Spikes | 4 descriptors plus hooks | status interception and switch-entry hazards on the generic side lifecycle |
| 2 | contact-response abilities | 5 abilities + 5 hooks, condition-gated | post-damage ability dispatch and owned probability; Flame Body is the first independently closable witness |
| 3 | remaining fixed/relative damage | 4 moves | declarative damage formulas without new event topology |

Choice control, Mist, and the starter `BasePower` family are now closed. Rank 1 must still be split by semantic
boundary: Safeguard intercepts status installation, while Spikes dispatches on
switch entry and may faint before a request. Shared side ownership alone does
not justify one implementation family.

> Current status: the callback-free ordinary multi-hit extension is now
> implemented. Bone Rush plus thirteen additional fixed/distributed
> descriptors share one generation-parameterized loop; see
> `MULTIHIT_FAMILY_PLAN.md`. The older ranking snapshots below are retained as
> decision history rather than current support claims.

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This section is the live work-order audit after the weather/ability tranche and
the first major-status slice. The older Checkpoint 6 snapshot remains below as
history; its counts and recommendation are no longer current.

The descriptor map currently has exactly **980 unsupported records**:

| Kind | Unsupported |
| --- | ---: |
| move | 252 |
| ability | 60 |
| item | 91 |
| condition | 65 |
| format rule | 38 |
| target mode | 4 |
| callback-hook ownership | 470 |

## Live ranking

| Rank | Honest slice | Direct obligations closed | New semantic dependencies |
| ---: | --- | ---: | --- |
| 1 | Callback-free, single-effect damaging secondaries | **39 moves now**; 43-row semantic ceiling | Generated move/effect rows and rotation evidence; four rows lack a legal holder inside the fail-closed executable ability set |
| 2 | Pure direct recovery | **4 moves** | Fractional base-max-HP heal effect, numeric `TryHeal`, heal trace and rollback |
| 3 | Oran + Sitrus consumption | **8**: 2 items + 6 hooks | Residual item discovery, `UseItem`/`TryEatItem`/`Eat` transaction, persistent removal and `lastItem` |
| 4 | Full seven healing berries | **28**: 7 items + 21 hooks | Rank 3 plus nature/flavor confusion; the five flavor berries cannot be claimed as fixed-heal rows |
| 5 | Remaining superficially ordinary attacks | **1 immediately ordinary move** (`hypervoice`) | A legal executable holder/ability combination; the other 12 candidates own exceptional semantics |

### 1. Single-effect damaging secondaries

This is the highest-closure next slice because the native engine already owns
all required semantic operations: the ordinary hit/damage pipeline, one
labeled `move.secondary` draw for every reached secondary, including chance 100, atomic
`SET_STATUS`, and single-stat `BOOST` effects. These 43 effective Gen 3 move
descriptors own no callback hooks.

The **22 status-secondary moves** are:

`blizzard`, `dragonbreath`, `fireblast`, `firepunch`, `flamethrower`,
`flamewheel`, `heatwave`, `icebeam`, `icepunch`, `lick`, `poisonfang`,
`poisonsting`, `powdersnow`, `sacredfire`, `sludge`, `sludgebomb`, `smog`,
`spark`, `thunderbolt`, `thunderpunch`, `thundershock`, `zapcannon`.

`sacredfire` is one of the 43 semantic rows but is deferred from the immediate
classification slice: no legal holder in the frozen Gen 3 OU inventory has an
ability currently admitted by the fail-closed native capability set.

Their generated effects cover burn, freeze, paralysis, regular poison, and
Toxic at chances 10, 30, 40, 50, and 100. Flame Wheel and Sacred Fire retain
their generated defrost flag; Fire-hit thawing remains the generic hit
boundary. Poison Fang installs Toxic through the same status transaction as a
direct move. A 100-percent secondary still owns and consumes its labeled draw.

The **21 single-stat secondary moves** are:

`acid`, `aurorabeam`, `bubble`, `bubblebeam`, `constrict`, `crunch`,
`crushclaw`, `icywind`, `irontail`, `lusterpurge`, `metalclaw`, `meteormash`,
`mistball`, `muddywater`, `mudshot`, `mudslap`, `octazooka`, `psychic`,
`rocksmash`, `rocktomb`, `shadowball`.

The same holder gate defers `lusterpurge`, `mistball`, and `muddywater` from
immediate classification. Therefore the first rotation closes exactly
**39 move descriptors** (21 status-secondary plus 18 single-stat-secondary),
while generation may safely describe all 43 rows. The four deferred rows must
remain unsupported until a legal holder's ability is itself honestly admitted.

They reuse the installed boost transaction for one target or self stat change.
Ancient Power and Silver Wind are deliberately excluded: their five-stat self
boost is one probabilistic secondary and therefore needs a grouped effect
transaction, not five independently rolled operations. Flinch, confusion,
Tri Attack's sampled status, multihit poison, and every callback-bearing move
remain separate families.

The smallest honest implementation is a generator table whose rows contain
the ordinary move fields plus exactly one secondary descriptor
`{chance, target, effect}`. Runtime code must not branch on any of the 43 move
IDs. Focused and differential rotations must prove hit/miss, chance failure and
success, 100-percent draw staging, type/ability immunity, occupied status,
boost cap and prevention, self versus foe targeting, Substitute and Protect,
Fire thaw/defrost, exact source provenance, deterministic replay, and rollback.

### 2. Direct recovery

`recover`, `milkdrink`, `slackoff`, and `softboiled` close four move records
with one declarative half-base-max-HP effect. Although smaller, this is the
best foundational control-flow slice after rank 1: it establishes the numeric
`TryHeal` relay and a canonical heal transaction used later by weather
recovery, Leftovers, Rain Dish, Wish, Ingrain, Leech Seed, and berries. The
exact boundary and proof matrix are in `HEAL_FAMILY_PLAN.md`.

### 3--4. Berries

Oran and Sitrus are the smallest honest item-mutation slice: two item records
plus `Residual`, `TryEatItem`, and `Eat` for each, eight obligations total.
They require considerably more new state/control flow than rank 1 or 2:
captured installation identity, residual stale-handler checks, cancellable
consumption, current-item removal, `lastItem`, and switch/Thief persistence.

The five flavor berries add 20 more obligations but are not the same fixed-heal
descriptor: they require normalized nature/flavor data and conditional
confusion. Consequently the apparent 28-entry full-family closure does not
justify taking it before the eight-entry transaction slice. See
`BERRY_FAMILY_PLAN.md` for the complete dependency and interaction closure.

### 5. Ordinary attacks and remaining core gaps

Only 13 unsupported damaging descriptors superficially look effect-free:
`aerialace`, `eruption`, `explosion`, `feintattack`, `gust`, `hypervoice`,
`magicalleaf`, `selfdestruct`, `shadowpunch`, `shockwave`, `skyuppercut`,
`swift`, and `waterspout`. Twelve are not ordinary: they require always-hit,
HP-scaled power, self-faint/Defense halving, or semi-invulnerable-target
semantics. `hypervoice` is the sole ordinary row, and its legal Gen 3 holders
currently require an ability outside the fail-closed executable capability
set. There is therefore no honest high-closure ordinary-attack tranche left.

The raw hook totals (`Start` 53, `Hit` 44, `Residual` 34, `Eat` 22,
`TryHit` 21) are not implementation families. The remaining four target modes
(`allyTeam`, `foeSide`, `randomNormal`, `scripted`) likewise do not unlock a
coherent singles slice by themselves. The next foundational event boundaries
are numeric `TryHeal`, then item consumption/residual installation identity;
large hook-name counts must not outrank those semantic transactions.

## Recommendation

Generate all 43 rows and verify/classify the 39 executable single-effect
damaging secondaries next. It is the
largest current closure that exercises already-earned primitives rather than
introducing a new state machine. Then implement the four direct-recovery moves
to establish the reusable heal boundary, followed by Oran/Sitrus as the first
item-consumption slice.

---

# Historical Checkpoint 6 ranking after Boost32

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This is a read-only audit of the current descriptor map.  It is a work-order
recommendation, not a support claim.  The map currently has exactly 1,060
unsupported records:

> Follow-up: the ordinary-attack implementation re-audited this candidate set
> against legal holders and closed 16 move descriptors plus Hard Stone,
> SilverPowder, Dragon Fang, and their hooks. Hyper Voice remains unsupported:
> all legal Gen 3 learners require an ability outside the fail-closed native
> capability set. See `ORDINARY_ATTACK_FAMILY.md`. Counts below preserve the
> ranking-time snapshot rather than pretending this historical audit is live.

| Kind | Unsupported |
| --- | ---: |
| move | 283 |
| ability | 68 |
| item | 103 |
| condition | 68 |
| format rule | 39 |
| target mode | 4 |
| callback-hook ownership | 495 |

The ranking counts both owner descriptors and their hook-ownership records.
It does not treat a generated identity row as implemented behavior.  In
particular, a held item with no callback still participates in item loss,
transfer, suppression, and canonical state; those catalog entries are not
credited here merely because their static fields are generated.

## Ranking

| Rank | Semantic family | Direct obligations closed | New prerequisites | Why this position |
| ---: | --- | ---: | --- | --- |
| 1 | Gen 3 type-boost held items | **34**: 17 items + 17 hooks | Add `ModifySpA`; generalize the existing typed `ModifyAtk` relay call site by Gen 3 damage category | Black Belt already proves the exact handler shape, ordering, move-type guard, and Q12 `1.1` chain.  This is the largest closure that mostly extends generated data rather than control flow. |
| 2 | Ordinary constant-power attacks | **17** moves | Generated executable rows and rotation evidence; no new event algebra | Accuracy, type immunity, criticals, damage rolls, Protect, Substitute, Mirror Move, and category damage already exist.  The bounded list deliberately excludes high-critical, self-destruct, invulnerability-interaction, variable-power, and effect-bearing attacks. |
| 3 | Remaining core statuses plus direct status moves | **29**: 4 conditions + 13 hooks + 12 moves | Complete status lifecycle, immobilization PRNG, speed relay, thaw/wake rules, and status application/immunity | High closure and foundational for abilities, berries, and damaging secondaries, but materially more stateful than ranks 1--2. |
| 4 | Rain, sun, and hail field lifecycle | **19**: 3 conditions + 13 hooks + 3 moves | Field-scoped discovery, weather replacement/end, typed weather relays, hail residual | Sandstorm supplies one installed-weather scaffold, but these conditions require the honest `fieldEvent` topology and damage/immunity relays rather than three more weather tags. |
| 5 | Gen 3 pinch/healing berries | **28**: 7 items + 21 hooks | `eatItem`/item removal, residual trigger scheduling, fraction heal, flavor/nature confusion, canonical consumed state | Good closure and establishes the item-mutation boundary needed by most remaining items.  It ranks below weather because five berries require nature-flavor semantics that the current battle set does not retain merely for stat calculation. |

The numerator alone is not the ranking.  For example, 45 apparently passive
balls, fossils, evolution items, and later-generation berry metadata are not a
45-obligation quick win: legal Gen 3 moves can steal, swap, or remove held
items, so descriptor-wide conformance depends on the generic item-mutation
family.  Likewise, the much larger set of damaging moves is not one semantic
family: high-critical, two-turn, self-destruct, partial-trap, recoil, fixed
damage, and stateful callbacks own different staging and interaction rules.

The later item-mutation checkpoint now implements that prerequisite for
Thief, Covet, Knock Off, Recycle, Sticky Hold, Mail, and the separate typed
Trick swap transaction. This ranking table is a historical planning snapshot,
not a claim that the remaining item catalog is supported.

## 1. Gen 3 type-boost held items (recommended next slice)

### Exact membership and count

The 17 unsupported item descriptors and their 17 unsupported owner bindings
are:

| Event | Type | Item IDs |
| --- | --- | --- |
| `ModifyAtk` | Rock | `hardstone` |
| `ModifyAtk` | Steel | `metalcoat` |
| `ModifyAtk` | Poison | `poisonbarb` |
| `ModifyAtk` | Flying | `sharpbeak` |
| `ModifyAtk` | Normal | `silkscarf` |
| `ModifyAtk` | Bug | `silverpowder` |
| `ModifyAtk` | Ground | `softsand` |
| `ModifyAtk` | Ghost | `spelltag` |
| `ModifySpA` | Dark | `blackglasses` |
| `ModifySpA` | Fire | `charcoal` |
| `ModifySpA` | Dragon | `dragonfang` |
| `ModifySpA` | Electric | `magnet` |
| `ModifySpA` | Grass | `miracleseed` |
| `ModifySpA` | Water | `mysticwater` |
| `ModifySpA` | Ice | `nevermeltice` |
| `ModifySpA` | Water | `seaincense` |
| `ModifySpA` | Psychic | `twistedspoon` |

Black Belt is deliberately absent: its Fighting `ModifyAtk` descriptor and
hook are already implemented and are the executable exemplar.  Deep Sea
Tooth, Light Ball, and Thick Club are also absent: despite sharing event names,
they are species-conditioned stat multipliers, not type-boost items.

### Authoritative and native boundaries

- Showdown: `data/mods/gen3/items.ts`, the symbols listed above.  Each removes
  the inherited `onBasePower`, declares priority 1 on either `onModifyAtk` or
  `onModifySpA`, checks `move.type`, and returns `chainModify(1.1)`, except
  Sea Incense which returns Gen 3's `chainModify(1.05)`.
- Event control flow: `sim/battle.ts#runEvent` and the Gen 3 damage path in
  `data/mods/gen3/scripts.ts`.
- Native data/program shape: `PokemonItemData`,
  `PokemonHandlerDescriptor`, `PokemonOwnerBindingIndex`, and
  `POKEMON_HANDLER_OP_GUARD_MOVE_TYPE` followed by
  `POKEMON_HANDLER_OP_CHAIN_Q12`.
- Native call site: the attack-stat selection in `resolve_hit` in
  `native/pokemon.c`.  Physical moves dispatch `ModifyAtk`; special moves must
  dispatch a distinct generated `ModifySpA` event.  Do not rename both events
  to a generic native-only event because ordering and trace identity are
  observable Showdown boundaries.

### Required proof

1. Focused physical and special tests prove matching type applies its exact
   generated Q12 modifier (4505, or 4300 for Sea Incense) and a nonmatching
   type is a discovered no-op.
2. A Water rotation proves both Mystic Water and Sea Incense are independent
   descriptors with the same denotation.
3. A three-handler synthetic test preserves priority/order/tie behavior; do
   not special-case "held type item" outside event discovery.
4. Rotate all 17 item/type pairs and at least one mismatch per event family.
5. Differential cases include physical and special exact damage, critical,
   burn/Guts ordering on the physical side, Water Absorb early cancellation,
   Protect/Substitute early exits, switch persistence, and deterministic
   replay with no extra PRNG calls.
6. Only after every rotation passes, update 17 item and 17 hook records with
   source, native boundary, focused test, differential case, and revision.

This slice should be generated from `(item_id, event, type, modifier_q12)`
records.  No item ID belongs in generic control flow.

## 2. Ordinary constant-power attacks

### Exact membership and count

Seventeen unsupported moves have constant positive base power, ordinary
accuracy, crit ratio 1, priority 0, and no callbacks, secondary, status,
volatile, weather, recoil, drain, multihit, force-switch, self-switch, or
variable-damage formula:

`cut`, `dragonclaw`, `drillpeck`, `eggbomb`, `hornattack`, `hydropump`,
`hypervoice`, `megahorn`, `megakick`, `peck`, `pound`, `rockthrow`, `slam`,
`vinewhip`, `visegrip`, `waterfall`, `watergun`.

The source boundary is each symbol in `data/moves.ts`; the flattened fields are
the existing `PokemonMoveData` base power, type/category, accuracy, target,
priority, PP, and flags.  The native boundary is the existing generic move-hit
pipeline and Gen 3 damage operation.  The target modes used here are already
supported.

This list excludes `explosion`/`selfdestruct` (self-faint and Gen 3 Defense
halving), `gust`/`skyuppercut` (two-turn invulnerability exceptions), all
high-critical moves, and every move with an attached effect.  Modern-only
metadata flags may be generated but may not acquire invented Gen 3 behavior.

Required proof is a generated table rotation over all 17, forced hit/miss and
critical vectors, physical/special category vectors, type immunity and STAB,
and recombination with Protect, Substitute, Mirror Move, the rank-1 held
items, and Water Absorb.  Contact/sound owner hooks remain separately
unsupported obligations; the tests must still prove that the move flags and
event staging are preserved for those later handlers.

## 3. Remaining core statuses and direct status moves

### Exact membership and count

- Conditions: `statuses.frz`, `statuses.par`, `statuses.psn`, `statuses.slp`
  (4).
- Direct moves: `glare`, `grasswhistle`, `hypnosis`, `lovelykiss`,
  `poisongas`, `poisonpowder`, `sing`, `sleeppowder`, `spore`, `stunspore`,
  `thunderwave`, `willowisp` (12).  Will-O-Wisp uses the already-supported burn
  condition but still belongs to the direct status-application rotation.
- Hooks (13): `frz` owns `AfterMoveSecondary`, `BeforeMove`, `DamagingHit`,
  `ModifyMove`, `Start`; `par` owns `BeforeMove`, `ModifySpe`, `Start`; `psn`
  owns `Residual`, `Start`; `slp` owns `BeforeMove`, `Start`, `SwitchIn`.

Authoritative sources are `data/conditions.ts`,
`data/mods/gen3/conditions.ts` (Gen 3 sleep/freeze overrides),
`data/moves.ts`, and the Glare/Hypnosis overrides in
`data/mods/gen3/moves.ts`.  The native family must use the canonical status
slot, installed-owner metadata, event discovery, and labeled draws; it must
not implement `resolve_sleep_move` or equivalent move-name branches.

Required proof covers exact sleep duration and switch behavior, freeze thaw
and Fire interaction, paralysis speed and full-paralysis staging, regular
poison residual, type/status immunity, duplicate/failure behavior, Synchronize
source provenance (without claiming that ability), switch/faint cleanup, and
all 12 move accuracy/target rotations.  The family is not complete if it only
stores four more enum values.

## 4. Rain, sun, and hail field lifecycle

### Exact membership and count

- Moves: `hail`, `raindance`, `sunnyday` (3).
- Conditions: `weather.hail`, `weather.raindance`, `weather.sunnyday` (3).
- Hooks: Hail owns `FieldStart`, `FieldResidual`, `FieldEnd`, `Weather` (4);
  Rain owns `FieldStart`, `FieldResidual`, `FieldEnd`,
  `WeatherModifyDamage` (4); Sun owns `FieldStart`, `FieldResidual`,
  `FieldEnd`, `Immunity`, `WeatherModifyDamage` (5).

The authoritative definitions are the named records in `data/conditions.ts`
and `data/moves.ts`, interpreted through `sim/field.ts` and
`sim/battle.ts#fieldEvent`.  Native work belongs in generic field-owner
discovery, the installed weather state, residual queue, and generation data
for duration, immunity, and modifiers.  Sandstorm is evidence for storage and
one residual phase, not permission to add three weather-specific branches.

Tests must cover start/restart/replacement/end, five-turn move weather,
weather-to-weather replacement ordering, rain/sun Fire and Water rounding,
Solar Beam interaction as a still-separate move obligation, hail damage and
immunities, simultaneous status/weather residual order, residual KO/forced
replacement, switch persistence, and identical replay/PRNG state.

## 5. Gen 3 pinch/healing berries

### Exact membership and count

Items: `aguavberry`, `figyberry`, `iapapaberry`, `magoberry`, `oranberry`,
`sitrusberry`, `wikiberry` (7).  Each owns `onResidual`, `onTryEatItem`, and
`onEat`, for 21 hook records and 28 total obligations.

The authoritative Gen 3 threshold scheduling is in the corresponding symbols
in `data/mods/gen3/items.ts`; the inherited eat/flavor behavior is in
`data/items.ts`.  `sim/pokemon.ts#eatItem` owns the item-removal and event
sequence.  Native work belongs in a generic consume/eat mutation, residual
item discovery, generated threshold/heal descriptors, and retained normalized
nature/flavor data.  It must not be seven item-name branches.

Proof must exercise HP immediately above/at/below each threshold, exact floor
rounding and max-HP clamp, failed `TryEatItem`, each flavor-confusion match and
mismatch, one-time consumption, competing residual handlers and their order,
switch persistence, faint/terminal edges, and replay.  Oran/Sitrus can be an
internal sub-slice, but the seven-item family cannot be classified from those
two because the five flavor berries have an additional observable predicate.

## Recommendation

Implement rank 1 next.  It extends one proven program into a generated family,
forces the kernel to expose the honest physical-versus-special event boundary,
and provides 34 descriptor-level closures without adding state, phases, or
PRNG.  Follow it with rank 2 as a table-rotation exercise.  Then take rank 3
before berries: status semantics are a prerequisite for the broader cure and
contact-proc item/ability families and therefore reduce more downstream
uncertainty than berry consumption alone.
