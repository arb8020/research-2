"""Grammar-constrained sampling seam: a Matcher is a per-request FSM
(fill/accept/rollback/terminated) attached under the submit lock, detached at finish/cancel,
never crossing into Zig. Every CompiledGrammar must come from kelpie-core/xgrammar_shim's
libxgrammar.so, never a pip xgrammar wheel (ABI-incompatible)."""

# TODO(grammar-artifact) decided 2026-09-06: Python's only job is compile. Build TokenizerInfo +
# GrammarCompiler + mask width ONCE per model at startup (a tier-3 artifact beside the model), so
# per request is compile(schema) -> CompiledGrammar ptr -> Engine.attach_grammar. Today every
# request rebuilds TokenizerInfo from the full vocab and a fresh compiler (the "cache_enabled"
# comment in server.py is false: the cache dies with the compiler). Delete XGrammarMatcher,
# Matcher, logit_masks, compile_json_schema_from_vocab, the factory() closure; test_grammar drives
# the Zig loop (attach + step_sync, observe constrained output / grammar_dead_end). Keep the
# same-.so ABI paragraph above. Do together with TODO(vocab-words) in kelpie-http cli.py.
from __future__ import annotations

import json
import warnings
from typing import Any, Protocol

import numpy as np

from kelpie_engine import _xgrammar_ffi as ffi

MASK_BITS = 32

VOCAB_RAW, VOCAB_BYTE_FALLBACK, VOCAB_BYTE_LEVEL = 0, 1, 2

_lib: Any = None


def _load() -> Any:
    global _lib
    if _lib is None:
        _lib = ffi.load()
    return _lib


class Matcher(Protocol):
    """Four verbs a grammar-constrained request needs from its FSM. `words` is the row width
    of `fill`'s buffer (int32[words], bit v of word v // 32 set = token v allowed)."""

    words: int
    max_rollback: int  # rollback(n) is only valid for n <= this (speculative-decode K bound)

    def fill(self, mask_row: np.ndarray) -> None:
        """Write the allowed-token bitmask for the next token into `mask_row` (int32[words]),
        in place. A terminated matcher fills an EOS-only row."""
        ...

    def accept(self, token: int) -> bool:
        """Advance the FSM by one accepted token. Returns False (does not raise) if the grammar
        has no transition for `token` -- a dead-end mask row (all bits clear) makes `ops.sample`
        emit token 0 rather than a fallback sample, and the core turns a False return here into
        the request's `grammar_dead_end` finish."""
        ...

    def rollback(self, n: int) -> None:
        """Undo the last n accepted tokens (speculative-decode rejection hook; n == 0 today)."""
        ...

    def terminated(self) -> bool:
        """No further tokens are possible (the grammar is satisfied and closed, e.g. after EOS)."""
        ...


class XGrammarMatcher:
    """Adapts kelpie-core's vendored xgrammar shim to the four-verb Matcher. Holds its own
    xgrammar_matcher_t (one matcher per request, same as the old pip-wheel factory() pattern) and
    the xgrammar_compiled_grammar_t it was built from (`compiled_ptr`, kept alive for the
    matcher's lifetime and exposed so a caller can also hand it to Engine.attach_grammar).
    `words` and `max_rollback` are supplied by the compiling side
    (compile_json_schema): xgrammar's C++ matcher does not expose a rollback bound the way the
    pip wheel's GrammarMatcher.max_rollback_tokens did, so callers that need a real (non-zero)
    bound must track it themselves -- today's callers (grammar.py, tests) all use 0."""

    def __init__(self, compiled_ptr: int, words: int, max_rollback: int = 0) -> None:
        self._lib = _load()
        self.compiled_ptr = compiled_ptr
        self.words = words
        self.max_rollback = max_rollback
        self._matcher = self._lib.xgrammar_matcher_create(compiled_ptr)
        if not self._matcher:
            raise ValueError("xgrammar_matcher_create failed")

    def fill(self, mask_row: np.ndarray) -> None:
        assert mask_row.shape == (self.words,), (mask_row.shape, self.words)
        arr = np.ascontiguousarray(mask_row, dtype=np.int32)
        ptr = arr.ctypes.data_as(ffi.i32_p)
        ok = self._lib.xgrammar_matcher_fill(self._matcher, ptr, self.words)
        if not ok:
            raise ValueError("xgrammar_matcher_fill failed")
        if arr is not mask_row:
            mask_row[:] = arr

    def accept(self, token: int) -> bool:
        return bool(self._lib.xgrammar_matcher_accept(self._matcher, int(token)))

    def rollback(self, n: int) -> None:
        if n == 0:
            return
        self._lib.xgrammar_matcher_rollback(self._matcher, n)

    def terminated(self) -> bool:
        return bool(self._lib.xgrammar_matcher_is_terminated(self._matcher))

    def __del__(self) -> None:
        lib = getattr(self, "_lib", None)
        matcher = getattr(self, "_matcher", None)
        if lib is not None and matcher:
            lib.xgrammar_matcher_destroy(matcher)


def _tokenizer_info_create(
    lib: Any,
    encoded_vocab: list[str],
    vocab_type: int,
    vocab_size: int,
    stop_token_ids: list[int] | None,
    add_prefix_space: bool,
) -> int:
    vocab_json = json.dumps(encoded_vocab).encode("utf-8")
    if stop_token_ids:
        stops_arr = (ffi.i32 * len(stop_token_ids))(*stop_token_ids)
        stops_ptr = ffi.ctypes.cast(stops_arr, ffi.i32_p)
        n_stop = len(stop_token_ids)
    else:
        stops_ptr = None
        n_stop = 0
    info = lib.xgrammar_tokenizer_info_create(
        vocab_json, vocab_type, vocab_size, stops_ptr, n_stop, add_prefix_space
    )
    if not info:
        raise ValueError("xgrammar_tokenizer_info_create failed")
    return info


def _detect_metadata_from_hf(lib: Any, backend_str: str) -> dict[str, Any]:
    """-> {"vocab_type": int, "add_prefix_space": bool}, via xgrammar's own HF-backend-string
    detector (xgrammar_c.h's xgrammar_detect_metadata_from_hf)."""
    raw = lib.xgrammar_detect_metadata_from_hf(backend_str.encode("utf-8"))
    if not raw:
        raise ValueError("xgrammar_detect_metadata_from_hf failed")
    try:
        metadata_json = ffi.ctypes.string_at(raw).decode("utf-8")
    finally:
        lib.xgrammar_free_string(raw)
    return json.loads(metadata_json)


def _is_sentencepiece_tokenizer(tokenizer: Any) -> bool:
    try:
        import sentencepiece
    except ImportError:
        return False
    has_sp_model_attr = hasattr(tokenizer, "sp_model") and isinstance(
        tokenizer.sp_model, sentencepiece.SentencePieceProcessor
    )
    has_nested_sp_model_attr = (
        hasattr(tokenizer, "tokenizer")
        and hasattr(tokenizer.tokenizer, "sp_model")
        and isinstance(tokenizer.tokenizer.sp_model, sentencepiece.SentencePieceProcessor)
    ) or (hasattr(tokenizer, "tok") and isinstance(tokenizer.tok, sentencepiece.SentencePieceProcessor))
    return has_sp_model_attr or has_nested_sp_model_attr


def _tokenizer_info_from_huggingface(
    lib: Any, tokenizer: Any, vocab_size: int, stop_token_ids: list[int] | None
) -> int:
    """Mirrors xgrammar's Python TokenizerInfo.from_huggingface (tokenizer_info.py) for the
    fast-tokenizer and sentencepiece backends -- the HF-format detection stays here in Python
    (backend string parsing, sp_model probing) exactly as it did against the pip wheel; only the
    final construction step now goes through _tokenizer_info_create's shim call instead of
    `_core.TokenizerInfo(...)`. Tiktoken backends are not handled (the pip wheel's
    _is_tiktoken_tokenizer path) -- no caller in this repo has exercised one; add it if needed."""
    try:
        vocab_dict = tokenizer.get_vocab()
    except AttributeError as e:
        raise ValueError(
            f"Cannot get the vocabulary of the tokenizer {type(tokenizer)}. The tokenizer "
            "should have a get_vocab method."
        ) from e

    encoded_vocab = [""] * vocab_size
    for token, idx in vocab_dict.items():
        if idx < vocab_size:
            encoded_vocab[idx] = token

    from transformers import PreTrainedTokenizerFast

    if isinstance(tokenizer, PreTrainedTokenizerFast):
        backend_str = tokenizer.backend_tokenizer.to_str()
        if stop_token_ids is None:
            eos = getattr(tokenizer, "eos_token_id", None)
            if eos is not None:
                stop_token_ids = [eos]
            else:
                warnings.warn(
                    "When constructing a tokenizer info from a huggingface tokenizer, "
                    "stop_token_ids is neither provided by user nor found from the tokenizer. "
                    "It will be automatically detected."
                )
        metadata = _detect_metadata_from_hf(lib, backend_str)
        return _tokenizer_info_create(
            lib,
            encoded_vocab,
            metadata["vocab_type"],
            vocab_size,
            stop_token_ids,
            metadata["add_prefix_space"],
        )

    if _is_sentencepiece_tokenizer(tokenizer):
        if hasattr(tokenizer, "sp_model"):
            sp_model = tokenizer.sp_model
        elif hasattr(tokenizer, "tokenizer") and hasattr(tokenizer.tokenizer, "sp_model"):
            sp_model = tokenizer.tokenizer.sp_model
        else:
            sp_model = tokenizer.tok
        if stop_token_ids is None:
            eos = getattr(tokenizer, "eos_token_id", None)
            if eos is not None:
                stop_token_ids = [eos]
            else:
                eos_id = sp_model.eos_id()
                if eos_id != -1:
                    stop_token_ids = [eos_id]
                else:
                    warnings.warn(
                        "When constructing a tokenizer info from a huggingface tokenizer, "
                        "stop_token_ids is neither provided by user nor found from the tokenizer. "
                        "It will be automatically detected."
                    )
        vocab_type = VOCAB_BYTE_FALLBACK if "<0x0A>" in vocab_dict else VOCAB_RAW
        return _tokenizer_info_create(
            lib, encoded_vocab, vocab_type, vocab_size, stop_token_ids, True
        )

    raise ValueError(f"Unsupported tokenizer type: {type(tokenizer)}")


def compile_json_schema(
    schema: dict[str, Any] | str, tokenizer: Any, vocab_size: int | None = None
) -> Any:
    """-> a zero-arg factory producing a fresh XGrammarMatcher for the schema, one per request.
    Compiles through kelpie-core's vendored xgrammar shim (this module's header comment) so the
    resulting matcher's `compiled_ptr` is safe to also hand to Engine.attach_grammar. Building
    the compiler needs the tokenizer once, so this compiles eagerly and returns a cheap factory
    rather than doing the compile work per-request; the shim's GrammarCompiler is
    cache_enabled=True (xgrammar_c.cc), so a repeated schema/tool array is cheap regardless.
    Raises ValueError on an invalid schema or tokenizer -- the caller (HTTP handler) turns that
    into a 400 before any slot is taken.

    `vocab_size` MUST be the model's logits width (`cfg.vocab`), not the tokenizer's: a
    checkpoint's vocab is commonly padded above the tokenizer's (Qwen3: 151936 vs 151643), and
    the logit mask is sized from `cfg.vocab`. Sizing the matcher from the
    tokenizer instead makes `fill` assert on a row 9 words too wide. Defaults to the tokenizer's
    for callers with no model handy (tests); xgrammar pads the extra ids as disallowed."""
    lib = _load()
    if vocab_size is None:
        vocab_size = getattr(tokenizer, "vocab_size", None)
    assert vocab_size is not None, "tokenizer must expose vocab_size"

    info = _tokenizer_info_from_huggingface(lib, tokenizer, vocab_size, None)
    try:
        return _compile_json_schema_over_info(lib, info, schema, vocab_size)
    finally:
        lib.xgrammar_tokenizer_info_destroy(info)


def compile_json_schema_from_vocab(
    schema: dict[str, Any] | str,
    encoded_vocab: list[str],
    vocab_size: int | None = None,
    *,
    vocab_type: int = VOCAB_RAW,
    stop_token_ids: list[int] | None = None,
    add_prefix_space: bool = False,
) -> Any:
    """Like compile_json_schema, but for a caller with a raw vocab list instead of an HF
    tokenizer object -- skips the from_huggingface format-detection path entirely (fixed-vocab
    test fixtures; a tokenizer-less caller that already has encoded_vocab/vocab_type from
    elsewhere, e.g. a cached TokenizerInfo.dump_metadata). `vocab_size` defaults to
    len(encoded_vocab), same as xgrammar's own TokenizerInfo default."""
    lib = _load()
    size = len(encoded_vocab) if vocab_size is None else vocab_size
    info = _tokenizer_info_create(lib, encoded_vocab, vocab_type, size, stop_token_ids, add_prefix_space)
    try:
        return _compile_json_schema_over_info(lib, info, schema, size)
    finally:
        lib.xgrammar_tokenizer_info_destroy(info)


def _compile_json_schema_over_info(
    lib: Any, info: Any, schema: dict[str, Any] | str, vocab_size: int
) -> Any:
    """Shared compile_json_schema tail: an already-built xgrammar_tokenizer_info_t -> a zero-arg
    XGrammarMatcher factory. Compiles through kelpie-core's vendored xgrammar shim (this module's
    header comment) so the resulting matcher's `compiled_ptr` is safe to also hand to
    Engine.attach_grammar. Building the compiler needs the tokenizer info once, so this compiles
    eagerly and returns a cheap factory rather than doing the compile work per-request; the
    shim's GrammarCompiler is cache_enabled=True (xgrammar_c.cc), so a repeated schema/tool array
    is cheap regardless. Raises ValueError on an invalid schema or tokenizer info -- the caller
    (HTTP handler) turns that into a 400 before any slot is taken."""
    words = (vocab_size + MASK_BITS - 1) // MASK_BITS
    compiler = lib.xgrammar_compiler_create(info)
    if not compiler:
        raise ValueError("xgrammar_compiler_create failed")

    schema_str = schema if isinstance(schema, str) else json.dumps(schema)
    compiled = lib.xgrammar_compile_json_schema(compiler, schema_str.encode("utf-8"))
    # compiler's own cache (cache_enabled=true) keeps a repeated schema cheap; safe to destroy
    # the compiler handle itself once this one compile is done, same as the old
    # xgr.GrammarCompiler-per-call-site lifetime.
    if not compiled:
        lib.xgrammar_compiler_destroy(compiler)
        raise ValueError(f"failed to compile JSON schema: {schema_str[:200]}")

    def factory() -> XGrammarMatcher:
        # xgrammar_compiled_grammar_wrap copy-constructs its own box (xgrammar_c.cc), so the
        # matcher's owning handle is independent of `compiled` here; each factory() call makes
        # its own wrapped copy rather than sharing `compiled` across matchers/requests.
        wrapped = lib.xgrammar_compiled_grammar_wrap(compiled)
        if not wrapped:
            raise ValueError("xgrammar_compiled_grammar_wrap failed")
        return XGrammarMatcher(wrapped, words)

    # `compiled_ptr`: the raw xgrammar_compiled_grammar_t this factory compiles matchers from,
    # for a caller that drives the grammar in Zig (Engine.attach_grammar /
    # kelpie_attach_grammar). Same handle type factory()'s XGrammarMatcher wraps
    # (xgrammar_compiled_grammar_wrap copies it either way), so passing this one straight to
    # attach_grammar is exactly as safe as going through factory() first and reading
    # matcher.compiled_ptr off the result -- just without building a Python matcher nobody
    # will call fill/accept/rollback on. `words`: the mask row width the caller compiled for
    # (== KelpiePlan.logit_mask's row width iff this engine's vocab_words matches).
    factory.compiled_ptr = compiled  # type: ignore[attr-defined]
    factory.words = words  # type: ignore[attr-defined]
    return factory


def logit_masks(req_ids: list[int], grammars: dict[int, Matcher], words: int) -> np.ndarray:
    """int32[len(req_ids), words], all-ones for a request with no grammar (or none planned) so
    the sampler's mask application is a no-op branch, never a host conditional. This is what
    Graph.fill_logit_mask copies into the logit_mask leaf between launch_forward and launch_sample
    (docs/grammar-design.md section 2 -- not wired into StepBatch/Zig by this change)."""
    mask = np.full((len(req_ids), words), -1, dtype=np.int32)  # 0xFFFFFFFF per word
    for i, rid in enumerate(req_ids):
        g = grammars.get(rid)
        if g is not None:
            g.fill(mask[i])
    return mask
