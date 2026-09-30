# Add/restart volatile transaction

Pinned oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Showdown's `Pokemon#addVolatile` owns one semantic transaction: reject a
fainted target, restart an existing condition when it has `onRestart`, run
`TryAddVolatile`, allocate and initialize state, run `Start`, and roll back a
rejected start. Gen 3 Flash Fire consumes the resulting boolean to distinguish
a first activation from the explicit immunity presentation of a duplicate.

The native boundary is therefore
`pokemon_try_add_or_restart_volatile(...) -> APPLIED | FAILED`. It delegates to
the existing fixed-capacity condition lifecycle and retains the attacking
Pokemon as source and the ability handler as source effect. Capacity and
configuration failures remain runtime errors; they are not mechanic failures.

`TRY_ADD_OR_RESTART_HOLDER_VOLATILE(kind)` exposes this transaction to a
generated, target-owned ability `TryHit` program. A following declarative
`RETURN_NULL` owns cancellation. The transaction itself only records whether
that cancellation should emit an immunity message.

Focused native tests prove first install, duplicate failure, restart success,
no duplicate allocation, restart tracing, and invariant preservation. The
native, randomized-play, Ocean, and ASan/UBSan suites pass. This boundary alone
does not classify Flash Fire: exact predicates, the volatile-owned damage
modifier, ability-loss cleanup, and Baton Pass `noCopy` semantics remain.

