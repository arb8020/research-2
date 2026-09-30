# Low Kick target-weight power

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Low Kick is the first generated target-current-species weight consumer. The
effective Gen 3 descriptor inherits `data/moves.ts#lowkick`; its
`basePowerCallback` reads `Pokemon#getWeight` and selects powers
20/40/60/80/100/120 at 10/25/50/100/200 kg. In Showdown's internal units these
are hectogram thresholds 100/250/500/1000/2000. `sim/battle-actions.ts#getDamage`
runs immunity before this callback, then critical-hit and damage-roll staging.

The native implementation does not branch on Low Kick. Generated species rows
carry immutable weight, mutable current-species identity selects the live row,
and `PokemonWeightPowerPolicy` supplies a validated monotone bracket table.
The generic `POKEMON_BASE_POWER_TARGET_WEIGHT` operation resolves power before
the ordinary BasePower event and damage calculation. Bundle validation rejects
missing, duplicate, empty, or nonmonotone policies and zero species weights
before battle mutation or PRNG consumption.

Evidence:

- `native/test_pokemon.c#test_target_weight_base_power_policy` covers both
  sides of every threshold, malformed-policy atomic rejection, and immunity
  before critical/damage draws.
- Seven legal differential fixtures `low-kick-*` cover all six powers plus
  Ghost immunity through the normal queue, state, event, and labeled-PRNG
  contract.
- The complete 2,931-boundary corpus and both deterministic replays match the
  pinned oracle.

This closes only `move:lowkick`. Weight is now canonical generated data that a
later Transform battle-profile operation can copy by changing current species
identity; no cached generation-specific weight state was added.
