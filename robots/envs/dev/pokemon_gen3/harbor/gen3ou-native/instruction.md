# Implement the native Gen 3 OU battle interpreter

Replace the legacy move-pair resolver tree with the smallest compositional C
interpreter that conforms to the supported-feature manifest and the pinned
Pokemon Showdown `gen3ou` oracle.

Keep these ownership boundaries:

- `engine/gen3_abi.c/.h` is the self-contained native battle engine;
- generated, immutable Gen 3 data describes ordinary mechanics;
- named native handlers implement only genuinely exceptional mechanics;
- `ocean/pokemon_gen3.h` is a thin PufferLib Ocean adapter.

Normalize choices into typed actions, build and order an explicit action queue,
discover and order event handlers, execute actions independently, drain
faint/switch work, and make phase/request transitions explicit. Randomness must
be consumed by the semantic operation that owns it and reported with a stable
label in verifier builds. Do not advance guessed PRNG frames.

The submission must run complete legal battles for every required feature in
`harbor/gen3ou-native/supported-features.json`. It must expose normalized legal/forced choices,
queue and handler records, phases and requests, canonical state, labeled PRNG
draws, typed events, replacements, and terminal results to the verifier. Given
the same normalized initial state, choices, and seed, replay must be byte-for-
byte deterministic.

The production runtime may not invoke or link Pokemon Showdown, Node, Python,
or a network service. The verifier owns the pinned Showdown checkout and all
oracle instrumentation.

Passing known traces by dispatching on move pairs, species pairs, teams, seeds,
choice prefixes, or corpus identifiers is not a solution. Hidden tests
recombine mechanics and include unseen teams, seeds, and legal choice paths.

See `harbor/gen3ou-native/GRADER_CONTRACT.md` for the exact observable contract,
hard gates, score, failure artifacts, and completion definition. Canonical case
parameters and progress accounting are defined by
`harbor/gen3ou-native/case.schema.json` and
`harbor/gen3ou-native/TEST_PARAMETERIZATION.md`.
