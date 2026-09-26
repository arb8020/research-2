"""`box gc`'s staleness rule for volume cache keys: pure, over a fake recursive listing."""

from __future__ import annotations

from box.gc import DAY_S
from box.kelpie.gc import stale_keys

NOW = 100 * DAY_S
WEEK = 7 * DAY_S


def _key(name: str, *, complete: float | None, used: float | None, so: float) -> list[tuple[str, float]]:
    base = f"builds/libkelpie/{name}"
    rows = [(base, so), (f"{base}/libkelpie.so", so)]
    rows += [(f"{base}/.complete", complete)] if complete is not None else []
    rows += [(f"{base}/.used", used)] if used is not None else []
    return rows


def test_used_long_ago_is_stale_recently_used_is_not():
    listing = _key("old", complete=10 * DAY_S, used=NOW - 8 * DAY_S, so=10 * DAY_S)
    listing += _key("hot", complete=10 * DAY_S, used=NOW - DAY_S, so=10 * DAY_S)
    assert [k for k, _ in stale_keys(listing, WEEK, NOW)] == ["builds/libkelpie/old"]


def test_complete_key_without_used_is_never_stale():
    """A checkout from before .used may use it daily; its .complete says only when it was built."""
    assert stale_keys(_key("legacy", complete=DAY_S, used=None, so=DAY_S), WEEK, NOW) == []


def test_dead_build_ages_by_its_newest_file():
    dead = _key("dead", complete=None, used=None, so=NOW - 30 * DAY_S)
    fresh = _key("building", complete=None, used=None, so=NOW - 60)
    assert [k for k, _ in stale_keys(dead + fresh, WEEK, NOW)] == ["builds/libkelpie/dead"]


def test_other_trees_on_the_volume_are_ignored():
    listing = [("builds/other/k/.used", 0.0), ("hf/hub/models--x/.used", 0.0), ("builds", 0.0)]
    assert stale_keys(listing, WEEK, NOW) == []
