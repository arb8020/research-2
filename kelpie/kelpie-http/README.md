# kelpie-http

OpenAI-compatible `/v1/completions` served over the 4-call core API
(`submit` / `step` / `poll` / `cancel`, see `../docs/core-api.md`).

`--model gpt2|Qwen/Qwen3-0.6B|HuggingFaceTB/SmolVLM-256M-Instruct|openai/gpt-oss-20b` runs the real path: Zig scheduler (`kelpie-core`,
via `kelpie-engine`) planning batches, a torch forward from `kelpie-models` bound
through `kelpie_models.bridge`, tokenizer from the HF model id. `--model stub`
runs `StubCore`, a pure-Python reference core that "generates" by echoing the
prompt tokens in reverse, one token per scheduler tick.

`/v1/chat/completions` (SmolVLM only): OpenAI content parts, `image_url` as a base64
`data:` URL. `kelpie_http/vlm.py` expands the image into placeholder tokens (HF's
Idefics3 expansion), preprocesses tiles, and hashes the bytes into `mm_hash`; the
handler still only submits/polls/cancels.

    curl localhost:8000/v1/chat/completions -d '{"messages":[{"role":"user","content":[
      {"type":"image_url","image_url":{"url":"data:image/png;base64,..."}},
      {"type":"text","text":"Describe this image."}]}],"max_tokens":32,"temperature":0}'

Layout:

- `kelpie_http/core.py` — the `Core` protocol and `StubCore`.
- `kelpie_http/wire.py` — the only file that knows the OpenAI JSON/SSE format.
- `kelpie_http/server.py` — FastAPI app; handlers only `submit`/`poll`/`cancel`;
  one background thread calls `step()` at its own pace. `kelpie_models.launch.build` +
  `KelpieCore` (see `kelpie_http/cli.py`, `examples/main.py`) build
  Engine (block 16, cache groups derived from the model's config by
  `kelpie_models.bridge.engine_groups`, max_seq_len 2048, max_batch_tokens 1024)
  + model + `KelpieCore`. gpt-oss gets two groups (sliding window 128 + full);
  gpt2/Qwen3 one.

## Run

    cd ../kelpie-core && ../scripts/zig build lib      # libkelpie.{dylib,so} in zig-out/lib (needs Zig 0.14.1, see scripts/zig)
    cd ../kelpie-http && uv sync
    uv run kelpie serve --model gpt2 --device mps --kv-blocks 256 --port 8000
    uv run kelpie-http --model Qwen/Qwen3-0.6B --device cuda --kv-blocks 512
    uv run kelpie-http --model stub --max-requests 8
    uv run kelpie-http --model openai/gpt-oss-20b --device cuda --kv-blocks 512   # bf16, ~41 GB
    uv run kelpie-http --model openai/gpt-oss-120b --tp 2 --ep 2 --kv-blocks 2048  # 4 GPUs, ~61 GB each

## Chat completions (`/v1/chat/completions`)

The prompt side is the model's chat template with `tools`; the output side is a streaming
tool-call / reasoning parser (`kelpie_http/chat/`): `content`, `reasoning_content` and
`tool_calls` in both the non-stream message and the SSE deltas (OpenAI shapes; the openai SDK
reassembles them). The family is picked from the model name -- Qwen3 (Hermes JSON), gpt-oss
(harmony, via openai_harmony), Kimi K3 (XTML), DeepSeek V3.2 (DSML), GLM-5.x, Llama-3, and
`default` = the tokenizer's `apply_chat_template` (SmolLM/SmolVLM) -- or with `--chat-format`
for a local path. The format's stop tokens (e.g. gpt-oss `<|call|>`) end the turn through the
core's `stop_token_ids`. `reasoning_effort` and `chat_template_kwargs.enable_thinking` are
honoured where the template has them. `tool_choice` is `auto`/`none` only (no forced calls yet).

    uv run kelpie-http --model Qwen/Qwen3-0.6B --device mps --kv-blocks 512
    uv run pytest tests/test_render_parity.py tests/test_parsers.py   # tokenizers only
    uv run pytest tests/test_chat_tools.py                             # Qwen3-0.6B, mps

`--kv-blocks` counts the null block 0 (never allocated); usable KV is
`(N - 1) * 16` tokens. Weights load in float32 (the golden-logits tolerance).

## Observed (greedy, prompt "The capital of France is", max_tokens 16)

Mac (M-series, `--device mps`, fp32 eager):

- gpt2: ` the capital of the French Republic, and the capital of the French
  Republic is the` — 0.82 s wall for 16 tokens (~20 tok/s single stream).
- Qwen/Qwen3-0.6B: ` Paris. The capital of Italy is Rome. The capital of Spain is
  Madrid.` — 1.9 s wall (~8 tok/s single stream).

Streaming yields one SSE chunk per token for both. `tests/test_kelpie_core.py`
checks the gpt2 text against HF `generate` (non-stream, stream, and two
concurrent requests batched in one step).

One NVIDIA B200 (`--device cuda`, torch 2.13+cu130, fp32 eager),
same prompt, identical text to the Mac runs:

- gpt2: 0.59 s wall for 16 tokens (~27 tok/s single stream).
- Qwen/Qwen3-0.6B: 0.86 s wall (~19 tok/s single stream).

Single-stream throughput is Python-bound, not GPU-bound: the eager attention
loops per request per layer, the stepper sleeps 2 ms between steps and the
handler polls every 5 ms. All four suites pass on the B200 with
`KELPIE_DEVICE=cuda ZIG=/tmp/zig-linux-x86_64-0.14.1/zig`.

### gpt-oss-20b (wave1/groups: sliding-window + full cache groups)

One B200 (`--device cuda`, bf16 dequantized from the hub's MXFP4, `--kv-blocks 512`):
weights load in 146 s and sit at 41.2 GB on the GPU (`nvidia-smi`), the engine has two
cache groups (`window=128` for the even layers, full for the odd ones; see
`docs/cache-groups-ladder.md`).

- `The capital of France is`, 16 greedy tokens: ` Paris."\n\nSure! Here's a simple example of
  a Python program that uses a` in 1.56 s wall (first request; includes warm-up).
- A 405-token prompt (40 x "The quick brown fox jumps over the lazy dog." + "In summary,
  the fox"), longer than the 128-token window, so the window group slides during prefill and
  decode: ` is quick and the dog is lazy. The quick brown fox jumps over the lazy` in 1.08 s.

### gpt-oss-120b (wave2/parallel: tp=2 x ep=2 over 4 GPUs, docs/parallelism.md)

An 8x B200 host, `--model openai/gpt-oss-120b --tp 2 --ep 2 --gpu-offset 0 --kv-blocks 2048`,
bf16 dequantized from MXFP4 at load, every rank slicing its own shard of the checkpoint
(`scripts/parallel_eval.py` for the numbers; reference kernels throughout, no Triton):

| | tp2 x ep2 (4 ranks) | tp2 (2 ranks) |
|---|---|---|
| load (page cache warm) | 33 s | 21 s |
| device memory per rank | 61.2 GB used (56.6 GiB allocated on rank 0) | 123 GB |
| greedy, batch 1 | 9.0 tok/s (first request 3.9, warm-up) | 7.8 tok/s |
| greedy, 16 x the same prompt | 47 tok/s (HTTP: 43 tok/s, 16 concurrent clients) | 44 tok/s |
| plan broadcast per step | 2.5 ms in-step, 2.7 ms wire-only | 2.3 / 2.1 ms |

Greedy text over 32 tokens on three prompts vs HF `GptOssForCausalLM` (bf16, eager,
`device_map="auto"` over the other 4 GPUs, `Mxfp4Config(dequantize=True)`), through
`/v1/completions` and through the core directly (identical):

- `The capital of France is` (5 tokens): identical for 24 tokens (` Paris.\n\nGreat! If you
  have any more questions or need further assistance, feel free to ask!\n\nSure!`), then HF
  picks `\n\n` and we pick ` If`; HF's own logprob of its token is only 0.125 nats above ours
  (a bf16 near-tie).
- `def fibonacci(n):` docstring (13 tokens): exact over 32 tokens.
- 222-token Apollo prompt (> the 128-token window, so the sliding layers slide in prefill and
  decode): exact over 32 tokens (` Neil Armstrong.\n\nIt looks like you're emphasizing ...`).
- Last-prompt-token logits vs HF: max |diff| 0.25 / 0.38 / 0.48 on scales 23 / 16 / 15
  (bf16 experts summed in a different order; argmax equal on all three).

Batch invariance across world sizes: the same prompts at tp2 (world 2) vs tp2 x ep2 (world 4)
give last-prompt-token logits with max |diff| 0.47 / 0.38 / 0.50 (same scales; argmax equal;
greedy ids equal on prompts 1 and 2, prompt 0 differs at the same near-tie). Two runs of the
*same* world-4 config differ by 0.00 / 0.36 / 0.23: the MoE scatter-add (`index_add_`, CUDA
atomics in bf16) is not run-to-run deterministic on one device either, so the cross-world
number is at the noise floor of the reference forward, not a sharding effect. Making it
invariant needs a deterministic expert combine (sort-and-segment-sum) and an fp32 all_reduce
of the expert partial sums -- not built.

Correctness for the sliding window is in `kelpie-models/tests/test_gpt_oss.py` (first 4 layers,
fetched by HTTP range requests: a 200-token prefill and a 150-token prompt decoded with the
core's slid-out rows nulled match HF's logits/greedy text) and in the fp32 oracle corpus
(`tests/oracle/corpus/gpt_oss`, 2 layers, 200-token prompt: max abs diff 5e-5); both run on
the Mac (mps) and on a B200 (cuda). bf16 greedy text can differ between runs when the request is
batched with others (different padded shapes, different bf16 rounding): not a scheduler bug.

## Non-streaming

    curl -s localhost:8000/v1/completions \
      -H 'content-type: application/json' \
      -d '{"prompt": "the quick brown fox", "max_tokens": 16}'

## Streaming (SSE)

    curl -sN localhost:8000/v1/completions \
      -H 'content-type: application/json' \
      -d '{"prompt": "the quick brown fox", "max_tokens": 16, "stream": true}'

Chunks arrive as `data: {...}` lines; the stream ends with `data: [DONE]`.

## Errors

- Request slots exhausted (`error.Full`): **429** with `Retry-After: 1`. Chosen over
  503 because OpenAI client libraries retry 429 automatically.
- Prompt too long (`error.TooLong`) or malformed body: **400**.
- Client disconnects mid-generation: the request is cancelled in the core.

## Wire contract

The HTTP surface is frozen as a language-independent spec, `docs/wire-contract.md` (rev 1), with
byte-level recorded responses in `tests/contract/`. `python -m kelpie_http.contract` is the
deterministic contract-mode server the goldens were recorded against; `scripts/contract_check.sh
[URL]` replays the cases against any server in contract mode (the future Zig one included).

## Tests

    uv run pytest
