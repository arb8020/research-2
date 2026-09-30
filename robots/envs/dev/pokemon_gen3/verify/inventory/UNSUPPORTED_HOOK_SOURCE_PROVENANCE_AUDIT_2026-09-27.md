# Unsupported event-hook source-provenance audit

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Result

All 25 currently unsupported event-hook records omit the physical Showdown
table file that defines the effective callback. Their `showdown_sources` lists
are identical generic runtime lists:

- `sim/battle.ts`
- `sim/battle-actions.ts`
- `sim/pokemon.ts`
- `sim/side.ts`
- `sim/field.ts`
- `data/mods/gen3/scripts.ts`

Those are useful dispatch and generation-runtime references, but they do not
identify the callback owner. This is a classifier provenance defect, not 25
independent documentation omissions.

The missing defining sources are:

| Defining source | Unsupported hooks |
| --- | --- |
| `data/mods/gen3/moves.ts:31` (`beatup`) | `move.beatup.onModifyMove`, `move.beatup.condition.onModifySpA`, `move.beatup.condition.onFoeModifySpD` |
| `data/mods/gen3/moves.ts:357` (`highjumpkick`) | `move.highjumpkick.onMoveFail` |
| `data/mods/gen3/moves.ts:372` (`jumpkick`) | `move.jumpkick.onMoveFail` |
| `data/mods/gen3/abilities.ts:197` (`truant`) | `ability.truant.onSwitchIn`, `ability.truant.onBeforeMove`, `ability.truant.onResidual` |
| `data/moves.ts:608` (`assist`) | `move.assist.onHit` |
| `data/moves.ts:1213` (`bellydrum`) | `move.bellydrum.onHit` |
| `data/moves.ts:3262` (`curse`) | `move.curse.onModifyMove`, `move.curse.onTryHit`, `move.curse.onHit`, `move.curse.condition.onStart`, `move.curse.condition.onResidual` |
| `data/moves.ts:4247` (`dreameater`) | `move.dreameater.onTryImmunity` |
| `data/moves.ts:11778` (`metronome`) | `move.metronome.onHit` |
| `data/moves.ts:13127` (`painsplit`) | `move.painsplit.onHit` |
| `data/moves.ts:16869` (`sleeptalk`) | `move.sleeptalk.onTryHit` |
| `data/moves.ts:17016` (`smellingsalts`) | `move.smellingsalts.onHit` |
| `data/moves.ts:19836` (`transform`) | `move.transform.onHit` |
| `data/moves.ts:19855` (`triattack`) | `move.triattack.secondary.onHit` |
| `data/abilities.ts:1425` (`forecast`) | `ability.forecast.onStart`, `ability.forecast.onWeatherChange` |
| `data/conditions.ts:364` (`mustrecharge`) | `condition.mustrecharge.onStart` |

Inheritance matters. Assist's Gen 3 override changes only flags, Forecast's
Gen 3 override changes flags, and Sleep Talk's Gen 3 override replaces
`onHit` but not `onTryHit`; therefore the listed unsupported callbacks are
physically inherited from the base table files. Conversely, Beat Up, the two
jump-kick failure callbacks, and Truant are physically replaced by Gen 3 mod
entries.

## Mechanical repair

Do not add another hand-maintained family switch to `classify.js`.
`generate.js` already builds `descriptorSources` with
`buildDescriptorSourceIndex()`, and `descriptorSource()` proves a resolved
function identity maps to exactly one physical callback definition using the
pinned TypeScript source maps. Preserve that result when callback hooks are
first extracted:

1. Make callback traversal return the hook path and callback value, rather
   than only the hook path.
2. For each function-valued hook, freeze
   `showdown_source: descriptorSource(descriptorSources, callback, identity)`
   in `gen3ou-inventory.json`.
3. Build a canonical hook-ID to frozen source lookup in `classify.js` and
   prepend that source to the existing dispatch/runtime references.
4. Treat the `onCriticalHit: false` sentinel separately. It is executable
   policy but has no function identity; locate/freeze its owning descriptor
   table source explicitly rather than pretending it is a callback function.

This makes provenance follow the resolved callback through Showdown mod
inheritance. It also fixes implemented, inert, and unreachable hooks, rather
than repairing only today's unsupported set.

## Required validation assertions

- Every function-valued frozen callback hook has exactly one
  `showdown_source` with nonempty `path` and `symbol`.
- The callback-identity source lookup remains exactly-one; zero or multiple
  physical definitions fail inventory generation.
- Every event-hook descriptor-map record includes its frozen defining source
  path in `showdown_sources`.
- Every event-hook record includes at least one defining table path matching
  `data/(mods/<mod>/)?(moves|abilities|items|conditions|rulesets).ts`; a list
  containing only `sim/*` or `scripts.ts` fails validation.
- The stored owner kind, owner ID, and nested hook path reproduce the canonical
  event-hook ID exactly, preventing provenance from being attached to a
  neighboring callback.
- Regeneration at the pinned revision is byte-deterministic and changes the
  frozen inventory digest deliberately.
- A focused regression assertion covers one Gen 3 override (`beatup`), one
  inherited base callback (`assist`), one partially overridden descriptor
  (`sleeptalk.onTryHit`), one ability override (`truant`), and one condition
  (`mustrecharge`).

Classification must remain unchanged by this repair; it strengthens source
evidence only.
