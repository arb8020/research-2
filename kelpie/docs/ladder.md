# The model ladder

What kelpie serves, ordered by what each rung forces on the *engine* (KV cache, scheduler,
batching) rather than on the forward math. The numbering is crucible's 10-rung ladder
(`crucible/benchmarks/model_ladder/meta/FANOUT.md`, PR #19) plus two small stand-ins kelpie added
so an axis can be tested on a model that runs everywhere.

Rules: a rung is a model file in `kelpie-models/kelpie_models/models/torch/`; a file lives in
`models/unported/` until it runs on the kernel seam; a "config delta" rung is the same file as its parent with a
different config and is not ported separately. The ladder is a roadmap, not a promise: adding a
rung should be one model file plus the catalog entries its layers need.

## Engine axes

| axis | what the engine must have | first rung that needs it |
|---|---|---|
| baseline | one KV cache group, paged blocks, prefix cache | 00 |
| multi-group KV | per-layer cache groups (full vs sliding window), sinks as a kernel arg | 05 |
| encoder | non-token prefill inputs: an encoder runs outside the step, embeddings enter the batch | smolvlm |
| recurrent state | a per-slot state ring beside the KV (GDN/KDA + conv states); prefix cache off | qwen3_next |
| MLA layout | compressed latent per token (`kv_layout` differs), `mla_attention` backend op | 03 |
| DSA indexer | a per-layer indexer cache beside the KV; top-k sparse attention over it (`dsa_attention` backend op) | 03 (V3.2), reused by 09 |
| spec-decode head | an MTP/draft head shipped in the checkpoint: `1+K` rows, `kind`/`n_drafts`, verify sampling | 03 (1 head), 06 (8-layer module), 09 (DSpark) |
| windowed + compressed KV | window ring + per-layer compressed KV at 4:1/128:1; compression on ratio boundaries | 09 only |

## Rungs

| # | model | HF id | engine features (from `config.json`) | axis | status |
|---|---|---|---|---|---|
| 00 | GPT-2 | `openai-community/gpt2` | MHA, learned pos (hard 1024 cap) | baseline | **ported** (seam) |
| 01 | Qwen3-0.6B | `Qwen/Qwen3-0.6B` | GQA 8 kv, no SWA | baseline | **ported** (seam) |
| 02 | Qwen3-30B-A3B | `Qwen/Qwen3-30B-A3B` | same cache as 01; MoE is forward-only | baseline | config delta of 01 |
| 03 | DeepSeek-V3.2 | `deepseek-ai/DeepSeek-V3.2` | MLA (`kv_lora_rank` 512 + rope 64) + DSA (lightning indexer, top-k 2048), 1 MTP head | MLA + DSA indexer + spec head | unported (`deepseek_v32.py`); plain V3 (`DeepSeek-V3-0324`, crucible's 03) is the config delta with the indexer off |
| 04 | Kimi-Linear-48B | `moonshotai/Kimi-Linear-48B-A3B-Instruct` | 20 KDA layers (recurrent + 3 conv states) + 7 MLA layers with no RoPE (`mla_use_nope`) | recurrent + MLA | not started; KDA kernel vendored (M7); in the box test set (2026-09-09), KDA generalizes GDN so qwen3_next adds no kernel |
| 05 | gpt-oss-20b | `openai/gpt-oss-20b` | alternating sliding(128)/full layers, per-head sinks, MoE, yarn x32 | multi-group KV | **ported** (seam); DFlash target (M4) |
| 06 | Inkling-Small | `thinkingmachines/Inkling-Small` | 35/42 SWA-512 layers, short-conv state, 8-layer MTP module with its own SWA split, vision + audio encoders; no HF modeling code | multi-group KV + encoder + spec head | not started |
| 07 | GLM-4.7-Flash | `zai-org/GLM-4.7-Flash` | MLA (`q_lora_rank` 768), 1 MTP head, ctx 202k | MLA + spec head | config delta of 03 |
| — | GLM-5.3-Flash | `zai-org/GLM-5.3-Flash` | 320B-A18B, DSA indexer on 11/45 layers | MLA + DSA indexer | rung 03's smaller checkpoint stand-in (no DSA checkpoint under ~280B exists, survey 2026-09-09); B200 only |
| 08 | Qwen3.8-27B | `Qwen/Qwen3.8-27B` | Qwen3.5 arch: GDN 3:1 hybrid (48 GDN + 16 attn @ 4 kv), mRoPE 3-D positions, vision tower, 1 MTP | recurrent + encoder + spec head | not started; axis covered by qwen3_next, mRoPE positions are new scheduler metadata |
| 09 | DeepSeek-V4-Flash | `deepseek-ai/DeepSeek-V4-Flash-0731` | 1 kv head 512-wide; every layer SWA-128 ring + compressed KV per layer (`compress_ratios` 0/4/128) + the 03 indexer cache on 4:1 layers; DSpark head reads 3 target layers | windowed + compressed KV + DSA indexer + spec head | unported (`deepseek_v4.py`, reference); needs a cache design pass before M7; DSpark target |
| — | SmolVLM | `HuggingFaceTB/SmolVLM-256M-Instruct` | vision encoder, image embeds in prefill | encoder | **ported** (seam; `llama.py` text tower) |
| — | Qwen3-Next | `Qwen/Qwen3-Next-80B-A3B-Instruct` | GDN + gated attention hybrid | recurrent | unported; `attention` + `gdn`, groupless workspace slot to decide |

`llama.py` is not a rung (nothing engine-side over 01/05) but stays in `kelpie_models/models/torch/`: it is SmolVLM's text tower and is ported with it. Rung 03 is the V3.2 file, not
plain V3: V3.2 = V3 + DSA, and its indexer cache is the one 09 reuses, so it is built there first.

## Order of work

1. ~~Port 01 and smolvlm to the seam~~ done 2026-09-09; `models/` = what runs.
2. qwen3_next (recurrent), then 03 (MLA + the DSA indexer cache), both reference-only kernels.
3. 09 cache design (window ring + compressed KV on top of the 03 indexer), then the deepseek_v4 port.
4. 04 / 06 / 08 once their kernels are vendored (KDA, Inkling attention, GDN).

Audit of the ten configs: 2026-09-09 (BREADCRUMBS). Spec-decode plan: `docs/brief-dflash.md`.

Box test set (2026-09-09): gpt2, Qwen3-0.6B, gpt-oss-20b, SmolVLM-256M, Kimi-Linear-48B-A3B,
DeepSeek-V4-Flash, plus two synthetic tiny configs from `kelpie_models/synth/roll.py` —
`deepseek_v4_tiny` and `kimi_linear_tiny` — that put the CSA/DSA and KDA classes on one chip. See
`docs/decisions.md` 2026-09-09 (session 4) for the full ruling.
