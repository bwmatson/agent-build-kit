"""The planning home and the state directory are scrub terms, like the worktree root."""

from pathlib import Path

import pytest

from agent_build_kit.scrub_terms import terms_for
from tests.conftest import make_installation


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    faked = tmp_path / "homes" / "quuxuser"
    faked.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(faked))
    return faked


@pytest.mark.parametrize("key", ["home", "state_dir"])
def test_the_directory_is_a_term(tmp_path: Path, home: Path, key: str) -> None:
    inst = make_installation(
        tmp_path / "planning", planning={key: str(home / ".trees-x" / "place")}
    )
    target = tmp_path / "checkout"
    target.mkdir()

    assert ".trees-x" in terms_for(inst, target=target)
