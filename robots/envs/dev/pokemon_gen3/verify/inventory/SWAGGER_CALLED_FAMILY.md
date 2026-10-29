# Swagger through legal called-move entry

Oracle: pinned Pokemon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`, effective `gen3ou` dex.

Swagger is banned from direct Gen 3 OU team submission, but it remains part of
the executable move catalog because legal Metronome can select it. The native
format validator continues to reject submitted Swagger sets; this closure is a
runtime claim reached only through the generic called-move boundary.

The effective descriptor is inherited from `data/moves.ts` with Gen 3's
90-percent accuracy resolved through `data/mods/gen6/moves.ts`. It is an
ordinary status move whose ordered primary product is target Attack +2 followed
by confusion installation. No Swagger-specific resolver is required: generated
data emits `BOOST(ATK,+2)` and `ADD_VOLATILE(confusion)` and the generic effect
interpreter preserves their order.

Four legal Metronome fixtures prove the observable closure:

- successful selection, accuracy, confusion duration, and later self-hit;
- accuracy failure before either primary operation;
- Own Tempo rejecting confusion while the preceding Attack boost remains;
- Safeguard rejecting confusion while the preceding Attack boost remains.

The focused C test additionally proves the generated descriptor shape and that
a capped Attack boost does not suppress the independent confusion operation.
The verifier-only observer labels the base Metronome sampling call used by Gen
3; the previous observer labeled only the Gen 4 override and was incomplete.

Evidence consists of `native/test_pokemon.c#test_flatter_ordered_primary_effects`,
the four `metronome-swagger-*` differential cases, exact labeled PRNG traces,
and the pinned source revision above. Only `move:swagger` is promoted by this
slice. The separate format-rule/admission record remains governed by admission
evidence and is not inferred from runtime execution.
