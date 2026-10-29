# Gen 3 healing-family implementation plan

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, effective `gen3ou` dex.

This is a source audit and bounded implementation plan, not a support claim.
The smallest reusable slice is the four declarative direct-recovery moves. It
must not be widened into a generic "anything that raises HP" opcode: Showdown
has several distinct operations whose ordering, source effect, and failure
semantics differ observably.

## Exact reachable inventory

### Pure direct recovery: implement first

Exactly four legal/reachable Gen 3 moves have an effective declarative
`heal: [1, 2]` tuple and no callback:

| Move | Target | Fraction | Other effective facts relevant here |
|---|---|---:|---|
| Recover | self | 1/2 | `snatch`, `heal` flags |
| Milk Drink | self | 1/2 | `snatch`, `heal` flags |
| Slack Off | self | 1/2 | `snatch`, `heal` flags |
| Soft-Boiled | self | 1/2 | `snatch`, `heal` flags |

This closes four move descriptors and no hook-ownership records: the moves
own no callback. The frozen inventory has no legal Gen 3 Heal Block move or
installed Heal Block condition. Its modern selection/execution restriction is
therefore absent, not a hidden obligation for this generation. The generated
`heal` flag must still be preserved because it is real effective move data and
future generations use it.

### Adjacent but separate families

The remaining reachable healing mechanics are deliberately not part of the
four-move proof:

- **Weather recovery (3 moves):** Moonlight, Morning Sun, and Synthesis share
  one effective `onHit` callback. They heal `baseMaxhp / 2` in clear weather,
  `maxhp * 2 / 3` in sun, and `baseMaxhp / 4` in rain, sand, or hail. The
  current effective implementation comes from the Gen 4 parent mod. This is
  one generated weather-dependent recovery operation, not three named move
  handlers. Clear and Sandstorm are currently constructible natively; honest
  support for the descriptors also requires Sunny Day, Rain Dance, and Hail.
- **Rest (1 move, 2 owned hooks):** `onTry` rejects sleep, full HP, Insomnia,
  and Vital Spirit; `onHit` installs sleep, sets both sleep counters to 3, then
  heals to full. It belongs with sleep/status lifecycle, not direct recovery.
- **Wish (1 move, 1 condition hook plus 1 slot condition):** installs a
  duration-2 slot condition. At `onEnd`, the Pokemon occupying that slot heals
  by half of its own `baseMaxhp`, even after a switch, while the announcement
  retains the original wisher. This needs slot-condition lifecycle and
  residual ordering.
- **Leech Seed and Ingrain (2 moves, 2 installed volatiles):** both heal in
  ordered residual handlers. Leech Seed first damages `baseMaxhp / 8` from the
  seeded holder, then heals the still-valid source-slot occupant by actual
  damage; Ingrain heals its holder by `baseMaxhp / 16`. They require installed
  condition provenance, residual discovery, switching semantics, and Liquid
  Ooze interaction.
- **Swallow (1 move):** heals 1/4, 1/2, or all max HP from Stockpile layers,
  then removes Stockpile. It belongs with the Stockpile product state.
- **Damage drain (5 moves):** Absorb, Dream Eater, Giga Drain, Leech Life, and
  Mega Drain have `drain: [1, 2]`. The native damage-relative family already
  proves Giga Drain, but descriptor closure also needs the other moves and
  Dream Eater's sleep/substitute immunity predicate. Drain is based on actual
  damage, not max HP, and remains a distinct effect kind.
- **Abilities (3):** Water Absorb and Volt Absorb null-cancel qualifying hits
  and attempt quarter-max-HP healing; Rain Dish heals 1/16 max HP at residual
  order 10/sub-order 3 only in rain. Water Absorb is already evidenced. Volt
  Absorb additionally excludes Thunder Wave. Rain Dish belongs with weather
  residual discovery.
- **Items (9):** Leftovers heals 1/16 at residual order 10/sub-order 4; Shell
  Bell heals 1/8 of `move.totalDamage` after the move unless force-switching;
  Oran Berry heals 10 and Sitrus Berry heals 30 on consumption; Aguav, Figy,
  Iapapa, Mago, and Wiki heal 1/8 and may confuse based on nature. Berries
  require thresholds, `EatItem`, persistent item loss, nature predicates, and
  possibly confusion. They are not direct-recovery rows.

There is exactly one reachable `TryHeal` callback owner: Liquid Ooze's
`onSourceTryHeal`. It converts drain or Leech Seed healing into damage and
returns zero. It does not modify the four direct moves, but the generic heal
primitive must still dispatch `TryHeal`; skipping the event because today's
direct-heal result is unchanged would make the boundary generation-specific.

## Authoritative Showdown boundary

Gen 3 declares `inherit: 'gen4'` in `data/mods/gen3/scripts.ts`. Effective
descriptors must therefore be read from the flattened Gen 3 dex, not inferred
from only `data/mods/gen3/moves.ts`.

For the pure slice, `data/moves.ts` supplies each `heal: [1, 2]` descriptor.
`BattleActions.runMoveEffects` in `sim/battle-actions.ts:1207-1242` owns the
semantic staging:

1. reject an already fainted target;
2. fail before healing when current HP is already max HP;
3. compute `baseMaxhp * numerator / denominator`;
4. for generations below 5, floor the amount;
5. call `Battle.heal` with target, source, and the move as source effect;
6. fail the move if healing is cancelled.

`Battle.heal` in `sim/battle.ts:2937-2971` truncates, dispatches the numeric
`TryHeal` relay, rejects a zero relay, dead/inactive/full targets, delegates to
`Pokemon.heal`, and emits the move-heal message. `Pokemon.heal` in
`sim/pokemon.ts:1647-1661` truncates again, rejects nonpositive/dead/full
targets, clamps to missing HP, mutates HP, and returns the actual healed
amount. Direct recovery consumes no PRNG.

Weather recovery is the shared Gen 4 override in
`data/mods/gen4/moves.ts` under `moonlight`, `morningsun`, and `synthesis`.
Rest and Wish are the effective callbacks in `data/moves.ts` and
`data/mods/gen4/moves.ts`, respectively. Leech Seed and Ingrain are installed
conditions in `data/moves.ts`. Ability and item behavior is flattened from
`data/abilities.ts`, `data/items.ts`, and their Gen 3 overrides.

## Native representation

Add a generation-neutral primary effect, conceptually:

```text
HEAL_FRACTION {
    basis: BASE_MAX_HP,
    numerator,
    denominator,
    rounding: GENERATION_POLICY
}
```

The generated Gen 3 rows for the four moves all reference the same operation
shape with `1/2`. The generic move-effect interpreter owns target selection,
full-HP failure, typed numeric `TryHeal` dispatch, mutation, event/effect
trace, and returned move result. `GenerationRules` or `GenerationOps` owns
fraction rounding (`floor` for Gen 3); neither the interpreter nor the data
row should mention a move ID or hard-code "half".

Do not reuse `POKEMON_HANDLER_OP_HEAL_QUARTER_MAX_HP`. That opcode is a
handler-program instruction currently used by absorption abilities, whereas
declarative primary move effects have different staging and failure behavior.
Likewise, do not reuse `POKEMON_EFFECT_DAMAGE_RELATIVE`: direct recovery has
no damage basis.

The heal trace must record requested amount, actual applied amount, fraction,
basis, source/target, source-effect move, before/after HP, and event result.
The `TryHeal` relay is numeric-or-null (not a Boolean notification), so later
generation/item modifiers and Liquid Ooze can compose at the same boundary.
Capacity/configuration failure must roll back PP, HP, events, traces, and seed
byte-for-byte.

The existing Snatch plan remains an interaction requirement. All four moves
carry the generated `snatch` flag. If no Snatch installation is reachable,
the direct moves can be enabled first; after Snatch is enabled, stealing must
fall out of the generic `PrepareHit` re-entry path without changing healing.

## Focused proof for the four-move slice

Use an odd maximum HP as the rounding witness and exercise every row. Required
focused cases are:

1. each of the four moves at partial HP heals exactly
   `floor(baseMaxhp / 2)` and consumes one PP but no PRNG;
2. clamp when missing HP is smaller than the requested amount, while tracing
   requested and actual values separately;
3. full HP fails with no HP mutation or heal event, while preserving exact PP
   and move-result semantics;
4. 1 HP remaining and odd/even maximum HP cases;
5. dead and inactive target rejection through focused injected-state tests;
6. a synthetic numeric `TryHeal` handler that reduces the relay amount, one
   that returns zero/null, and three tied handlers proving discovery/order and
   labeled handler-order draws;
7. exact event/effect-trace capacity and one-over-capacity transactional
   rollback;
8. deterministic replay from identical state, choices, and seed;
9. Snatch-flag generation for all four moves, with stolen execution added to
   the differential matrix when the Snatch condition is supported.

Tests must assert normalized action, PP, invocation/source-effect identity,
ordered `TryHeal` handler evidence, before/requested/applied/after HP, request,
canonical state, labeled draws (normally none), and final seed.

## Differential matrix and classification gate

Generate a deterministic four-row rotation rather than four hand-written
resolver cases. For every move compare against pinned Showdown at:

- ordinary partial HP with odd max HP;
- near-full clamp;
- full-HP failure; and
- replay of the same seed and choices.

Recombine at least one row with Protect on the opposing action, a switch on
the opposing action, status/residual damage before the next recovery, and
Snatch once reachable. The weather-family follow-up needs each of the three
moves under clear, sun, rain, sand, and hail, including odd-HP rounding and
weather expiry/replacement. Rest, Wish, residual healers, absorption, drain,
and items each retain the separate boundaries described above.

Only after focused tests, exact stable-boundary differential cases, inventory
validation, deterministic replay, random/Ocean regression, and sanitizers pass
may the four direct-recovery move descriptors be reclassified. No ability,
item, condition, or callback hook becomes implemented merely because it also
raises HP.
