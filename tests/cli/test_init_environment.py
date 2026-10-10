"""`abk init` writes the `environment` section where it can recognise a layout,
fills it when missing, leaves one present alone, and writes the lock files it
finds into the generated-file patterns."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import init as init_cmd
from agent_build_kit.cli import main
from agent_build_kit.config import load
from tests.cli.test_init import fake_claude, fake_openspec
from tests.factories import git, init_repo

SOURCES = (
    '[project]\nname = "planning"\ndependencies = ["framework"]\n\n'
    '[tool.uv.sources]\nframework = { path = "../framework", editable = true }\n'
)


@pytest.fixture(autouse=True)
def stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_cmd, "run_openspec", fake_openspec)
    monkeypatch.setattr(init_cmd, "run_claude", fake_claude)
    monkeypatch.setattr(init_cmd, "ask", lambda prompt: pytest.fail("prompted unexpectedly"))
    monkeypatch.setattr(
        init_cmd, "run_fix", lambda argv, **kwargs: pytest.fail(f"ran a fix unasked: {argv}")
    )
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t.t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t.t")


def code_repo(tmp_path: Path, name: str, **files: str) -> Path:
    repo = init_repo(tmp_path / name)
    git(repo, "remote", "add", "origin", f"git@github.com:example/{name}.git")
    (repo / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n')
    for file, content in files.items():
        (repo / file).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "first")
    return repo


def planning_with(tmp_path: Path, **files: str) -> Path:
    planning = tmp_path / "planning"
    planning.mkdir()
    for file, content in files.items():
        (planning / file).write_text(content)
    return planning


def run_init(planning: Path, repo: Path, *extra: str) -> int:
    argv = ["init", str(planning), "--repo", str(repo), "--yes", "--skip-research"]
    return main([*argv, "--skip-propose", *extra])


def written(planning: Path) -> dict:
    return yaml.safe_load((planning / "abk.yaml").read_text())


def test_a_recognised_layout_gets_commands_and_the_files_found_including_a_checkout_s(
    tmp_path: Path,
) -> None:
    (tmp_path / "framework").mkdir()
    (tmp_path / "framework" / "pyproject.toml").write_text('[project]\nname = "framework"\n')
    (tmp_path / "framework" / "uv.lock").write_text("")
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})

    assert run_init(planning, code_repo(tmp_path, "app")) == 0

    environment = written(planning)["environment"]
    assert environment["sync"]
    assert environment["check"]
    deps = environment["inputs"]["dependencies"]
    lock = environment["inputs"]["lock"]
    assert {"pyproject.toml", "../framework/pyproject.toml"} <= set(deps)
    assert {"uv.lock", "../framework/uv.lock"} <= set(lock)


def test_the_dry_run_shows_the_section_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})

    assert run_init(planning, code_repo(tmp_path, "app"), "--dry-run") == 0

    out = capsys.readouterr().out
    assert "environment:" in out
    assert "pyproject.toml" in out
    assert "uv.lock" in out
    assert not (planning / "abk.yaml").exists()


def test_a_layout_it_does_not_recognise_gets_empty_commands_and_a_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planning = planning_with(tmp_path)

    assert run_init(planning, code_repo(tmp_path, "app")) == 0

    environment = written(planning)["environment"]
    assert not environment.get("sync")
    assert not environment.get("check")
    out = capsys.readouterr().out.lower()
    assert any("environment" in line and "set" in line for line in out.splitlines())


def test_a_present_section_is_left_alone_and_a_missing_one_is_filled(tmp_path: Path) -> None:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})
    run_init(planning, app)
    config = written(planning)
    mine = {"sync": ["my-sync"], "check": ["my-check"], "inputs": {"lock": ["my.lock"]}}
    config["environment"] = mine
    config["limits"] = {"generated_files": ["mine.lock"]}
    config["repos"]["app"].pop("environment", None)
    config["repos"]["app"]["description"] = "kept as written"
    (planning / "abk.yaml").write_text(yaml.safe_dump(config))

    assert run_init(planning, app) == 0

    after = written(planning)
    assert after["environment"] == mine
    assert after["limits"]["generated_files"] == ["mine.lock"]
    assert after["repos"]["app"]["description"] == "kept as written"
    filled = after["repos"]["app"]["environment"]
    assert filled["sync"]
    assert filled["check"]
    assert filled["inputs"]["lock"] == ["uv.lock"]


def test_the_generated_file_patterns_are_filled_when_missing_and_nothing_else_changes(
    tmp_path: Path,
) -> None:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})
    run_init(planning, app)
    config = written(planning)
    mine = {"sync": ["my-sync"], "check": ["my-check"]}
    config["environment"] = mine
    config["limits"] = {"max_unit_lines": 900}
    (planning / "abk.yaml").write_text(yaml.safe_dump(config))

    assert run_init(planning, app) == 0

    after = written(planning)
    assert "uv.lock" in after["limits"]["generated_files"]
    assert after["limits"]["max_unit_lines"] == 900
    assert after["environment"] == mine


def test_a_repository_s_section_comes_from_the_files_found_in_that_repository(
    tmp_path: Path,
) -> None:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path)

    assert run_init(planning, app) == 0

    environment = written(planning)["repos"]["app"]["environment"]
    assert environment["sync"]
    assert environment["check"]
    assert environment["inputs"]["dependencies"] == ["pyproject.toml"]
    assert environment["inputs"]["lock"] == ["uv.lock"]


def test_the_lock_files_found_are_written_into_the_generated_file_patterns(
    tmp_path: Path,
) -> None:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})

    assert run_init(planning, app) == 0

    assert "uv.lock" in written(planning)["limits"]["generated_files"]


def test_the_dry_run_shows_a_repository_s_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})

    assert run_init(planning_with(tmp_path), app, "--dry-run") == 0

    shown = capsys.readouterr().out.split("# what would be generated:")[0]
    config = yaml.safe_load(shown)
    assert config["repos"]["app"]["environment"]["inputs"]["lock"] == ["uv.lock"]


ANNOTATED = """\
# Hand-written: the installation's own notes.
version: 1  # the schema
repos:
  app:
    path: '{app}'   # quoted by hand
    slug: "example/app"
limits:
  max_unit_lines: 900  # raised on purpose
"""


def annotated_installation(tmp_path: Path) -> tuple[Path, Path, str]:
    app = code_repo(tmp_path, "app", **{"uv.lock": ""})
    planning = planning_with(tmp_path, **{"pyproject.toml": SOURCES, "uv.lock": ""})
    original = ANNOTATED.format(app=app)
    (planning / "abk.yaml").write_text(original)
    return planning, app, original


def test_a_fill_keeps_every_line_and_comment_of_the_file_it_adds_to(tmp_path: Path) -> None:
    planning, app, original = annotated_installation(tmp_path)

    assert run_init(planning, app) == 0

    after = (planning / "abk.yaml").read_text().splitlines()
    remaining = iter(after)
    for line in original.splitlines():
        assert line in remaining, f"{line!r} is gone or out of order"
    assert "# Hand-written: the installation's own notes." in after
    assert any(line.endswith("# raised on purpose") for line in after)
    config = load(planning / "abk.yaml")
    assert config.environment is not None
    assert config.repos["app"].environment is not None
    assert config.limits.generated_files == ("uv.lock",)
    assert config.limits.max_unit_lines == 900


def test_a_fill_adds_a_limits_block_when_there_is_none(tmp_path: Path) -> None:
    planning, app, original = annotated_installation(tmp_path)
    without = original.replace("limits:\n  max_unit_lines: 900  # raised on purpose\n", "")
    (planning / "abk.yaml").write_text(without)

    assert run_init(planning, app) == 0

    assert load(planning / "abk.yaml").limits.generated_files == ("uv.lock",)
    assert "limits:\n" in (planning / "abk.yaml").read_text()


def test_the_dry_run_over_an_existing_file_lists_what_it_would_fill_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    planning, app, original = annotated_installation(tmp_path)

    assert run_init(planning, app, "--dry-run") == 0

    out = capsys.readouterr().out
    assert "would fill environment in abk.yaml" in out
    assert "would fill repos.app.environment in abk.yaml" in out
    assert "would fill limits.generated_files in abk.yaml" in out
    assert "as it would be written" not in out
    assert (planning / "abk.yaml").read_text() == original


def test_a_kept_file_without_a_section_and_nothing_recognised_is_told_to_add_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = code_repo(tmp_path, "app")
    planning = planning_with(tmp_path)
    (planning / "abk.yaml").write_text("version: 1\n")

    assert run_init(planning, app) == 0

    assert "add an `environment` section" in capsys.readouterr().out
    assert (planning / "abk.yaml").read_text().startswith("version: 1\n")


def test_no_set_by_hand_message_over_a_kept_file_with_its_own_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    app = code_repo(tmp_path, "app")
    planning = planning_with(tmp_path)
    (planning / "abk.yaml").write_text("environment:\n  sync: [my-sync]\n  check: [my-check]\n")

    assert run_init(planning, app) == 0

    assert "nothing recognised" not in capsys.readouterr().out
