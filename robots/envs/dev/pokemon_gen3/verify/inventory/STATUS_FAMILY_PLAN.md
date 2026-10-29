# Gen 3 major-status family plan

Oracle: pinned Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format `gen3ou`.

This is an inventory and implementation plan, not a support claim.  In
particular, a move is not implemented merely because its status field is
generated: it is implemented only after every reachable interaction below is
either supported or rejected by an explicit capability check.

## Frozen move inventory

The effective Gen 3 dex contains exactly **43 legal/reachable move
descriptors** with a declarative primary or secondary major status.  `Toxic`
is the only one currently classified implemented; the other **42 are
unsupported**.

| Status | Primary moves | Secondary moves |
|---|---|---|
| burn | Will-O-Wisp | Blaze Kick, Ember, Fire Blast, Fire Punch, Flamethrower, Flame Wheel, Heat Wave, Sacred Fire |
| paralysis | Glare, Stun Spore, Thunder Wave | Body Slam, Bounce, Dragon Breath, Lick, Secret Power, Spark, Thunder, Thunderbolt, Thunder Punch, Thunder Shock, Zap Cannon |
| poison | Poison Gas, Poison Powder | Poison Sting, Poison Tail, Sludge, Sludge Bomb, Smog, Twineedle |
| toxic poison | Toxic | Poison Fang |
| sleep | Grass Whistle, Hypnosis, Lovely Kiss, Sing, Sleep Powder, Spore | none |
| freeze | none | Blizzard, Ice Beam, Ice Punch, Powder Snow |

There are exactly 43 declarative status-effect records: every listed move has
one major-status outcome in the frozen Gen 3 set.

The generic declarative route covers 39 currently unsupported descriptors.
Three descriptors must remain gated until their independent program is
supported: `Bounce` (two-turn state), `Secret Power` (environment-dependent
secondary construction), and `Thunder` (weather-dependent accuracy).  `Toxic`
is the existing regression anchor.  `Twineedle` additionally depends on the
generic multihit family, but its poison effect itself is ordinary.

The static inventory is not the whole family.  These moves cure or otherwise
consume status through callbacks and remain separate program obligations:

- `Aromatherapy` and `Heal Bell`: team-wide cure with different immunity
  checks and the currently unsupported `allyTeam` target;
- `Refresh`: self-cure burn/paralysis/poison/toxic, but not sleep/freeze;
- `Rest`: atomic sleep installation, fixed counter 3, then full healing;
- `Smelling Salts`: doubled power against paralysis and cure after the hit;
- `Sleep Talk` and `Snore`: sleep-only action rules;
- `Uproar`: sleep prevention and cure through its installed condition;
- `Yawn`: delayed sleep through a volatile;
- `Tri Attack`: one secondary callback randomly selects burn/freeze/paralysis.

## Canonical status transaction

The authoritative boundary is `Pokemon.setStatus` in
`sim/pokemon.ts:1685-1749`; move effects enter it from
`sim/battle-actions.ts:1245-1255`.  The native operation must be one atomic
transaction:

1. reject a fainted target and an already occupied major-status slot;
2. normalize `tox` immunity as poison immunity;
3. check natural type immunity, then ordered `Immunity` handlers;
4. run the ordered `SetStatus` gate over the proposed condition value;
5. install a new status owner identity and source reference;
6. run the status's `Start` single event;
7. roll back the previous status and payload if `Start` cancels;
8. run ordered `AfterSetStatus` handlers.

`trySetStatus` deliberately attempts the current status when the slot is
already occupied; it is not a second mutation primitive.  `cureStatus` removes
Nightmare when curing sleep, emits the cure observation, then uses the same
empty-status transition.  Generated move effects call this transaction;
generic control flow must not branch on move IDs.

The current native engine has two status-setting implementations
(`apply_effect_op` and the primary-effect path), accepts only burn/toxic/
paralysis in its ABI enum, and performs bespoke immunity checks.  They must be
replaced by this single transaction before adding more descriptors.

## Six status conditions

| Status | Installation/lifecycle semantics | PRNG and action semantics |
|---|---|---|
| `brn` | Fire-type immunity; residual `floor(baseMaxHP/8)`; halves physical Attack unless modified by Guts | no status-owned draw |
| `psn` | Poison- and Steel-type immunity; residual `floor(baseMaxHP/8)` | no status-owned draw |
| `tox` | same immunity as poison; stage starts 0, increments through 15, damage `max(1,floor(baseMaxHP/16))*stage`; stage resets on switch-in | no status-owned draw |
| `par` | no Gen 3 type immunity; Speed is quartered | one `BeforeMove` 1-in-4 draw; cancellation consumes the turn |
| `slp` | no type immunity; `Start` samples time in `[2,6)` and removes Nightmare; skipped Sleep Talk/Snore time is restored on switch-in; Early Bird decrements twice | exactly one four-way draw at successful installation; no later wake draw |
| `frz` | Ice-type immunity; damaging effective Fire-type hits thaw; defrost moves and `thawsTarget` cure at their defined boundaries | one 1-in-5 `BeforeMove` thaw draw before checking a defrost move |

The status conditions contribute exactly **4 currently unsupported condition
descriptors** (`psn`, `par`, `slp`, `frz`); burn and toxic are existing
implemented anchors.  The complete status semantics have exactly **18 frozen
condition hook records**: all six `Start` callbacks; burn/poison/toxic
`Residual`; toxic `SwitchIn`; paralysis `ModifySpe` and `BeforeMove`; sleep
`BeforeMove` and `SwitchIn`; and freeze `BeforeMove`, `ModifyMove`,
`AfterMoveSecondary`, and `DamagingHit`.

## Immunity and clause handlers

Natural immunity comes from the generated Gen 3 type chart.  Ability and
format policy then participate through the ordinary event dispatcher:

- `Immunity` blocks poison/toxic (`onSetStatus`);
- `Insomnia` and `Vital Spirit` block sleep (`onSetStatus`) and Yawn
  (`onTryAddVolatile`);
- `Limber` blocks paralysis (`onSetStatus`);
- `Water Veil` blocks burn (`onSetStatus`);
- `Magma Armor` blocks freeze (`onImmunity`);
- `Safeguard` is an installed side-condition `onSetStatus` gate;
- `Uproar` supplies an installed `onAnySetStatus` gate;
- sunny weather's freeze immunity is an installed weather handler.

The five `onSetStatus` abilities plus Magma Armor are exactly **6 ability
descriptors and 14 hook records**, all currently unsupported: five
`onSetStatus`, Magma Armor's `onImmunity`, six `onUpdate` cures, and the
Insomnia/Vital Spirit `onTryAddVolatile` gates for Yawn.

The OU rule table installs both `Sleep Clause Mod` and `Freeze Clause Mod`.
Both are `SetStatus` handlers, not pre-move special cases:

- Sleep Clause rejects foe-inflicted sleep when a living teammate is already
  asleep due to a non-ally source.  Self-sleep (notably Rest) neither triggers
  nor satisfies the opponent-inflicted predicate.
- Freeze Clause rejects foe-inflicted freeze when any teammate is already
  frozen.  The existing frozen teammate need not be alive.

These are exactly **2 currently unsupported format-rule descriptors**.  The
status state must therefore preserve an honest source reference across turns
and switches; a bare status enum cannot implement Sleep Clause.

## Status-producing and status-curing owners

The remaining reachable producers/cures are compositional follow-on slices:

| Family | Owners | Required ordering/PRNG |
|---|---|---|
| contact status | Effect Spore, Flame Body, Poison Point, Static | `DamagingHit` after real damage and contact; ability chance draw, then Effect Spore's independent 3-way sample |
| reflection | Synchronize | `AfterSetStatus`; ignore sleep/freeze; Gen 3 converts reflected toxic to ordinary poison |
| cure on switch | Natural Cure | `SwitchOut`, before ordinary outgoing cleanup; no draw |
| cure at residual | Shed Skin | residual order 10/suborder 3; 33/100 draw only while alive and statused |
| immediate item cure | Lum Berry | priority-1 `AfterSetStatus`, consumes item after a successful installation |
| sleep rate | Early Bird | status-owned `BeforeMove` decrements sleep time twice; ability has no callback of its own |

These are **8 additional ability descriptors** (`effectspore`, `flamebody`,
`poisonpoint`, `static`, `synchronize`, `naturalcure`, `shedskin`,
`earlybird`), **7 callback hook records** (Early Bird is data queried by
sleep), and **1 item descriptor plus 1 hook record** for Lum Berry.  They are
all currently unsupported.  Aromatherapy/Heal Bell/Refresh/Rest and the other
callback moves above are deliberately not counted as closed by this table.

## Bounded first slice and closure accounting

The smallest useful implementation slice is the transaction plus the four
missing installed status kinds, natural type immunity, status-owned action and
residual behavior, the six prevention abilities, and both OU clauses.  It
should enable the 12 otherwise-simple primary status moves (Glare, Grass
Whistle, Hypnosis, Lovely Kiss, Poison Gas, Poison Powder, Sing, Sleep Powder,
Spore, Stun Spore, Thunder Wave, Will-O-Wisp), with Toxic as a regression
anchor.

This slice has an exact maximum closure of **38 frozen obligations**:

```text
12 move descriptors
+ 4 status-condition descriptors
+ 6 prevention-ability descriptors
+ 14 ability hook records
+ 2 format-rule descriptors
= 38
```

That number is conditional, not a promise: no entry moves out of unsupported
until every listed interaction is executable and proven.  The subsequent
ordinary-secondary rotation can close up to **27 more move descriptors**
(the remaining 39 generic candidates minus the 12 primary moves), but only as
their independent damage, multihit, crit, spread, and move-program obligations
also close.  The contact/reflection/cure table is a separate exact **17
obligation** tranche (8 abilities + 7 hooks + Lum Berry + its hook).

## Proof matrix

Focused native tests must cover:

1. empty-slot success, occupied-slot failure, fainted target, and rollback of
   a cancelling `Start` handler byte-for-byte;
2. all four natural type immunities and all six prevention abilities;
3. Sleep/Freeze Clause over active and benched teammates, self-inflicted Rest
   sleep, fainted sleepers/freezes, and preserved source identity;
4. burn/poison/toxic residual arithmetic at small and non-divisible max HP;
5. toxic stage cap and switch reset;
6. paralysis Speed ordering plus both allowed and cancelled actions with the
   exact labeled 1-in-4 draw;
7. sleep installation draws at both endpoints, wake timing, Early Bird,
   Sleep Talk/Snore skipped time, switch-out/in, and Nightmare removal;
8. freeze failed thaw, random thaw, defrost move, target-thaw move, and
   effective Fire hit, with exact labeled 1-in-5 staging;
9. primary versus secondary application, 0/10/30/50/100-percent outcomes,
   no secondary after miss/immunity/faint/Substitute, and Serene Grace as a
   later modifier rather than duplicated move data;
10. handler ordering among clause, ability, side/weather, status, Synchronize,
    and Lum Berry owners, including tie draws only where Showdown draws;
11. deterministic replay with identical canonical state, observations,
    labeled draws, and final seed.

Differential generation should rotate every one of the 43 declarative moves
through neutral, naturally immune, ability-immune, occupied-status, clause,
Substitute, and fainting targets.  It must additionally rotate the producer/
cure owners and persist a minimized case at the first divergent boundary.
Compare normalized choices, queue, `Immunity`/`SetStatus`/`Start`/
`AfterSetStatus` handler sequences, status payload/source, action cancellation,
residual work, request, and labeled PRNG consumption.

## Authoritative sources

- `sim/pokemon.ts:1670-1761` (`trySetStatus`, `cureStatus`, `setStatus`,
  `clearStatus`)
- `sim/pokemon.ts:2252-2271` (`runStatusImmunity`)
- `sim/battle-actions.ts:1245-1255` (declarative status move effects)
- `data/conditions.ts` and `data/mods/gen3/conditions.ts` (effective six
  status conditions)
- `data/abilities.ts`, `data/mods/gen4/abilities.ts`, and
  `data/mods/gen3/abilities.ts` (effective Gen 3 owners)
- `data/moves.ts` and `data/mods/gen3/moves.ts` (move descriptors/programs)
- `data/rulesets.ts:1378-1410,1451-1471` (OU clauses)
