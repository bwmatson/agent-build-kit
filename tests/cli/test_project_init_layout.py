"""`abk project init` edits the file in force, follows the layouts `abk init` follows, and
refuses what it cannot place or what leaves the repo (spec: project-init)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.project_init_support import project_init, projects_of, write_commented


def test_a_quoted_repo_key_gains_its_entry(tmp_path: Path) -> None:
    config = write_commented(tmp_path)
    config.write_text(config.read_text().replace("  app:\n", '  "app":\n'))

    code = project_init(config, "web", "--profile", "node-npm", "--repo", "app")

    assert code == 0
    assert projects_of(config, "app")[-1] == {"path": "web", "profile": "node-npm"}


def test_the_file_in_force_is_the_one_edited_whatever_its_name(tmp_path: Path) -> None:
    named = write_commented(tmp_path).rename(tmp_path / "workspace.yaml")

    code = project_init(named, "web", "--profile", "node-npm", "--repo", "platform")

    assert code == 0
    assert projects_of(named, "platform") == [{"path": "web", "profile": "node-npm"}]
    assert not (tmp_path / "abk.yaml").exists()


def test_an_inline_projects_list_is_refused_not_rewritten(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    slug = "    slug: example/platform\n"
    config.write_text(config.read_text().replace(slug, slug + "    projects: []\n"))
    before = config.read_text()

    code = project_init(config, "web", "--profile", "node-npm", "--repo", "platform")

    assert code != 0
    assert "platform" in capsys.readouterr().err
    assert config.read_text() == before


def test_a_leading_dot_slash_is_the_same_path(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(config, "./svc-a", "--profile", "python-uv", "--repo", "app")

    assert code != 0
    assert "svc-a" in capsys.readouterr().err
    assert config.read_text() == before


@pytest.mark.parametrize("path", ["../elsewhere", "/abs/elsewhere", "a/../../b"])
def test_a_path_outside_the_repo_is_refused_and_nothing_is_written(
    tmp_path: Path, path: str
) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(config, path, "--profile", "python-uv", "--repo", "app", "--scaffold")

    assert code != 0
    assert config.read_text() == before
    assert not (tmp_path / "elsewhere").exists()


def test_an_absolute_path_inside_the_repo_is_registered_relative(tmp_path: Path) -> None:
    config = write_commented(tmp_path)

    code = project_init(
        config, str(tmp_path / "app" / "web"), "--profile", "node-npm", "--repo", "app"
    )

    assert code == 0
    assert projects_of(config, "app")[-1] == {"path": "web", "profile": "node-npm"}


def test_an_absolute_path_of_a_registered_project_is_a_duplicate(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(
        config, str(tmp_path / "app" / "svc-a"), "--profile", "python-uv", "--repo", "app"
    )

    assert code != 0
    assert "svc-a" in capsys.readouterr().err
    assert config.read_text() == before
