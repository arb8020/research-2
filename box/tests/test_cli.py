"""The CLI's exit codes: an SDK refusal is a one-line `box: ...` and exit 2; anything else is a bug and
keeps its traceback."""

from __future__ import annotations

import sys

import pytest

from box import cli


def test_a_refusal_is_one_line_and_exit_2(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(sys, "argv", ["box", "--provider", "local", "run", "--ceiling", "0", "--", "true"])
    with pytest.raises(SystemExit) as exit_:
        cli.main()
    assert exit_.value.code == 2
    assert capsys.readouterr().err.startswith("box: ceiling_s=0.0: a ceiling is more than 0")


def test_a_value_error_that_is_not_a_refusal_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    def bug() -> str:
        raise ValueError("a bug, not a refusal")

    monkeypatch.setattr(cli.gpus, "table", bug)
    monkeypatch.setattr(sys, "argv", ["box", "gpus"])
    with pytest.raises(ValueError, match="a bug, not a refusal"):
        cli.main()
