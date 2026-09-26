"""`box run` ownership (labels) and the kelpie job's ShellBox: pure, no provider calls."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from box import runs
from box.kelpie.inside import TIMEOUT_EXIT, ShellBox
from box.provider import Offering, Status
from box.recipe import plain

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
OFFERING = Offering(provider="fake", id="A10G", gpu_model="A10G", gpu_count=2, gpu_memory_gb=24, price_hr=None)


class LabelledBox:
    def __init__(self, labels: dict[str, str]):
        self.provider_id = "fake-1"
        self.offering = OFFERING
        self.status = Status.RUNNING
        self.labels = labels


def test_labels_round_trip_to_a_run():
    recipe = plain(None, {"kelpie-a1": "/data"}, "echo 'hi there'", 60)
    run = runs.parse(LabelledBox(runs.labels(recipe, "echo 'hi there'", NOW)))
    assert run is not None
    assert (run.gpu, run.cmd, run.started, run.limit_s) == ("A10G:2", "echo 'hi there'", NOW, recipe.box_timeout)


def test_a_box_run_did_not_launch_is_not_ours():
    """kill and gc refuse on None."""
    assert runs.parse(LabelledBox({})) is None
    assert runs.parse(LabelledBox({runs.LABEL_BY: "someone else"})) is None


def test_our_label_without_the_rest_is_an_error_not_a_guess():
    with pytest.raises(ValueError, match="lacks"):
        runs.parse(LabelledBox({runs.LABEL_BY: runs.BY, "box.cmd": "x"}))


def test_long_command_is_cut_in_the_label_only():
    recipe = plain(None, {}, "x" * 1000, 60)
    assert len(runs.labels(recipe, recipe.cmd, NOW)["box.cmd"]) == runs.CMD_LABEL_LIMIT
    assert recipe.cmd == "x" * 1000


def test_shellbox_exec_env_status_and_timeout():
    box = ShellBox()
    ok = box.exec('echo "$FOO"; echo err >&2; exit 3', env={"FOO": "bar"})
    assert (ok.stdout, ok.stderr, ok.returncode) == ("bar\n", "err\n", 3)
    slow = box.exec("sleep 5", timeout=1)
    assert slow.returncode == TIMEOUT_EXIT
