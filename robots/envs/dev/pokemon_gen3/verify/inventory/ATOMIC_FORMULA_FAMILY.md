# Atomic formula family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

This slice closes Smelling Salts and Belly Drum without move-identity branches
in the generic kernel.

Smelling Salts' `basePowerCallback` is descriptor staging, not a Showdown event.
`PokemonMoveData` therefore carries a validated target-status mask and power
multiplier, applied after other descriptor-owned power formulas and before
`BasePower` event dispatch. Its ordinary `onHit` callback is a generated
status-clear program. When Substitute intercepts, the generic hit pipeline
projects Showdown's null target and does not dispatch the target callback.

Belly Drum is a generated program over one reusable atomic operation. It
requires maximum HP greater than one, current HP strictly greater than the
floored fractional cost, and room below the generation's maximum Attack stage;
only then does it pay direct HP and request enough boost to reach the cap.
Malformed operands and malformed status-power descriptors reject the resolved
bundle before battle mutation or PRNG consumption.

Focused evidence is
`native/test_pokemon.c#test_generated_atomic_formula_moves`. Differential
evidence is the three `smelling-salts-*` and four `belly-drum-*` fixtures under
`verify/cases/derived/`. They cover clean and paralyzed damage, status removal,
Substitute preservation, odd/even maximum HP, the exact half-HP rejection, and
the +6 rejection. The full corpus matches across 2,964 stable boundaries with
byte-identical native and oracle replay.
