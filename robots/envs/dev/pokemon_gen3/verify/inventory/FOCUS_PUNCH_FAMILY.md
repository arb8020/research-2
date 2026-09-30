# Focus Punch prepared-action family

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Gen 3 inherits the Gen 4 Focus Punch override. A synthetic order-5 pre-turn
action installs a one-turn condition before ordinary switches and moves. The
condition marks itself invalid after a non-status hit, rejects flinch
admission, and the move's later `Try` handler cancels execution when marked.
Ordinary and Pressure PP deduction precedes that `Try` handler in Gen 3.

Native boundaries:

- `native/gen3_slice_data.c`: generated move descriptor, condition identity,
  ordered handler descriptors, effect programs, and owner bindings.
- `native/pokemon.c`: generic pre-turn action queueing, fixed-duration volatile
  lifecycle, category guard, typed counter payload, target-owned Hit dispatch,
  volatile-admission cancellation, and null-result move cancellation.
- `native/test_pokemon.c#test_focus_punch_prepared_action_lifecycle`: focused
  damage interruption, PP staging, status non-interruption, successful hit,
  handler counts, PRNG ownership, expiry, and invariant checks.

Differential evidence:

- `focus-punch-interrupted-pp-spent`
- `focus-punch-status-hit-succeeds`
- `focus-punch-substitute-interception`
- `focus-punch-preparation-before-switch`
- `focus-punch-fake-out-interruption`

The observer exposes preparation lifecycle, `lostFocus` as a typed boolean
counter, ordered `Hit` and `TryAddVolatile` discovery, and the move-local `Try`
callback. The five fixtures match pinned Showdown across 11 stable boundaries.
Substitute interception deliberately suppresses target-owned `Hit` discovery;
this is a generic target-null semantic correction, not a Focus Punch branch.

These cases prove exactly `move:focuspunch`,
`condition:volatiles.focuspunch`, and its `onStart`, `onHit`,
`onTryAddVolatile`, and move `onTry` hooks. They do not widen any other
supported claim.
