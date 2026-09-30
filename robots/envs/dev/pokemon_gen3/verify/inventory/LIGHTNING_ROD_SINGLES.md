# Lightning Rod in Gen 3 OU singles

The effective Gen 3 ability clears the modern immunity callback and retains
only `onFoeRedirectTarget`. That callback checks the base move descriptor's
type and returns the holder as the target. Showdown dispatches
`RedirectTarget` only when `activePerHalf > 1`; the supported singles format
has exactly one active per half. The callback is therefore unreachable, while
the observable ability identity is inert.

The generator asserts the flattened callback shape, including the deliberate
base-type check that excludes Hidden Power. Native data retains ability ID 31
with no executable handler. No Lightning Rod branch exists in the kernel.

Two legal cases rotate an Electric and non-Electric attack against a Lightning
Rod holder and prove ordinary state, targeting, event, and PRNG behavior. The
focused native inventory test proves that the identity is admitted without an
attached handler. These claims are format-relative and do not apply to doubles.

Authority: pinned `data/mods/gen3/abilities.ts`, `sim/pokemon.ts`, and the
recursive mod result at revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
