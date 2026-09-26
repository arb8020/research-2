"""Model files not yet on the six-arg seam (docs/ladder.md). Each moves back to
kelpie_models/models/torch/ when its forward is
`forward(weights, config, tokens, requests, kv, taps)` over `Tokens` / `Requests` /
`torch.ops.kelpie.*`, the way models/torch/qwen3.py is written.

Every module here raises `NotImplementedError` at import, naming the deleted pre-Plan modules
it still reads, so it fails with a reason instead of an `ImportError` on a module nobody can
find any more.
"""
