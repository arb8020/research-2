# Pinned Showdown non-entity test census

Oracle revision: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`

This is the non-entity partition of the Gen 3 OU upstream regression audit. It
deliberately excludes `test/sim/{moves,abilities,items}`; that partition has a
separate owner. The generated census covers every `it()` or `test()` in:

- `test/sim/{choice-parser,data,decisions,dex,events}.js`;
- `test/sim/misc/**/*.js`;
- `test/sim/rulesets/**/*.js`;
- `test/sim/team-validator/**/*.js`.

Pinned Showdown contains no separate `test/sim/conditions` or formats test
directory. Condition behavior appears in `misc` and entity suites; format and
rule resolution appears in `rulesets`, `dex`, and `team-validator`.

## Result

The census has 496 unique records:

| Disposition | Count | Meaning |
|---|---:|---|
| `gen3-explicit` | 2 | The test directly constructs a Gen 3 battle. |
| `verifier-admission` | 9 | The test directly validates a Gen 3 team/format. This belongs to hermetic admission verification, not battle-kernel control flow. |
| `different-generation` | 247 | The test body explicitly selects generations, none of which is Gen 3. |
| `post-gen3-unreachable` | 13 | The named mechanic or format did not exist in Gen 3. |
| `requires-source-adjudication` | 225 | The test uses the default/current engine or has no generation anchor. It is not honest Gen 3 evidence until the assertion is checked against pinned Gen 3 source. |

This last category is an audit finding, not coverage. It prevents a generic
modern test from silently becoming a Gen 3 claim. The entity-suite audit can
resolve many such records through descriptor existence and Gen 3 override
inspection; non-entity records require explicit boundary review.

## Direct gaps

The only direct battle-runtime assertion in this partition is
`test/sim/misc/faint-order.js:26`, `Fainting > should end the turn in Gen 3`.
No exact native evidence ID was found. Existing recoil/faint fixtures cover
related boundaries, but do not port this Explosion assertion: after
Explosion's self-faint creates a forced-replacement request, the foe's queued
Substitute must not execute. Add a legal Gen 3 differential fixture and a
focused queue-drain test.

The nine direct validator assertions cover Gen 3 breeding/egg-move legality,
Pomeg Glitch Clause, Deoxys formes, and cross-generation move/ability origin.
They currently have no exact project evidence IDs. If submitted teams are
declared pre-normalized and pre-admitted, record that boundary explicitly and
run these in the verifier/oracle layer. If Harbor owns team admission, port
them as hermetic verifier tests; do not add learnset legality to the battle
kernel.

`test/sim/misc/ohko.js:38` is runtime-reachable: OHKO Clause rejects directly
submitted OHKO moves, but legal Metronome can select the effective Gen 3 OHKO
descriptors. It therefore requires a legal forced-Metronome differential plus
focused accuracy, level, HP-damage, Substitute, and Sturdy policy tests.

## Reproduction and validation

From this directory, with the pinned Showdown checkout including its installed
dependencies:

```sh
node build-core-census.js /private/tmp/pokemon-lockon-showdown . /path/to/pokemon_gen3
node validate-core-census.js core-test-census.json
```

The optional project path is used only to cross-check exact accepted-case or
differential provenance names. Similar filenames and related mechanics are not
accepted as coverage.

`core-test-census.json` is the canonical artifact. The TSV is a review-friendly
projection. The validator rejects duplicate tests, revision drift, missing
applicability evidence, missing semantic boundaries, and unscoped requested
cases. Passing this validator does not promote any supported-feature claim.
