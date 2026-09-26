"""The golden fixture is the cross-language contract; drift must be deliberate.

This is the test that would have caught the span/metric field-set bug: the
committed fixture is what the TypeScript parser reads, so if Python's on-disk
shape changes, the bytes change and this fails.
"""

from __future__ import annotations

from pathlib import Path

from observe.scripts.golden import FIXTURE, generate

REGENERATE = "run observe/scripts/golden.py and review the diff"


def test_fixture_regenerates_byte_for_byte(tmp_path: Path) -> None:
    fresh = tmp_path / "golden.jsonl"
    generate(fresh)
    assert fresh.read_bytes() == FIXTURE.read_bytes(), (
        f"golden.jsonl no longer matches what the emitters produce — {REGENERATE}"
    )


def test_fixture_is_deterministic(tmp_path: Path) -> None:
    """Two generations agree, so a diff always means a real contract change."""
    first, second = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    generate(first)
    generate(second)
    assert first.read_bytes() == second.read_bytes(), (
        f"golden.py is not deterministic — {REGENERATE}"
    )
