# Spite PP-mutation family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Spite is the first generated target-PP mutation. The move descriptor remains an
ordinary 100-accuracy status move; one generated `Hit` program performs a
uniform labeled draw in `[2, 6)`, resolves the target's current slot matching
its canonical `last_move_id`, and deducts that many PP with a zero floor.
Missing history, a missing current slot, and an already-empty slot cancel the
effect, but only after the draw. Protect and accuracy retain ownership of their
earlier gates, while Substitute is bypassed by the resolved Gen 3 descriptor.

This boundary follows `data/mods/gen3/moves.ts` for Spite's callback and
descriptor, `sim/pokemon.ts` for `deductPP`, and `sim/battle-actions.ts` for
selected-move history. It is represented natively by the generic
`DEDUCT_TARGET_LAST_MOVE_PP_UNIFORM` handler operation rather than a Spite
resolver or a move-pair branch.

`test_spite_target_last_move_pp_transaction` proves ordinary deduction,
draw-before-failure staging, zero-floor clamping, base/current PP alignment,
handler discovery, and battle invariants. The legal
`spite-pressure-pp-lifecycle` differential fixture recombines Spite with
Pressure and repeated Heal Bell use. It proves the first deduction and a later
clamped deduction through the public state/trace contract. The complete corpus
matches the pinned oracle at 2,606 boundaries with deterministic replay.

The upstream Spite regression tests target later-generation PP amounts and do
not directly establish Gen 3 behavior. They remain mapped as non-applicable;
the support claim rests on the pinned Gen 3 source, focused native test, and
the independent differential fixture above.
