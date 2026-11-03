"""A move that brings in only changelog and documents is re-tested lightly (spec:
restack-points).

The rule over the files is tried alone and over a real repository whose branch and `main`
both changed the changelog. The command runner is faked at its boundary: it answers each
command with an exit status, and the order of what ran reads from the profile's named words;
the changelog check alone runs for real, over the merged file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import RepoConfig, RestackCheck
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.moved_base import moved_base_scope, scope_of
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.factories import git
from tests.moved_base_fakes import Profile, moved, passing, restack_lines

NOTES = "".join(f"- note {n}\n\n" for n in range(6))
CHANGELOG = "# Changelog\n\n## Unreleased\n\n## 1.0.0\n\n" + NOTES
OWN_CHANGELOG = CHANGELOG + "- own\n"
GUIDE = "# Guide\n" + "\n" * 8 + "tail\n"
BASE = {"a.py": "a = 1\n", "c.py": "c = 1\n", "CHANGELOG.md": CHANGELOG, "docs/guide.md": GUIDE}


def main_changelog(bullets: str) -> str:
    return CHANGELOG.replace("## Unreleased\n\n", "## Unreleased\n\n" + bullets, 1)


WELL_FORMED = main_changelog("- main one\n\n- main two\n\n")
RUN_TOGETHER = main_changelog("- main one\n- main two\n\n")


class NodeShaped(Profile):
    """A profile that keeps no check of the changelog, as a node-shaped repo's has none."""

    def extra_checks(self, repo: RepoConfig) -> list[list[str]]:
        return []


def lite_move(tmp_path: Path, changelog_from_main: str = WELL_FORMED) -> tuple[Path, str]:
    """A branch that changed the changelog and a guide, onto a main that changed both."""
    return moved(
        tmp_path,
        base=BASE,
        own={"CHANGELOG.md": OWN_CHANGELOG, "docs/guide.md": GUIDE.replace("tail", "tail\nown")},
        incoming={
            "CHANGELOG.md": changelog_from_main,
            "docs/guide.md": GUIDE.replace("# Guide\n", "# Guide\nmain\n"),
        },
    )


def is_changelog_check(command: list[str]) -> bool:
    return "changelog" in command and "check" in command


def retested(
    repo: Path, old_base: str, profile: Profile
) -> tuple[bool, str, list[list[str]], list[str]]:
    """(passed, output, the commands that ran, the run log) of the unit-test after a move,
    where the changelog check runs for real and every other command passes."""
    ran: list[list[str]] = []
    said: list[str] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        if is_changelog_check(command):
            return subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)
        return passing(command)

    passed, output = build_unit_test(
        profile=profile,
        run=run,
        log=said.append,
        repo=RepoConfig(path=repo, changelog="CHANGELOG.md"),
    )(cwd=repo, base="main", moved_from=old_base)
    return passed, output, ran, said


def test_a_move_that_brought_in_only_changelog_and_documents_is_lite() -> None:
    result = scope_of(
        ["CHANGELOG.md", "docs/guide.md", "a.py"],
        ["CHANGELOG.md", "docs/guide.md"],
        RestackCheck.AFFECTED,
    )

    assert result.lite
    assert not result.scoped
    assert "changelog" in result.reason.lower()


def test_a_move_that_also_brought_in_code_is_not_lite() -> None:
    result = scope_of(["CHANGELOG.md", "a.py"], ["CHANGELOG.md", "c.py"], RestackCheck.AFFECTED)

    assert not result.lite
    assert not result.scoped
    assert "CHANGELOG.md" in result.reason


def test_a_shared_code_file_beside_a_shared_document_is_not_lite() -> None:
    result = scope_of(["CHANGELOG.md", "a.py"], ["CHANGELOG.md", "a.py"], RestackCheck.AFFECTED)

    assert not result.lite
    assert not result.scoped
    assert "a.py" in result.reason


def test_a_shared_test_file_is_not_lite() -> None:
    result = scope_of(["tests/test_a.py"], ["tests/test_a.py"], RestackCheck.AFFECTED)

    assert not result.lite


def test_shared_test_data_the_profile_calls_a_test_is_not_lite() -> None:
    def is_test(path: str) -> bool:
        return path.startswith("tests/")

    for path in ("tests/fixtures/expected.txt", "tests/snapshots/x.md"):
        result = scope_of([path], [path], RestackCheck.AFFECTED, is_test=is_test)

        assert not result.lite, path


def test_a_shared_plain_text_file_is_not_lite() -> None:
    result = scope_of(["requirements.txt"], ["requirements.txt"], RestackCheck.AFFECTED)

    assert not result.lite


def test_the_repos_own_changelog_path_counts_as_a_document() -> None:
    result = scope_of(["HISTORY"], ["HISTORY"], RestackCheck.AFFECTED, changelog="HISTORY")

    assert result.lite


def test_a_move_that_brought_in_nothing_is_not_lite() -> None:
    assert not scope_of(["CHANGELOG.md"], [], RestackCheck.AFFECTED).lite


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


def test_a_lite_re_test_checks_the_merged_changelog_and_does_not_start_the_full_suite(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, old_base = lite_move(tmp_path)

    passed, output, ran, said = retested(repo, old_base, Profile())

    assert passed, output
    assert [c for c in ran if is_changelog_check(c)]
    assert ["tests"] not in ran, "the full suite did not start"
    assert any("lite re-test" in line and "changelog" in line for line in said)
    (line,) = restack_lines(workspace)
    assert (line["retest"], line["retest_result"]) == ("lite", "passed")


def test_a_merged_changelog_with_bullets_run_together_fails_the_lite_re_test(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, old_base = lite_move(tmp_path, RUN_TOGETHER)

    passed, output, ran, _ = retested(repo, old_base, Profile())

    assert not passed
    assert "not separated by a blank line" in output
    assert ["tests"] not in ran
    (line,) = restack_lines(workspace)
    assert (line["retest"], line["retest_result"]) == ("lite", "failed")


def test_a_move_that_brought_in_code_beside_a_shared_changelog_runs_the_tests(
    tmp_path: Path,
) -> None:
    repo, old_base = moved(
        tmp_path,
        base=BASE,
        own={"CHANGELOG.md": OWN_CHANGELOG, "a.py": "a = 2\n"},
        incoming={"CHANGELOG.md": WELL_FORMED, "c.py": "c = 2\n"},
    )

    passed, output, ran, _ = retested(repo, old_base, Profile())

    assert passed, output
    assert ["tests"] in ran


def test_a_node_shaped_repo_with_no_changelog_check_takes_the_full_path(
    tmp_path: Path, workspace: Installation
) -> None:
    repo, old_base = lite_move(tmp_path)

    passed, output, ran, said = retested(repo, old_base, NodeShaped())

    assert passed, output
    assert ["tests"] in ran
    assert any("full suite" in line and "lite" in line for line in said)
    (line,) = restack_lines(workspace)
    assert line["retest"] == "full"
