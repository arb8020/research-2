# Generated status-clause policy

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

Gen 3 OU's Sleep Clause and Freeze Clause are format rules, not properties of
sleep or freeze themselves. The resolved generation bundle therefore owns a
table of `PokemonStatusClausePolicy` records. Each record binds a generated
format handler to a proposed status and a small typed admission predicate. The
generic event kernel discovers every installed format handler, preserves
Showdown's handler-order PRNG staging, and interprets the selected predicate.

The policies deliberately retain the semantic difference in pinned
`data/rulesets.ts`:

- Sleep Clause applies only to an opposing source and blocks when a living
  teammate is asleep because of an opponent.
- Freeze Clause applies only to an opposing source and blocks whenever any
  teammate is already frozen, including a benched or fainted member.

Self/allied status attempts bypass both policies. A format without either
clause supplies an empty table. Bundle validation rejects a missing table,
duplicate status or handler identity, invalid predicate, or a policy whose
generated `SetStatus` descriptor is absent, before state mutation or PRNG use.

Focused evidence lives in
`native/test_pokemon.c#test_status_ability_hooks_and_clauses`. Differential
evidence is the `freeze-clause-*` fixture family plus the existing
`status-sleep-clause` and `sleep-clause-rest-self-sleep` cases. The Freeze
Clause fixtures prove first admission, rejection from a frozen bench member,
Natural Cure removal, and later readmission through legal Gen 3 OU teams.

