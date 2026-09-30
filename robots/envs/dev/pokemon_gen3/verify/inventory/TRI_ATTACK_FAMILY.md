# Tri Attack sampled-status secondary

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Tri Attack closes `move:triattack` and
`event_hook:move.triattack.secondary.onHit` without a move-identity branch.
The generated Gen 3 descriptor is an ordinary 80-power Normal physical move
whose 20% target secondary samples uniformly from burn, paralysis, and freeze.

## Semantic boundary

- `data/moves.ts#triattack` defines the secondary callback and its three
  candidate statuses; resolved Gen 3 data supplies the type-derived physical
  category.
- `sim/battle-actions.ts#secondaries` owns the secondary gate and Substitute
  interception. `ability:serenegrace` changes the gate through the resolved
  generation policy, while Shield Dust removes the target secondary through
  `ModifySecondaries`.
- `native/gen3_slice_data.c` stores the move effect and immutable candidate
  distribution. `native/pokemon.c` samples the distribution only after the
  secondary gate and Substitute boundary, then delegates to the ordinary
  status-admission transaction.
- The labeled draws are `move.secondary` followed, only when eligible, by
  `move.status_selection`. Status rejection and lethal damage still consume
  both draws; Protect, immunity, Shield Dust, failed gates, and Substitute
  stop at their respective earlier boundaries.

## Evidence

`native/test_pokemon.c#test_sampled_status_secondary_distribution` proves the
descriptor shape, all candidates, draw ownership, Shield Dust and Substitute
staging, status rejection, and fail-closed bundle validation.

`verify/cases/generate-tri-attack-cases.js` produces eleven legality-validated
fixtures covering burn, paralysis, freeze, failed base chance, Serene Grace,
Shield Dust, Substitute, Protect, Ghost immunity, an existing status, and a
lethal hit. The complete corpus matches the pinned observer at 2,893 stable
boundaries and repeats byte-for-byte for both implementations.
