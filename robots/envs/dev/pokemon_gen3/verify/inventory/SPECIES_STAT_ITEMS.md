# Species-conditioned stat items

This family is compiled from the pinned Pokémon Showdown revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0` into ordinary item-owned handler
descriptors. The generic kernel knows only the `ModifySpA`, `ModifySpD`, and
`ModifySpe` event algebras, ordered handler discovery, declarative holder
guards, and Q12 chaining.

| Item | Showdown boundary | Native descriptor | Legal differential evidence |
|---|---|---|---|
| Deep Sea Scale | `data/items.ts`, `onModifySpD`, priority 2, Clamperl ×2 | species guard + Q12 8192 | `stat-item-deep-sea-scale{,-guard}` |
| Deep Sea Tooth | `data/items.ts`, `onModifySpA`, priority 1, Clamperl ×2 | species guard + Q12 8192 | `stat-item-deep-sea-tooth{,-guard}` |
| Light Ball | `data/mods/gen3/items.ts`, special Attack only, Pikachu ×2 | species guard + Q12 8192 | `stat-item-light-ball-{special,physical-control}` |
| Macho Brace | `data/items.ts`, `onModifySpe`, ×0.5 | Q12 2048 | `stat-item-macho-brace{,-control}` |
| Soul Dew | inherited `onModifySpA`/`onModifySpD`, priorities 1/2, Lati ×1.5 | two observable format-specialized no-op callbacks; authoritative Q12 metadata 6144 | `stat-item-soul-dew-legal-noop` |

Soul Dew is not inert metadata. A legal ordinary holder causes both callbacks
to be discovered and invoked, so erasing them would violate the handler-trace
contract. Their positive predicates require base species 380 or 381; both are
banned by the resolved Gen 3 OU rule table. The OU plugin therefore preserves
the callback boundaries while compiling the predicate-positive branches to
`RETURN_UNDEFINED`. This is a claim about the resolved Gen 3 OU bundle, not
about positive Soul Dew behavior in formats where Latias or Latios is legal.

Focused native evidence is
`test_generated_species_stat_item_handlers`. It proves species guards, exact
Q12 staging, item sub-order, both Soul Dew callbacks, and that a critical hit's
defensive-stage suppression still runs the later item-owned `ModifySpD` event.
The observer patch records `ModifySpD` handler and relay boundaries, and the
nine legal fixtures agree exactly with the pinned oracle over choices, queues,
handlers, state, events, and labeled PRNG consumption.
