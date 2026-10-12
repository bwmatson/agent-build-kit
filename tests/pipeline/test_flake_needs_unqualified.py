"""The `Needs:` line a flaky test's parking writes is an unqualified dependency: the
parked unit waits until the fix is in review, not until it has merged."""

from __future__ import annotations

from datetime import UTC, datetime

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, wait_on_fix
from agent_build_kit.pipeline.work_graph import group_needs, merged_needs_warnings
from tests.factories import stored_unit

TEST = "tests/test_widget.py::test_renders_the_label"
TASKS = (
    "# Tasks\n\n## 1. [app] [tier1] Do the work\n\n"
    "- [ ] 1.1 Test: it works\n- [ ] 1.2 Make it work\n"
)


def test_the_needs_line_written_for_a_flake_does_not_say_merged(
    installation: Installation,
) -> None:
    tasks = installation.changes_dir / "feature" / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TASKS)
    flake = Flake(
        test=TEST,
        unit="feature/1",
        command="uv run pytest -n auto -q",
        output="FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n",
        at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
    )

    fix = wait_on_fix(installation, flake, stored_unit("feature/1", change="feature"))

    (need,) = group_needs(tasks)[1]
    assert (need.change, need.group, need.merged) == (fix, 1, False)
    assert TEST in need.reason
    assert merged_needs_warnings(tasks) == []
