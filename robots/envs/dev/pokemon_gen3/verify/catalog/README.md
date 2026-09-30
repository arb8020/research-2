# Gen 3 immutable-catalog differential

This verifier proves that the native Gen 3 generation image agrees with pinned
Pokémon Showdown for every frozen Gen 3 OU catalog identity:

- 369 species/forms: identity, source number, tier, types, base stats, the Shedinja
  HP override, and three neutral-nature calculated-stat vectors;
- 354 moves: identity, source number, type, category, base power, accuracy,
  priority, base/max PP, target and flags;
- 70 abilities and 104 items: identity and source number.

The native program reads only the generated C catalog. The Node oracle is
verifier-only and loads Showdown at revision
`6e71625b9e6cffeda268b548ae7f43a7643fc3f0`. The comparison is ordered,
field-by-field, and reports the first descriptor and field that differs. A
SHA-256 digest of the canonical 897-record JSONL artifact makes repeat runs
directly comparable. The runner repeats both producers byte-for-byte and
includes a negative test proving that a corrupted field is localized to its
descriptor and JSON path.

Catalog presence is not executable-mechanics support. In particular, this
check does not classify a move, ability or item as implemented.

Run:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/pinned/showdown node verify/catalog/test.js
```
