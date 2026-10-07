"""pytest configuration for box tests."""


def pytest_configure(config):
    config.addinivalue_line("markers", "live: requires real API credentials")


def pytest_collection_modifyitems(config, items):
    # Skip @live tests unless --live is passed
    if not config.getoption("--live", default=False):
        skip = __import__("pytest").mark.skip(reason="use --live to run")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip)


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run live API tests")
    parser.addoption("--provider", default="local", help="the provider test_sdk runs on: local, modal, runpod")
