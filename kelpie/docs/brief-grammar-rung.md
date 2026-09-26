# Brief: grammar rung on the new path

Date: 2026-09-09. Executor: sonnet, worktree `worktrees/http-grammar-rung`, branch `http/grammar-rung` (exists, clean, off main 8b18da7). "You are a subagent. Don't run memo." Stop and report on any ambiguity.

Siblings edit `ops.py`, `kernels/`, `sdk/run.py`, `serve.py`, `models/torch/*` — do NOT edit those. Yours: `kelpie_http/sdk/{app,chat}.py`, `kelpie_http/wire.py` (a field), `kelpie_engine/grammar.py` (re-home under `kelpie_engine/sdk/` if on the old path), `kelpie_models/sdk/step.py` (`sample` only), `kelpie_engine/sdk/engine.py` (`attach_grammar` only if missing).

Read: docs/CODING_STANDARDS.md, docs/brief-greenfield-glue.md ("grammar mask rung"), kelpie-core/include/kelpie.h (`kelpie_attach_grammar`, `KelpiePlan.logit_mask`), kelpie_engine/{grammar.py,_xgrammar_ffi.py} (xgrammar shim via ctypes), kelpie_engine/sdk/{engine,plan}.py (`Plan.sampling.logit_mask`, `supports_grammar`), sdk/step.py (`Step.sample`), kelpie_http/sdk/{app,chat}.py (`NOT_YET` 400), the OLD path (`kelpie_http/server.py`, `core.py` — for what worked, not structure).

Task: serve `response_format` json_schema / json_object on the new path.
1. HTTP: parse `response_format`; compile with the xgrammar shim (re-signatured: no StepBatch, no old core); `engine.attach_grammar(request_id, grammar)` right after `submit`.
2. Step: `Step.sample` applies `plan.sampling.logit_mask` (filled by the Zig core — confirm in c_api.zig) before `torch.ops.kelpie.sample`; bitmask over vocab_words, same application as the old sampler; assert mask shape vs vocab.
3. Remove `NOT_YET` for `response_format` (keep it for images).
4. Echo: 400 "echo has no vocabulary for grammar" or skip — say which.

Verify: `scripts/test`; gpt2 CPU smoke `python examples/main.py 8147`; `curl /v1/chat/completions` with json_schema `{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}` and a capital-of-France prompt — output must parse as JSON matching the schema (the mask guarantees validity, not gpt2); plain completion still " its capital city, Burgundy". No pytest, no test files.

Rules: no abbreviations, no `Any`, asserts, no history comments. Commit per step, trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. `mimir breadcrumb -a grammar-rung`, `mimir papercut`. Report: request->grammar->mask->sample pseudocode, what was re-homed/deleted, curl transcript, STOPs, uncertainties, commits.
