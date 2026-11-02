"""The kind of re-test a moved-base run records, and the files it counts by kind (spec:
restack-points, each restack decision is recorded and summarised). The runner is the faked
boundary, as in the moved-base tests; the repository is real."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.wiring import build_unit_test
from tests.moved_base_fakes import Profile, moved, passing
from tests.pipeline.test_moved_base_flake import FILES, OTHER, Failing
from tests.pipeline.test_moved_base_selection import Runner, Selecting, run_moved
from tests.pipeline.test_restack_record import restack_lines


def test_a_run_the_profiles_selection_answered_is_recorded_as_scoped(
    tmp_path: Path, workspace: Installation
) -> None:
    passed, _ = run_moved(
        tmp_path, Selecting([["affected"]]), Runner(), workspace=workspace, **FILES
    )

    assert passed
    (line,) = restack_lines(workspace)
    assert (line["retest"], line["retest_result"]) == ("scoped", "passed")


def test_a_run_the_full_suite_stood_in_for_is_recorded_as_full(
    tmp_path: Path, workspace: Installation
) -> None:
    passed, _ = run_moved(tmp_path, Selecting(None), Runner(), workspace=workspace, **FILES)

    assert passed
    (line,) = restack_lines(workspace)
    assert (line["retest"], line["retest_result"]) == ("full", "passed")


def test_a_scoped_flake_the_unit_goes_on_from_is_recorded_as_a_passed_scoped_run(
    tmp_path: Path, workspace: Installation
) -> None:
    with pytest.raises(FlakeFound):
        run_moved(
            tmp_path,
            Selecting([["affected"]]),
            Failing(["affected"], OTHER, again=0),
            workspace=workspace,
            **FILES,
        )

    (line,) = restack_lines(workspace)
    assert (line["retest"], line["retest_result"]) == ("scoped", "passed")


def test_the_changelog_is_the_one_the_repo_names(tmp_path: Path, workspace: Installation) -> None:
    repo, old_base = moved(
        tmp_path,
        own={"a.py": "a = 2\n"},
        incoming={"docs/HISTORY.md": "# log\n", "CHANGELOG.md": "# other\n", "b.py": "b = 2\n"},
    )

    passed, _ = build_unit_test(
        profile=Profile(),
        run=lambda command, **kwargs: passing(command),
        log=lambda message: None,
        repo=RepoConfig(path=repo, changelog="docs/HISTORY.md"),
    )(cwd=repo, base="main", moved_from=old_base)

    assert passed
    (line,) = restack_lines(workspace)
    assert (line["changelog"], line["documents"], line["code"]) == (1, 1, 1)
