# Gen 3 Focus Band family

The pinned `data/items.ts` implementation supplies Focus Band as an item-owned
`Damage` handler at priority `-40`. Its probability check is the first operand
of the callback's short-circuit expression, so every reached Damage event
consumes the 1/10 draw before testing lethality or ordinary-move provenance.
Only successful draws for lethal damage whose source effect is a move cap the
relay to the holder's current real HP minus one.

Generated Gen 3 data binds the item to a three-operation handler program:
labeled probability guard, ordinary-move damage-kind guard, and real-HP cap.
The generic kernel owns ordered Damage discovery, relay composition, labeled
PRNG consumption, and mutation after the relay completes. It contains no Focus
Band identity branch. Plugin ABI version 6 records the extended labeled-draw
vocabulary used by generated programs.

Focused evidence is
`native/test_pokemon.c#test_focus_band_generated_damage_gate`.
`focus-band-lethal-success`, `focus-band-lethal-failure`, and
`focus-band-nonlethal-draw` prove activation, nonactivation, handler ordering,
HP/faint consequences, and the otherwise easy-to-miss nonlethal PRNG draw.
Together they add six exact stable boundaries against Pokémon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
