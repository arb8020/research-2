// Standalone smoke test for xgrammar_c.h -- NOT wired into any build target by default
// (build/run manually, see kelpie-core/scripts/build_xgrammar.sh --smoke-test). Exercises the
// full path: compile a tiny JSON-schema grammar via xgrammar's own C++ API (standing in for
// what Python's compile_json_schema does today), wrap the CompiledGrammar through the shim,
// then drive fill/accept/rollback/terminated exactly as the Zig step loop would.
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>

#include <xgrammar/compiler.h>
#include <xgrammar/matcher.h>
#include <xgrammar/tokenizer_info.h>

#include "xgrammar_c.h"

int main() {
  // A minimal byte-level vocab: enough tokens to spell {"a":true} plus a stop token.
  std::vector<std::string> vocab = {
      "{", "}", "\"", "a", "\"", ":", "true", ",", " ", "<eos>",
  };
  xgrammar::TokenizerInfo tok_info(vocab, xgrammar::VocabType::RAW, /*vocab_size=*/vocab.size(),
                                    /*stop_token_ids=*/std::vector<int32_t>{9});
  xgrammar::GrammarCompiler compiler(tok_info);
  xgrammar::CompiledGrammar compiled = compiler.CompileJSONSchema(
      R"({"type": "object", "properties": {"a": {"type": "boolean"}}, "required": ["a"]})"
  );

  xgrammar_compiled_grammar_t g = xgrammar_compiled_grammar_wrap(&compiled);
  assert(g != nullptr && "wrap failed");

  xgrammar_matcher_t m = xgrammar_matcher_create(g);
  assert(m != nullptr && "matcher create failed");
  assert(!xgrammar_matcher_is_terminated(m));

  int32_t mask_len = xgrammar::GetBitmaskSize(static_cast<int>(vocab.size()));
  std::vector<int32_t> mask(mask_len);

  bool ok = xgrammar_matcher_fill(m, mask.data(), mask_len);
  assert(ok && "fill failed");
  // Grammar starts with '{' (token 0); confirm bit 0 is set and check accept/reject behavior.
  bool token0_allowed = (mask[0] & (1 << 0)) != 0;
  assert(token0_allowed && "expected '{' to be allowed as the first token");

  bool accepted = xgrammar_matcher_accept(m, 0);  // "{"
  assert(accepted && "expected '{' to be accepted");

  // Rollback should be a documented no-op contract for n == 0, and should restore state for
  // n == 1 (undo the accept above).
  xgrammar_matcher_rollback(m, 1);
  ok = xgrammar_matcher_fill(m, mask.data(), mask_len);
  assert(ok);
  assert(((mask[0] & (1 << 0)) != 0) && "expected '{' allowed again after rollback");

  // Re-accept and confirm a clearly-wrong token (e.g. "true" right after "{") is rejected.
  accepted = xgrammar_matcher_accept(m, 0);  // "{"
  assert(accepted);
  bool bad_accept = xgrammar_matcher_accept(m, 6);  // "true" -- not valid right after "{"
  assert(!bad_accept && "expected \"true\" to be rejected right after '{'");

  xgrammar_matcher_destroy(m);
  xgrammar_compiled_grammar_destroy(g);

  std::printf("xgrammar_c smoke test: OK\n");
  return 0;
}
