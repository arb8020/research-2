# Nature Power: fixed move delegation

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Resolved Gen 3 Nature Power is a 95%-accurate self-targeting status move whose
`onHit` calls Swift against the original target
(`data/mods/gen3/moves.ts:447`). The parent owns choice normalization, PP, and
its Gen 3 accuracy check. The child is a new move invocation: it owns targeting,
protection, hit resolution, damage, effects, and trace provenance, but does not
deduct Swift PP. Fixed delegation consumes no move-selection PRNG.

This is represented by generated owner data containing
`POKEMON_HANDLER_OP_CALL_FIXED_MOVE`, interpreted by the generic kernel. The
kernel contains no Nature Power or Swift branch. The operand is validated with
the resolved generation bundle before mutation or PRNG consumption.

## Evidence

- Generated source: `tools/generate_slice_data.js` validates the resolved
  descriptor and emits the Nature Power owner binding and Swift operand.
- Kernel: `native/pokemon.c` validates and executes the generic fixed-call
  operation using the ordinary called-move path.
- Focused test: `test_generated_fixed_move_delegation` proves parent-only PP,
  child provenance, exact accuracy staging, no selection draw, protection, and
  atomic rejection of an invalid operand.
- Differential case: `nature-power-fixed-swift-protect` proves the complete
  observable boundary against the pinned oracle.
- Feature claim: `move.fixed-delegation` is deliberately narrower than general
  random, moveset-selected, copied-slot, or dynamically constructed moves.

Passing this slice does not claim Assist, Metronome, Mimic, Sketch, or Sleep
Talk. Those need distinct candidate-set or moveset-mutation capabilities.
