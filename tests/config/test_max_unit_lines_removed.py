"""`global_limits.max_unit_lines` is no longer accepted: the load fails naming the setting that
replaces it and the command that moves the value (spec: review-always-on)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit.config import ConfigError, load, overlay_path

REPOS = {"app": {"path": "/work/app", "slug": "example/app"}}


def write(root: Path, document: dict[str, Any], overlay: dict[str, Any] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "repos": REPOS, **document}))
    if overlay is not None:
        overlay_path(path).write_text(yaml.safe_dump(overlay))
    return path


def refusal(path: Path) -> str:
    with pytest.raises(ConfigError) as refused:
        load(path)
    return str(refused.value)


@pytest.mark.parametrize("root", ["global_limits", "limits"])
def test_the_key_fails_the_load_naming_the_replacement_and_the_migration(
    tmp_path: Path, root: str
) -> None:
    message = refusal(write(tmp_path, {root: {"max_unit_lines": 900}}))

    assert "review.ceilings.full" in message
    assert "abk config --migrate" in message


def test_the_key_fails_when_only_the_overlay_sets_it(tmp_path: Path) -> None:
    message = refusal(write(tmp_path, {}, overlay={"global_limits": {"max_unit_lines": 900}}))

    assert "review.ceilings.full" in message
    assert "abk config --migrate" in message


def test_the_key_fails_even_beside_the_full_ceiling_it_agrees_with(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {"global_limits": {"max_unit_lines": 750}, "review": {"ceilings": {"full": 750}}},
    )

    assert "abk config --migrate" in refusal(path)
