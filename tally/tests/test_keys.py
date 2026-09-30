import hashlib
from pathlib import Path

from tally import Ctx, Hashed, KeyFn, Step, ast_fp, key_stability, keys, value_fp


def good(ctx: Ctx, x: int, *, out: Path) -> int:
    return x + 1


def hash_key(step: Step, args: tuple, kwargs: dict) -> str:
    """BAD: str hash() is salted per process (PYTHONHASHSEED)."""
    return hashlib.sha256(str(hash(step.name)).encode()).hexdigest()


def id_key(step: Step, args: tuple, kwargs: dict) -> str:
    """BAD: id() is a memory address."""
    return hashlib.sha256(str(id(step)).encode()).hexdigest()


GOOD = Step(good)
BAD_HASH = Step(good, key=KeyFn("key", hash_key))
BAD_ID = Step(good, key=KeyFn("key", id_key))


def test_builtin_key_is_stable_across_processes() -> None:
    assert len(set(key_stability("test_keys:GOOD", (41,)))) == 1


def test_hash_based_key_is_flagged() -> None:
    assert len(set(key_stability("test_keys:BAD_HASH", (41,)))) > 1


def test_id_based_key_is_flagged() -> None:
    assert len(set(key_stability("test_keys:BAD_ID", (41,)))) > 1


def _v1() -> object:
    def f(x: int) -> int:
        return x + 1
    return f


def _v2() -> object:
    def f(x: int) -> int:
        # a comment
        return (x
                + 1)
    return f


def _v3() -> object:
    def f(x: int) -> int:
        return x + 2
    return f


def test_ast_fp_ignores_comments_and_formatting() -> None:
    assert ast_fp(_v1()) == ast_fp(_v2())
    assert ast_fp(_v1()) != ast_fp(_v3())


def test_value_fp_is_canonical() -> None:
    assert value_fp({"a": 1, "b": 2}) == value_fp({"b": 2, "a": 1})
    assert value_fp([1, 2]) != value_fp({"dict": [1, 2]})


def test_recipe_vs_bytes_read_different_handle_fields() -> None:
    a = Hashed(key="k" * 64, path="/x", digest="d" * 64)
    b = Hashed(key="K" * 64, path="/y", digest="d" * 64)  # different recipe, same bytes
    assert keys.bytes(GOOD, (a,), {}) == keys.bytes(GOOD, (b,), {})
    assert keys.recipe(GOOD, (a,), {}) != keys.recipe(GOOD, (b,), {})
