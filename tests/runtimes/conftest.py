"""Fixtures the runtimes' tests share."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from tests.factories import init_repo
from tests.runtimes.acp_sandbox_support import PROXY_VARIABLES, SECRETS, Recording, Scene
from tests.sandboxes.landlock_support import require_working


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    """Where `doctor` and `init` ask from: the planning checkout, which the
    probe must leave as it found it."""
    root = init_repo(tmp_path / "planning")
    (root / "abk.yaml").write_text("repos: {}\n")
    return root


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    """The ACP sandbox tests' scene, with abk's secrets set and the proxy variables cleared."""
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    return Scene(tmp_path)


@pytest.fixture
def backend(monkeypatch: pytest.MonkeyPatch) -> Recording:
    """The real sandbox backend, recording what it is asked to wrap; skips where none works."""
    real = sandboxes.get("landlock")
    require_working(real)
    recording = Recording(real)
    monkeypatch.setattr(sandboxes, "probe", lambda name="auto": (recording, real.availability()))
    return recording
