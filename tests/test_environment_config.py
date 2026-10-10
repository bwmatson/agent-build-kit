"""The `environment` section: commands and file lists, required where present.

The framework knows no package manager and no lock file name, so a section is
valid only by what it says: a `sync` and a `check` that are not empty.
"""

from __future__ import annotations

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
