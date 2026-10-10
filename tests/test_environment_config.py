"""The `environment` section: commands and file lists, required where present.

The framework knows no package manager and no lock file name, so a section is
valid only by what it says: a `sync` and a `check` that are not empty.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError, load

SECTION = """\
environment:
  sync: [env-sync, --all]
  check: [env-check]
  inputs:
    dependencies: [manifest.toml]
    lock: [manifest.lock]
    other: [settings.cfg]
"""

REPO_SECTION = """\
repos:
  app:
    path: /tmp/app
    slug: example/app
    environment:
      sync: [env-sync]
      check: [env-check]
      inputs:
        dependencies: [manifest.toml]
        lock: [manifest.lock]
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return path


def refused(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigError) as error:
        load(write(tmp_path, text))
    return str(error.value)


def test_a_complete_section_loads_and_an_empty_command_does_not(tmp_path: Path) -> None:
    environment = load(write(tmp_path, SECTION)).environment

    assert environment is not None
    assert environment.sync == ["env-sync", "--all"]
    assert environment.check == ["env-check"]
    assert environment.inputs.dependencies == ["manifest.toml"]
    assert environment.inputs.lock == ["manifest.lock"]
    assert environment.inputs.other == ["settings.cfg"]
    assert "environment.check" in refused(tmp_path, SECTION.replace("[env-check]", "[]"))


@pytest.mark.parametrize("field", ["sync", "check"])
def test_an_empty_command_is_refused_naming_its_field(tmp_path: Path, field: str) -> None:
    other = "check" if field == "sync" else "sync"

    message = refused(tmp_path, f"environment:\n  {other}: [env-cmd]\n  {field}: []\n")

    assert f"environment.{field}" in message


@pytest.mark.parametrize("field", ["sync", "check"])
def test_a_missing_command_is_refused_naming_its_field(tmp_path: Path, field: str) -> None:
    other = "check" if field == "sync" else "sync"

    message = refused(tmp_path, f"environment:\n  {other}: [env-cmd]\n")

    assert f"environment.{field}" in message


def test_a_section_with_neither_command_is_refused_for_both(tmp_path: Path) -> None:
    message = refused(tmp_path, "environment:\n  inputs:\n    lock: [manifest.lock]\n")

    assert "environment.sync" in message
    assert "environment.check" in message


def test_a_repository_entry_accepts_the_same_section_and_validates_it(tmp_path: Path) -> None:
    environment = load(write(tmp_path, REPO_SECTION)).repos["app"].environment

    assert environment is not None
    assert environment.sync == ["env-sync"]
    assert environment.check == ["env-check"]
    assert environment.inputs.lock == ["manifest.lock"]
    assert environment.inputs.other == []
    bad = REPO_SECTION.replace("check: [env-check]", "check: []")
    assert "repos.app.environment.check" in refused(tmp_path, bad)


def test_a_repository_section_without_sync_is_refused_naming_the_field(tmp_path: Path) -> None:
    bad = REPO_SECTION.replace("      sync: [env-sync]\n", "")

    assert "repos.app.environment.sync" in refused(tmp_path, bad)


def test_artifacts_default_to_none_and_load_as_patterns(tmp_path: Path) -> None:
    without = load(write(tmp_path, SECTION)).environment
    with_them = load(write(tmp_path, SECTION + "  artifacts: [modules, '**/build']\n")).environment

    assert without is not None and with_them is not None
    assert without.artifacts == []
    assert with_them.artifacts == ["modules", "**/build"]


def test_a_nested_pattern_is_accepted_in_every_input_list(tmp_path: Path) -> None:
    text = SECTION.replace("[manifest.toml]", "['**/manifest.toml', packages/*/extra.toml]")

    environment = load(write(tmp_path, text)).environment

    assert environment is not None
    assert environment.inputs.dependencies == ["**/manifest.toml", "packages/*/extra.toml"]


@pytest.mark.parametrize("list_name", ["dependencies", "lock", "other"])
@pytest.mark.parametrize("pattern", ["/etc/manifest", "../*/manifest", "packages/../../*/manifest"])
def test_an_input_pattern_leaving_the_repository_is_refused_naming_its_field(
    tmp_path: Path, list_name: str, pattern: str
) -> None:
    head = "environment:\n  sync: [env-sync]\n  check: [env-check]\n"
    text = f"{head}  inputs:\n    {list_name}: ['{pattern}']\n"

    assert f"environment.inputs.{list_name}" in refused(tmp_path, text)


@pytest.mark.parametrize("list_name", ["dependencies", "lock", "other"])
def test_a_literal_input_leaving_the_repository_still_loads_with_a_warning(
    tmp_path: Path, list_name: str, caplog: pytest.LogCaptureFixture
) -> None:
    head = "environment:\n  sync: [env-sync]\n  check: [env-check]\n"
    text = f"{head}  inputs:\n    {list_name}: ['../other/manifest.toml']\n"

    with caplog.at_level(logging.WARNING):
        environment = load(write(tmp_path, text)).environment

    assert environment is not None
    assert getattr(environment.inputs, list_name) == ["../other/manifest.toml"]
    assert f"environment.inputs.{list_name}" in caplog.text
    assert "../other/manifest.toml" in caplog.text
    assert "next release" in caplog.text


@pytest.mark.parametrize("pattern", ["/var/cache", "../cache", "build/../../cache"])
def test_an_artifact_pattern_leaving_the_repository_is_refused_naming_its_field(
    tmp_path: Path, pattern: str
) -> None:
    text = f"environment:\n  sync: [env-sync]\n  check: [env-check]\n  artifacts: ['{pattern}']\n"

    assert "environment.artifacts" in refused(tmp_path, text)


def test_a_repository_entry_refuses_a_pattern_leaving_the_repository(tmp_path: Path) -> None:
    bad = REPO_SECTION.replace("dependencies: [manifest.toml]", "dependencies: ['../*/manifest']")

    assert "repos.app.environment.inputs.dependencies" in refused(tmp_path, bad)
    worse = REPO_SECTION + "      artifacts: ['/abs']\n"
    assert "repos.app.environment.artifacts" in refused(tmp_path, worse)
