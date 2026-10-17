"""pytest configuration for box tests, and the fixtures every feature test takes: which provider
(--provider), how slow it is (scale), and launch on it."""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from box import sdk
from box.sdk import Provider
from box.tests import providers


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real API credentials")
    config.addinivalue_line("markers", "needs(what): skipped on a provider that cannot do what (providers.CANNOT)")


def pytest_collection_modifyitems(config, items):
    # Skip @live tests unless --live is passed
    if not config.getoption("--live", default=False):
        skip = __import__("pytest").mark.skip(reason="use --live to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)
    cannot = providers.CANNOT.get(config.getoption("--provider"), {})
    for item in items:
        for mark in item.iter_markers("needs"):
            (what,) = mark.args
            if what in cannot:
                item.add_marker(pytest.mark.skip(reason=cannot[what]))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run live API tests")
    parser.addoption("--provider", default="local", help="the provider test_sdk runs on: local, modal, runpod, colab-fake")


@pytest.fixture
def name(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--provider")


@pytest.fixture
def provider(name: str, tmp_path: Path) -> Iterator[Provider]:
    p = providers.make(name, tmp_path / "machines")
    yield p
    p.close()  # the test made it, the test closes it (Modal: joins its loop thread)


@pytest.fixture
def scale(name: str) -> float:
    return providers.SCALE[name]


@pytest.fixture
def launch(provider: Provider, name: str) -> Callable[..., sdk.Session]:
    return lambda **kw: sdk.launch(provider, **providers.launch_kw(name), **kw)
