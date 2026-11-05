"""Adding, removing and replacing a project keep the file as it was (spec: project-lines)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.init.scaffold import (
    ScaffoldError,
    add_project,
    remove_project,
    replace_project,
)
from tests.cli.project_init_support import write_commented

QUOTED = """# The workspace.
repos:
  app:  # the application
    path: {app}
    slug: example/app
    projects:
      # first service
      - path: "svc-a"
        profile: python-uv
      # second service
      - path: 'svc-b'   # kept
        profile: 'node-npm'
  platform:
    path: {platform}
    slug: example/platform
    projects: []
# Limits.
project_limits:
  max_concurrent_stacks: 2  # kept low
"""

FLOW = (
    "repos:\n"
    "  app: {{path: {app}, slug: example/app, projects: [{{path: svc-a, profile: python-uv}}]}}\n"
)


def write_quoted(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    app, platform = root / "app", root / "platform"
    app.mkdir()
    platform.mkdir()
    config = root / "abk.yaml"
    config.write_text(QUOTED.format(app=app, platform=platform))
    return config


def projects(config: Path, repo: str) -> list[dict]:
    return yaml.safe_load(config.read_text())["repos"][repo].get("projects", [])


def test_a_remove_keeps_the_other_entries_comments_and_quoting(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text().splitlines()

    assert remove_project(config, "app", "svc-a") is True

    assert projects(config, "app") == [{"path": "svc-b", "profile": "node-npm"}]
    after = config.read_text().splitlines()
    for line in before:
        if "svc-a" not in line and "python-uv" not in line and "first service" not in line:
            assert line in after


def test_a_remove_reads_the_path_as_project_init_does(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)

    assert remove_project(config, "app", "./svc-b/") is True

    assert [entry["path"] for entry in projects(config, "app")] == ["svc-a"]


def test_removing_the_last_project_leaves_a_valid_empty_list(tmp_path: Path) -> None:
    config = write_commented(tmp_path)

    assert remove_project(config, "app", "svc-a") is True

    assert projects(config, "app") == []


def test_a_remove_of_an_absent_path_is_a_reported_no_op(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    assert remove_project(config, "app", "gone") is False

    assert config.read_text() == before


def test_a_replace_keeps_position_and_the_other_entries(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)

    assert replace_project(config, "app", "svc-a", {"path": "svc-c", "profile": "node-npm"}) is True

    assert projects(config, "app") == [
        {"path": "svc-c", "profile": "node-npm"},
        {"path": "svc-b", "profile": "node-npm"},
    ]
    after = config.read_text().splitlines()
    assert "      - path: 'svc-b'   # kept" in after
    assert "# Limits." in after and "  max_concurrent_stacks: 2  # kept low" in after
    assert "  app:  # the application" in after


def test_a_replace_whose_old_path_is_absent_is_a_reported_no_op(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    assert replace_project(config, "app", "gone", {"path": "svc-c", "profile": "node-npm"}) is False

    assert config.read_text() == before


def test_an_add_into_an_inline_empty_list_makes_it_a_list(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)

    assert add_project(config, "platform", {"path": "web", "profile": "node-npm"}) is True

    assert projects(config, "platform") == [{"path": "web", "profile": "node-npm"}]
    assert "# Limits." in config.read_text().splitlines()


def test_an_add_of_a_present_path_is_a_reported_no_op(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    assert add_project(config, "app", {"path": "svc-a", "profile": "python-uv"}) is False

    assert config.read_text() == before


def test_an_add_of_an_unknown_profile_is_refused_with_the_file_unchanged(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    with pytest.raises(ScaffoldError, match="nope"):
        add_project(config, "app", {"path": "svc-z", "profile": "nope"})

    assert config.read_text() == before


@pytest.mark.parametrize("bad", ["../elsewhere", "/etc/elsewhere", "a/../../b"])
def test_a_path_outside_the_repository_is_refused_with_the_file_unchanged(
    tmp_path: Path, bad: str
) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    with pytest.raises(ScaffoldError, match="inside"):
        add_project(config, "app", {"path": bad, "profile": "python-uv"})
    with pytest.raises(ScaffoldError, match="inside"):
        replace_project(config, "app", "svc-a", {"path": bad, "profile": "python-uv"})

    assert config.read_text() == before


def test_a_replace_into_an_unknown_profile_is_refused_with_the_file_unchanged(
    tmp_path: Path,
) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    with pytest.raises(ScaffoldError, match="nope"):
        replace_project(config, "app", "svc-a", {"path": "svc-c", "profile": "nope"})

    assert config.read_text() == before


def test_remove_and_replace_refuse_an_unknown_repository_naming_the_known_ones(
    tmp_path: Path,
) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    with pytest.raises(ScaffoldError, match="app"):
        remove_project(config, "other", "svc-a")
    with pytest.raises(ScaffoldError, match="app"):
        replace_project(config, "other", "svc-a", {"path": "x", "profile": "python-uv"})

    assert config.read_text() == before


def test_a_write_goes_through_a_backup_of_the_original(tmp_path: Path) -> None:
    config = write_quoted(tmp_path)
    before = config.read_text()

    remove_project(config, "app", "svc-a")

    assert config.with_name("abk.yaml.abk-backup").read_text() == before


def test_a_layout_that_cannot_be_followed_leaves_the_file_and_no_backup(tmp_path: Path) -> None:
    config = tmp_path / "abk.yaml"
    app = tmp_path / "app"
    app.mkdir()
    config.write_text(FLOW.format(app=app))
    before = config.read_text()

    with pytest.raises(ScaffoldError):
        remove_project(config, "app", "svc-a")

    assert config.read_text() == before
    assert not config.with_name("abk.yaml.abk-backup").exists()
