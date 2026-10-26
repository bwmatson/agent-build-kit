"""An installation loads when its `.env` cannot be opened, as in a confined step, and takes nothing
from it (spec: sandbox-abk-exec)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import settings as settings_module
from agent_build_kit.config import dump
from agent_build_kit.installation import load_installation
from tests.conftest import make_installation

SECRET = "sentinel-credential"


def skip_if_openable(path: Path) -> None:
    if os.access(path, os.R_OK):
        pytest.skip("this user can open a mode 000 file")


@pytest.fixture
def denied(tmp_path: Path) -> Iterator[Path]:
    """A `.env` holding a credential that the process may not open."""
    env = tmp_path / "plan" / ".env"
    env.parent.mkdir()
    env.write_text(f"ABK_ADO_PAT={SECRET}\n")
    env.chmod(0o000)
    yield env
    env.chmod(0o600)


def test_a_file_that_can_be_opened_is_readable(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\n")

    assert settings_module.readable(env) == env


def test_a_file_that_is_not_there_is_not_readable(tmp_path: Path) -> None:
    assert settings_module.readable(tmp_path / ".env") is None


def test_a_file_that_cannot_be_opened_is_not_readable(denied: Path) -> None:
    skip_if_openable(denied)

    assert settings_module.readable(denied) is None


def test_an_installation_loads_without_the_env_it_cannot_open(
    denied: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ABK_ADO_PAT", raising=False)
    monkeypatch.delenv("AZURE_DEVOPS_EXT_PAT", raising=False)
    skip_if_openable(denied)
    root = denied.parent
    config = root / "abk.yaml"
    config.write_text(dump(make_installation(root).config))

    load_installation(config)

    assert settings_module.settings.ado_pat == ""
