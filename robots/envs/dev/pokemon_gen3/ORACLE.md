# Gen 3 OU correctness oracle

## Denotation of "correct"

For this environment, correct Gen 3 OU behavior means behavioral equivalence
to Pokémon Showdown's `gen3ou` implementation at the pinned revision below.
Smogon rules and mechanic documentation explain intent; Showdown is the
executable oracle used to reject engine behavior.

The comparison surface is:

1. normalized teams and complete battle snapshots;
2. legal choices at every decision boundary;
3. ordered Showdown protocol events, normalized into typed semantic events;
4. PRNG state and consumption order; and
5. terminal result.

Passing a finite differential corpus is evidence, not proof of completeness.
Every newly supported mechanic must add direct tests and expand the lockstep
corpus. Unsupported mechanics must fail explicitly without mutating state.

## Pinned oracle

- Repository: `https://github.com/smogon/pokemon-showdown.git`
- Commit: `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`
- Format: `gen3ou`

Place a checkout at `third_party/pokemon-showdown`, or set
`POKEMON_SHOWDOWN_DIR` to an equivalent checkout. Do not commit `node_modules`
or build output.

```sh
git clone https://github.com/smogon/pokemon-showdown.git \
  third_party/pokemon-showdown
git -C third_party/pokemon-showdown checkout \
  6e71625b9e6cffeda268b548ae7f43a7643fc3f0
```

Any patch needed solely to align non-semantic RNG consumption belongs in a
reviewable patch file beside this document. Such a patch must not change
observable battle behavior, and the patched tree's identity must be recorded.
