"""`builders.per_group_commits` defaults to on (spec: per-group-commits)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit import profiles
from agent_build_kit.config import WorkspaceConfig, dump
from agent_build_kit.profiles.base import stubbed_build
from tests.config.builders_config import load

ROOT = Path(__file__).resolve().parents[2]
SETTING_DOCUMENTS = (
    ROOT / "docs" / "configuration.md",
    ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md",
)


def test_a_workspace_with_no_builders_section_reports_the_setting_on() -> None:
    assert load().builders.per_group_commits is True
    assert load({"installable_files": []}).builders.per_group_commits is True


def test_a_workspace_with_no_builders_section_builds_stubbed() -> None:
    assert stubbed_build(load().builders, profiles.get("python-uv")) is True
    assert stubbed_build(load().builders, profiles.get("node-npm")) is True


def test_an_explicit_off_reports_off_and_reads_unstubbed_beside_the_default_on() -> None:
    """The one-pair build itself is pinned in tests/graph/test_per_group_unstubbed.py."""
    off = load({"per_group_commits": False}).builders

    assert load().builders.per_group_commits is True
    assert off.per_group_commits is False
    assert stubbed_build(off, profiles.get("python-uv")) is False


def test_the_config_abk_init_writes_leaves_the_setting_on() -> None:
    written = yaml.safe_load(dump(load()))

    assert "per_group_commits" not in written.get("builders", {})
    assert WorkspaceConfig.model_validate(written).builders.per_group_commits is True


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=["configuration.md", "abk-config-skill"])
def test_the_documents_state_the_default_as_on(path: Path) -> None:
    text = " ".join(path.read_text(encoding="utf-8").replace("`", "").split())
    start = text.index("per_group_commits:")

    assert re.search(r"default on", text[start : start + 900], re.I)
    assert not re.search(r"default off", text[start : start + 900], re.I)
