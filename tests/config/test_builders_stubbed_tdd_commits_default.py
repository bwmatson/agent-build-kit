"""`builders.stubbed_tdd_commits` defaults to on (spec: per-group-commits)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_build_kit import profiles
from agent_build_kit.cli import main
from agent_build_kit.config import ConfigError, WorkspaceConfig, deprecations, dump
from agent_build_kit.config import load as load_file
from agent_build_kit.config_migrate import ConfigMigrateError, migrate
from agent_build_kit.profiles.base import stubbed_build
from tests.config.builders_config import load

ROOT = Path(__file__).resolve().parents[2]
SETTING_DOCUMENTS = (
    ROOT / "docs" / "configuration.md",
    ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md",
)


def test_a_workspace_with_no_builders_section_reports_the_setting_on() -> None:
    assert load().builders.stubbed_tdd_commits is True
    assert load({"installable_files": []}).builders.stubbed_tdd_commits is True


def test_a_workspace_with_no_builders_section_builds_stubbed() -> None:
    assert stubbed_build(load().builders, profiles.get("python-uv")) is True
    assert stubbed_build(load().builders, profiles.get("node-npm")) is True


def test_an_explicit_off_reports_off_and_reads_unstubbed_beside_the_default_on() -> None:
    """The one-pair build itself is pinned in tests/graph/test_per_group_unstubbed.py."""
    off = load({"stubbed_tdd_commits": False}).builders

    assert load().builders.stubbed_tdd_commits is True
    assert off.stubbed_tdd_commits is False
    assert stubbed_build(off, profiles.get("python-uv")) is False


def test_the_config_abk_init_writes_leaves_the_setting_on() -> None:
    written = yaml.safe_load(dump(load()))

    assert "stubbed_tdd_commits" not in written.get("builders", {})
    assert WorkspaceConfig.model_validate(written).builders.stubbed_tdd_commits is True


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=["configuration.md", "abk-config-skill"])
def test_the_documents_state_the_default_as_on(path: Path) -> None:
    text = " ".join(path.read_text(encoding="utf-8").replace("`", "").split())
    start = text.index("stubbed_tdd_commits:")

    assert re.search(r"default on", text[start : start + 900], re.I)
    assert not re.search(r"default off", text[start : start + 900], re.I)


FILE = "version: 1\nrepos:\n  app:\n    path: /work/app\n    slug: example/app\n"


def test_the_old_name_is_read_as_the_new_one() -> None:
    assert load({"per_group_commits": False}).builders.stubbed_tdd_commits is False
    assert load({"per_group_commits": True}).builders.stubbed_tdd_commits is True


def test_a_file_setting_both_names_is_refused_naming_both(tmp_path: Path) -> None:
    both = {"per_group_commits": True, "stubbed_tdd_commits": False}

    with pytest.raises(ValidationError, match="per_group_commits.*stubbed_tdd_commits"):
        load(both)
    path = tmp_path / "abk.yaml"
    path.write_text(FILE + "builders:\n  per_group_commits: true\n  stubbed_tdd_commits: true\n")
    with pytest.raises(ConfigError) as refused:
        load_file(path)
    assert "per_group_commits" in str(refused.value)
    assert "stubbed_tdd_commits" in str(refused.value)


@pytest.mark.parametrize("name", ["per_group_commits", "stubbed_tdd_commits"])
def test_a_string_is_refused_naming_the_key_as_the_file_spells_it(
    tmp_path: Path, name: str
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(FILE + f"builders:\n  {name}: yes please\n")

    with pytest.raises(ConfigError) as refused:
        load_file(path)

    assert f"builders.{name}" in str(refused.value)


def test_an_old_name_in_a_file_loads_and_is_reported_as_deprecated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(FILE + "builders:\n  per_group_commits: false\n")

    assert load_file(path).builders.stubbed_tdd_commits is False
    assert deprecations(path) == ["builders.per_group_commits"]
    assert main(["--config", str(path), "config"]) == 0
    err = capsys.readouterr().err
    assert "`builders.per_group_commits` is deprecated for `builders.stubbed_tdd_commits`" in err
    assert "abk config --migrate" in err


def test_the_new_name_says_nothing_of_the_kind(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(FILE + "builders:\n  stubbed_tdd_commits: false\n")

    assert deprecations(path) == []


@pytest.mark.parametrize("value", ["true", "false"])
def test_migrate_renames_the_old_key_and_changes_nothing_else(value: str) -> None:
    before = (
        "version: 1\nbuilders:\n  installable_files: []\n"
        f"  per_group_commits: {value}  # soak\nrepos: {{}}\n"
    )

    migrated = migrate(before).text

    assert migrated == before.replace("per_group_commits", "stubbed_tdd_commits")
    assert migrate(migrated).text == migrated


def test_migrate_refuses_a_file_setting_both_names() -> None:
    both = "builders:\n  per_group_commits: true\n  stubbed_tdd_commits: true\n"

    with pytest.raises(ConfigMigrateError, match="per_group_commits"):
        migrate(both)
