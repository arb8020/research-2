# kelpie-core boundary (v0, additive-only once used)

Python calls Zig. Zig is a library; Python owns the process and the HTTP loop.

    submit(prompt_tokens: []u32, max_new_tokens: u32, temperature: f32, mm_hash: u64 = 0) -> request_id | error.Full | error.TooLong
        mm_hash: content hash of the request's multimodal inputs (0 = text only). Stored on the request, echoed per
        plan entry (KelpiePlan.mm_hashes), folded into the request's prefix block hashes once the prefix index exists.
        C ABI: kelpie_submit (text) and kelpie_submit_mm (additive). Image data itself never enters Zig: kelpie-py's
        KelpieCore.submit(..., mm_payload=) hands it to model_fn.attach(request_id, payload) under the submit lock and
        detaches at the poll that observes finish, or at cancel.
    step()                       one scheduler tick: build batch, call model, sample, advance cursors
    poll(request_id)             -> new tokens since last poll, finished: bool, finish_reason
    cancel(request_id)             frees KV blocks and releases the slot immediately; unpolled tokens are dropped

Rules:
- HTTP handlers only submit/poll/cancel. step() runs on its own thread at its own pace.
- Wire format (OpenAI /v1/completions, SSE) lives in one Python file that only uses these four calls.
- Tokenize/detokenize in Python (HF tokenizers). Zig sees token ids only.
- Model forward pass is a Python callable Zig invokes with (token_ids, positions, slot_map, ...) -> logits on GPU.
- poll on a released or never-acquired id reports finished+cancelled with no tokens. A request id may be reused by a later submit once its slot is released (after cancel, or after the poll that observed finish); callers stop polling at that point.
- Sampling on the Zig side (custom kernel later; argmax/temperature first).
