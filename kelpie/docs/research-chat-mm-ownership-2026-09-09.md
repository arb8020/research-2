# Who owns chat rendering, tool parsing, and multimodal preprocessing?

A survey of vLLM, SGLang, and TokenSpeed, read against kelpie's "the model is the plugin"
question: for each of (a) chat-template rendering, (b) tool-call parsing + the per-family stop
set, and (c) multimodal preprocessing, does the **model definition**, the **HTTP/serving
layer**, or a **third registry** own it -- and how does serving discover which one applies to a
loaded checkpoint?

Sources read as code, not docs:
- vLLM `/tmp/vllm-survey` (sparse: `vllm/{multimodal,entrypoints,model_executor/models,transformers_utils,tool_parsers,reasoning,config}`)
- SGLang (github.com/sgl-project/sglang)
- TokenSpeed `/tmp/tokenspeed-survey` (github.com/lightseekorg/tokenspeed)

---

## vLLM

| Concern | Owner | Discovery mechanism |
|---|---|---|
| Chat template | **Serving** -- `vllm/renderers/hf.py:263` `resolve_chat_template` | 4-tier fallback: `--chat-template` flag -> AutoProcessor `chat_template` -> `tokenizer_config.json` -> vLLM's own fallback dict keyed on **`hf_config.model_type` string** (`vllm/transformers_utils/chat_templates/registry.py:26`, 8 `.jinja` files) |
| MM placeholder string | **Model class** -- `vllm/entrypoints/chat_utils.py:645` calls `self.model_cls.get_placeholder_str(modality, num_items)` | `get_model_cls(model_config)` (`chat_utils.py:583-587`) resolves `config.architectures` -> class. The single point where rendering reaches into the model |
| Tool-call parsing | **Serving** -- `vllm/tool_parsers/` (52 parser files); `ToolParserManager` at `vllm/tool_parsers/abstract_tool_parser.py:222`, `register_module` at `:317` | `--tool-call-parser <string>`, validated against `ToolParserManager.list_registered()` (`vllm/entrypoints/launchers/cli_args.py:216`). **No checkpoint auto-detection** |
| Stop set / EOS | **Checkpoint data** -- `vllm/config/model.py:1690` `try_get_generation_config` | `generation_config="auto"` reads `generation_config.json` (`model.py:1734`); overridable via `--override-generation-config`. The model class contributes nothing |
| MM preprocessing | **Model class** -- `@MULTIMODAL_REGISTRY.register_processor(...)` stamps `_processor_factory` **onto the class** (`vllm/multimodal/registry.py:178`) | `_get_model_cls` (`registry.py:188-198`): `architectures` -> model class -> `hasattr(model_cls, "_processor_factory")`. Capability flags are `ClassVar`s (`models/interfaces.py:164` `supports_multimodal`), checked structurally by `getattr` (`interfaces.py:595`) |
| MM pixel work | **HF `AutoProcessor`** | `ProcessingInfo.get_hf_processor` / `call_hf_processor` (`vllm/multimodal/processing/context.py:208,314`) -- from `preprocessor_config.json`. vLLM's own abstract surface is only 2 methods: `_get_mm_fields_config` and `_get_prompt_updates` (`processing/processor.py:1085,1094`) |

Note the registry is not really a side table: the decorator writes onto the model class, so
multimodal genuinely belongs to the model definition and the decorator is only syntax. Contrast
with chat templates, whose fallback *is* a side table keyed on a config string.

## SGLang

| Concern | Owner | Discovery mechanism |
|---|---|---|
| Chat template | **Serving** -- `python/sglang/srt/parser/template_manager.py:131`; registry `parser/conversation.py:502` (`chat_templates: Dict[str, Conversation]`) | `--chat-template` (registry key, `.jinja` file, or JSON) -> else **model-path regex** predicate chain: `register_conv_template_matching_function` (`conversation.py:516`) appends to an ordered list; `get_conv_template_by_model_path` (`:520-524`) returns the first match. Predicates regex the checkpoint's *directory name* (e.g. `conversation.py:1140` `match_internvl`), some falling back to `config.json` `model_type` via `get_model_type` (`:1127`). Else the HF tokenizer template |
| Tool / reasoning parsing | **Serving** -- `srt/function_call/` (40 detector files); hardcoded dict `ToolCallParserEnum` (`function_call/function_call_parser.py:65`), dispatched at `:104` | `--tool-call-parser` string; `"auto"` sniffs the **rendered jinja text + tokenizer vocab** (`parser/template_detection.py:702`) -- the only real checkpoint-derived auto-detect in either mature engine |
| Stop set | **Welded to the chat template** -- `Conversation.stop_str` (`conversation.py:94`), a field of each registered template (e.g. `:767`, `:781`, `:795`) | Only travels the conversation-template path (`conversation.py:548,617`). The default HF-jinja path gets no per-family stop strings (`serving_chat.py:1434`) |
| MM preprocessing | **Third registry** -- `srt/multimodal/processors/*`, each subclass declaring `models = [...]` of **model architecture classes** (`base_processor.py:194`; e.g. `qwen_vl.py:292`) | `import_processors` (`srt/managers/multimodal_processor.py:16-41`) `pkgutil`-walks the package, reads each subclass's `models`, builds `PROCESSOR_MAPPING[arch_cls] = processor_cls`. Matched by **class name** against `hf_config.architectures` (`:55-57`). Dependency is **inverted vs vLLM**: the processor imports the model class (`processors/internvl.py:16-17`) |
| MM forward-side | **Model class** -- `pad_input_ids`, `get_image_feature` (`srt/models/qwen2_5_vl.py:763,767`) | Resolved by **string interpolation** on the modality: `getattr(model, f"get_{modality}_feature")` |

## TokenSpeed

| Concern | Owner | Discovery mechanism |
|---|---|---|
| Chat template | **Out of process** -- the Rust `smg` gateway. The Python engine never renders | `cli/_argsplit.py:38,70` forwards `--chat-template` to the gateway verbatim. No in-repo Jinja/conversation registry at all. One exception: DeepSeek-V4 `importlib`s an `encode_messages` **from inside the checkpoint directory** (`hf_transformers_utils.py:613-676`) -- template as shipped *code* |
| Tool-call parsing | **Out of process** (gateway) | A substring sniff on the model id picks one gateway default (`serve_smg.py:388`). No parser zoo in the engine |
| Stop set | **Checkpoint data** -- `configs/model_config.py:777` unions `config.json` + `generation_config.json` eos ids | Plus one hardcoded Llama-3 `<\|eom_id\|>` special case |
| MM preprocessing | **Out of process** -- the gateway ships precomputed tensors; the engine "never preprocesses images" (`runtime/engine/async_llm.py:159`) | No processor registry, no `AutoProcessor` anywhere. EPD disaggregation gives encode its own workers (`runtime/epd/encode_worker.py`) |
| MM forward-side | **Model class** -- `get_image_feature`, `pad_input_ids` (`models/qwen3_omni.py:224`) | `EntryClass` module export + `pkgutil` scan; `config.architectures` -> class (`models/registry.py:88`) |

---

## Synthesis

**Where all three converge.** One boundary is genuinely stable: the split between *preprocessing*
and *execution*. Nobody makes the model definition decode a JPEG. Pixel math is HF's
`AutoProcessor` (vLLM, SGLang) or another process entirely (TokenSpeed). What the model class
universally owns is the GPU-side half -- the vision tower, `get_image_feature`, and
placeholder-token padding -- because that is inseparable from the forward pass. All three also
read stop tokens from `generation_config.json` rather than code, SGLang being the partial
exception.

**Where they disagree, sharply.** Chat templates and tool parsing have no agreed owner. vLLM keys
template fallbacks on the `model_type` string; SGLang regex-matches the *filesystem path* of the
checkpoint (rename a directory and rendering changes); TokenSpeed refuses the problem and pushes
it across a process boundary. For tool parsing, vLLM and SGLang each maintain 52 and 40
hand-written per-family detectors chosen by an operator-typed string -- the largest pile of
per-family code in either repo, and the one that fails silently, since a wrong parser yields
unparsed text rather than an error.

**What each pays.**
- *vLLM*: the decorator stamping `_processor_factory` onto the model class means multimodal
  really belongs to the model definition; the price is that `chat_utils.py` must import the model
  loader and build a processor just to render a message -- a heavy frontend->executor dependency
  -- and a new MM model means ~6 coupled artifacts held together by a structural `Protocol` that
  fails at request time, not registration time.
- *SGLang*: the inverted dependency (processor lists the model class) lets a contributor add a
  family by appending to a list without touching shared dispatch, plausibly why it scaled to 40+
  families. It pays in silent failure: `import_processors` swallows import errors into
  "unsupported model" (`multimodal_processor.py:22-24`), and `get_{modality}_feature` is built by
  string interpolation, so a typo is a no-op. `stop_str`-on-`Conversation` means per-family stop
  strings quietly vanish on the jinja path that is now the default.
- *TokenSpeed*: buys the cleanest core -- no Jinja, no `AutoProcessor`, no parser zoo in the hot
  path -- at the cost of an unversioned, stringly-typed cross-process contract.
  `input_processor.py:255-278` exists solely to recompute an mrope field the gateway forgets to
  send, which had been silently degrading OCR accuracy.

## Data vs code: what HF ships in the checkpoint

The trend is toward the checkpoint. `tokenizer_config.json` `chat_template`,
`preprocessor_config.json`, and `generation_config.json` now carry most of (a) and (c) as shipped
*data*; the in-repo registries are shrinking fallback sets for checkpoints that ship nothing --
vLLM is down to 8 `.jinja` files, all for older/vision checkpoints predating the convention.

Tool-call parsing is the outlier that has **not** moved into the checkpoint. There is no standard
HF field describing a model's tool-call surface syntax, which is exactly why both mature engines
still carry ~50 hand-written parsers plus a mandatory string flag. TokenSpeed's DeepSeek-V4 case
is the interesting edge: the checkpoint ships executable `encode_messages` Python, i.e. template
as code-in-the-weights rather than data-in-the-weights.

## Caveats

- SGLang paths are from `worktrees/client-only-agentic`; the top-level `sglang-upstream` checkout
  has no `python/sglang/srt/` of its own, so line numbers may drift from upstream `main`.
- vLLM was read at `main` tip with a sparse checkout; `vllm/tool_parsers` and `vllm/renderers`
  are recently promoted to top-level packages (they were under `entrypoints/openai/` before), so
  older references will not match.
- File:line refs for TokenSpeed and parts of vLLM/SGLang come from delegated sub-surveys; the
  vLLM multimodal-registry, chat-template-registry, and SGLang conversation/processor mechanisms
  were verified directly.

---

## kelpie today, read against this

Stated factually; no recommendation implied.

- **`SmolVLMAdapter` (`kelpie-http/kelpie_http/vlm.py:27`) does pixel decode+tile, placeholder
  expansion, and chat rendering in one class.** Its `prepare` (`:34`) calls
  `decode_image` + `preprocess` for tiles (`:43`), `chat_prompt` for the prompt text (`:49`), and
  builds `MultimodalInput(placeholder_positions=..., data=tiles)` (`:57`). The module docstring
  states the adapter owns preprocessing "so the handler stays at submit/poll/cancel". The three
  concerns that vLLM/SGLang split across a serving renderer, a processor registry, and the model
  class sit in one HTTP-layer class here -- though the actual work is delegated to
  `kelpie_models.smolvlm`, which is the model module.
- **`CHAT_FAMILY` on the model module plays the role of `--tool-call-parser`.** It is one of four
  model facts (`kelpie-models/kelpie_models/facts.py:16`), documented as "the chat template +
  tool-parser family" (`facts.py:4`), declared per model module (`llama.py:22` `"llama-3"`,
  `gpt_oss.py:29` `"gpt-oss"`, `smolvlm.py:37` `"default"`). It selects renderer, parser, *and*
  stop set together: `resolve` (`chat/__init__.py:50-70`) fans one family string out to
  `make_render`, `parser_factory`, and `stop_token_ids`. Where vLLM/SGLang make this an operator
  string flag defaulting to nothing, kelpie makes it a declaration on the model, with
  `--chat-format` as the override (`cli.py:75`).
- **`chat.family_of(model_name)` (`chat/__init__.py:73`) is name-sniffing like SGLang's path
  regex** -- an ordered `[(pattern, family)]` list (`:78-85`) matched against the basename of the
  model id, first match wins, exactly SGLang's `matching_function_registry` shape. One structural
  difference: in kelpie it is the *last-resort fallback*, not the primary path --
  `family = chat_format or family_of(model_name)` (`:55`), so `CHAT_FAMILY` wins when a model
  module exists, and the docstring calls `family_of` "the last-resort guess for a bare HF id
  nobody has written a model file for yet". Unresolvable local paths raise rather than guess
  (`:56-60`).
- Stop sets are family-derived rather than read from `generation_config.json`:
  `stop_token_ids(family, tokenizer)` (`chat/render/__init__.py:42-52`) hardcodes gpt-oss's
  `<|return|>`/`<|call|>`, special-cases SmolVLM's `<end_of_utterance>` under `"default"`, and
  otherwise asks the family's renderer. This is closer to SGLang's `stop_str`-on-template than to
  vLLM/TokenSpeed's checkpoint-data approach.
