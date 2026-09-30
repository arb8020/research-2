# Ocean adapter

`pokemon_gen3.h` targets PufferLib's `5.0` branch at commit
`6ffa5b10dbbbe4d1e8288367c7d9d3acd3bad4a2`. It uses the required two-agent
`Agent` array and `puf_*` lifecycle.

The `battle_init_path` environment setting names one file containing exactly
one ABI-versioned `Gen3BattleInit`. The adapter copies and validates it during
`puf_init`; each `puf_reset` creates a fresh native battle with a deterministic
episode seed. The trainer wires agent buffers after initialization, so reset is
the first point that publishes observations and action masks.

Create the payload from two Showdown team exports with:

```sh
POKEMON_SHOWDOWN_DIR=/path/to/pokemon-showdown \
  python tools/write_battle_init.py p1.txt p2.txt battle.bin
```

Observations are symmetric, perfect-information products. Each agent sees its
own request-order roster first, followed by the opponent roster. Every Pokémon
encodes identity, item, ability, HP fraction, status, active position, level,
Protect and Toxic counters, Leech Seed state, gender, six stats, and four
`(move ID, PP fraction)` pairs. The leading scalar
is the turn number. Hidden-information policy can be changed later at this
single projection boundary without changing battle mechanics.

The engine is not complete. If it rejects a boundary, `puf_step` aborts rather
than silently inventing battle behavior. This makes the adapter structurally
usable for supported differential slices without misrepresenting it as a
trainable complete Gen 3 OU environment.
