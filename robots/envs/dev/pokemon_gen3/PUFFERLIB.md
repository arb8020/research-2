# PufferLib Ocean integration boundary

The target contract is PufferLib 5.x, not the older flat-buffer Ocean API.
The reference template is:

`https://github.com/PufferAI/PufferLib/blob/5.0/ocean/minimal/minimal.h`

At the time this boundary was established, that contract requires:

- `#include "pufferenv.h"` after defining `obs_t`;
- `ACT_SIZES`, `OBS_SIZE`, and `NUM_ATNS` metadata;
- an `Env` with `Log log`, `int num_agents`, RNG state, and `Agent agents[2]`;
- `puf_init`, `puf_reset`, `puf_step`, `puf_render`, `puf_close`, and `puf_log`;
- observations, actions, rewards, terminals, and action masks owned through each
  `Agent` rather than one flat environment-level buffer.

The Ocean adapter must translate those buffers to `gen3_abi` calls. It must not
implement moves, switching, RNG, legality, rewards, or terminal semantics a
second time.

The initial adapter resolves two of the three boundary choices:

1. two normalized teams enter as an exact ABI-versioned `Gen3BattleInit` file;
2. observations are symmetric perfect-information product types; and
3. it remains undecided whether a terminal `puf_step` exposes the terminal observation before reset
   or resets immediately under PufferLib's vector-environment lifecycle.

The native ABI and differential harness remain the authoritative mechanics
surface. The adapter aborts on unsupported boundaries instead of introducing a
second mechanics implementation.
