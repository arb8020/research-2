# Mutable move-slot copy family

Pinned oracle: Pokémon Showdown `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Semantic boundary

Showdown keeps `baseMoveSlots` and `moveSlots` as distinct mutable products.
Ordinary PP use updates the shared base-backed slot. Mimic replaces only the
current slot and switch/faint restoration exposes the already-spent base slot.
Sketch replaces both products, so the copied identity and subsequently spent PP
persist through switching.

The native kernel represents that boundary with fixed-capacity current and base
move-slot arrays plus a temporary-slot mask. Generated move descriptors carry
raw PP, PP-boost policy, and Mimic/Sketch eligibility. A single generated
`COPY_TARGET_LAST_MOVE_TO_SOURCE_SLOT` program performs admission and either a
temporary-current or persistent-base replacement; the kernel contains no
Mimic- or Sketch-ID branch.

Authoritative source:

- `data/mods/gen4/moves.ts`: inherited Mimic and Sketch `onHit` callbacks
- `data/mods/gen3/moves.ts`: Gen 3 flags and inherited overrides
- `sim/pokemon.ts`: move-slot construction and switch restoration
- `sim/battle.ts`: PP calculation
- `sim/battle-actions.ts`: move-local `singleEvent('Hit')` staging

## Evidence

- `native/test_pokemon.c#test_generated_move_slot_copy_family` proves Mimic's
  `5/32` Recover slot, restoration to spent `15/16` Mimic, Sketch's `20/20`
  persistent Recover slot, subsequent PP persistence, duplicate rejection, and
  atomic rejection of an invalid generated program.
- `mimic-copy-switch-reset` and `sketch-copy-switch-persistence` prove canonical
  state, choices, queues, direct callback traces, events, and labeled PRNG
  boundaries against the pinned oracle.
- The complete differential corpus matches at 2,382 boundaries and repeats
  byte-for-byte deterministically.

The implemented inventory claim is deliberately limited to `move:mimic`,
`move:sketch`, and their `onHit` hooks. Transform remains a separate unsupported
family even though the copy operation rejects an explicitly transformed source.
