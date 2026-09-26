/* xgrammar_c.h -- thin extern "C" wrapper around xgrammar's GrammarMatcher and compile path,
 * for Zig's @cImport and (via ctypes) kelpie-engine/kelpie_engine/grammar.py.
 *
 * Both halves live on this one boundary now: grammar.py compiles a schema through
 * xgrammar_tokenizer_info_create / xgrammar_compiler_create / xgrammar_compile_json_schema
 * (below), producing an xgrammar_compiled_grammar_t built by THIS build's libxgrammar.so; that
 * same handle is then safe to hand to kelpie_attach_grammar and, on the hot path, to
 * xgrammar_matcher_create/fill/accept/rollback/terminated. There is deliberately only one
 * libxgrammar.so in the process now -- grammar.py no longer imports the pip `xgrammar` wheel,
 * so there is no second, ABI-incompatible copy of the C++ core to keep straight.
 */
#ifndef KELPIE_XGRAMMAR_C_H_
#define KELPIE_XGRAMMAR_C_H_

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handles. xgrammar_compiled_grammar_t wraps a heap-allocated xgrammar::CompiledGrammar
 * (a PImpl/shared_ptr value type in xgrammar's own C++ API); xgrammar_matcher_t wraps a
 * heap-allocated xgrammar::GrammarMatcher. Neither has a defined layout on this side of the
 * boundary -- only the shim's .cc knows what's inside. */
typedef struct xgrammar_compiled_grammar_s* xgrammar_compiled_grammar_t;
typedef struct xgrammar_matcher_s* xgrammar_matcher_t;
/* xgrammar_tokenizer_info_t wraps a heap-allocated xgrammar::TokenizerInfo;
 * xgrammar_compiler_t wraps a heap-allocated xgrammar::GrammarCompiler. Compile-path handles
 * (grammar.py's compile_json_schema, run once per schema/tokenizer, not per token) -- kept
 * separate from the matcher hot path above. */
typedef struct xgrammar_tokenizer_info_s* xgrammar_tokenizer_info_t;
typedef struct xgrammar_compiler_s* xgrammar_compiler_t;

/* Wraps an xgrammar::CompiledGrammar built from this same libxgrammar.so, taking ownership of
 * a copy of it. `handle` must be a non-null CompiledGrammar* (see xgrammar_compiled_grammar_t
 * doc above). Returns NULL only if `handle` is NULL. Caller must eventually call
 * xgrammar_compiled_grammar_destroy. */
xgrammar_compiled_grammar_t xgrammar_compiled_grammar_wrap(void* handle);
void xgrammar_compiled_grammar_destroy(xgrammar_compiled_grammar_t grammar);

/* Creates a fresh matcher over `compiled_grammar` (one matcher per request; xgrammar's own
 * grammar.py factory() does the same on the Python side). Returns NULL on failure (e.g. NULL
 * compiled_grammar, or an xgrammar-internal exception during construction). */
xgrammar_matcher_t xgrammar_matcher_create(xgrammar_compiled_grammar_t compiled_grammar);
void xgrammar_matcher_destroy(xgrammar_matcher_t matcher);

/* Fills `mask` (int32[mask_len], one bit per token id: bit v of word v/32 set = token v
 * allowed) with the set of tokens acceptable as the next token, matching grammar.py's
 * XGrammarMatcher.fill / Matcher.fill contract (mask_len == words, the row width of
 * logit_masks' buffer). Builds and tears down the DLTensor view of `mask` internally --
 * DLPack never crosses this boundary. Returns false if `matcher` or `mask` is NULL, or if
 * xgrammar's FillNextTokenBitmask throws; true otherwise (mirrors FillNextTokenBitmask's own
 * "needs to be applied" return only loosely -- callers that want that exact signal should read
 * FillNextTokenBitmask's doc comment; this shim's bool is a plain success/failure flag). */
bool xgrammar_matcher_fill(xgrammar_matcher_t matcher, int32_t* mask, int32_t mask_len);

/* Advances the matcher by one accepted token. Returns false (matches grammar.py's
 * Matcher.accept contract) if the grammar has no transition for token_id, or if matcher is
 * NULL; never throws across the boundary. */
bool xgrammar_matcher_accept(xgrammar_matcher_t matcher, int32_t token_id);

/* Undoes the last n accepted tokens. n == 0 is a no-op (matches grammar.py's
 * XGrammarMatcher.rollback short-circuit). No return value: an out-of-bound n is a caller
 * bug (the Python side asserts n <= max_rollback before calling); this shim does not
 * second-guess it, matching upstream Rollback's own assert-on-misuse contract. */
void xgrammar_matcher_rollback(xgrammar_matcher_t matcher, int32_t n);

/* True if the matcher is terminated (no further tokens possible). Matches grammar.py's
 * Matcher.terminated. A NULL matcher reads as terminated (true) -- fail closed, same
 * direction as XGrammarMatcher.fill's "unfillable mask" failure mode. */
bool xgrammar_matcher_is_terminated(xgrammar_matcher_t matcher);

/* ---- compile path (grammar.py): schema -> CompiledGrammar, run once per request's schema ---- */

/* Constructs a TokenizerInfo from a vocabulary and metadata, mirroring xgrammar's Python
 * TokenizerInfo.__init__(encoded_vocab, vocab_type, vocab_size, stop_token_ids,
 * add_prefix_space) (third_party/xgrammar/python/xgrammar/tokenizer_info.py) -- the raw
 * constructor TokenizerInfo.from_huggingface eventually calls after it has done its
 * HF-tokenizer-format detection in Python (backend string parsing, sentencepiece/tiktoken
 * checks); that detection logic has no C++ counterpart and stays in grammar.py, calling this
 * only for the final construction step.
 *
 * `encoded_vocab_json` is a JSON array of `vocab_size` UTF-8 strings (token text, in id order;
 * "" for an unused id -- see from_huggingface's own placeholder-filling loop). `vocab_type` is
 * a VocabType enum value (0 = RAW, 1 = BYTE_FALLBACK, 2 = BYTE_LEVEL, xgrammar/tokenizer_info.h).
 * `stop_token_ids`/`n_stop` may be (NULL, 0) for "auto-detect" (xgrammar's own default when no
 * stop ids are given). Returns NULL on a malformed encoded_vocab_json or an xgrammar-internal
 * exception. Caller must eventually call xgrammar_tokenizer_info_destroy. */
xgrammar_tokenizer_info_t xgrammar_tokenizer_info_create(
    const char* encoded_vocab_json, int32_t vocab_type, int32_t vocab_size,
    const int32_t* stop_token_ids, int32_t n_stop, bool add_prefix_space
);
void xgrammar_tokenizer_info_destroy(xgrammar_tokenizer_info_t info);

/* Wraps xgrammar::TokenizerInfo::DetectMetadataFromHF: given a HF fast tokenizer's serialized
 * backend JSON (`tokenizer.backend_tokenizer.to_str()` on the Python side -- the common case
 * TokenizerInfo.from_huggingface handles first), returns a heap-allocated, NUL-terminated JSON
 * string `{"vocab_type": int, "add_prefix_space": bool}` for the caller to parse and feed into
 * xgrammar_tokenizer_info_create's vocab_type/add_prefix_space. Returns NULL on a malformed
 * backend_str or an xgrammar-internal exception. Caller must eventually call
 * xgrammar_free_string on a non-NULL result. */
char* xgrammar_detect_metadata_from_hf(const char* backend_str);
void xgrammar_free_string(char* s);

/* Wraps xgrammar::GrammarCompiler(tokenizer_info) (xgrammar/compiler.h); cache_enabled=true,
 * max_threads=8, max_memory_bytes unlimited -- the same defaults grammar.py's
 * compile_json_schema relies on today via xgr.GrammarCompiler(tok_info). Copies
 * `tokenizer_info` in (like xgrammar_compiled_grammar_wrap, PImpl/shared_ptr value type), so
 * `info` may be destroyed any time after this call returns. Returns NULL if `info` is NULL or
 * construction throws. Caller must eventually call xgrammar_compiler_destroy. */
xgrammar_compiler_t xgrammar_compiler_create(xgrammar_tokenizer_info_t info);
void xgrammar_compiler_destroy(xgrammar_compiler_t compiler);

/* Compiles a JSON-schema string into a CompiledGrammar (GrammarCompiler::CompileJSONSchema,
 * default options: any_whitespace=true, indent=unset, separators=unset, strict_mode=true,
 * max_whitespace_cnt=unset, any_order=false -- grammar.py's compile_json_schema has never
 * overridden any of these). `compiler`'s own cache (cache_enabled=true above) makes a repeated
 * schema across requests cheap, same as today. Returns NULL if `compiler` is NULL, `schema_json`
 * is not valid JSON Schema, or compilation throws. Caller must eventually call
 * xgrammar_compiled_grammar_destroy (same destroy fn as xgrammar_compiled_grammar_wrap's
 * result -- both produce the same handle type). */
xgrammar_compiled_grammar_t xgrammar_compile_json_schema(
    xgrammar_compiler_t compiler, const char* schema_json
);

/* TEST-ONLY: builds and returns a small, fixed CompiledGrammar directly through this same
 * libxgrammar.so -- a 10-token vocab (see smoke_test.cc) and the JSON-schema grammar
 * {"type":"object","properties":{"a":{"type":"boolean"}},"required":["a"]}. Exists so Zig's own
 * tests (kelpie-core/src/c_api.zig) can exercise kelpie_attach_grammar/fill/accept end to end
 * without a Python or C++ harness in the loop -- Zig cannot call xgrammar's C++ API directly,
 * only this shim's extern "C" surface. NOT part of the hot path; do not call from production
 * code. vocab_words (GetBitmaskSize(10)) is exposed via xgrammar_test_vocab_words() so callers
 * don't have to hardcode it. Returns NULL on failure (should not happen for this fixed input).
 * Caller owns the result (xgrammar_compiled_grammar_destroy). */
xgrammar_compiled_grammar_t xgrammar_test_compiled_grammar_create(void);
int32_t xgrammar_test_vocab_words(void);
/* Token ids for the fixed test vocab/grammar above, in xgrammar_test_compiled_grammar_create's
 * vocab order: "{" "}" "\"" "a" "\"" ":" "true" "," " " "<eos>". A matcher over the test grammar
 * accepts "{" (0) first; "true" (6) right after "{" is a reject (used to exercise
 * grammar_dead_end end to end). */
enum { XGRAMMAR_TEST_TOKEN_OPEN_BRACE = 0, XGRAMMAR_TEST_TOKEN_TRUE = 6 };

#ifdef __cplusplus
}
#endif

#endif /* KELPIE_XGRAMMAR_C_H_ */
