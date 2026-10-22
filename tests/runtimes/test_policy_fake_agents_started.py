"""`started` is true only once both pid files hold a pid, not once they merely exist.

The fake agent creates a pid file and then writes it, so a file seen between the two is empty;
a caller that reads it at that moment must not be told the agent is up.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtimes.policy_fake_agents import pids, started


@pytest.mark.parametrize(
    ("agent", "child"),
    [("", ""), ("123", ""), ("", "456")],
    ids=["both empty", "child empty", "agent empty"],
)
def test_a_pid_file_created_but_not_yet_written_is_not_started(
    tmp_path: Path, agent: str, child: str
) -> None:
    (tmp_path / "agent.pid").write_text(agent)
    (tmp_path / "child.pid").write_text(child)

    assert not started(tmp_path)


def test_once_both_pid_files_are_written_started_is_true_and_the_pids_can_be_read(
    tmp_path: Path,
) -> None:
    (tmp_path / "agent.pid").write_text("")
    (tmp_path / "child.pid").write_text("")
    assert not started(tmp_path)

    (tmp_path / "agent.pid").write_text("123")
    (tmp_path / "child.pid").write_text("456")

    assert started(tmp_path)
    assert pids(tmp_path) == [123, 456]
