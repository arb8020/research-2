# Parameterized upstream-test completeness audit

> Historical structural audit. Its 1,174/282 estimates were superseded by the
> instrumented Mocha registration census: 2,172 registered tests, 196 dynamic
> expansions, and 41 applicable dynamic variants. Use
> `runtime-registration-census.json` and `REGRESSION_MAP_COMPLETENESS_PROOF.md`
> for current counts. The analysis below is retained as provenance for the
> first loop-expansion audit.

Pinned Pokémon Showdown revision:
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.

The canonical `gen3ou-test-map.json` contains one row per static `it()` or
`test()` declaration. This report audits declarations registered repeatedly by
top-level loops. It does not change any support classification.

## Enumeration method

1. Parse every JavaScript file below pinned `test/sim` with the pinned
   TypeScript parser.
2. Find every `it()` or `test()` call lexically nested in a `for`, `for..of`,
   or `for..in` statement.
3. Resolve the finite top-level arrays/objects used by those loops and count
   the Mocha tests registered when each file loads.
4. Intersect those sites with the entity, core, and supplemental partitions
   used by `gen3ou-test-map.json`.
5. Adjudicate each expanded value against the resolved Gen 3 Dex and Gen 3 OU
   singles rules. A modern value in an otherwise relevant parameter table is
   not Gen 3 evidence.

The AST scan found 58 parameterized declaration sites under `test/sim`. Eight
belong to post-Gen-3 item files (`items/drives.js` and `items/plates.js`) that
are outside the frozen Gen 3 entity partition. The remaining 50 mapped
declarations register 171 runtime tests, or 121 more instances than
their 50 static rows. The bounded map therefore represents 1,174 runtime test
instances, not 1,053, when parameter expansion is counted.

Of the canonical map's 248 applicable static declarations, parameter expansion
adds 30 applicable Gen 3 instances. The instance-level applicable count is
therefore 281. This is an accounting refinement, not 30 newly supported
features: sibling instances often exercise the same semantic operation with a
different move descriptor.

## Gen 3-applicable expansions

### Generic trapping moves

`test/sim/misc/trapmoves.js` declares tests inside:

```text
Block, Mean Look, Spider Web, Thousand Waves, Anchor Shot, Spirit Shackle
```

Only Block, Mean Look, and Spider Web exist in Gen 3. Three applicable
assertion declarations expand across those three moves:

- line 16: normal switching is forbidden;
- line 28: move-driven switching remains possible;
- line 52: trapping ends when the source leaves the field.

These are nine applicable instances rather than three rows, adding six. The
Ghost trapping-immunity assertion at line 40 is modern semantics; line 67 is
Doubles-only; line 92 explicitly runs Gen 4.

The runtime census maps all three source moves to their descriptor-rotation
fixtures and the shared focused source-link test. Block has a direct
source-departure differential; Mean Look and Spider Web combine their own
binding fixture with that shared cleanup proof. Each of the three Baton Pass
instances now has a legal descriptor-specific differential proving
move-driven switching through the trap.

### Partial trapping moves

The partial-trapper table is:

```text
Bind, Clamp, Fire Spin, Infestation, Magma Storm, Sand Tomb, Whirlpool, Wrap
```

Infestation and Magma Storm postdate Gen 3. The other six moves expand four
applicable assertions:

- line 131: normal switching is forbidden;
- line 143: move-driven switching remains possible;
- line 167: trapping ends when the source leaves;
- line 182: Rapid Spin removes the relation.

These are 24 applicable instances rather than four rows, adding 20. The
default-generation 1/8 residual assertion at line 120 conflicts with Gen 3's
1/16 residual and is correctly generation-different. The Ghost immunity test
at line 155 is also modern semantics.

The runtime census rotates every Gen 3 partial-trapping descriptor through its
own installation/source-departure fixture and maps Rapid Spin through the
shared `partiallytrapped` identity. The six Baton Pass instances now also have
descriptor-specific differentials. Descriptor rotation remains necessary
because shared kernel evidence alone does not prove every generated binding.

### Rollout and Ice Ball

`test/sim/moves/rollout.js` runs every declaration for both Ice Ball and
Rollout. Four applicable declarations at lines 18, 42, 72, and 100 therefore
represent eight instances, adding four:

- five-step power progression and reset;
- miss reset;
- immobilization reset;
- Defense Curl doubling.

Required evidence should name both moves. One shared focused lifecycle test is
appropriate, but differential rotation must include both descriptor bindings.
Parental Bond and the Gen 7 storage-glitch assertions remain post-Gen-3.

## Expanded but not Gen 3 battle obligations

- `test/sim/data.js:388` registers nine generation-count tests, including one
  Gen 3 instance. It checks Showdown's JS data-table census, not the native
  battle observable contract. The native catalog census is the analogous
  verifier proof; it should not be called a battle differential.
- `test/sim/data.js:411` registers four later-mod census tests.
- Nineteen declarations in `test/sim/decisions.js:756-1207` run for both
  `revoke` and `override`. Undo/override is not exposed by the native ABI;
  shift, double-switch, and team-preview variants are additionally unreachable
  in Gen 3 OU singles.
- `test/sim/misc/ateabilities.js` expands two declarations over four
  post-Gen-3 abilities.
- `test/sim/misc/typechange.js` expands five declarations over
  Trick-or-Treat and Forest's Curse, both post-Gen-3.
- `test/sim/moves/curse.js:229` expands over three Triples positions and is
  format-unreachable.

## Map recommendation

The runtime-registration census remains keyed by source declaration and stores
one variant row per resolved loop instance:

```json
{
  "parameters": {"move": "block"},
  "resolved_name": "Trapping Moves > Block > should prevent ...",
  "applicability": "g3_source_applicable",
  "evidence": {"native_units": [], "differential_cases": []},
  "required_case": "trap-block-normal-switch"
}
```

Its validator now enforces 33 trapping instances and proof for all 33,
including the nine Baton Pass instances. The broader
canonical map still reports declaration-level evidence, so completeness claims
must continue to distinguish “1,053 static declarations / 1,174 runtime
instances; 248 applicable declarations / 278 applicable instances.”

## Uncertainty

This audit covers direct `it()`/`test()` calls nested in finite loop statements.
It found no `it.each` usage. Helper functions that register tests indirectly,
dynamic imports, or future upstream registration patterns would require a
Mocha discovery run or instrumentation of the test globals. The safest final
completeness proof is to capture Mocha's discovered test-name list at the
pinned revision and reconcile it against expanded map keys.
