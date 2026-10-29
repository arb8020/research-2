# Gen 3 differential harness

The current vertical slice grows mechanics only behind an executable oracle:

1. Load an explicit team pair or deterministically sample the checked-in pool.
2. Parse and validate exactly six Pokemon per side with Showdown's `gen3ou`
   validator.
3. Derive one canonical `TeamSpec`; send its packed form to Showdown and its
   fixed-width numeric form to the native C ABI.
4. Compare initial private state and legal choices after every supported
   decision boundary.
5. Stop at the first unsupported semantic fact and write a replayable case.

The native slice supports simultaneous switches for the deliberately inert
fixture ability set, mixed switch/Seismic Toss and switch/Protect turns, and a
bounded Ice Beam/Earthquake standard-damage exchange. Proc outcomes and teams
whose abilities create switch-time effects are reported as unsupported without
mutating native state. Standard Ice Beam can also target an unequal-speed
switch-in, and supported switch turns apply Leftovers in Showdown order.
Explosion additionally exercises self-fainting and an asymmetric forced-switch
request before residual processing resumes.
Protect activation/blocking and Toxic status/residual/Natural Cure behavior are
also part of the typed lockstep surface. Leech Seed volatile state, start
events, switch clearing, and residual drain/healing are included in ABI v12,
along with battle stat stages and typed boost/unboost events.

Run the deterministic pool:

```sh
python harness/diff.py --battles 1 -j 1 --seed 42
```

Generated runs continue until a terminal boundary or the first divergence and
write `failures/first-divergence.json`. Replay one and continue frontier
discovery with:

```sh
python harness/diff.py --case failures/first-divergence.json -j 1
```

Run the checked regression corpus with:

```sh
python harness/diff.py --corpus regressions/gen3ou -j 1
```

Corpus cases are named finite prefixes. They stop exactly after their last
recorded choice and never synthesize a suffix with the seeded action picker.
This makes each passing result attributable to the behavior actually recorded
in that case. See `regressions/gen3ou/README.md` for the case schema and
selection policy.

Use explicit legal team exports with:

```sh
python harness/diff.py \
  --team-p1 path/to/p1.txt \
  --team-p2 path/to/p2.txt \
  --battles 1 -j 1
```

Mixed-gender species must explicitly state `(M)` or `(F)`. Showdown otherwise
draws gender from battle RNG during initialization, which would make the two
engines consume different randomness before turn one.

Verification:

```sh
make -C engine clean all test
PYTHONPATH=harness python -m unittest discover -s harness -p 'test_*.py' -v
python -W error::ResourceWarning -m unittest discover -s tests -v
```
