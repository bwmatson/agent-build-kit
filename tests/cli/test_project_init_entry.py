"""`abk project init` adds a project entry and keeps the file as it was (spec: project-init)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.project_init_support import project_init, projects_of, write_commented


def is_subsequence(wanted: list[str], lines: list[str]) -> bool:
    remaining = iter(lines)
    return all(any(line == want for line in remaining) for want in wanted)


def test_an_entry_is_added_and_every_comment_and_key_order_survives(tmp_path: Path) -> None:
    config = write_commented(tmp_path)
    before = config.read_text().splitlines()

    code = project_init(config, "agent-assessment", "--profile", "python-uv", "--repo", "app")

    assert code == 0
    projects = projects_of(config, "app")
    assert projects[0]["path"] == "svc-a"
    assert projects[-1] == {"path": "agent-assessment", "profile": "python-uv"}
    assert is_subsequence(before, config.read_text().splitlines())


def test_a_repo_with_no_projects_key_gains_one(tmp_path: Path) -> None:
    config = write_commented(tmp_path)
    before = config.read_text().splitlines()

    code = project_init(config, "web", "--profile", "node-npm", "--repo", "platform")

    assert code == 0
    assert projects_of(config, "platform") == [{"path": "web", "profile": "node-npm"}]
    assert is_subsequence(before, config.read_text().splitlines())


def test_a_duplicate_path_is_refused_naming_the_entry(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(config, "svc-a", "--profile", "python-uv", "--repo", "app")

    assert code != 0
    assert "svc-a" in capsys.readouterr().err
    assert config.read_text() == before


def test_an_unknown_profile_is_refused_naming_the_registered_ones(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(config, "agent-assessment", "--profile", "nope", "--repo", "app")

    assert code != 0
    err = capsys.readouterr().err
    assert "python-uv" in err and "node-npm" in err
    assert config.read_text() == before


def test_an_undeclared_repo_is_refused_naming_the_declared_ones(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)
    before = config.read_text()

    code = project_init(config, "agent-assessment", "--profile", "python-uv", "--repo", "other")

    assert code != 0
    err = capsys.readouterr().err
    assert "app" in err and "platform" in err
    assert config.read_text() == before


@pytest.mark.parametrize("profile", ["python-uv", "node-npm"])
def test_without_scaffold_nothing_is_written_beside_abk_yaml(tmp_path: Path, profile: str) -> None:
    config = write_commented(tmp_path)

    code = project_init(config, "new-project", "--profile", profile, "--repo", "app")

    assert code == 0
    assert not (tmp_path / "app" / "new-project").exists()
