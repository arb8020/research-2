# Gen 3 berry and item-consumption implementation plan

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, effective `gen3ou` dex.

This is a source audit and bounded implementation plan, not a native support
claim. The effective Gen 3 dex inherits through Gen 4 and the current base
data, so the flattened dex is authoritative; reading only
`data/mods/gen3/items.ts` loses every `onEat` body and all status-berry hooks.

## Exact reachable inventory

The smallest useful berry slice contains 16 legal item descriptors and 35
owned callback records:

| Family | Items | Trigger in effective Gen 3 | Effect |
|---|---|---|---|
| fixed healing | Oran, Sitrus | `Residual`, order 10/sub-order 4, at or below 1/2 max HP | heal 10 / heal 30 |
| deterministic pinch boosts | Liechi, Ganlon, Salac, Petaya, Apicot | `Residual`, order 10/sub-order 4, at or below 1/4 max HP | +1 Atk / Def / Spe / SpA / SpD |
| exceptional pinch | Lansat | same quarter-HP residual trigger | install Focus Energy |
| exceptional pinch | Starf | same quarter-HP residual trigger | choose uniformly among non-maxed Atk/Def/SpA/SpD/Spe, then +2 |
| single-status cure | Cheri, Chesto, Pecha, Rawst, Aspear | `Update` while par/slp/psn-or-tox/brn/frz respectively | cure that status |
| confusion cure | Persim | `Update` while confused | remove confusion |
| universal cure | Lum | immediate `AfterSetStatus` at priority -1, and `Update` for status or confusion | cure status and remove confusion |

The 35 records are: two each for the seven pinch berries; three each for Oran,
Sitrus, and Lum; and two each for the other six status berries. White Herb is
adjacent but separate: one descriptor and six callbacks (`Start`,
`AnySwitchIn`, `AnyAfterMega`, `AnyAfterMove`, `Residual`, and `Use`). Its
payload-bearing use protocol is already described by the hook-shape audit and
should not be disguised as a berry row.

Gen 3 deliberately replaces the base `onUpdate` trigger of the healing and
pinch berries with `onResidual` in `data/mods/gen3/items.ts:2-22,102-111,
153-162,176-185,269-289,306-315,357-369,395-404`. Activation is therefore
end-of-turn, not immediately after crossing the threshold. The comparisons
`hp <= maxhp / 2` and `hp <= maxhp / 4` are equivalent for integer HP to
`hp <= floor(maxhp / 2)` and `hp <= floor(maxhp / 4)`. The Gen 3 override also
removes the modern Gluttony branch. Gluttony is absent from the legal Gen 3
ability inventory in any event.

The inherited bodies are in `data/items.ts`: Oran heals 10 after a `TryHeal`
gate; Sitrus is overridden to heal exactly 30; the five deterministic pinch
berries boost one stat; Lansat installs `focusenergy`; Starf samples eligible
stats; the six narrow cures test their exact ailment again during `Eat`; and
Lum cures both status and confusion. A failed cure predicate does not undo
consumption if another effect changed the ailment between trigger and `Eat`.

The five flavor berries require the fully flattened Gen 3 dex, not just the
base item plus the local Gen 3 override. Their effective `TryEatItem` gate
requests `floor(baseMaxHP / 3)`, while the inherited effective `onEat` body
heals `floor(baseMaxHP / 8)` before conditionally adding confusion. This split
is observable and is frozen against `Dex.mod('gen3').items`; inspecting only
`data/items.ts` incorrectly suggests that both stages use one third.
Because activation requires at most one-half HP and the Eat heal is one-eighth
max HP, the ordinary Gen 3 transaction cannot reach the max-HP clamp; odd-HP
flooring is the reachable rounding boundary to verify.

## Canonical consumption transaction

`Pokemon#eatItem` in `sim/pokemon.ts:1786-1826` is one reusable mutation
primitive, not sixteen item-specific removal paths:

1. require a held item and a living, active holder;
2. derive omitted source/source-effect from the current event and reject a
   stale item callback attempting to eat a different replacement item;
3. dispatch cancellable `UseItem`, then cancellable `TryEatItem` unless forced;
4. emit consumption, execute the held installation's `Eat` callback, then
   dispatch `EatItem` while the item and its installation are still current;
5. copy the current id to `lastItem`, clear current item and installation
   state, and set `usedItemThisTurn` and `ateBerry`;
6. dispatch `AfterUseItem` after the holder is empty.

For a berry's own `Update` or `Residual` callback, source is the holder and
source-effect is that item. `Eat` receives the captured item installation.
The native trace must retain those identities; reporting only the final empty
item loses the causal boundary.

`fieldEvent('Residual')` discovers all residual handlers, sorts by event order,
priority, sub-order, speed, and tie PRNG, and rejects an item handler whose
captured installation is no longer the holder's canonical item state before
execution (`sim/battle.ts:1075-1177`). Ordinary `runEvent('Update')` does not
perform this installation-identity stale check. That asymmetry is intentional.
The generic runtime must not apply one global stale-handler rule.

In Gen 3 move resolution, `eachEvent('Update')` runs after the completed hit
and before `AfterMoveSecondary`/`AfterMoveSecondarySelf`
(`data/mods/gen3/scripts.ts:476-508` and `:277-278`). Thus status berries can
act at that boundary; healing and pinch berries cannot, because their
effective `onUpdate` is explicitly absent. Lum's `AfterSetStatus` hook can act
still earlier, directly after status installation. White Herb's relevant
post-move hook is `AnyAfterMove`, not `AfterMoveSecondarySelf`.

## Item loss, restoration, and transfer

These interactions are part of admitting berry consumption, not optional
cleanup:

- **Recycle:** its effective `onHit` requires an empty current item and a
  nonempty `lastItem`, clears `lastItem`, then calls `setItem`. In Gen 3,
  `lastItem` follows the active **slot** across a switch
  (`sim/battle-actions.ts:117-143`), so a replacement can Recycle the outgoing
  Pokemon's consumed berry. Reinstallation creates fresh item state and
  `effectOrder`, and executes `Start`.
- **Knock Off:** Gen 3 inherits the Gen 4 override
  (`data/mods/gen4/moves.ts:694-704`). It clears the target's current item
  directly and sets the battle-long, per-Pokemon `itemKnockedOff` flag. This
  override deliberately does **not** call `takeItem`: it neither clears the old
  installation state nor runs `End`/`AfterTakeItem`. Current-item discovery
  nevertheless stops because the current id is empty; switch-in later replaces
  the stale installation state. It does not populate `lastItem`, so the knocked
  item is not Recyclable.
- **Thief:** after a successful damaging hit, an empty-handed source calls
  `target.takeItem(source)`, then installs the returned descriptor on itself.
  `takeItem` rejects when either participant has `itemKnockedOff` in Gen 3/4
  (`sim/pokemon.ts:1869-1883`). It also does not populate `lastItem`.
- **Consumed berries:** consumption does populate `lastItem`, so Recycle can
  reinstall them. A subsequent activation is a new installation and must be
  independently discoverable. Switching never restores the set item.

The interaction closure is four move descriptors and four hook records:
Recycle `onHit`, Knock Off `onAfterHit`, and the shared Thief/Covet
`onAfterHit` transfer family. Sticky Hold plus `onTakeItem`, and Mail plus
`onTakeItem`, close the two reachable TakeItem gates. Knock Off's
effective Gen 3 base power/category come from the flattened dex; its removal
must not reuse modern `takeItem`, because the Gen 3/4 override intentionally
sets the permanent lockout. Thief requires the complete take-then-set
transaction and rollback-to-target behavior if the receiver cannot accept the
item. No move-name resolver branch is justified: generate primary/secondary
item operations and keep the one generation-policy distinction for pre-Gen-5
Knock Off semantics.

## Smallest honest implementation slices

Implement in dependency order:

1. **Eat transaction + residual fixed-heal berries:** Oran and Sitrus close 2
   item descriptors and 6 hook records. This first proves field-event item
   discovery, half-HP thresholds, `TryEatItem`, `Eat`, persistent item loss,
   `lastItem`, and fixed healing without needing boosts or statuses.
2. **Deterministic pinch boosts:** Liechi, Ganlon, Salac, Petaya, and Apicot
   close 5 descriptors and 10 records through one declarative threshold/boost
   family. This requires the complete boost pipeline, including capped boosts.
3. **Status cures:** Cheri, Chesto, Pecha, Rawst, Aspear, Persim, and Lum close
   7 descriptors and 15 records after all six statuses and confusion have
   honest lifecycle support. Lum additionally proves immediate
   `AfterSetStatus` ordering.
4. **Lansat and Starf:** close 2 descriptors and 4 records after Focus Energy,
   critical-ratio mutation, eligible-stat construction, and labeled PRNG are
   supported. Starf cannot be represented as a generic fixed boost.
5. **Recycle / Knock Off / Thief / Covet:** close the 4 move descriptors and 4 hook
   records only after `setItem`, `takeItem`, slot-scoped `lastItem`, fresh
   installation identity, and Knock Off lockout are all modeled.

White Herb remains a separate follow-up because it stores a boost map in its
installation between `Start` and `Use`. Treating it as the same transaction is
useful; treating its trigger/effect as a berry descriptor is not.

## Required focused and differential evidence

For slice 1, test both sides of the threshold with odd and even max HP, exact
10/30 healing and near-full clamp, full-HP `TryHeal` rejection, dead/inactive
guards, cancelled `UseItem` and `TryEatItem`, exact event order, empty current
item plus populated `lastItem`, fresh state after Recycle, and byte-for-byte
rollback on event/trace capacity failure. Prove residual ordering against a
status/weather residual both faster and slower, including a speed tie and its
labeled handler-order draws.

For slice 2, rotate all five stats, exercise exactly above/at/below quarter HP,
boost cap, Contrary/Clear Body-style modifiers where applicable, and two berry
holders whose residual order is speed-dependent. For slice 3, test every exact
status, Toxic as poison for Pecha, mismatched statuses, confusion, Lum with
status alone/confusion alone/both, status inflicted during a move, and the
relative order of `AfterSetStatus`, `Update`, `AfterMoveSecondary`, and
`AfterMoveSecondarySelf`.

For slice 4, Lansat must prove idempotent Focus Energy installation/restart
semantics. Starf must prove the candidate order Atk, Def, SpA, SpD, Spe; omit
stats already at +6; fail harmlessly when all five are capped; consume exactly
one uniform draw only when candidates exist; and replay the same selected stat
from the same seed. The pinned oracle currently calls bare `sample` in
`data/items.ts`; the verifier patch should label that call
`item.starfberry.stat` without changing PRNG consumption.

For slice 5, test consumed-item Recycle, Recycle failure while holding an item
or without `lastItem`, Gen 3 slot transfer of `lastItem`, Knock Off not setting
`lastItem`, switch persistence of empty/knocked state, Thief transfer with
fresh installation identity, both Knock Off guards on `takeItem`, and
berry-trigger ordering after a stolen/recycled installation. Recombine each
operation with a same-turn faint and switch.

Every differential case must compare normalized choices, queue/events,
canonical item id and installation token/order, HP/status/boost/volatile state,
`lastItem`, `usedItemThisTurn`, `ateBerry`, `itemKnockedOff`, request/phase,
labeled draws, and final seed at every stable boundary. Descriptor and hook
records may be reclassified only after focused tests, exact pinned-Showdown
differential cases, deterministic replay, random/Ocean regression, inventory
validation, and sanitizers all pass.

## Slice 1 implementation status

Oran and Sitrus plus their six `Residual`/`TryEatItem`/`Eat` hooks are now
implemented by one generated fixed-heal-berry transaction. Differential
evidence covers threshold success and rejection, consumption across a switch,
and ordering after Rain Dish; focused evidence additionally covers odd-max-HP
thresholds, near-full clamping, full-HP rejection, and consume-once behavior.
The full 599-boundary corpus and deterministic replays match the pinned oracle.

Recycle, Knock Off, Thief, Covet, Sticky Hold, and Mail are implemented through
generic item mutation operations and generated semantic capabilities. Trick is
implemented as a separate typed swap transaction because its sequential
two-holder exchange and raw-ID rollback behavior are not ordinary take/set.

Liechi, Ganlon, Salac, Petaya, and Apicot plus their ten effective
`onResidual`/`onEat` hooks are also implemented through one generated
quarter-HP boost transaction. Focused evidence rotates all five stats, odd-HP
at/above/below thresholds, positive `TryBoost` filtering, +6 caps, and
consume-once item state. Differential evidence rotates every descriptor,
recombines Liechi with Clear Body, and proves that two holders are fully
discovered and speed-ordered before either callback executes. The complete
613-boundary corpus and both deterministic replays match the pinned oracle.

Cheri, Chesto, Pecha, Rawst, and Aspear plus their ten effective
`onUpdate`/`onEat` hooks are implemented through one generated status-mask
transaction. Pecha's mask contains both Poison and Toxic; the other four
contain exactly one major status. Focused evidence covers mismatches, both
Pecha statuses, Chesto sleep-counter clearing, and item persistence.
Differential evidence rotates post-move cures and recombines cures with
voluntary switching, including a mismatched incoming holder. That switch case
also closes the generic Gen 3 folded `runSwitch` Update boundary and
zero-stage Toxic switch trace. The complete 625-boundary corpus and both
deterministic replays match the pinned oracle. Persim and Lum remain
unsupported because confusion and Lum's additional immediate
`AfterSetStatus` path are outside this slice.
