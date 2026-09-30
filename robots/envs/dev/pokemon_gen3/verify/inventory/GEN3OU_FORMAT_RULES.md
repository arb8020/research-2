# Gen 3 OU format-rule boundary

Oracle: Pokemon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, format
`gen3ou`. This classifies the 42 effective entries frozen in
`gen3ou-inventory.json`; it does not treat every `RuleTable` entry as battle
mechanics.

## Result

Showdown has two distinct extension points:

- `ValidatorRule` rejects or normalizes a submitted team before battle.
- `Rule` participates in battle through the ordinary event system or changes
  battle/protocol policy.

For Gen 3 OU, 35 entries are validation or rule-table composition. Seven are
battle-facing, but only four change canonical battle evolution: Sleep Clause,
Freeze Clause, switch priority, and Endless Battle Clause. HP Percentage, Cancel,
and Beat Up Nicknames change protocol/presentation rather than canonical battle
state.

| Frozen entries | Boundary | Current `PokemonSet` sufficiency | Typed predicate / policy |
|---|---|---|---|
| `-ability:sandveil`, `-ability:soundproof` | set validation | yes | banned descriptor ID |
| `-item:brightpowder`, `-item:laxincense` | set validation | yes | banned descriptor ID |
| `-move:acupressure`, `-move:assist`, `-move:doubleteam`, `-move:minimize`, `-move:swagger` | set validation | yes | banned descriptor ID |
| `-pokemontag:uber` | set validation | yes, with generated species tag | banned descriptor tag |
| `-nonexistent`, `-pokemontag:unobtainable`, `-unreleased` | set validation | IDs are present; generated existence/release/obtainability metadata is missing | banned descriptor tag |
| `Baton Pass + Block`, `Baton Pass + Mean Look`, `Baton Pass + Spider Web` | set validation | yes | same-set conjunction of move IDs |
| `Smeargle + Ingrain` | set validation | yes | same-set conjunction of species and move IDs |
| `Huntail + Shell Smash + Sucker Punch` | validation inherited from generic Obtainable Moves; unreachable in Gen 3 data | yes syntactically; source-generation legality data missing | same-set conjunction, retained as oracle provenance rather than a Gen 3 runtime feature |
| `Hypnosis + Gengarite` | validation inherited from Sleep Clause; unreachable in Gen 3 data | yes syntactically; item absent | same-set conjunction, retained as oracle provenance |
| `accuracytrapclause` | set validation | yes, once move/ability semantic tags are generated | conjunction of guaranteed accuracy drop and trapping effect |
| `oneboostpasserclause` | team validation | yes, once effect tags are generated | per-set Baton Pass + boost-source cardinality, then team cardinality |
| `speedpassclause` | team validation | yes, once effect tags are generated | Baton Pass + speed-boost-source conjunction |
| `speciesclause` | team validation | yes, with generated base-species/number | uniqueness by base species number |
| `nicknameclause` | team validation | **no**: nickname is absent | uniqueness by normalized nickname, excluding the base-species name |
| `ohkoclause` | set validation | yes, with generated move tag | any move tagged OHKO |
| `evasionitemsclause`, `evasionmovesclause` | rule-table composition plus set validation | yes | expand to the frozen item/move bans above |
| `evlimit` | set validation | yes, in the normalized admission input | generated six-stat vector policy; each EV is `0..255` and sum(EVs) <= 510 |
| `obtainablemoves` | set validation | IDs are present; learnset/source/event relations are missing | species/set-to-move legality relation |
| `obtainableabilities` | set validation | yes, in the normalized admission bundle | generated compressed-row species-to-ability legality relation |
| `obtainableformes` | set validation | IDs are present; forme/base/change constraints are missing | forme legality predicate |
| `obtainablemisc` | set validation/normalization | partial: EVs are normalized for the implemented EV-limit boundary; IVs, nature, happiness, shiny, Pokeball, Hidden Power choice, nickname, and event/source facts are absent | duplicate moves plus remaining typed set-metadata and event/source predicates |
| `obtainable` | rule-table composition plus validation | not by itself; expands to the preceding legality families and nonstandard bans | aggregate legality policy |
| `standardag`, `standard` | rule-table composition | n/a | named aggregate expanded before runtime |
| `sleepclausemod` | battle runtime (`onSetStatus`) plus one unreachable complex ban | yes: major-status state records source ownership and the resolved format policy enables source-aware admission | reject foe-inflicted sleep if a living foe is already asleep from an opponent; permit self-inflicted Rest |
| `freezeclausemod` | battle runtime (`onSetStatus`) | **no in current mutable state**: freeze is absent from `PokemonStatus` | reject foe-inflicted freeze if any teammate is already frozen |
| `switchpriorityclausemod` | battle runtime queue policy | yes | order simultaneous switches by effective Speed (then normal tie policy) |
| `endlessbattleclause` | battle runtime terminal policy | **no currently demonstrated equivalent**; requires the battle's stale/endless bookkeeping | typed terminal rule, not a validator predicate |
| `hppercentagemod` | output/presentation policy | canonical state is sufficient | render public HP as percentage; no state mutation |
| `cancelmod` | request/choice protocol policy | outside the current simultaneous Ocean `step` contract | permit replacing an uncommitted choice |
| `beatupnicknamesmod` | output/information policy; move behavior is in Gen 3 move override | **no** nickname field, but the native ABI need not reveal names | suppress party-member identity in Beat Up messages |

## Authoritative symbols and tests

- Format declaration: `config/formats.ts`, `[Gen 3] OU`.
- Gen-specific aggregate: `data/mods/gen3/rulesets.ts`, `Rulesets.standard`.
- Rule implementations: `data/rulesets.ts` symbols named by the normalized IDs
  above (`accuracytrapclause`, `oneboostpasserclause`, `speedpassclause`, etc.).
- Ban expansion, inheritance, complex bans, tag rules, and numeric values:
  `sim/dex-formats.ts`, `RuleTable`, especially `check`, `addComplexBan`, and
  `resolveNumbers`.
- Admission execution: `sim/team-validator.ts`, `validateTeam`, `validateSet`,
  `validateStats`, `checkCanLearn`, and the descriptor checks around
  `RuleTable.check`.
- Focused battle tests present upstream:
  `test/sim/rulesets/sleepclausemod.js` and
  `test/sim/rulesets/endlessbattleclause.js`.
- Gen 3 learnability/event regression coverage present upstream:
  `test/sim/team-validator/breeding.js`; general validator behavior is covered
  by `basic.js`, `custom-rules.js`, `events.js`, `formes.js`, and `misc.js`.
- Freeze Clause, switch priority, Accuracy Trap, One Boost Passer, Speed Pass,
  and the exact Gen 3 OU expanded manifest do not have equivalently named
  focused upstream files at this revision. Native focused and differential
  tests should therefore be added rather than inferred from the inventory.

## Minimal generation-neutral native shape

Do not copy Showdown's string-keyed `Map` or callback surface into the hot path.
Resolve inheritance during generation and emit a closed manifest:

```c
typedef struct {
    uint8_t min_team_size, max_team_size, max_moves;
    uint8_t min_level, max_level, default_level;
    uint8_t ev_limit_enabled;
    uint16_t ev_limit;
} PokemonFormatLimits;

typedef struct { PokemonDescriptorKind kind; uint16_t id; } PokemonBan;

typedef struct {
    uint8_t component_count;
    PokemonBan components[3];
    uint8_t limit; /* zero for every current Gen 3 OU complex ban */
} PokemonSetConjunctionBan;

typedef enum {
    POKEMON_TEAM_UNIQUE_BASE_SPECIES,
    POKEMON_TEAM_UNIQUE_NICKNAME,
    POKEMON_TEAM_ONE_BOOST_PASSER,
    POKEMON_TEAM_NO_SPEED_PASSER,
} PokemonTeamPredicateKind;

typedef enum {
    POKEMON_RULE_SLEEP_CLAUSE,
    POKEMON_RULE_FREEZE_CLAUSE,
    POKEMON_RULE_SPEED_ORDERED_SWITCHES,
    POKEMON_RULE_ENDLESS_BATTLE,
    POKEMON_RULE_PERCENT_HP_OUTPUT,
    POKEMON_RULE_CANCEL_UNCOMMITTED_CHOICE,
    POKEMON_RULE_HIDE_BEAT_UP_IDENTITIES,
} PokemonBattleRuleKind;
```

The format manifest should contain spans of atomic bans, same-set conjunctions,
team predicates, stat-vector policies, and battle-rule IDs, plus a reference to
generated generation legality data. Optional numeric policies use an explicit
presence field rather than overloading zero. The generic validator evaluates
those typed records. The generic
battle engine exposes stable event/queue/terminal hooks; the generation plugin
supplies their ordered rule descriptors. Aggregates (`standard`, `obtainable`,
evasion clauses) should not survive generation as executable records.

This follows Showdown's useful abstraction—the format composes validator rules
and battle rules—while replacing its dynamic callback/string machinery with
fixed-capacity typed data suitable for C and Ocean.
