# Gen 3 ordinary constant-power attack family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Executable product

The bounded family contains 17 moves:

`cut`, `dragonclaw`, `drillpeck`, `eggbomb`, `hornattack`, `hydropump`,
`megahorn`, `megakick`, `peck`, `pound`, `payday`, `rockthrow`, `slam`, `vinewhip`,
`visegrip`, `waterfall`, and `watergun`.

At the pinned revision each has positive constant base power, numeric accuracy,
critical ratio 1, priority 0, a supported target, and no nonempty secondary,
status, volatile, weather, recoil, drain, multihit, force-switch, self-switch,
variable-damage, or stateful custom callback. Pay Day's callback only emits a
protocol message and is inert at the canonical-state boundary. Their denotation is exactly the generated
`PokemonMoveData` row interpreted by the generic target, immunity, accuracy,
critical, damage, and hit pipeline. Contact, sound, bullet, slicing, distance,
and `nonsky` remain generated flags; future owner hooks consume those flags
without changing this move family.

`hypervoice` satisfies the move-shape predicate but is not executable yet.
Every legal Gen 3 learner has Cute Charm, Own Tempo, or Soundproof, none of
which is currently an admissible native ability. Admitting one only to host a
test would broaden the reachable state space with known-wrong ability
semantics, so initialization continues to fail closed for this move.

Other exclusions from the larger damaging-move inventory are semantic: high-
critical moves, self-destruct, two-turn invulnerability exceptions, variable
or fixed power, and any attached effect remain in their own families.

## Evidence

- `native/test_pokemon.c#test_generated_ordinary_attack_family` rotates all 17
  descriptors and asserts category, type, power, accuracy, PP, target,
  ordinary formula, and absence of effects and multihit.
- `verify/cases/generate-ordinary-attack-rotation.js` generates one fresh,
  legal-holder battle per descriptor. Oracle and native agree on all 32 new
  stable boundaries.
- Dragon Claw uses the established forced-critical seed. The rotation covers
  physical and special damage, 75/80/85/90/95/100 accuracy descriptors,
  `normal`, `any`, STAB, and the generic flag-bearing path.
- Rock Throw + Hard Stone, Megahorn + SilverPowder, and Dragon Claw + Dragon
  Fang close the three type-item descriptors and hooks unlocked here. Poison
  Barb, Spell Tag, Magnet, Never-Melt Ice, and Twisted Spoon remain unsupported
  because every matching Gen 3 attack has additional semantics.
- Generated data are deterministic; the full corpus agrees for 376/376 stable
  boundaries and deterministic replay.

No move identity is inspected by generic runtime control flow.
