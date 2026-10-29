# Gen 3 Fake Out family

Pinned Showdown keeps `activeMoveActions` as canonical mutable Pokemon state,
distinct from `activeTurns`. `sim/battle-actions.ts` resets it on switch-in and
increments it at the start of `runMove`, before `BeforeMove`. The resolved Gen
3 Fake Out descriptor in `data/moves.ts` has a move-owned `Try` callback which
returns false when that counter exceeds one. Its 100% flinch remains an
ordinary after-hit secondary.

The native kernel mirrors that boundary with `active_move_actions`. Only a
selected outer move action increments it; called moves continue through the
same move interpreter without pretending to be another selection. Switch-in
resets it. The generated Fake Out `Try` handler uses one generic conditional
return operation, while its flinch uses the existing declarative secondary
pipeline. No move ID appears in generic control flow.

Focused evidence is
`native/test_pokemon.c#test_fake_out_selected_action_counter`. It proves first
use, repeated failure without hit PRNG, and that an action canceled by
`BeforeMove` still consumes eligibility. Differential cases
`fake-out-pressure-ghost-repeat`, `fake-out-flinched-action-counts`, and
`fake-out-switch-reset` additionally prove Pressure/PP and immunity staging,
flinch-aborted action ownership, and switch re-entry reset. All evidence is
pinned to Pokemon Showdown commit
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
