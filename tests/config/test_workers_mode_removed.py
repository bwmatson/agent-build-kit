"""`workers.mode` is no longer a setting: a configuration that still names it, at the top level or
under a repo, is refused with a message saying it has been removed (spec: worker-kinds)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config import ConfigError, load, overlay_path

REPO = {"path": "/work/app", "slug": "example/app"}


def write(root: Path, document: dict[str, Any], overlay: dict[str, Any] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "repos": {"app": REPO}, **document}))
    if overlay is not None:
        overlay_path(path).write_text(yaml.safe_dump(overlay))
    return path


def refusal(path: Path) -> str:
    """The message `load` refuses with, or "loaded" when it did not refuse."""
    try:
        load(path)
    except ConfigError as refused:
        return str(refused)
    return "loaded"


@pytest.mark.parametrize("mode", ["threads", "processes"])
def test_the_top_level_mode_is_refused_as_removed(tmp_path: Path, mode: str) -> None:
    message = refusal(write(tmp_path, {"workers": {"mode": mode}}))

    assert "workers.mode" in message
    assert "removed" in message


def test_a_repos_own_mode_is_refused_as_removed(tmp_path: Path) -> None:
    document = {"repos": {"app": {**REPO, "workers": {"mode": "processes"}}}}

    message = refusal(write(tmp_path, document))

    assert "workers.mode" in message
    assert "removed" in message


def test_the_mode_is_refused_when_only_the_overlay_sets_it(tmp_path: Path) -> None:
    message = refusal(write(tmp_path, {}, overlay={"workers": {"mode": "processes"}}))

    assert "workers.mode" in message
    assert "removed" in message
