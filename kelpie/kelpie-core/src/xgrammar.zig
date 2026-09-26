//! @cImport of xgrammar_shim/xgrammar_c.h -- the only file that touches xgrammar (design-rules.md
//! #7, messy boundary / sharp interior, same discipline as cuda.zig for the CUDA driver API).
//! c_api.zig calls the thin Zig wrappers below; nothing else in kelpie-core imports this file.
//!
//! The xgrammar_compiled_grammar_t this expects to wrap must come from THIS build's
//! libxgrammar.so (kelpie-core/xgrammar_shim), built by kelpie-core/scripts/build_xgrammar.sh.
//! kelpie-engine/kelpie_engine/grammar.py compiles its grammars through this same shared lib now (via
//! ctypes, xgrammar_c.h's compile-path functions), so every CompiledGrammar in the process is
//! built by this one .so.

const c = @cImport({
    @cInclude("xgrammar_c.h");
});

pub const CompiledGrammar = c.xgrammar_compiled_grammar_t;
pub const Matcher = c.xgrammar_matcher_t;

pub const compiledGrammarWrap = c.xgrammar_compiled_grammar_wrap;
pub const compiledGrammarDestroy = c.xgrammar_compiled_grammar_destroy;
pub const matcherCreate = c.xgrammar_matcher_create;
pub const matcherDestroy = c.xgrammar_matcher_destroy;
pub const matcherFill = c.xgrammar_matcher_fill;
pub const matcherAccept = c.xgrammar_matcher_accept;
pub const matcherRollback = c.xgrammar_matcher_rollback;
pub const matcherIsTerminated = c.xgrammar_matcher_is_terminated;

// TEST-ONLY (see xgrammar_c.h's doc comment): a fixed compiled grammar Zig's own tests can
// attach without any Python/C++ harness. Never called from production code.
pub const testCompiledGrammarCreate = c.xgrammar_test_compiled_grammar_create;
pub const testVocabWords = c.xgrammar_test_vocab_words;
pub const test_token_open_brace: i32 = c.XGRAMMAR_TEST_TOKEN_OPEN_BRACE;
pub const test_token_true: i32 = c.XGRAMMAR_TEST_TOKEN_TRUE;
