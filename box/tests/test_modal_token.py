"""ModalToken.from_config: the one place box reads Modal credentials from disk (for the CLI)."""

from __future__ import annotations

from pathlib import Path

import pytest

from box.providers.modal import ModalToken

ACTIVE = '[work]\ntoken_id = "ak-work"\ntoken_secret = "as-work"\nactive = true\n'
OTHER = '[home]\ntoken_id = "ak-home"\ntoken_secret = "as-home"\n'


def config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "modal.toml"
    path.write_text(text)
    return path


def test_the_active_profile_is_the_token(tmp_path: Path) -> None:
    assert ModalToken.from_config(config(tmp_path, OTHER + ACTIVE)) == ModalToken("ak-work", "as-work")


@pytest.mark.parametrize("text", [OTHER, ACTIVE + ACTIVE.replace("work", "work2")], ids=["none", "two"])
def test_no_single_active_profile_is_refused(tmp_path: Path, text: str) -> None:
    with pytest.raises(ValueError, match="active profiles"):
        ModalToken.from_config(config(tmp_path, text))


def test_a_named_profile_is_read_active_or_not(tmp_path: Path) -> None:
    assert ModalToken.from_profile("home", config(tmp_path, OTHER + ACTIVE)) == ModalToken("ak-home", "as-home")
    with pytest.raises(ValueError, match="no profile 'gone'"):
        ModalToken.from_profile("gone", config(tmp_path, OTHER))


def test_a_token_never_prints(tmp_path: Path) -> None:
    token = ModalToken.from_config(config(tmp_path, ACTIVE))
    assert "ak-work" not in repr(token)
    assert "as-work" not in repr(token)
