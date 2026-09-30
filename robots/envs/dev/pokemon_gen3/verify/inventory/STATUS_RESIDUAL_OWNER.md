# Major-status residual owner family

Pinned Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The resolved Gen 3 burn, poison, and Toxic conditions inherit order 10,
suborder 6 residual callbacks. Burn and poison deal one eighth of base maximum
HP. Toxic increments a capped stage before dealing
`floor(baseMaxHP / 16) * stage`, and its stage resets when the holder switches.

`tools/generate_slice_data.js` asserts those effective callback shapes and
emits one immutable status-residual product per canonical condition descriptor:
damage formula plus `STATELESS`, `TICK`, or
`ESCALATE` state policy. The generic residual queue and
executor now select by installed descriptor; they contain no burn, poison, or
Toxic branch tree.

`native/test_pokemon.c#test_generated_status_residual_policy_family` proves
generated identities, 301-HP floor rounding, order/suborder, Toxic stage-15
cap and 401-HP damage, and pre-mutation bundle rejection for duplicate policy
products. Existing Toxic switch/reset and residual-KO tests continue to prove
stage reset, fainting, and forced replacement.

The observer and native projection now expose residual discovery, damage, and
execution symmetrically for all three statuses. Legal fixtures
`direct-heal-burn-residual`, `status-primary-rotation`, `toxic-ramp`, and
`toxic-switch-reset` prove ordering and state transitions. This promotes the
three `onResidual` hooks and closes the ordinary-poison condition descriptor
using its existing installation, immunity, state, and residual evidence.
Unproven callback rows remain independently unsupported.
