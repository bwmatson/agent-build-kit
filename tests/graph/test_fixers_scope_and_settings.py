"""The real fixer runner in a build: which files it is given, what the repo's settings and the
profile decide, and what the log says (spec: fixers-run-before-commits). The build runs over a
real git branch, and the fix command is the fake command runner of the fixer pass's tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.wiring import build_fixers
from tests.fixers_fakes import Bare, FakeProfile, FakeRun, activate_app
from tests.graph.branch_fakes import agent_calls, prepared, subjects
from tests.graph.test_build_path import build

SILENT_FREE = ["claude:tests", "claude:impl"] * 3
PROTECTED = ".github/workflows/ci.yml"


def built_with(
    tmp_path: Path,
    *,
    tests: dict[str, Any] | None = None,
    profile: object | None = None,
    run: FakeRun | None = None,
    meanwhile: Any = None,
) -> tuple[Any, FakeRun, Any, Path]:
    activate_app(**({"tests": tests} if tests is not None else {}))
    recorder, repo = prepared(tmp_path, meanwhile=meanwhile)
    run = run or FakeRun()
    fixers = build_fixers(profile=profile or FakeProfile(), repo_name="app", run=run)  # type: ignore[arg-type]
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path), run_fixers=fixers)
    return recorder, run, outcome, repo


def test_only_the_files_the_unit_changed_are_given_and_no_model_is_called_for_them(
    tmp_path: Path,
) -> None:
    recorder, run, outcome, repo = built_with(tmp_path)

    assert outcome.status == "open", outcome.detail
    given = {name for argv, _ in run.calls for name in argv[1:]}
    assert given, "the fixers ran over the unit's files"
    assert all(name.startswith("work-") for name in given), given
    assert "base.txt" not in given, "a file committed on the base is not passed"
    assert agent_calls(recorder.events) == SILENT_FREE, "the fixers made no model call"
    assert len(subjects(repo)) == 6


def test_fixers_given_files_that_they_leave_alone_log_one_changed_nothing_line_per_call(
    tmp_path: Path,
) -> None:
    recorder, run, outcome, _ = built_with(tmp_path)

    assert outcome.status == "open", outcome.detail
    lines = [line for line in recorder.logged if "fixers " in line]
    assert run.calls, "the fixers ran over the unit's files"
    assert len(lines) == len(run.calls), lines
    assert all("fixers changed nothing" in line for line in lines), lines


def test_the_empty_fix_command_turns_the_fixers_off_and_the_build_is_as_before(
    tmp_path: Path,
) -> None:
    _, on, _, _ = built_with(tmp_path / "on")
    assert on.calls, "with the setting unset the profile's fixers run"

    recorder, run, outcome, repo = built_with(tmp_path / "off", tests={"fix_command": []})

    assert outcome.status == "open", outcome.detail
    assert run.calls == []
    assert not [line for line in recorder.logged if "fixers " in line]
    assert len(subjects(repo)) == 6


def test_a_profile_without_the_method_runs_no_fixer_and_the_build_is_as_before(
    tmp_path: Path,
) -> None:
    _, on, _, _ = built_with(tmp_path / "on")
    assert on.calls, "a profile with the method gets its fixers"

    recorder, run, outcome, repo = built_with(tmp_path / "off", profile=Bare())

    assert outcome.status == "open", outcome.detail
    assert run.calls == []
    assert not [line for line in recorder.logged if "fixers " in line]
    assert len(subjects(repo)) == 6


def test_the_repos_own_fix_command_runs_instead_of_the_profiles(tmp_path: Path) -> None:
    _, run, outcome, _ = built_with(tmp_path, tests={"fix_command": ["scripts/format.sh"]})

    assert outcome.status == "open", outcome.detail
    assert run.calls, "the repo's command ran"
    assert {argv[0] for argv, _ in run.calls} == {"scripts/format.sh"}
    assert all(argv[1].startswith("work-") for argv, _ in run.calls)


def test_a_fixer_that_cannot_run_is_logged_and_the_build_goes_on_to_its_check(
    tmp_path: Path,
) -> None:
    def missing(argv: list[str], where: Path, call: int) -> int:
        raise FileNotFoundError(argv[0])

    recorder, _, outcome, repo = built_with(tmp_path, run=FakeRun(missing))

    assert outcome.status == "open", outcome.detail
    assert any("fixers could not run: fmt" in line for line in recorder.logged)
    assert "stub-checks" in recorder.events
    assert agent_calls(recorder.events) == SILENT_FREE
    assert len(subjects(repo)) == 6


def test_a_protected_file_is_skipped_and_the_log_says_so(tmp_path: Path) -> None:
    def drop_protected(repo: Path) -> None:
        (repo / PROTECTED).parent.mkdir(parents=True)
        (repo / PROTECTED).write_text("name: ci\n")

    recorder, run, outcome, _ = built_with(tmp_path, meanwhile=drop_protected)

    assert outcome.status == "open", outcome.detail
    assert PROTECTED not in {name for argv, _ in run.calls for name in argv[1:]}
    assert any(f"fixers skipped protected: {PROTECTED}" in line for line in recorder.logged)
