"""The node-npm profile selects tier-2 tests by a marker in the file name,
`<name>.<marker>.test.<ext>` (spec: node-npm-workspaces)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.e2e import TestTime
from agent_build_kit.pipeline.red_check import REPORT_MARK
from tests.node_npx_fake import VITEST
from tests.node_workspace import touch, workspace

MARKED = "src/live.local_stack.test.ts"
UNMARKED = "src/unit.test.ts"
# Carries both markers: e2e-test selects it, and only the exclusion keeps it out of acceptance.
DEV = "src/dev.dev_stack.local_stack.test.ts"
# The marker is not right before `test`, so it is not a tier-2 file.
DETACHED = "src/x.local_stack.browser.test.ts"


@pytest.fixture
def profile():
    return profiles.get("node-npm")


def selects(command: list[str], path: str) -> bool:
    """Whether a Vitest run of `command` takes the file `path`: the words after
    `sh -c <script> sh <directory>` are filters, each matching by substring."""
    return any(f in path for f in command[5:])


def test_tier_two_selects_the_files_carrying_the_marker_and_not_the_unmarked(
    profile, tmp_path: Path
) -> None:
    touch(tmp_path, MARKED, UNMARKED)

    (command,) = profile.e2e_commands(tmp_path, marker="local_stack")

    assert selects(command, MARKED)
    assert not selects(command, UNMARKED)


def test_the_marker_is_the_configured_one(profile, tmp_path: Path) -> None:
    touch(tmp_path, MARKED, "src/x.live.test.ts")

    (command,) = profile.e2e_commands(tmp_path, marker="live")

    assert selects(command, "src/x.live.test.ts")
    assert not selects(command, MARKED)


def test_tier_two_of_a_workspace_runs_each_member_in_its_directory(profile, tmp_path: Path) -> None:
    workspace(tmp_path, ["packages/a", "packages/b"])
    touch(tmp_path, f"packages/a/{MARKED}", f"packages/b/{MARKED}")

    commands = profile.e2e_commands(tmp_path, marker="local_stack")

    assert len(commands) == 2
    assert sorted("packages/a" in " ".join(c) for c in commands) == [False, True]
    assert all(selects(c, MARKED) for c in commands)


def acceptance(profile, root: Path, paths: list[str]) -> list[list[str]]:
    return profile.acceptance_commands(
        root, paths, marker="local_stack", exclude_marker="dev_stack", root_extras=[]
    )


def test_acceptance_names_the_changed_marked_files_only(profile, tmp_path: Path) -> None:
    touch(tmp_path, MARKED, UNMARKED)

    text = "\n".join(" ".join(c) for c in acceptance(profile, tmp_path, [MARKED, UNMARKED]))

    assert MARKED in text
    assert UNMARKED not in text


def test_acceptance_leaves_out_the_dev_stack_markers_files(profile, tmp_path: Path) -> None:
    touch(tmp_path, MARKED, DEV)
    (e2e,) = profile.e2e_commands(tmp_path, marker="local_stack")

    assert selects(e2e, DEV)

    text = "\n".join(" ".join(c) for c in acceptance(profile, tmp_path, [MARKED, DEV]))

    assert MARKED in text
    assert DEV not in text


def test_acceptance_has_nothing_to_run_without_a_changed_marked_file(
    profile, tmp_path: Path
) -> None:
    touch(tmp_path, MARKED, UNMARKED)

    assert acceptance(profile, tmp_path, [UNMARKED, "src/gone.local_stack.test.ts"]) == []


def test_each_tests_time_comes_from_the_recorded_tier_two_report(profile) -> None:
    output = f"RUN v5.0.4\n{REPORT_MARK}\n{(VITEST / 'tier2.xml').read_text()}"

    times = profile.parse_test_durations(output)

    assert [(t.test, t.phase) for t in times] == [
        ("live.local_stack.test.ts > waits", "call"),
        ("live.local_stack.test.ts > answers", "call"),
    ]
    assert all(isinstance(t, TestTime) for t in times)
    assert times[0].seconds == pytest.approx(0.0532, abs=0.001)
    assert times[1].seconds == pytest.approx(0.00047, abs=0.0001)


def test_a_marker_not_right_before_test_is_a_tier_two_file_for_neither_run(
    profile, tmp_path: Path
) -> None:
    touch(tmp_path, DETACHED)
    (e2e,) = profile.e2e_commands(tmp_path, marker="local_stack")

    assert not selects(e2e, DETACHED)
    assert acceptance(profile, tmp_path, [DETACHED]) == []
