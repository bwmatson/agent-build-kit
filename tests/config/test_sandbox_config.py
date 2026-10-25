"""The `sandbox` keys: a backend that exists, and a runtime policy slot (the default is pinned in
`test_sandbox_default.py`)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.config import ConfigError, load
from agent_build_kit.runtimes.base import ToolPolicy


def write(tmp_path: Path, body: str = "") -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text("repos: {}\n" + body)
    return path


def test_a_backend_name_is_checked_at_load_and_the_known_ones_are_named(tmp_path: Path) -> None:
    for known in ("auto", *sandboxes.names()):
        loaded = load(write(tmp_path, f"sandbox:\n  enabled: true\n  backend: {known}\n"))
        assert loaded.model_dump()["sandbox"] == {"enabled": True, "backend": known}

    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, "sandbox:\n  backend: nope\n"))

    assert "nope" in str(caught.value)
    for known in sandboxes.names():
        assert known in str(caught.value)


def test_required_is_a_repo_setting_and_a_project_refuses_it(tmp_path: Path) -> None:
    repo = (
        "repos:\n  app:\n    path: /srv/app\n    slug: example/app\n"
        "    sandbox:\n      required: none\n"
    )
    path = tmp_path / "abk.yaml"
    path.write_text(repo)
    assert load(path).repos["app"].sandbox.required == "none"

    path.write_text(
        repo + "    projects:\n      - path: web\n        sandbox:\n          required: none\n"
    )
    with pytest.raises(ConfigError, match="required"):
        load(path)


def test_the_runtime_tool_policy_has_no_sandbox_by_default() -> None:
    assert ToolPolicy().model_dump()["sandbox"] is None
