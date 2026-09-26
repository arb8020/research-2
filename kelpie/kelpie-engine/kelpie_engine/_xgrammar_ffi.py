"""ctypes declarations mirroring kelpie-core/xgrammar_shim/xgrammar_c.h. grammar.py is the
only caller. Loads THIS build's libxgrammar_shim (kelpie-core/xgrammar_shim/build) -- the native
Zig loop's kelpie_attach_grammar drives its matcher through the same shared object, so every
CompiledGrammar must come from here, never a pip xgrammar wheel (ABI-incompatible)."""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

# Opaque handles: void* on this side, real types only inside xgrammar_c.cc.
compiled_grammar_p = ctypes.c_void_p
matcher_p = ctypes.c_void_p
tokenizer_info_p = ctypes.c_void_p
compiler_p = ctypes.c_void_p

i32 = ctypes.c_int32
i32_p = ctypes.POINTER(i32)


def default_lib_path() -> Path:
    ext = "dylib" if sys.platform == "darwin" else "so"
    repo = Path(__file__).resolve().parents[2]
    return repo / "kelpie-core" / "xgrammar_shim" / "build" / f"libxgrammar_shim.{ext}"


def load(path: str | os.PathLike[str] | None = None) -> ctypes.CDLL:
    """Load libxgrammar_shim from `path`, $KELPIE_XGRAMMAR_LIB, or
    kelpie-core/xgrammar_shim/build."""
    resolved = Path(path or os.environ.get("KELPIE_XGRAMMAR_LIB") or default_lib_path())
    if not resolved.exists():
        raise FileNotFoundError(
            f"libxgrammar_shim not found at {resolved}; run "
            "kelpie-core/scripts/build_xgrammar.sh"
        )
    lib = ctypes.CDLL(str(resolved))
    sigs: dict[str, tuple[list[object], object]] = {
        "xgrammar_compiled_grammar_wrap": ([ctypes.c_void_p], compiled_grammar_p),
        "xgrammar_compiled_grammar_destroy": ([compiled_grammar_p], None),
        "xgrammar_matcher_create": ([compiled_grammar_p], matcher_p),
        "xgrammar_matcher_destroy": ([matcher_p], None),
        "xgrammar_matcher_fill": ([matcher_p, i32_p, i32], ctypes.c_bool),
        "xgrammar_matcher_accept": ([matcher_p, i32], ctypes.c_bool),
        "xgrammar_matcher_rollback": ([matcher_p, i32], None),
        "xgrammar_matcher_is_terminated": ([matcher_p], ctypes.c_bool),
        "xgrammar_tokenizer_info_create": (
            [ctypes.c_char_p, i32, i32, i32_p, i32, ctypes.c_bool],
            tokenizer_info_p,
        ),
        "xgrammar_tokenizer_info_destroy": ([tokenizer_info_p], None),
        "xgrammar_detect_metadata_from_hf": ([ctypes.c_char_p], ctypes.c_void_p),
        "xgrammar_free_string": ([ctypes.c_void_p], None),
        "xgrammar_compiler_create": ([tokenizer_info_p], compiler_p),
        "xgrammar_compiler_destroy": ([compiler_p], None),
        "xgrammar_compile_json_schema": (
            [compiler_p, ctypes.c_char_p],
            compiled_grammar_p,
        ),
    }
    for name, (argtypes, restype) in sigs.items():
        fn = getattr(lib, name)
        fn.argtypes = argtypes
        fn.restype = restype
    return lib
