"""A move that brings in only changelog and documents is re-tested lightly (spec:
restack-points).

The rule over the files is tried alone and over a real repository whose branch and `main`
both changed the changelog. The command runner is faked at its boundary: it answers each
command with an exit status, and the order of what ran reads from the profile's named words.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig, RestackCheck
from agent_build_kit.pipeline.moved_base import moved_base_scope, scope_of
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.factories import git
from tests.moved_base_fakes import Profile, moved, passing

PADDING = "\n" * 8
BASE = {
    "a.py": "a = 1\n",
    "CHANGELOG.md": "# Changelog\n" + PADDING + "tail\n",
    "docs/guide.md": "# Guide\n" + PADDING + "tail\n",
}
GUIDE_FROM_MAIN = "# Guide\nmain\n" + PADDING + "tail\n"


def lite_move(tmp_path: Path, changelog_from_main: str | None = None) -> tuple[Path, str]:
    """A branch that changed the changelog and a guide, onto a main that changed both."""
    return moved(
        tmp_path,
        base=BASE,
        own={
            "CHANGELOG.md": "# Changelog\n" + PADDING + "tail\n- own\n",
            "docs/guide.md": "# Guide\n" + PADDING + "tail\nown\n",
        },
        incoming={
            "CHANGELOG.md": changelog_from_main or "# Changelog\n- main\n" + PADDING + "tail\n",
            "docs/guide.md": GUIDE_FROM_MAIN,
        },
    )


def is_changelog_check(command: list[str]) -> bool:
    return "changelog" in command and "check" in command


def test_a_move_whose_shared_files_are_all_changelog_or_documents_is_lite() -> None:
    result = scope_of(
        ["CHANGELOG.md", "docs/guide.md", "a.py"],
        ["CHANGELOG.md", "docs/guide.md"],
        RestackCheck.AFFECTED,
    )

    assert result.lite
    assert not result.scoped
    assert "changelog" in result.reason.lower()
    assert "documentation" in result.reason.lower()


def test_the_lite_rule_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")

    scope_of(["CHANGELOG.md"], ["CHANGELOG.md"], RestackCheck.AFFECTED)

    assert "lite" in caplog.text.lower()


def test_a_shared_code_file_beside_a_shared_document_is_not_lite() -> None:
    result = scope_of(["CHANGELOG.md", "a.py"], ["CHANGELOG.md", "a.py"], RestackCheck.AFFECTED)

    assert not result.lite
    assert not result.scoped
    assert "a.py" in result.reason


def test_a_shared_test_file_is_not_lite() -> None:
    result = scope_of(["tests/test_a.py"], ["tests/test_a.py"], RestackCheck.AFFECTED)

    assert not result.lite


def test_a_unit_that_changed_nothing_of_its_own_is_full_not_lite() -> None:
    result = scope_of([], ["CHANGELOG.md"], RestackCheck.AFFECTED)

    assert not result.lite
    assert not result.scoped


def test_the_full_setting_is_full_not_lite() -> None:
    result = scope_of(["CHANGELOG.md"], ["CHANGELOG.md"], RestackCheck.FULL)

    assert not result.lite
    assert not result.scoped
    assert "restack_check" in result.reason


def test_a_real_move_over_a_shared_changelog_and_guide_is_lite(tmp_path: Path) -> None:
    repo, old_base = lite_move(tmp_path)
    own = git(repo, "diff", "--name-only", "main...HEAD").split()

    result = moved_base_scope(
        repo, own=own, base="main", moved_from=old_base, setting=RestackCheck.AFFECTED
    )

    assert result.lite


def test_a_lite_re_test_runs_the_changelog_check_and_not_the_full_suite(tmp_path: Path) -> None:
    repo, old_base = lite_move(tmp_path)
    ran: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        return passing(command)

    passed, _ = build_unit_test(
        profile=Profile(),
        run=run,
        log=lambda message: None,
        repo=RepoConfig(path=repo, changelog="CHANGELOG.md"),
    )(cwd=repo, base="main", moved_from=old_base)

    assert passed
    assert [c for c in ran if is_changelog_check(c)]
    assert ["tests"] not in ran, "the full suite did not start"


def test_a_merged_changelog_with_a_malformed_bullet_fails_the_lite_re_test(
    tmp_path: Path,
) -> None:
    repo, old_base = lite_move(
        tmp_path, "# Changelog\n- main\n- run together\n" + PADDING + "tail\n"
    )
    ran: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        failed = 1 if is_changelog_check(command) else 0
        return subprocess.CompletedProcess(command, failed, "bad bullet\n" if failed else "", "")

    passed, output = build_unit_test(
        profile=Profile(),
        run=run,
        log=lambda message: None,
        repo=RepoConfig(path=repo, changelog="CHANGELOG.md"),
    )(cwd=repo, base="main", moved_from=old_base)

    assert not passed
    assert "bad bullet" in output
    assert ["tests"] not in ran
