# Gen 3 OU differential regression corpus

`manifest.json` names finite choice prefixes that must remain lockstep-equivalent
to the pinned Pokemon Showdown oracle. Corpus replay stops after the final
recorded decision boundary; it never invents a suffix with the action picker.

Run the corpus with:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  python harness/diff.py --corpus regressions/gen3ou -j 1
```

Each case refers to normalized team exports in `fixtures/gen3ou`, fixes the
battle seed, records every choice through the claimed boundary, and declares
whether that boundary is terminal. Cases are deliberately compact; transient
engine/oracle dumps and the historical divergence are diagnostics and belong
under ignored `failures/`, not in this corpus.

The manifest schema is version 1 and contains `format`, the exact
`showdown_commit`, and an ordered list of unique `{name, path}` entries. A case
schema is also version 1 and contains:

- the same unique `name` used by the manifest;
- `format`, `battle_index`, `action_seed`, and four-word `battle_seed`;
- exactly two component-relative `team_files`;
- a nonempty ordered list of `[p1, p2]` choices, where a waiting side is `null`;
- `expected.terminal`, plus `expected.winner` (`p1` or `p2`) only for a terminal
  case; and
- optional human-facing `description` and `tags`.

The loader rejects stale schema versions, an oracle revision other than the
pinned commit, duplicate names or paths, paths escaping the component, invalid
choice pairs, and inconsistent terminal expectations before starting battles.

The initial corpus contains two independently revalidated switch/PRNG prefixes,
focused one-sided and simultaneous forced-replacement boundaries, and one
complete 259-boundary battle covering the longer scheduler and Struggle
endgame. Long traces should
be added only after they pass live against both the current C engine and the
pinned oracle. Prefer one maximal meaningful prefix per battle identity over
retaining every intermediate first-divergence artifact; a short case may
intentionally overlap a full trace when it isolates a load-bearing boundary.
