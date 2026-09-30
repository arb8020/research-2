# Rapid Spin partial-trap cleanup

Gen 3 inherits Rapid Spin's `self.onHit` program from
`data/mods/gen4/moves.ts` at the pinned Showdown revision. After a connected
hit, that program removes the user's `partiallytrapped` volatile (alongside
other cleanup families that remain independently unsupported). The Gen 3
resolved move supplies 20 base power and the generation's type-based Physical
category.

The native generator validates those resolved facts and emits one generic
`REMOVE_VOLATILE` after-hit operation targeting the user. The kernel executes
that operation through the existing central volatile end/removal transaction;
it contains no Rapid Spin ID or name branch. Failed accuracy, immunity,
Protect, and other pre-hit exits therefore never reach cleanup.

`test_partial_trap_condition_programs` proves the generated descriptor,
central removal path, lifecycle reason, and invariants. The legal
`partial-trap-rapid-spin-cleanup` differential fixture has Smeargle install
Bind on Torkoal, then proves that a connected Rapid Spin removes the volatile
at the same canonical state and lifecycle boundary as the pinned oracle.

This evidence promotes only the Gen 3 `move.rapidspin.self.onHit` ownership
record. Rapid Spin's inherited cleanup of Leech Seed and Spikes, and its
later-generation `onAfterHit`/`onAfterSubDamage` callbacks, remain unsupported
until their own semantic products and recombinations are verified.
