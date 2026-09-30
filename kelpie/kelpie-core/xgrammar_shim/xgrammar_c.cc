// xgrammar_c.cc -- implementation of xgrammar_c.h. Constructs the DLTensor xgrammar's
// FillNextTokenBitmask wants from a raw int32* + length, so DLPack never crosses into Zig; the
// only DLPack-aware code in this whole path lives here.
#include "xgrammar_c.h"

#include <dlpack/dlpack.h>
#include <picojson.h>
#include <xgrammar/compiler.h>
#include <xgrammar/matcher.h>
#include <xgrammar/tokenizer_info.h>

#include <cstdlib>
#include <cstring>
#include <exception>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace {

// Owns one xgrammar::CompiledGrammar. Matches grammar.py's factory() closure: the compiled
// grammar outlives every matcher built from it, and many matchers may share one compiled
// grammar (xgrammar::CompiledGrammar is itself a PImpl/shared_ptr value type, so copying it
// here is cheap and safe to hold independently of whatever owns the original).
struct CompiledGrammarBox {
  xgrammar::CompiledGrammar grammar;
};

struct MatcherBox {
  xgrammar::GrammarMatcher matcher;
};

struct TokenizerInfoBox {
  xgrammar::TokenizerInfo info;
};

struct CompilerBox {
  xgrammar::GrammarCompiler compiler;
};

}  // namespace

extern "C" {

xgrammar_compiled_grammar_t xgrammar_compiled_grammar_wrap(void* handle) {
  if (handle == nullptr) return nullptr;
  try {
    // `handle` is expected to point at a live xgrammar::CompiledGrammar built by this same
    // libxgrammar.so (see xgrammar_c.h's ABI note). We copy-construct into our own box so the
    // box's lifetime is independent of whatever owned `handle`.
    auto* src = static_cast<xgrammar::CompiledGrammar*>(handle);
    return reinterpret_cast<xgrammar_compiled_grammar_t>(new CompiledGrammarBox{*src});
  } catch (const std::exception&) {
    return nullptr;
  }
}

void xgrammar_compiled_grammar_destroy(xgrammar_compiled_grammar_t grammar) {
  delete reinterpret_cast<CompiledGrammarBox*>(grammar);
}

xgrammar_matcher_t xgrammar_matcher_create(xgrammar_compiled_grammar_t compiled_grammar) {
  auto* box = reinterpret_cast<CompiledGrammarBox*>(compiled_grammar);
  if (box == nullptr) return nullptr;
  try {
    return reinterpret_cast<xgrammar_matcher_t>(new MatcherBox{xgrammar::GrammarMatcher(box->grammar)});
  } catch (const std::exception&) {
    return nullptr;
  }
}

void xgrammar_matcher_destroy(xgrammar_matcher_t matcher) {
  delete reinterpret_cast<MatcherBox*>(matcher);
}

bool xgrammar_matcher_fill(xgrammar_matcher_t matcher, int32_t* mask, int32_t mask_len) {
  auto* box = reinterpret_cast<MatcherBox*>(matcher);
  if (box == nullptr || mask == nullptr || mask_len <= 0) return false;

  int64_t shape[1] = {mask_len};
  DLTensor tensor{};
  tensor.data = mask;
  tensor.device = DLDevice{kDLCPU, 0};
  tensor.ndim = 1;
  tensor.dtype = xgrammar::GetBitmaskDLType();  // {kDLInt, 32, 1}
  tensor.shape = shape;
  tensor.strides = nullptr;  // nullptr = row-major/contiguous, per DLPack convention
  tensor.byte_offset = 0;

  try {
    // index = 0: this shim hands FillNextTokenBitmask a single-row [mask_len] view every call
    // (grammar.py's XGrammarMatcher.fill does the same via a length-1 torch view), never the
    // batched multi-row form.
    box->matcher.FillNextTokenBitmask(&tensor, /*index=*/0);
    return true;
  } catch (const std::exception&) {
    return false;
  }
}

bool xgrammar_matcher_accept(xgrammar_matcher_t matcher, int32_t token_id) {
  auto* box = reinterpret_cast<MatcherBox*>(matcher);
  if (box == nullptr) return false;
  try {
    return box->matcher.AcceptToken(token_id);
  } catch (const std::exception&) {
    return false;
  }
}

void xgrammar_matcher_rollback(xgrammar_matcher_t matcher, int32_t n) {
  auto* box = reinterpret_cast<MatcherBox*>(matcher);
  if (box == nullptr || n == 0) return;
  box->matcher.Rollback(n);
}

bool xgrammar_matcher_is_terminated(xgrammar_matcher_t matcher) {
  auto* box = reinterpret_cast<MatcherBox*>(matcher);
  if (box == nullptr) return true;  // fail closed: no matcher means no further tokens possible
  try {
    return box->matcher.IsTerminated();
  } catch (const std::exception&) {
    return true;
  }
}

xgrammar_tokenizer_info_t xgrammar_tokenizer_info_create(
    const char* encoded_vocab_json, int32_t vocab_type, int32_t vocab_size,
    const int32_t* stop_token_ids, int32_t n_stop, bool add_prefix_space
) {
  if (encoded_vocab_json == nullptr || vocab_size < 0 || n_stop < 0) return nullptr;
  try {
    picojson::value parsed;
    std::string err = picojson::parse(parsed, encoded_vocab_json);
    if (!err.empty() || !parsed.is<picojson::array>()) return nullptr;
    const auto& arr = parsed.get<picojson::array>();
    std::vector<std::string> vocab;
    vocab.reserve(arr.size());
    for (const auto& item : arr) {
      if (!item.is<std::string>()) return nullptr;
      vocab.push_back(item.get<std::string>());
    }
    std::optional<std::vector<int32_t>> stops;
    if (n_stop > 0) {
      if (stop_token_ids == nullptr) return nullptr;
      stops = std::vector<int32_t>(stop_token_ids, stop_token_ids + n_stop);
    }
    xgrammar::TokenizerInfo info(
        vocab, static_cast<xgrammar::VocabType>(vocab_type), vocab_size, stops, add_prefix_space
    );
    return reinterpret_cast<xgrammar_tokenizer_info_t>(new TokenizerInfoBox{std::move(info)});
  } catch (const std::exception&) {
    return nullptr;
  }
}

void xgrammar_tokenizer_info_destroy(xgrammar_tokenizer_info_t info) {
  delete reinterpret_cast<TokenizerInfoBox*>(info);
}

char* xgrammar_detect_metadata_from_hf(const char* backend_str) {
  if (backend_str == nullptr) return nullptr;
  try {
    std::string metadata = xgrammar::TokenizerInfo::DetectMetadataFromHF(backend_str);
    char* out = static_cast<char*>(std::malloc(metadata.size() + 1));
    if (out == nullptr) return nullptr;
    std::memcpy(out, metadata.data(), metadata.size());
    out[metadata.size()] = '\0';
    return out;
  } catch (const std::exception&) {
    return nullptr;
  }
}

void xgrammar_free_string(char* s) { std::free(s); }

xgrammar_compiler_t xgrammar_compiler_create(xgrammar_tokenizer_info_t info) {
  auto* box = reinterpret_cast<TokenizerInfoBox*>(info);
  if (box == nullptr) return nullptr;
  try {
    return reinterpret_cast<xgrammar_compiler_t>(new CompilerBox{xgrammar::GrammarCompiler(box->info)});
  } catch (const std::exception&) {
    return nullptr;
  }
}

void xgrammar_compiler_destroy(xgrammar_compiler_t compiler) {
  delete reinterpret_cast<CompilerBox*>(compiler);
}

xgrammar_compiled_grammar_t xgrammar_compile_json_schema(
    xgrammar_compiler_t compiler, const char* schema_json
) {
  auto* box = reinterpret_cast<CompilerBox*>(compiler);
  if (box == nullptr || schema_json == nullptr) return nullptr;
  try {
    xgrammar::CompiledGrammar compiled = box->compiler.CompileJSONSchema(schema_json);
    return reinterpret_cast<xgrammar_compiled_grammar_t>(new CompiledGrammarBox{std::move(compiled)});
  } catch (const std::exception&) {
    return nullptr;
  }
}

xgrammar_compiled_grammar_t xgrammar_test_compiled_grammar_create(void) {
  try {
    std::vector<std::string> vocab = {
        "{", "}", "\"", "a", "\"", ":", "true", ",", " ", "<eos>",
    };
    xgrammar::TokenizerInfo tok_info(
        vocab, xgrammar::VocabType::RAW, /*vocab_size=*/static_cast<int>(vocab.size()),
        /*stop_token_ids=*/std::vector<int32_t>{9}
    );
    xgrammar::GrammarCompiler compiler(tok_info);
    xgrammar::CompiledGrammar compiled = compiler.CompileJSONSchema(
        R"({"type": "object", "properties": {"a": {"type": "boolean"}}, "required": ["a"]})"
    );
    return reinterpret_cast<xgrammar_compiled_grammar_t>(new CompiledGrammarBox{compiled});
  } catch (const std::exception&) {
    return nullptr;
  }
}

int32_t xgrammar_test_vocab_words(void) { return xgrammar::GetBitmaskSize(10); }

}  // extern "C"
