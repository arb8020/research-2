# Mental Herb semantic boundary

Pinned oracle: Pokémon Showdown
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Effective Gen 3 Mental Herb is inherited from `data/mods/gen4/items.ts`, not
from the modern base item. Its `Update` callback checks only for Attract, uses
the held item, and removes that volatile. It does not cure Encore, Disable,
Taunt, or Torment. Because it calls `useItem`, consumption updates `last_item`
and `used_item_this_turn` without berry or `ItemEat` semantics.

The native implementation adds three generic item-owned `Update` operations:
guard on a holder volatile, use the handler-owned held item, and remove the
holder volatile through its normal `End` event. Generated data composes those
operations for Mental Herb. Attract's inherited `onEnd` callback is represented
explicitly so handler discovery and ordering remain observable.

Focused native evidence is `test_mental_herb_use_item_transaction`.
Differential cases cover direct Attract cure, absence of Attract, same-gender
immunity, the Gen 3 Encore exclusion, Cute Charm acquisition, and Recycle of
the used item. These cases prove the use-item state transition, distinguish it
from berry consumption, and compare the complete handler sequence.

This closes `item:mentalherb`, `item.mentalherb.onUpdate`, and
`move.attract.condition.onEnd`. It adds no item-name or generation check to the
kernel.
