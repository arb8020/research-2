#!/bin/bash
set -euo pipefail
cd /pufferlib
mkdir -p ocean/pokemon build
cp /pokemon/ocean/training-smoke.ini config/pokemon.ini
printf 'typedef float obs_t;\n#include "/pokemon/ocean/pokemon_slice.h"\n' > ocean/pokemon/pokemon.h
objects=()
for source in pokemon gen3_rules gen3_slice_data singles2; do
    clang -std=c11 -O3 -c "/pokemon/native/$source.c" -o "build/pokemon_$source.o"
    objects+=("$PWD/build/pokemon_$source.o")
done
NVCC_EXTRA="${objects[*]}" bash build.sh pokemon --float
./puffer train --base.checkpoint_dir=/tmp/pokemon-checkpoints --base.log_dir=/tmp/pokemon-logs
test -n "$(find /tmp/pokemon-checkpoints -type f -print -quit)"
checkpoint=$(find /tmp/pokemon-checkpoints -name '*.bin' | sort | tail -1)
./puffer eval "$checkpoint" --headless --base.eval_episodes=16
tar -cf /tmp/pokemon-training-checkpoints.tar -C /tmp pokemon-checkpoints pokemon-logs
