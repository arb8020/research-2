# Gen 3 locked-ramp family

This spike models Rollout and Ice Ball as two condition identities backed by
one generated `PokemonLockedRampPolicy`. The generic kernel knows only the
policy's move, condition descriptor, optional durationless power marker,
maximum hit count, multiplier, and refresh duration. It does not branch on a
generation, move ID, or condition ID.

## Showdown boundary

The source of truth is Pokemon Showdown revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, `data/moves.ts`:

- `onModifyMove` installs the move's volatile only when the user is awake, a
  target exists, and the volatile is absent. This occurs before accuracy.
- `basePowerCallback` multiplies by `2 ** contactHitCount`, advances both
  counters, refreshes the one-turn condition while below five hits, and
  doubles power when the user has the Defense Curl marker.
- `onLockMove` returns the condition's source move selector.
- `onResidual` removes the condition after Struggle.
- Defense Curl raises Defense and installs an independent, durationless
  marker.

The `rolloutstorage` `onAfterMove` branch is intentionally absent. The pinned
source guards it with `hitCount === 5 && contactHitCount < 5` and documents
the only producers as the later-generation Disguise and Ice Face effects.
Neither exists in the resolved Gen 3 data, so that state is unreachable in
this plugin.

## Native representation

Generated move and condition handlers use three reusable interpreter
operations: install a locked-ramp policy before accuracy, apply/advance its
base-power state, and remove it after the fallback move. Existing selector
return supplies forced-choice normalization. Condition-rule rows explicitly
declare this descriptor family repeatable; kind-only lookup rejects those
rows so first-match behavior cannot choose a descriptor accidentally.

Bundle validation rejects missing or mixed move/condition/marker descriptors,
invalid duration contracts, duplicate policy identities, and unsupported
limits before battle mutation or PRNG consumption. The ordinary move power
field is 16-bit because the fifth Rollout step has base power 480.

## Evidence

`native/test_pokemon.c` covers five-step growth and expiry, forced selector,
distinct Rollout/Ice Ball condition identity, Defense Curl multiplication,
miss expiry, invariant checks, and invalid policy bundles. Random legal play
and admission tests exercise the same generic kernel.

Six pinned-oracle fixtures cover successful five-step chains, a miss, full
paralysis, Protect, Wonder Guard, target replacement, phazing reset, Defense
Curl, exact queue/handler/lifecycle state, and labeled PRNG staging. Protect
and Wonder Guard both consume the move's accuracy draw after the locked-ramp
volatile is installed. The two later-generation `onAfterMove` hooks,
`rolloutstorage`, and its `onBasePower` hook remain explicitly unreachable in
the resolved Gen 3 plugin rather than being silently treated as implemented.
