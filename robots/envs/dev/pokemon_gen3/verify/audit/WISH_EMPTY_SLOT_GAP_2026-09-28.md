# Wish empty-slot regression reconciliation

Pinned oracle: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The original audit incorrectly classified `test/sim/moves/wish.js:31` and
`:64` as kernel and observer gaps. Reinspection of the current native tree
shows that the generic capability already exists:

- fixed-capacity `PokemonSlotConditionState` owned by battlefield position;
- generated Future Move and Wish slot-condition policies;
- generic installation, residual discovery, duration update, execution, and
  removal;
- residual discovery that does not require a living occupant;
- Wish healing that is a no-op for a fainted occupant;
- canonical slot-condition projection in both observers.

The remaining debt was assertion-specific verification. Two legal Gen 3 OU
fixtures now prove it:

- `upstream-wish-31`: one-HP Pichu installs Wish and is KOed by Seismic Toss.
  Forced Parasect replacement resumes the suspended residual, advances Wish,
  and the following turn heals the current occupant by
  `floor(baseMaxHP / 2)` before removing the slot condition.
- `upstream-wish-64`: one-HP Vaporeon installs Wish while Skarmory establishes
  Spikes. Shedinja and then Vaporeon faint on entry, producing a terminal
  result with no Wish heal.

Both fixtures agree with the pinned oracle on normalized choices, queue and
handler observations, phase/request transitions, canonical state, condition
traces, events, terminal state, and labeled PRNG consumption.

The earlier claim that Wish rounds half HP up was also wrong. The resolved
Gen 3 implementation inherits `data/mods/gen4/moves.ts#wish`, which calls
`heal(target.baseMaxhp / 2)`; Showdown truncates that amount, matching native
`gen3_fraction()` floor division.

Authoritative boundaries: `sim/side.ts` slot-condition ownership,
`sim/battle.ts` residual handler discovery and duration staging, and
`data/mods/gen4/moves.ts#wish`.
