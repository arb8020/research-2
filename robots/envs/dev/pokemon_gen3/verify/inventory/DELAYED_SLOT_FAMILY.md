# Delayed slot-condition family

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Future Sight and Doom Desire install the shared `futuremove` condition on a
battlefield position. Their Gen 3 callbacks reject a duplicate before taking a
damage snapshot, store fixed cast-time damage, and defer accuracy until expiry.
The effective `futuremove` condition removes Protect and Endure, invokes the
stored move against the current occupant, drains its faint transaction, and
checks the terminal result. Wish independently installs a duration-two slot
condition and heals half of the current recipient's maximum HP.

The native boundary is generated `PokemonSlotConditionPolicy` data consumed by
`install_move_slot_condition`, `execute_delayed_fixed_damage`, and generic
residual-slot execution. The kernel owns only fixed-capacity slot lifecycle,
payload execution, faint draining, suspension position, and request/terminal
transitions; the Gen 3 bundle owns descriptors, duration, ordering, effect
kind, accuracy, and healing ratio.

Focused coverage is `test_delayed_slot_condition_family`. Differential evidence:

- `future-sight-shared-collision-switch-protect-hit`
- `doom-desire-endure-expiry-miss`
- `wish-futuremove-coexist-switch-residual-order`
- `futuremove-fainted-occupant-no-accuracy`
- `futuremove-terminal-winner`
- `doom-desire-lethal-forced-replacement`

Together these prove shared-key rejection, cast-time snapshotting, expiry-time
accuracy ownership, Protect/Endure removal, slot ownership through switching,
Wish recipient-based healing, residual ordering, fainted-target no-draw,
delayed lethal forced replacement, residual-resume position, and terminal
winner resolution.

The inherited Wish `onEnd` guard for a fainted or empty occupant is not a
separate legal Gen 3 OU singles scenario: any nonterminal faint must be replaced
before a later residual phase, Wish order 7 precedes weather/status damage and
futuremove order 11, and a last-Pokémon faint terminates residual dispatch.
That negative callback branch is therefore unreachable under this format; the
reachable positive branch and condition removal are covered above. This is a
branch-reachability statement, not a claim about multi-active formats.
