# Current-slot type overlays

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Camouflage and Conversion share one semantic boundary: a move-owned `Hit`
program replaces the user's mutable effective-type product without changing
immutable species types. Generic switch cleanup restores the species product.

Camouflage resolves through `data/mods/gen4/moves.ts` in Gen 3 and supplies the
literal Normal type as generated data. It fails when the holder already has
Normal as either current type. Conversion follows `data/mods/gen3/moves.ts`:
it reads current mutable move slots, excludes Curse and types the holder
already has, preserves duplicate-slot weighting, fails without a draw when no
candidate exists, and samples even a singleton through the labeled
`move.type_selection` owner draw.

The kernel contains no Camouflage or Conversion identity branch. Generated
programs invoke a literal replacement operation or a current-slot type
sampler. `test_current_move_slot_type_overlays` proves literal replacement,
switch restoration, multiple weighted candidates, empty-set failure, and draw
staging. The legal `camouflage-normal-switch-reset` and
`conversion-current-slot-types` cases add five exact pinned-oracle boundaries.

The complete differential corpus and replay gate must remain exact before this
family is treated as integrated. These four records do not by themselves
claim Transform or Forecast; they establish the mutable type-overlay boundary
those later families can reuse.
