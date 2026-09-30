# Gate 3a: current executable handler programs

Oracle: resolved `Dex.forGen(3)` at Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Count correction

There are **four event-handler bindings**, not five:

| Owner | Frozen hook | Event algebra |
|---|---|---|
| Water Absorb | `onTryHit` | boolean-or-null gate |
| Guts | `onModifyAtk` | numeric relay with Q12 modifier |
| Black Belt | `onModifyAtk` | numeric relay with Q12 modifier |
| Rock Head | `onDamage` | numeric-or-cancel relay |

The frozen callback inventory has exactly one record for each and none for
Levitate. The native generated `HANDLERS` table also contains exactly these
four descriptors (`native/gen3_slice_data.c:1019-1032`). The likely “fifth
binding” is Levitate: native represents it separately as declarative Ground
immunity data on `PokemonAbilityData`, not as an event handler
(`native/pokemon.h:303-310`, `native/pokemon.c:919-928`). That separation is
semantically sound because Showdown's effective Gen 3 Levitate descriptor has
no callback; type/ability immunity is resolved by the immunity boundary.

## Exact resolved semantics

### Water Absorb — `TryHit`

Authoritative descriptor: `data/abilities.ts:5329-5341` (inherited unchanged
by Gen 3). Hit staging is `runImmunity` → accuracy → `runEvent('TryHit')` in
`data/mods/gen3/scripts.ts:324-405`.

Predicate:

```text
target != source && move.type == Water
```

On match it attempts to heal `target.baseMaxhp / 4`. `Battle.heal` truncates
the amount, runs `TryHeal`, requires a living active non-full target, mutates
HP, emits `-heal ... [from] ability: Water Absorb [of] <source>`, and then runs `Heal`
(`sim/battle.ts:2924-2965`). If no HP is healed, Water Absorb instead emits
`-immune ... [from] ability: Water Absorb`. It returns **`null` in both cases**.
That is a silent `TryHit` cancellation: later handlers do not run, the move
does not damage, and the generic `-fail` branch (which is reserved for
`false`) is not emitted. Accuracy has already consumed its owned draw.

Current native behavior now performs the quarter-base-HP heal and distinguishes
successful healing from full-HP immunity while returning the same silent
cancellation result. `derived-water-absorb-heal` and
`derived-water-absorb-try-hit` cover the damaged- and full-HP paths,
respectively. Its opposing-target topology makes `target != source` true in the
current singles format; the generated predicate remains explicit in the
handler program.

The effective descriptor also marks the ability `breakable`. That metadata
allows Showdown's generic event engine to suppress it for an applicable
ability-ignoring attacker (`sim/battle.ts:1436-1479`). Gen 3 OU has no reachable
Mold Breaker user, but the generated ability descriptor should retain the flag
for a multi-generation kernel rather than baking suppression into this program.

Minimal program:

```text
IF source != holder AND move.type == Water:
    healed = HEAL(holder, floor(holder.base_max_hp / 4), effect = owner)
    IF healed == 0: EMIT_IMMUNE(holder, from = owner)
    RETURN_NULL
RETURN_UNDEFINED
```

This is ordinary predicate + mutation + message + gate cancellation. It does
not justify a Water-Absorb-specific native function.

### Guts — `ModifyAtk`

Authoritative descriptor: `data/abilities.ts:1725-1735`.

Predicate: the holder has any non-empty major status; it is not restricted to
burn or poison. On match it calls `chainModify(1.5)` at priority 5. In Q12 the
factor is `floor(1.5 * 4096) = 6144`; `chainModify` mutates the current event's
modifier and returns `undefined` (`sim/battle.ts:2984-2993`). The numeric relay
itself therefore remains unchanged until `runEvent` applies the accumulated
modifier once at event exit (`sim/battle.ts:1550-1563`).

Gen 3 also suppresses the ordinary physical burn damage halving when the
attacker has Guts (`data/mods/gen3/scripts.ts:40-59`). That is a separate damage
stage policy, not a second callback hook.

Current native matches the status predicate, priority 5, Q12 factor 6144 and
final-once relay application. Its `guts_active` output is the native projection
of the separate burn-bypass policy.

Descriptor-map decision: **unsupported**. The executable status model and
differential corpus do not yet cover all reachable major statuses, especially
ordinary poison, sleep, and freeze. Burn evidence cannot prove the source
predicate “any non-empty major status.”

Minimal declarations:

```text
on ModifyAtk priority 5:
    IF holder.major_status != NONE: CHAIN_Q12(3 / 2)
ability policy: IGNORE_PHYSICAL_BURN_ATTACK_DROP
```

No exceptional handler is justified.

### Black Belt — `ModifyAtk`

Authoritative Gen 3 override: `data/mods/gen3/items.ts:38-47`. It explicitly
removes the inherited modern `onBasePower` handler and replaces it with
`onModifyAtk` priority 1.

Predicate: the active move exists and its resolved type is Fighting. On match
it calls `chainModify(1.1)`, which becomes Q12
`floor(1.1 * 4096) = 4505`; the callback returns `undefined`, and the combined
modifier is applied only when `ModifyAtk` exits. The Gen 3 override is exactly
1.1×, not the modern `[4915,4096]` base-power modifier in
`data/items.ts:508-521`.

Current native matches event, item holder, priority 1, type predicate and Q12
4505. Its suborder 8 is Showdown's default item suborder.

Minimal program:

```text
on ModifyAtk priority 1 suborder ITEM:
    IF move.exists AND move.type == Fighting: CHAIN_Q12(11 / 10)
```

The generation plugin selects this resolved program. No runtime generation
branch and no Black-Belt-specific handler are justified.

### Gen 3 type-boost items — `ModifyAtk` / `ModifySpA`

The same override shape applies to Hard Stone, Metal Coat, Poison Barb, Sharp
Beak, Silk Scarf, SilverPowder, Soft Sand, Spell Tag, BlackGlasses, Charcoal,
Dragon Fang, Magnet, Miracle Seed, Mystic Water, Never-Melt Ice, Sea Incense,
and Twisted Spoon. The pinned Gen 3 item source removes inherited
`onBasePower`, assigns priority 1 to the category-specific stat event, and
guards the resolved move type. All call `chainModify(1.1)` except Sea Incense,
which calls `chainModify(1.05)` in the pinned Gen 3 source.

The generated native record is the product `(item, event, type, modifierQ12)`:
4505 ordinarily and 4300 for Sea Incense. The
generic damage path selects `ModifyAtk` for physical moves and `ModifySpA` for
special moves; the event interpreter contains no item identity branch. Mystic
Water and Sea Incense intentionally produce distinct Water-special owner
bindings with different Gen 3 multipliers. Focused rotation covers every matching type and
a nonmatching type, plus real physical/special damage and held-item switch
persistence.

### Rock Head — `Damage`

Authoritative descriptor: `data/abilities.ts:3860-3874` (inherited unchanged
by Gen 3).

Predicate: the damage effect ID is `recoil`. This is the recoil *effect*, not a
move-name test. The callback requires an active move; missing it is an engine
invariant violation. It returns `null` only when the active move is not
Struggle. Thus ordinary recoil is cancelled silently, while Struggle recoil is
preserved. Non-recoil damage returns `undefined` and continues normally.

Current native cancels the generic `POKEMON_DAMAGE_RELATIVE_RECOIL` cause, but
does not encode the Struggle exclusion. That is correct for its currently
executable Double-Edge slice but is not a complete Rock Head program.

Descriptor-map decision: **unsupported**. Struggle is reachable when a legal
set exhausts all PP even though the current action surface cannot select it.
The missing action does not make the exception unreachable; it is a stable
interaction gap.

Minimal program:

```text
on Damage:
    IF damage.effect == RECOIL:
        REQUIRE active_move
        IF active_move != STRUGGLE: RETURN_NULL
RETURN_UNDEFINED
```

`STRUGGLE` should be a stable generated move/effect ID, not a string or a
resolver branch. This remains a generic cancel-damage program with one data
predicate; it does not justify a Rock-Head-specific function.

## Required focused evidence

Before these bindings count as Gate 3 executable support, synthetic event
tests and pinned structural differentials should prove:

- Water Absorb at damaged HP and full HP, including HP, messages, `null`
  cancellation, later-handler suppression and unchanged post-accuracy PRNG;
- Guts for every major-status kind and no status, plus burn-bypass as a
  distinct damage-stage record;
- Black Belt with Fighting and non-Fighting resolved move types, composed
  order-sensitively with Guts and rounded once;
- Rock Head for ordinary recoil, Struggle recoil and non-recoil damage; and
- Levitate through the immunity pipeline, with no fabricated handler discovery
  record.

Water Absorb now satisfies its two HP-state bullets. Guts and Rock Head do not
yet satisfy the complete interaction requirements above. Black Belt and
Levitate remain supported at their natural modifier/immunity boundaries. None
of the four hook-owner descriptors is promoted merely because the generic
handler-program interpreter exists; hook-level promotion still requires its
own complete source, focused, and differential evidence.
