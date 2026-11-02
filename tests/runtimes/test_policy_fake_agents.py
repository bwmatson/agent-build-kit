"""The fake agents of the policy tests: when they have started, and when they are gone.

`started` is true only once both pid files hold a pid, not once they merely exist. The fake agent
creates a pid file and then writes it, so a file seen between the two is empty; a caller that reads
it at that moment must not be told the agent is up. A kill takes a moment to take effect:
`still_alive` gives it that moment by asking again, through an injected sleep, instead of judging
the instant after the signal.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.runtimes.policy_fake_agents import pids, started, still_alive


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


def test_a_process_that_dies_while_it_is_waited_for_is_not_still_alive() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import threading; threading.Event().wait()"],
        stdin=subprocess.DEVNULL,
    )
    slept: list[float] = []

    def die_on_first_sleep(seconds: float) -> None:
        slept.append(seconds)
        child.kill()
        child.wait()

    assert still_alive([child.pid], sleep=die_on_first_sleep) == []
    assert len(slept) == 1


def test_a_process_that_stays_is_reported_after_a_bounded_number_of_asks() -> None:
    slept: list[float] = []

    assert still_alive([os.getpid()], sleep=slept.append, attempts=5) == [os.getpid()]
    assert len(slept) == 4
