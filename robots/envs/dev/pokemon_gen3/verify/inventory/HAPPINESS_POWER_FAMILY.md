# Gen 3 happiness power family

Pinned Showdown stores normalized happiness on each Pokemon. Numeric values
are clamped to 0–255 and omitted values default to 255; team-text import gives
an otherwise unspecified Frustration user happiness 0. Return resolves power
as `floor(happiness * 10 / 25)`, minimum one. Frustration resolves the same
formula over `255 - happiness`.

The native immutable set product now carries happiness plus an explicit
presence bit, so zero and omission cannot be conflated at the ABI boundary.
Battle initialization canonicalizes omission to 255. Generated move data
selects one of two typed base-power policies, resolved before critical and
BasePower events by the generic kernel. Neither move ID appears in generic
control flow. Ocean observations include normalized happiness, preserving the
Markov state needed to interpret either move.

Focused evidence is
`native/test_pokemon.c#test_happiness_base_power_policies`. Six legal
differential cases cover Return's omitted default, Frustration's team-import
default, both minimum-power extremes, and happiness 128 where Return has power
51 while Frustration has power 50. All evidence is pinned to Pokemon Showdown
commit `6e71625b9e6cffeda268b548ae7f43a7643fc3f0`.
