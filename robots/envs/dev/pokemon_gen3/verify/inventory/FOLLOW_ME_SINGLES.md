# Follow Me in Gen 3 OU singles

Pinned base move data defines `onTry` as `activePerHalf > 1`. The Gen 3 mod
inherits that callback, replaces the volatile with a slot condition, and
overrides the redirect handlers. In the supported singles format
`activePerHalf` is one, so the move always rejects at `Try` after ordinary PP
deduction. It consumes no accuracy draw and installs no slot condition.

Native generation data binds the move-owned `Try` descriptor to the existing
`RETURN_FALSE` program. The generic move interpreter owns PP staging and the
rejection. No Follow Me identity appears in generic control flow.

`follow-me-singles-try-rejection` proves request, queue, handler, state, event,
and labeled-PRNG equality. The focused native test proves PP-before-`Try`, the
absence of a hit or slot-condition installation, and invariant preservation.
The slot condition and its `onStart`/`onFoeRedirectTarget` hooks remain
unreachable under the explicit singles topology.

Authority: pinned `data/moves.ts` plus `data/mods/gen3/moves.ts`, revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
