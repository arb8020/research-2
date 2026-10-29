# Conversion 2 semantic family

Conversion 2 closes two frozen inventory records:

- `move:conversion2`
- `event_hook:move.conversion2.onHit`

The implementation is a generic response-to-last-invoked-move operation, not a
move-name branch. Gen 3 supplies the ordered candidate types, accepted type
chart multipliers, current-type policy, and Struggle catalog override through
an immutable `PokemonTypeResponsePolicy`.

## Showdown boundary

Pinned revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

- `data/mods/gen3/moves.ts#conversion2` defines candidate construction and the
  Gen 3 rule that an already-held type remains eligible.
- `data/mods/gen3/scripts.ts#useMoveInner` establishes invoked-move provenance,
  including called moves and their resolved type.
- `sim/battle-actions.ts` owns active-move modification and Hit staging.
- `sim/pokemon.ts` clears invoked-move history on switch.
- `test/sim/moves/conversion2.js` supplies the upstream semantic assertions.

`last_move_id` remains the selected outer move used by the public state. The
separate `PokemonLastUsedMove` product records the most recently invoked move
and its resolved type. A called move overwrites its caller; switching clears
the product.

## Native boundary

Generated data owns:

- the Conversion 2 descriptor and move-owned Hit program;
- the canonical Gen 3 type iteration order;
- resistant and immune multipliers;
- the Gen 3 current-type inclusion rule;
- Struggle's Normal attack-type override by catalog identity.

The generic kernel owns:

- canonical invoked-move history;
- handler discovery and move-owned Hit dispatch;
- type-chart filtering;
- one labeled `move.type_response.selection` draw, including singleton lists;
- atomic source type replacement and switch cleanup.

Malformed or incomplete policies fail during resolved-plugin validation before
battle mutation or PRNG consumption.

## Evidence basis

Focused native tests prove no-history failure, resolved Dragon history,
singleton sampling, the Gen 3 already-held Steel rule, the Struggle override,
called-move provenance, switch clearing, and plugin-validation atomicity:

- `test_conversion_2_resolved_last_move_response`
- `test_type_response_policy_validation_is_atomic`
- `test_sleep_talk_current_slot_call`

Seven legal differential fixtures prove the observable contract:

- `conversion2-dragon-singleton`
- `conversion2-normal-ghost-switch-reset`
- `conversion2-normal-rock`
- `conversion2-normal-steel`
- `conversion2-sleep-talk`
- `conversion2-struggle-torment`
- `conversion2-weather-ball`

The three Normal fixtures prove the exact filtered order
`Ghost, Steel, Rock`, rather than membership alone. Weather Ball proves use of
the resolved active type; Sleep Talk proves child invocation provenance; the
switch fixture proves history cleanup, and the Torment fixture reaches forced
Struggle legally and proves its Normal override. Together they add 25 exact
boundaries.

The complete deterministic differential corpus contains 2,592 boundaries and
matches the pinned oracle with byte-identical replay. Classification after this
family is 987 implemented, 424 inert, 37 unreachable, and 112 unsupported.

Constructing an arbitrary current type through Conversion remains outside the
supported public slice. The already-held Steel rule is nevertheless reached by
legal Aggron state in the focused native test. Forced Struggle is reached
differentially through the already-supported Torment lifecycle.
