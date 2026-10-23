import json
from pathlib import Path

import pytest

from tally import Handle, Ok, Step, StepCtx, effect_key, invalidate, open_store, rerun, start

SOURCE = effect_key("source", 0)


def source(ctx: StepCtx, *, idem_key: str, out: Path) -> Ok[str]:
    return Ok("raw")


def use(ctx: StepCtx, raw: Handle, *, out: Path) -> str:
    return ctx.load(raw).upper()


USE = Step(use)
USE_KEY = USE.key(USE, (Handle(SOURCE, ""),), {})


def chain(root: Path) -> list[str]:
    ctx = start(open_store(root))
    assert ctx.load(ctx.fetch(USE, ctx.effect("source", source, inputs=0, on_unknown=rerun))) == "RAW"
    return ctx.ran


def check(root: Path, downstream: bool, manifest: dict, archived: list[str], reran: list[str]) -> None:
    assert chain(root) == [SOURCE, "use"]
    archive = invalidate(open_store(root), [SOURCE], downstream=downstream)
    written = json.loads((archive / "manifest.json").read_text())
    seen = {
        "roots": written["roots"],
        "downstream": written["downstream"],
        "effects": [row["key"] for row in written["effects"]],
        "derivations": [row["key"] for row in written["derivations"]],
    }
    assert seen == manifest, downstream
    assert sorted(path.relative_to(archive).as_posix() for path in archive.glob("*/*")) == archived, downstream
    assert chain(root) == reran, downstream


def test_invalidate_archives_and_reruns(tmp_path: Path) -> None:
    table = [
        (True, {"roots": [SOURCE], "downstream": True, "effects": [SOURCE], "derivations": [USE_KEY]},
         [f"blobs/{USE_KEY}", f"effects/{SOURCE}"], [SOURCE, "use"]),
        (False, {"roots": [SOURCE], "downstream": False, "effects": [SOURCE], "derivations": []},
         [f"effects/{SOURCE}"], [SOURCE]),
    ]
    for downstream, manifest, archived, reran in table:
        check(tmp_path / str(downstream), downstream, manifest, archived, reran)


def test_invalidate_unknown_key(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="not in store"):
        invalidate(open_store(tmp_path), ["nope@00000000"])
