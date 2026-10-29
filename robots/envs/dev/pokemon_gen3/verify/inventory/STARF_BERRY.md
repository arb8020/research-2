# Starf Berry semantic boundary

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The resolved Gen 3 item combines `data/mods/gen3/items.ts` residual timing
(order 10/sub-order 4, quarter-HP threshold) with inherited `data/items.ts`
`onEat` behavior. On consumption it forms an ordered candidate set of Atk,
Def, SpA, SpD, and Spe stages below +6, uniformly samples one, and applies +2
through the ordinary boost transaction. Accuracy and evasion are never
candidates. A singleton candidate still consumes one draw; an empty candidate
set consumes no draw, although the berry itself is consumed.

Generated item data supplies the eligible-stat mask and boost delta. The
generic handler interpreter filters against the generation plugin's maximum
stage, owns the labeled `item.starfberry.stat` draw, and delegates the selected
delta to the existing ChangeBoost/TryBoost pipeline. The kernel contains no
Starf or Gen 3 stat-list branch.

Focused native evidence is
`test_starf_berry_random_eligible_boost_transaction`, including all-eligible,
singleton, all-capped, stage-cap, exact-threshold, and above-threshold states.
Six differential fixtures rotate the labeled draw through all five canonical
candidates and prove the adjacent non-triggering HP value.

This closes `item:starfberry`, `item.starfberry.onResidual`, and
`item.starfberry.onEat`. The verifier-only observer patch checksum is
`f8499699a5892bad81a586f529ed14d7b4922d6dfa4d53959ef509ee0f3dafeb`.
