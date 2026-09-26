# kelpie HTTP wire contract

    contract rev 2          (this document + kelpie-http/tests/contract/{cases,golden})
                            rev 2: config_hash is a hex string, not a JSON integer (section 12)
    covers kelpie-http 0.1  (implementation #1: Python/FastAPI; #2 will be the Zig server)

The HTTP surface is a language-independent contract (docs/decisions.md "HTTP ownership").
The Python server is one implementation of it; a second implementation is correct when
`scripts/contract_check.sh URL` passes against it in contract mode (section 9). Everything not
marked **variable** or **implementation-defined** below is compared byte for byte.

Conventions: **[OpenAI]** = defined by the OpenAI API and reproduced exactly; **[kelpie]** = a
kelpie extension or a kelpie choice inside OpenAI's latitude; **[pinned]** = was
implementation-defined in the Python server and is now fixed by this document;
**[implementation-defined]** = deliberately not part of the contract (listed in section 10).

Evolution rule: additive only (design rule 16). A new field or endpoint is a new contract rev;
changing or removing anything in this document is a new contract, and the goldens say so.

## 1. Transport

- HTTP/1.1. Paths are exact (`/v1/completions`, no trailing slash).
- Request bodies are JSON (UTF-8). The `Content-Type` request header is not checked.
- Every JSON response body is one JSON document, UTF-8, **compact**: separators `,` and `:`
  with no whitespace, non-ASCII characters written raw (no `\uXXXX` escapes), `NaN`/`Infinity`
  never produced. Object keys appear in the order this document lists them. [pinned]
- Integers are written without exponent or fraction; floats always carry a `.` or exponent
  (`0.0`, not `0`). Which fields are float is stated per field. [pinned]
- Response headers that are part of the contract: `Content-Type`, `Retry-After`, and
  `X-Kelpie-*` (section 7). Parameter spacing in `Content-Type` (`; charset=utf-8`) is not
  significant. All other headers (`Date`, `Server`, `Content-Length`, transfer encoding) are
  [implementation-defined].
- `Content-Type` values: `application/json` for JSON bodies; `text/event-stream; charset=utf-8`
  for streams; `text/plain; version=0.0.4; charset=utf-8` for `/metrics`.
- Unknown path -> 404, known path with the wrong method -> 405, both with the error body of
  section 8 (`type` `not_found` / `method_not_allowed`). [pinned]

## 2. Request parsing rules (all endpoints)

- A body that is not valid JSON -> 400 `body must be valid JSON`. A JSON body that is not an
  object -> 400 `body must be a JSON object`. [pinned]
- Unknown fields are ignored, never rejected. This is what lets OpenAI SDKs send `top_p`,
  `stop`, `logprobs`, `presence_penalty`, `user`, `seed`, ... today; each of them is
  **accepted and ignored** until a later contract rev implements it. [kelpie]
- A present field with the wrong JSON type is 400, never coerced: `stream: "yes"` is 400,
  `model: null` is 400, `max_tokens: true` is 400 (booleans are not integers). `null` is not
  "absent" except where stated (`content: null` in chat messages). [pinned]
- Errors are reported one at a time, in the order the fields are listed below (the first
  offending field wins). The `message` strings are pinned by the goldens.

## 3. `POST /v1/completions` [OpenAI]

Request fields, in check order:

| field | type | default | rule |
|---|---|---|---|
| `prompt` | string, or list of exactly one string | `""` | list of != 1 or non-string -> 400 |
| `max_tokens` | integer >= 0 | 16 | `0` is allowed: finishes `length` with no text |
| `temperature` | number >= 0 | 1.0 | integer accepted |
| `n` | integer | 1 | anything but 1 -> 400 |
| `stream` | boolean | false | |
| `model` | string | `"kelpie"` | echoed back verbatim; **not** checked against the served model [kelpie] |
| `stream_options` | object or absent | absent | non-object -> 400; `include_usage` boolean |

Then: prompt longer than the context -> 400 `prompt exceeds context length`; no free request
slot -> 429 (section 8).

Non-streaming response, 200:

```
{"id": "cmpl-<24 hex>", "object": "text_completion", "created": <int>, "model": <echoed>,
 "choices": [{"text": <string>, "index": 0, "logprobs": null, "finish_reason": "stop"|"length"}],
 "usage": {"prompt_tokens": <int>, "completion_tokens": <int>, "total_tokens": <int>,
           "prompt_tokens_details": {"cached_tokens": <int>}}}
```

- `id` **variable**: `cmpl-` + 24 lowercase hex characters. `created` **variable**: integer
  Unix seconds. [OpenAI shape, kelpie width]
- `logprobs` is always present and `null` (logprobs are not implemented). [pinned]
- `finish_reason` is exactly one of `stop`, `length`; never null in a non-streaming body, never
  a core lifecycle name (`finished_eos`, `cancelled`). [pinned]
- `usage.prompt_tokens` counts the tokenized prompt; `completion_tokens` counts generated
  tokens including a stop token; `total_tokens` is their sum. `prompt_tokens_details.cached_tokens`
  is the prefix-cache hit length, always present (0 without a cache). [OpenAI field, kelpie
  presence]

## 4. `POST /v1/chat/completions` [OpenAI + kelpie]

Request fields, in check order (`wire.parse_chat_request` then `chat.request.parse_chat_extras`):

| field | type | default | rule |
|---|---|---|---|
| `messages` | non-empty list of objects | required | each needs a string `role` |
| `messages[].content` | string, `null`/absent, or non-empty list of parts | | `null`/absent is an empty message (OpenAI's assistant tool-call turn) |
| `messages[].content[]` | `{"type":"text","text":string}` or `{"type":"image_url","image_url":{"url":string}}` (`image_url` may also be the string itself) | | other `type` -> 400 |
| image `url` | `data:<mime>;base64,<payload>` only | | any other URL -> 400 (no fetching) [kelpie] |
| `max_tokens`, `temperature`, `n`, `stream`, `model` | as section 3 | | |
| `tools` | list of `{"type":"function","function":{"name":string,...}}` | absent | missing `function.name` -> 400; `[]` = absent |
| `tool_choice` | `"auto"` or `"none"` | `"auto"` | any forced/object form -> 400 (no forced calls yet) [kelpie] |
| `reasoning_effort` | string | absent | passed to the chat template (gpt-oss) |
| `chat_template_kwargs` | object | absent | only `enable_thinking: boolean` is read |
| `messages[].tool_calls`, `tool_call_id`, `name`, `reasoning_content` | | | passed to the chat template as OpenAI defines them |
| `response_format` | `{"type":"text"}` (or absent), `{"type":"json_object"}`, or `{"type":"json_schema","json_schema":{"schema":object,...}}` | absent | `json_object`/`json_schema` compile a grammar the model is constrained to (section 13, rev 3 draft); a malformed `json_schema.schema` -> 400 before any slot is taken; needs a chat format -> 400 otherwise |

Then: images on a model without an image adapter -> 400 `this model does not take images`;
text chat on a server without a chat format -> 400; context length -> 400; slots -> 429.
`stream_options.include_usage` is **accepted and ignored** for chat (no usage chunk yet).

Non-streaming response, 200:

```
{"id": "chatcmpl-<24 hex>", "object": "chat.completion", "created": <int>, "model": <echoed>,
 "choices": [{"index": 0,
              "message": {"role": "assistant", "content": <string|null>
                          [, "reasoning_content": <string>] [, "tool_calls": [...]]},
              "logprobs": null, "finish_reason": "stop"|"length"|"tool_calls"}],
 "usage": {... as section 3 ...}}
```

- `message.content` is a string, or `null` exactly when the message has `tool_calls` and no
  text. [OpenAI]
- `reasoning_content` is **present only if non-empty** (the model's `<think>` channel, tags
  stripped). [kelpie, DeepSeek/vLLM convention]
- `tool_calls` is **present only if non-empty**: `[{"id": "call_<24 hex>", "type": "function",
  "function": {"name": <string>, "arguments": <string>}}]` in the order the model emitted them.
  `arguments` is the JSON text **as the model wrote it** (not re-serialised) when the format
  streams raw JSON (hermes); `id` **variable**. [OpenAI shape]
- `finish_reason` is `tool_calls` when the message carries tool calls and generation ended by
  itself, `length` when `max_tokens` cut it (even with calls), `stop` otherwise. [OpenAI]
- Whitespace between a `</think>` block and a `<tool_call>` reaches `content` (e.g. `"\n\n"`);
  whitespace *between* tool calls does not. This is the hermes parser's rule, pinned by golden
  `110_chat_reasoning_tool_call`.

## 5. Streaming (SSE) [OpenAI framing]

- Response: 200, `Content-Type: text/event-stream; charset=utf-8`, headers are sent before the
  first token (so `X-Kelpie-TTFT-Ms`/`-Steps` cannot appear on a stream: section 7).
- Framing: each event is exactly `data: <compact JSON>\n\n`. No `event:`, `id:` or `retry:`
  lines, no comments/keep-alives. The stream ends with `data: [DONE]\n\n`. [pinned]
- Chunk boundaries (how many tokens' text one chunk carries) are [implementation-defined];
  the concatenation of deltas is the contract. In contract mode: one chunk per token.

Completions chunk: `{"id","object":"text_completion","created","model","choices":[{"text":
<string>,"index":0,"logprobs":null,"finish_reason":null}]}` (no `usage`). `id`/`created` are
the same in every chunk of one response. The **last choice chunk** always carries
`finish_reason` (`stop`|`length`) and whatever text was still held back (possibly `""`).
With `stream_options.include_usage: true` one more chunk follows it: `{"id","object","created",
"model","choices":[],"usage":{...}}`; without it no chunk has `usage`. Then `[DONE]`.

Chat chunk: `{"id","object":"chat.completion.chunk","created","model","choices":[{"index":0,
"delta":<delta>,"logprobs":null,"finish_reason":null}]}`. Deltas:

- the **first** chunk's delta has `"role":"assistant"` as its first key, merged with the first
  content (kelpie does not send a separate role-only chunk; OpenAI clients accept both);
- `{"content": <string>}`, `{"reasoning_content": <string>}` (never both in one delta);
- `{"tool_calls":[{"index":<int>,"id":"call_<24 hex>","type":"function","function":{"name":
  <string>,"arguments":""}}]}` opens call `index`; then
  `{"tool_calls":[{"index":<int>,"function":{"arguments":<fragment>}}]}` per argument fragment;
  fragments concatenate to the non-streaming `arguments` string;
- the finish chunk: `"delta": {}` (or `{"role":"assistant"}` if nothing was emitted before),
  `finish_reason` `stop`|`length`|`tool_calls`. Then `[DONE]`.

Format markers (`<think>`, `<tool_call>`, channel tokens) never appear in a delta, partial
markers included; stop tokens never reach the text.

## 6. Reporting endpoints [kelpie]

`GET /v1/models` [OpenAI]: `{"object":"list","data":[{"id":<served model>,"object":"model",
"owned_by":"kelpie"}]}`. The served model name is what `--model` was given.

`GET /health`: `{"ok":<bool>,"reason":<null|string>,"alive":<bool>,"since_last_step_s":
<null|float>,"busy":<bool>}`; 200 when `ok`, 503 otherwise. `reason` is `null` when ok, else
`"stepper dead"` or `"stepper stalled"`. `since_last_step_s` is `null` until the first step,
then a float (**variable**). `busy` = the core has work.

`GET /v1/kelpie/stats`: the metrics snapshot as JSON:

```
{"last_step": null | {StepEvent fields in kelpie.engine.StepEvent order:
     step, t_plan_ns, t_forward_ns, t_commit_ns, n_running, n_waiting, n_prefill_reqs,
     n_decode_reqs, n_tokens, kv_free, kv_used, n_admitted, n_preempted, n_finished,
     n_rejected_full, prefix_queries, prefix_hits, prefix_hit_tokens (ints),
     order (string), config_hash (hex string), is_idle (bool)},
 "gauges": {n_running, n_waiting, kv_free, kv_used, kv_usage (float), config_hash (hex string), step}
           (empty object before the first step),
 "counters": {steps, step_events, request_events, requests_admitted, requests_rejected_full,
              requests_preempted, requests_finished, requests_cancelled, prompt_tokens,
              generated_tokens, prefix_hit_tokens, prefix_queries, prefix_hits,
              then "finished_<reason>" per finish reason seen, in first-seen order},
 "histograms": {ttft_ms, itl_ms, e2e_ms, queue_ms, step_us, plan_us, forward_us, commit_us,
                prompt_len, gen_len: {"count":int,"sum":number,"mean":number,
                "min":null|number,"max":null|number,"buckets":{"<bound>":int,...}}},
 "prefix": {"window":int,"hit_rate":float,"cached_token_rate":float},
 "n_dropped": int,
 "stepper": {"alive":bool,"since_last_step_s":null|float}}
```

Bucket keys are the upper bounds as decimal integers (`"1"`, `"2"`, ... same text as the
`le` labels in `/metrics`). `min`/`max` are `null` while `count` is 0. Every number is
**variable** (runtime data); the key set, order and null-ness are the contract.
`finished_<reason>` keys use the core's names (`finished_eos`, `finished_length`, `cancelled`)
[kelpie]; the `finished_` prefix and first-seen order are [pinned].

`GET /metrics`: Prometheus text exposition 0.0.4, `kelpie_` prefix. Family order: gauges
(`n_running`, `n_waiting`, `kv_free{group}`, `kv_used{group}`, `kv_usage{group}`,
`config_hash`, `step`), `scheduler_order{order}` (only after the first step), counters
(`<name>_total` in the stats order), `requests_finished_by_reason_total{reason}` (one sample
per reason seen, first-seen order), `prefix_hit_rate`, `prefix_cached_token_rate`,
`events_dropped_total`, then the histograms (`_bucket{le}` per bound, `le="+Inf"`, `_sum`,
`_count`). Each family is `# HELP`, `# TYPE`, samples; one `\n` after every line. HELP texts are
pinned by the golden (static: no runtime numbers in them). Sample values are **variable**.
Integral floats are written as integers (`1` not `1.0`); others as shortest round-trip decimals.

`GET /v1/kelpie/config`: `{"config":{"order":<"running_first"|"waiting_first">,
"reserve_ratio":<float>,"max_batch_tokens":<int>,"max_batch_reqs":<int>,"prefix_cache":<bool>},
"config_hash":<hex>}`. Values are the knobs as last applied by a plan. `reserve_ratio` is a
float32 in the core and is written as the shortest decimal that round-trips to that float32
(`0.3`, not `0.30000001192092896`). [pinned] 501 without a live engine (section 8).

`POST /v1/kelpie/config`: body `{<knob>: <value>, ...}`, non-empty object; knob names are the
five above; `order` a string in the enum, `prefix_cache` a boolean, `reserve_ratio` a number
>= 0, the two batch limits positive integers < 2^32. Unknown knob / wrong type / bad enum ->
400 (message names the knob); a value the engine's static buffers cannot hold -> 400
`<knob> out of range for this engine`; 200 `{"config_hash":<hex>,"apply_step":<int>}` =
the hash the config will have once everything queued applies, and the step that applies it;
64 changes queued and not yet applied -> 503 (section 8). All knobs of a body are
type-checked before any is queued; they are then queued in body order, and a range error on
the k-th leaves the first k-1 queued (not transactional). [pinned as-is]

`config_hash` (everywhere in JSON) is an unsigned 64-bit hash written as a JSON **string**:
`"0x"` + exactly 16 lowercase hex digits (`"0x00c0ffee00000001"`). Rev 1 wrote it as a JSON
integer, which exceeds 2^53 and silently loses bits in every JavaScript client; rev 2 fixed that
(section 12). Its value is engine-defined (**variable** in the goldens). On `/metrics` the same
hash is a Prometheus gauge, i.e. a float64: compare it for *change* only, never for equality
with the JSON value.

## 7. Headers [kelpie]

Opt-in (`--headers`); a server started without it sends none of them.

| header | on | value |
|---|---|---|
| `X-Kelpie-Request-Id` | every 200 completion/chat response, stream or not | the core's request id, decimal integer (**variable**) |
| `X-Kelpie-TTFT-Ms` | non-streaming 200 only | arrival to first token, milliseconds, fixed 3 decimals (`12.345`) (**variable**) |
| `X-Kelpie-Steps` | non-streaming 200 only | steps the request was part of, decimal integer (**variable**) |
| `Retry-After` | 429 and 503 | always `1` |

Error responses carry no `X-Kelpie-*` header.

## 8. Errors [OpenAI shape]

Body, always: `{"error":{"message":<string>,"type":<string>,"param":null,"code":null}}`.
`param` and `code` are always present and `null`. [pinned]

| status | `type` | when | headers |
|---|---|---|---|
| 400 | `invalid_request_error` | any parse failure of sections 2-4/6; prompt exceeds context length; a config value out of range | |
| 404 | `not_found` | unknown path | |
| 405 | `method_not_allowed` | wrong method | |
| 429 | `server_busy` | no free request slot (`all request slots busy, retry later`) | `Retry-After: 1` |
| 499 | `cancelled` | the client disconnected before the non-streaming response was ready (`client disconnected`); by construction nobody receives it. A stream that loses its client is cancelled in the core with no body. | |
| 501 | `not_implemented` | `/v1/kelpie/config` on a core without a live engine (`this core has no live config`) | |
| 503 | `server_busy` | config queue full (`config queue full, retry after a step`) | `Retry-After: 1` |
| 503 | (health body, not an error body) | `/health` when not ok | |

The error `message` strings are pinned by the goldens (a second implementation copies them);
they contain no language-specific renderings (no Python reprs, quotes are `'`).

Prior art (network `contracts/`, loom `proxy/app.py`): both use an `{"error": {...}}`
envelope; network adds `request_id`/`retry_after_ms` inside it, loom a single `type`. kelpie
keeps OpenAI's four-key envelope because OpenAI SDKs parse it; the request id travels in
`X-Kelpie-Request-Id` (the vendor-prefixed-header convention both repos use, e.g.
`x-loom-request-id`).

## 9. Contract mode and the recorded goldens

`kelpie-http/tests/contract/` holds `cases/NNN_name.json` (one HTTP exchange each) and
`golden/NNN_name.{json,sse,txt}` + `.meta.json` (status + contract headers). `scripts/contract_check.sh
[URL]` runs them; without a URL it starts the Python contract server in-process (`python -m
kelpie_http.contract`). The goldens were recorded against a **fresh** contract server. Cases are
independent: run in-process (pytest, no `KELPIE_CONTRACT_URL`), an in-process reset hook
(`core.reset()` + `metrics.reset()`, not on the wire) clears counters and the config queue before
every case, so cases pass in any order (`KELPIE_CONTRACT_SHUFFLE=1` proves it). A case needing
extra state of its own (a busy slot, a full config queue) builds it within itself
(`repeat_before`, `hold`). Against a remote server (`KELPIE_CONTRACT_URL`, e.g. the Zig server)
there is no in-process handle to reset, so `scripts/contract_check.sh` still runs cases in file
order there and that server must start fresh.

A server is in **contract mode** when (kelpie_http/contract.py is the reference):

- tokenizer `Qwen/Qwen3-0.6B`, chat format `qwen3`, served model name `contract`, headers on;
- one request slot; the core echoes the prompt reversed, one token per step, unless the decoded
  prompt contains `[[script:NAME]]`, in which case it emits `SCRIPTS[NAME]` from
  kelpie_http/contract.py (`plain`, `reasoning`, `tool_call`, `reasoning_tool_call`,
  `text_then_tool_calls`) and finishes `stop` when the script runs out; `stall` never
  finishes (it holds the slot until the client disconnects);
- one token per poll, so a stream has one chunk per token and the finish chunk carries no text;
- `created` = 1700000000; ids are the prefix + the 24-hex-digit ordinal of ids minted under
  that prefix;
- `/v1/kelpie/config` talks to an engine that is never stepped (max_requests 1, max_seq_len
  64, 8 blocks, batch 64 tokens / 1 request), or answers 501 when started without one; the
  cases marked `needs_engine` run only against the matching variant.

Variable fields are canonicalised before comparison, on the raw bytes, by
`tests/contract/wire_normalize.py` -- and nothing else is:

| where | rule |
|---|---|
| any body | `cmpl-`/`chatcmpl-`/`call_` + 24 hex -> the ordinal of that id's first appearance in the case (network's convention: identity is "the k-th id minted in this scenario") |
| any body | `"created":<int>` -> `1700000000`; `"apply_step":<int>` -> `0`; `"config_hash":"0x<16 hex>"` -> `"0x0000000000000000"`; `"since_last_step_s":<number>` -> `0.0` (null kept) |
| `/v1/kelpie/stats` | every unquoted number -> `0` |
| `/metrics` | every sample value -> `0` |
| headers | `X-Kelpie-Request-Id`, `X-Kelpie-Steps` (must match `^\d+$`) -> `<int>`; `X-Kelpie-TTFT-Ms` (must match `^\d+\.\d{3}$`) -> `<ms>`; only the section-7 headers plus `Content-Type` are compared |

Taken from prior art: byte-equal goldens refreshed only by an explicit record step (loom's
conformance corpus, network's `pacifica.dump.golden`); cases as data files that know nothing
about the implementation (loom `check.py`); ordinal id canonicalisation (network
`tests/thrash/upstream_diff.py`); an explicit contract rev header (network `.contract` files).
Deliberately not taken: loom's `sort_keys=True` canonical JSON (key order is part of this
contract, so clients see OpenAI's order), network's refuse-on-rev-mismatch (there is no rev
field on the wire; the goldens are the rev), JSON Schema (both repos avoid it too).

## 10. Implementation-defined (outside the contract)

- Chunk boundaries of a stream (section 5) and the exact partial-UTF-8 hold-back policy.
- The step/scheduling numbers behind `X-Kelpie-Steps`, `apply_step`, `last_step.*`.
- The hash function behind `config_hash`.
- Which finish reasons / label values have been seen (affects which `finished_*` keys and
  `by_reason` samples exist); only their order rule is pinned.
- Non-contract headers; HTTP keep-alive behaviour; the 499 body's visibility.
- Everything about fields that are accepted and ignored (section 2): a later rev may
  implement them, and that is additive.
- The `/health` stall window (5 s) and the poll safety-net timeout.

## 11. What changed to freeze this (Python leaks fixed in rev 1)

- SSE chunks were `json.dumps` defaults (`", "`/`": "` separators, `\uXXXX` escapes) while JSON
  bodies were compact UTF-8; now one `wire.dumps` for both.
- `finish_reason` could carry a core name or a `None`-fallback (`or "stop"`); now asserted to
  `stop`/`length`/`tool_calls` at the wire.
- `stream`/`include_usage` were Python-truthy (`"no"` -> true); `model` was `str()`-coerced
  (`null` -> `"None"`); now typed, 400 otherwise.
- `content: null` on an assistant tool-call message was 400; now accepted (OpenAI sends it).
- A non-JSON body was a 500 (unhandled `JSONDecodeError`); now 400.
- 404/405 were FastAPI's `{"detail": ...}`; now the error envelope.
- `reserve_ratio` was the float32 widened to a double (`0.30000001192092896`); now the
  shortest float32 decimal.
- Error messages embedded Python reprs (`('order', 'waiting_first')`, `got 'fastest'`,
  `max_batch_reqs=999`); now plain text.
- `/metrics` HELP for the prefix rates embedded the live window size; now static.
- A streaming client that disconnected left its request running (Starlette cancels the
  generator on disconnect, skipping the cancel path); the request slot leaked until the
  generation ended, forever for a long one. Now cancelled in `finally`.

## 12. rev 2 (2026-09-02): `config_hash` as a hex string

The one non-additive change so far, made deliberately: `config_hash` was a JSON integer holding
a u64. JSON has no integer type; every JavaScript client (and any `double`-backed parser) rounds
it above 2^53, so two different configs could read as equal. Now `"0x"` + 16 lowercase hex digits
on `/v1/kelpie/config` (GET and POST) and in `/v1/kelpie/stats` (`last_step.config_hash`,
`gauges.config_hash`). `/metrics` keeps the gauge (Prometheus is float64 by construction) with a
HELP text that says so. Goldens 400, 430, 500, 510 re-recorded; the normaliser maps any valid hex
value to all zeros. A rev-1 client that parsed the field as a number will now see a string: that
is the intended break.

Rev 2 originally missed one JSON surface: the JSONL event log (`kelpie.events.row_of`) kept
writing the raw u64 integer, so a reader comparing a StepEvent's `config_hash` against the one
`/v1/kelpie/config` returned compared an int to a string and never matched. "Everywhere in JSON"
includes the event log; `row_of` now hexes it, and the same 2^53 argument is why.

## 13. rev 3 draft (2026-09-02): grammar-constrained `response_format` [kelpie]

Additive; this section documents the field, the goldens are new cases (`175_...`,
`321_...`), and the revision counter at the top of this file is **not** bumped yet -- that
happens once the Zig-side overlap half of M3 lands and the two together are recorded as one
revision. A client that ignores `response_format` sees the same
`/v1/chat/completions` contract as rev 2.

`response_format` on `/v1/chat/completions` (section 4 table): `{"type":"json_object"}` compiles
to the trivial schema `{"type":"object"}`; `{"type":"json_schema","json_schema":{"schema":
<object>,...}}` compiles that schema (`kelpie.grammar.compile_json_schema`, xgrammar
`GrammarCompiler`, cache-enabled). Compilation happens in the handler, before `core.submit`, so
an invalid schema is a 400 with no slot taken (golden `321_err_response_format_bad_schema`,
message `response_format.json_schema.schema must be an object`). A valid grammar attaches a
`kelpie.grammar.Matcher` to the request (golden `175_chat_response_format_json_object`: the
contract server's echo model ignores it, so the response is unchanged -- the case exists to pin
that the field parses and does not break the request, not to prove masking; masking correctness
is a kelpie-py test, `test_ops_sample_respects_json_schema_grammar_mask`, against real xgrammar).
`response_format` without a chat format configured on the server -> 400 `response_format needs a
chat format (--chat-format)`.

New finish reason `grammar_dead_end` (`FinishReason`, `metrics.FINISH_REASONS`): a request whose
grammar has no legal next token (an unsatisfiable schema, or a model that drifted off the
grammar's language) is cancelled and reported finished with this reason rather than
`finished_length`/`finished_eos`/`cancelled`, none of which describe what happened. It appears
as a `kelpie_requests_finished_by_reason_total{reason="grammar_dead_end"}` counter on `/metrics`
and `/v1/kelpie/stats` (golden `510_metrics` re-recorded for the new series; `500_stats` is
separately known-stale, unrelated to this change). `finish_reason` on `/v1/chat/completions` itself still only ever reports OpenAI's three
(`stop`/`length`/`tool_calls`): `wire.public_finish_reason` maps `grammar_dead_end` to `length`
(closest fit -- generation stopped without completing the grammar's language, not on its own
terms). The engine-level distinction is not lost, only not surfaced on this response: it is
visible in `/metrics` and `/v1/kelpie/stats` via the counter above.
