# Oblivious and Role Play

This slice adds ability immunity and ability transfer as generic interpreter
boundaries. It does not add an Oblivious or Role Play resolver.

The authoritative flattened descriptors come from pinned Pokémon Showdown
revision `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`: `data/abilities.ts` supplies
Oblivious `onImmunity`; inherited Gen 5 ability data supplies its `onTryHit`
and `onUpdate`; `data/moves.ts` supplies Role Play `onTryHit` and `onHit`; and
`data/mods/gen3/scripts.ts` supplies the immediate post-hit `Update` phase.
`tools/generate_slice_data.js` asserts these source shapes before emitting the
resolved Gen 3 programs and owner bindings.

| Showdown semantic boundary | Native boundary | Differential evidence |
|---|---|---|
| volatile `Immunity` before `TryAddVolatile` | generic condition admission plus generated Attract guard | `attract-oblivious-immunity` |
| inherited Oblivious `TryHit` | ordered generated no-op for legal Gen 3 OU inputs | `attract-oblivious-taunt-negative` |
| ability `Update` removes Attract | generic ability-owned Update program | `attract-oblivious-role-play-update` |
| Role Play transfer admission | generated same-ability and semantic-flag guard | `role-play-same-ability-failure` |
| ability replacement | generic old-End, identity replacement, conditional new-Start lifecycle | `attract-oblivious-role-play-update` |

The positive Role Play case begins with the user attracted. It forces the
attraction action check to permit Role Play, copies Oblivious without a target
selection draw, and proves that the immediate Gen 3 `Update` removes Attract
before the foe's queued action. The same-ability case proves rejection before
accuracy or mutation. The Taunt case proves Gen 3 Oblivious does not inherit a
later-generation Taunt immunity.

Mutable ability identity is part of canonical differential state. The
generated ability descriptor carries typed `CANT_SUPPRESS` and
`FAIL_ROLE_PLAY` policy bits for transfer admission; unknown bits invalidate a
plugin. Wonder Guard remains unsupported, so this slice does not claim its
positive identity or broader semantics.
