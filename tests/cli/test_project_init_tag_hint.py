"""`abk project init` says how groups for a registered project are tagged."""

from __future__ import annotations

from pathlib import Path

from tests.cli.project_init_support import project_init, write_commented
from tests.prompt_text import flat


def test_a_registration_says_how_its_groups_are_tagged_and_a_refusal_says_nothing_of_it(
    tmp_path: Path, capsys
) -> None:
    config = write_commented(tmp_path)

    refused = project_init(config, "web", "--profile", "nope", "--repo", "app")
    refusal = capsys.readouterr()
    registered = project_init(config, "web", "--profile", "python-uv", "--repo", "app")
    said = flat(capsys.readouterr().out)

    assert refused != 0 and registered == 0
    assert "[app/web]" not in refusal.out + refusal.err
    assert "[app/web]" in said
    assert "apart" in said


def test_the_root_project_is_tagged_as_the_repo_alone(tmp_path: Path, capsys) -> None:
    config = write_commented(tmp_path)

    code = project_init(config, ".", "--profile", "python-uv", "--repo", "app")
    said = flat(capsys.readouterr().out)

    assert code == 0
    assert "tagged [app]," in said
    assert "[app/.]" not in said
