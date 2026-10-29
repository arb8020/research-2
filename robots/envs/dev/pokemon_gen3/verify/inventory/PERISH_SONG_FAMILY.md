# Perish Song semantic family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Showdown boundary

The resolved Gen 3 move is a field-target callback which visits each active
Pokémon independently. Each target passes through `Invulnerability` and
`TryHit`; an admitted target receives the `perishsong` volatile only when it
does not already have it. The inherited Gen 4 condition supplies duration 4,
Residual order 12/sub-order 2, and an End callback which faints its holder.
Switching removes the volatile through ordinary volatile cleanup. The generic
battle residual/faint/request machinery owns countdown ordering, simultaneous
terminal resolution, and forced replacement.

Authoritative source:

- `data/moves.ts`, `perishsong`: field callback, per-active admission, and
  duplicate suppression.
- `data/mods/gen4/moves.ts`, `perishsong`: the condition inherited by Gen 3.
- `sim/battle.ts`, `fieldEvent`, `residualEvent`, and faint processing: ordered
  dispatch and phase/request transitions.
- `config/formats.ts`, `[Gen 3] OU`: Soundproof is banned, so its Perish Song
  interaction is not a legal differential scenario for this format.

## Native boundary

- Generated data describes the move, its HitField program, and the condition's
  Residual and End programs.
- `APPLY_VOLATILE_TO_ADMITTED_ACTIVES` is the generic field-active iteration
  operation. It delegates admission to ordinary Invulnerability/TryHit events.
- `FAINT_HOLDER` is the generic condition-owned terminal effect.
- The kernel's existing volatile lifecycle, residual queue, faint queue,
  switch cleanup, request transition, and terminal resolver perform the rest.
- The family consumes no PRNG draws.

No move-pair resolver or Perish-Song-specific kernel branch is used.

## Evidence

- Focused native test: `test_perish_song_generated_lifecycle` covers
  installation/provenance, no restart, duration, terminal draw, switch cleanup,
  fainting, and forced replacement.
- `perish-song-duplicate-simultaneous-terminal` covers installation, duplicate
  application, all countdown boundaries, ordered End handlers, and the Gen 3
  terminal draw.
- `perish-song-switch-cleanup-forced-replacement` recombines Protect admission,
  switch cleanup, continuing peer countdown, fainting, and replacement entry.
- The upstream Soundproof regression is retained as a focused constructed-state
  obligation because Soundproof is banned by the pinned Gen 3 OU format.

Inventory promotion is limited to `move:perishsong`,
`condition:volatiles.perishsong`, and its HitField/Residual/End event hooks.
