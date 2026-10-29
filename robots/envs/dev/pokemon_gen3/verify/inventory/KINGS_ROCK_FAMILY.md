# Gen 3 King's Rock family

Pinned Gen 3 Showdown implements King's Rock in
`data/mods/gen3/items.ts` as an item-owned `ModifyMove` handler. It checks a
resolved 130-move eligibility list and appends a distinct 10% flinch secondary
to the active move. The ordinary per-hit secondary pipeline owns the chance
draw. Shield Dust removes the appended secondary before that draw, while Inner
Focus rejects a successful flinch installation after the draw.

The generator converts Showdown's resolved eligibility list into one move
modifier tag and emits the King's Rock handler program. The generic kernel
guards on that tag and appends a bounded effect value to the active move frame.
Each connected hit runs the same `ModifySecondaries`, labeled chance, and
volatile-installation pipeline used by descriptor-owned secondaries. Neither
the item ID nor the 130 move IDs appear in generic control flow.

Focused evidence is
`native/test_pokemon.c#test_kings_rock_appended_secondary_pipeline`. Legal
differential cases `kings-rock-tackle-success`,
`kings-rock-tackle-failure`, `kings-rock-shield-dust`, and
`kings-rock-arm-thrust-per-hit` prove eligible success and failure, filtering
before PRNG ownership, and one secondary draw per connected multihit. The
`kings-rock-serene-grace-order` recombination uses a roll of 18 to prove that
priority -1 King's Rock appends before priority -2 Serene Grace doubles the
chance to 20%. The Arm
Thrust seed produces three hits with secondary results `30`, `28`, and `8`;
only the third succeeds. All evidence is pinned to Pokémon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
