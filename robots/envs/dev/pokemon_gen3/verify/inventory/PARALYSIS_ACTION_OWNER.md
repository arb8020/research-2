# Paralysis action owner

Pinned Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The resolved `par` condition owns `onBeforeMove` at priority 1 and cancels the
action with probability 1/4. `tools/generate_slice_data.js` asserts that source
shape, emits the chance/false-return program, and binds it to the major-status
owner. `native/pokemon.c` only performs generic status-owner `BeforeMove`
discovery and execution; it no longer branches on paralysis.

`native/test_pokemon.c#test_generated_paralysis_action_owner` proves handler
identity, priority, exactly one labeled draw, cancellation and continuation,
and byte-exact rollback when the generated chance denominator is malformed.
The legal `status-paralysis-action` differential case proves queue speed,
handler discovery, action denial, canonical state, and PRNG staging over two
exact boundaries.

This closes only `condition.par.onBeforeMove`. Paralysis speed is independently
owned by its generated `ModifySpe` handler, and the condition-level support
claim remains open until every reachable hook has evidence.
