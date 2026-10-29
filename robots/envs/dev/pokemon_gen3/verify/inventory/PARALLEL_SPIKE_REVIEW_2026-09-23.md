# Parallel semantic spike review — 2026-09-23

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Side-condition lifecycle: Reflect and Light Screen

The isolated spike confirmed that installation, duplicate rejection, residual
expiry, side ownership, switch persistence, category filtering, and critical
bypass are the semantic boundary. Its prototype moved the current
Reflect/Light Screen enum branches into a `PokemonConditionRule` damage-policy
field.

That prototype is **not integrated**. It removes move-name branching, but it
would create a second condition-specific damage-dispatch mechanism beside the
ordered handler interpreter. The smaller long-term abstraction is generated
side-owned damage handlers with reusable category and critical guards plus the
existing Q12 relay. The source audit and proposed lifecycle/category/critical,
dual-screen, and Brick Break fixtures are retained as the merge plan for that
change.

Spike worktree/commit:
`/private/tmp/pokemon-sideconditions-light-screen-reflect-20260923`,
`9f43f68d8d8a72a02db29852157b7c49e8f83e65`.

## Partial trapping and request legality

The isolated audit confirmed one generic source-bound condition shared by
Bind, Clamp, Fire Spin, Whirlpool, and Wrap: uniform duration 3–6, residual
order/sub-order `10/9`, switch restriction while the recorded source remains
active, max-HP residual damage, and cleanup without damage when that source is
inactive. The existing kernel already implements that boundary and its exact
differential rotation.

Only the reusable invariant tightening was integrated: a serialized partial
trap must have a nonzero duration within its generation-owned rule and an
unused zero counter. No ABI, generated-data, observer, ID-map, or
classification change was needed. Future source-bound families may justify a
typed source-liveness policy; one family does not.

Spike worktree/commit:
`/private/tmp/pokemon-partial-trap-lane2`,
`b37b4d20e86a6b4d1fc9b1c41d985518a5d58f41`.

## Status lifecycle prerequisite and Rest

The integration worktree now resolves sleep `Start`, `BeforeMove`, and
`SwitchIn` as generated status-owner data. Generic lifecycle operations own
the labeled uniform duration draw, decrement/wake transition, sleep-usable
skipped-turn accounting, and switch restoration. Early Bird is a generated
operand and Snore is declarative move data plus a generated status guard; the
kernel names neither mechanic. The full 1,498-boundary corpus, deterministic
replay, sanitizer, random-play, Ocean, generator, and oracle-smoke gates pass.
The sleep condition, all three lifecycle hooks, Snore, and Early Bird are now
classified from focused and legal differential evidence.

The isolated Rest spike confirms the next merge order: add an explicit
`EMPTY_ONLY | REPLACE_DIFFERENT` status transaction policy, then generated
Rest `TryMove`/`Hit` programs over generic status replacement, counter write,
and max-heal operations. It must not introduce a Rest branch. The spike is
retained as design evidence and is not itself a support claim.

Spike worktree/commit:
`/private/tmp/pokemon-rest-semantic-family`, `4b2e30d`.

## Synchronize

The isolated Synchronize prototype establishes a reusable generated
`AfterSetStatus` reflection operation: allowed-status mask, generated
toxic-to-poison mapping, source/owner relation guard, and nested ordinary
status transaction. It contains no ability-name branch and proves burn,
toxic normalization, sleep exclusion, natural immunity, and occupied-source
rejection with legal pinned-oracle fixtures.

It is intentionally queued after Rest/status replacement stabilization.
Nested mutation and `AfterSetStatus` ordering (including Lum Berry priority
`-1`) make premature integration the higher-risk order.

Spike worktree/commits, in order:
`/private/tmp/pokemon-synchronize-spike`, `aaf653f`, then `9e8e61d`.
