"""The `configure` fixture: settings read from a temporary `.env` and a patched process."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest

from agent_build_kit.claude_account import NAMES
from agent_build_kit.settings import reload

# Sets the process environment and the `.env` as given (`process=`, `dotenv=`), reloads the
# settings from that `.env` and returns its path.
Configure = Callable[..., Path]


@pytest.fixture
def configure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Configure]:
    """Neither name set anywhere and `HOME` under the test's directory, until the test
    configures them; the settings are read from the process environment again afterwards."""
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    env_file = tmp_path / "planning.env"

    def apply(
        *, process: Mapping[str, str] | None = None, dotenv: Mapping[str, str] | None = None
    ) -> Path:
        for name in NAMES:
            monkeypatch.delenv(name, raising=False)
        for name, value in (process or {}).items():
            monkeypatch.setenv(name, value)
        env_file.write_text("".join(f"{name}={value}\n" for name, value in (dotenv or {}).items()))
        reload(env_file)
        return env_file

    yield apply
    monkeypatch.undo()
    reload(None)
