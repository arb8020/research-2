# Lansat Berry semantic boundary

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The resolved Gen 3 item has two effective callbacks:

- `data/mods/gen3/items.ts`: `Residual`, order 10/sub-order 4, consumes the
  berry at or below one quarter of maximum HP.
- inherited `data/items.ts`: `ItemEat` attempts to add `focusenergy`.

Consumption remains the existing generic held-berry transaction in
`native/pokemon.c`: `ItemEat` runs while the item is still installed, then the
item moves to `last_item_id` and the consumed-item flags are updated. The new
generated item descriptor supplies `add_volatile_kind = FOCUS_ENERGY`; the
generic handler interpreter performs the existing add-or-restart volatile
transaction with an item source effect. Focus Energy has no `Restart`
callback, so an already-present instance is unchanged even though Lansat is
still consumed.

Focused native evidence is
`test_lansat_berry_volatile_transaction`. Differential cases cover the exact
quarter threshold, the adjacent non-triggering HP value, and consumption after
Focus Energy was installed earlier in the same turn. Existing critical and
switch-cleanup cases remain the downstream evidence for Focus Energy itself.

This closes `item:lansatberry`, `item.lansatberry.onResidual`, and
`item.lansatberry.onEat`. It adds no item-name or generation check to the
kernel.
