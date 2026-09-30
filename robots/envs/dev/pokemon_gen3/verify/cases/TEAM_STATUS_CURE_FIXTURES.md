# Team-status-cure differential fixtures

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

## Showdown boundary

The resolved `gen3ou` move descriptors inherit both callbacks from
`data/mods/gen4/moves.ts`:

- Aromatherapy's `onHit` iterates `target.side.pokemon` in party order and
  calls `clearStatus()` on every member.
- Heal Bell's `onHit` iterates the same party and calls `cureStatus(true)` on
  every eligible member. Its Soundproof exception is unreachable in the
  resolved Gen 3 OU bundle because that ability is explicitly banned.
- `sim/pokemon.ts` makes both status-clear operations no-ops for a fainted or
  status-free Pokemon; both remove the Nightmare volatile when curing sleep.
- Both resolved descriptors target `allyTeam` and have always-hit accuracy.

These fixtures exercise the common, legal Gen 3 OU team-cure boundary without
adding an ability interaction:

- `team-cure-aromatherapy-mixed` and `team-cure-heal-bell-mixed` begin with a
  statused active Pokemon and two differently statused bench members. One move
  must clear all three in deterministic party order.
- The two `*-clean` controls prove that the move executes when no status can be
  removed and does not add move-owned PRNG consumption.

All source sets are legal in Gen 3: Smeargle obtains the cure move through
Sketch, Blissey uses Soft-Boiled, Alakazam uses Psychic, and Magikarp uses
Splash.

## Oracle evidence

Running each case through the pinned, observer-patched Showdown checkout
produced two exact stable boundaries per case (eight total). Repeating the run
was byte-identical. At the mixed-case result boundary the oracle reports three
ordered status-removal lifecycle records for slots 0, 1, and 2 and a null
status for every member. Neither cure move adds a PRNG record; the only draw is
the existing unconditional `turn.quick_claw` queue-stage draw.

Local output is intentionally left outside the commit at
`/private/tmp/pokemon-team-cure-fixtures/oracle-output/`.

## Integrated evidence

The native generator maps both moves to generated move-owned Hit programs.
Those programs call the generic team-major-status clear operation; target
resolution supplies `USER_TEAM`, and the kernel owns deterministic party-slot
iteration and the shared status-removal transaction. The focused native test is
`native/test_pokemon.c#test_team_major_status_cure_handlers`.

All four cases pass exact native/oracle comparison. The complete deterministic
replay gate passes 1,865 boundaries at the pinned revision. Inventory entries
for both moves, both inherited `onHit` callbacks, and `allyTeam` are therefore
implemented. Soundproof remains a format-ban fact, not a runtime support
claim for this bundle.
