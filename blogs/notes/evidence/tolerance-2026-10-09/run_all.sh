#!/bin/bash
# reproduces every table in this dir
set -e
cd "$(dirname "$0")"
C=gelu,layernorm,softmax,attention
uv run --quiet proto.py --seeds 5 --K 64 &                                   # main table
uv run --quiet proto.py --seeds 5 --K 64 --ops $C --inner fp32 --tag _opmath &  # MCA under an fp32-opmath contract
uv run --quiet proto.py --seeds 3 --K 32 --ops $C --mode sequential --tag _seq &  # MCA with sequential-sum model
wait
for K in 8 16 32 128; do uv run --quiet proto.py --seeds 2 --K $K --ops $C --tag _K$K & done
wait
uv run --quiet summarize.py > summary_mca.md; uv run --quiet overall.py > scorecard.md
