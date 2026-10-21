"""Models are named under the runtime that uses them: `runtimes.<name>.models`.

A top-level `models:` block still loads, for the active runtime only, with a notice naming
`runtimes.<active>.models`; a role set in both places takes the runtime's value and the notice
names it; `abk config --migrate` moves the block by text without changing what resolves; and a
machine's `ABK_*_MODEL` wins over both."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.settings import settings
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo
from tests.runtimes.selectable import SelectableRuntime, select

FLAT = (
    "version: 1\n"
    "# which model does what\n"
    "models:\n"
    "  # builds\n"
    "  implement: haiku  # cheap\n"
    "  rework: haiku\n"
    "  review: opus\n"
    "  rework_review: opus\n"
    "repos: {}\n"
)

RUNTIME_FORM = (
    "version: 1\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    models:\n"
    "      implement: haiku\n"
    "      rework: haiku\n"
    "      review: opus\n"
    "      rework_review: opus\n"
)

BOTH = (
    "version: 1\n"
    "models:\n"
    "  implement: haiku\n"
    "  review: sonnet\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    models:\n"
    "      review: opus\n"
)


def write(root: Path, text: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(text)
    return path


def resolved(path: Path) -> dict[str, str]:
    config.activate(config.load(path), path.parent)
    return config.models().model_dump()


def about_models(root: Path, text: str) -> list[Check]:
    """The doctor's checks that speak of the runtime's models block."""
    planning = init_repo(root / "planning")
    write(planning, text)
    checks = run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)
    return [c for c in checks if "runtimes." in c.detail + c.fix and "models" in c.detail + c.fix]


def test_doctor_warns_of_a_flat_block_naming_the_active_runtime_s_block(tmp_path: Path) -> None:
    warned = about_models(tmp_path, FLAT)

    assert [c.status for c in warned] == ["warn"]
    assert "runtimes.claude_code.models" in warned[0].detail
    assert "abk config --migrate" in warned[0].detail + warned[0].fix


def test_a_role_set_in_both_places_takes_the_runtime_s_and_the_notice_names_it(
    tmp_path: Path,
) -> None:
    warned = about_models(tmp_path / "doctor", BOTH)

    assert len(warned) == 1
    assert "review" in warned[0].detail
    assert "implement" not in warned[0].detail
    models = resolved(write(tmp_path / "load", BOTH))
    assert models["review"] == "opus"
    assert models["implement"] == "haiku"


def test_config_prints_the_notice_for_the_active_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    select(monkeypatch, SelectableRuntime("other"))
    path = write(tmp_path, "version: 1\nruntime: other\nmodels:\n  review: x\n")

    code = main(["--config", str(path), "config", "--show"])

    assert code == 0
    assert "runtimes.other.models" in capsys.readouterr().err


def test_migrating_moves_the_block_keeps_its_comments_and_resolves_the_same(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path / "work", FLAT)
    before = resolved(path)

    code = main(["--config", str(path), "config", "--migrate", "--yes"])

    assert code == 0
    text = path.read_text()
    assert "# which model does what" in text
    assert "# builds" in text
    assert "implement: haiku  # cheap" in text
    assert "\nmodels:" not in text
    assert resolved(path) == before
    capsys.readouterr()
    assert main(["--config", str(path), "config", "--show"]) == 0
    assert "runtimes.claude_code.models" not in capsys.readouterr().err
    assert not about_models(tmp_path / "again", text)


def test_a_file_in_the_runtime_form_is_left_as_it_is_and_the_doctor_says_nothing(
    tmp_path: Path,
) -> None:
    path = write(tmp_path / "work", RUNTIME_FORM)

    assert main(["--config", str(path), "config", "--migrate", "--yes"]) == 0

    assert path.read_text() == RUNTIME_FORM
    assert resolved(path)["implement"] == "haiku"
    assert not about_models(tmp_path / "again", RUNTIME_FORM)
    # The flat block is what is reported, so the same file written flat is not silent.
    assert about_models(tmp_path / "flat", FLAT)


def test_with_another_runtime_active_the_flat_block_moves_under_it_and_claude_code_names_stay_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("other"))
    text = (
        "version: 1\nruntime: other\nmodels:\n  review: other-reviewer\n"
        "runtimes:\n  claude_code:\n    models:\n      review: opus\n      implement: sonnet\n"
    )
    path = write(tmp_path, text)

    assert main(["--config", str(path), "config", "--migrate", "--yes"]) == 0

    moved = config.load(path)
    assert moved.runtimes["other"].models.review == "other-reviewer"
    assert "models" not in moved.model_fields_set
    models = resolved(path)
    assert models["review"] == "other-reviewer"
    assert "sonnet" not in models.values()


def test_the_machine_override_wins_over_both_places_and_the_notice_stays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "review_model", "this-machine")

    models = resolved(write(tmp_path / "load", BOTH))

    assert models["review"] == "this-machine"
    assert about_models(tmp_path / "doctor", BOTH)
