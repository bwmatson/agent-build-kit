"""The harness that drives an agent over the probe commands is bounded, never runs a command and
cleans up after itself, proven with fake agents (`policy_fake_agents.py`)."""

from __future__ import annotations

import signal
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.runtimes.policy_agent_harness import Progress, drive
from tests.runtimes.policy_fake_agents import command, did, pids, started, still_alive

COMMANDS = (
    ("git commit --no-verify -m probe", "skipping the commit gate"),
    ("git reset --hard HEAD", "a hard reset"),
    ("git clean -fd", "discarding untracked work"),
)
DEADLINE = 1.0
ENDS_WITHIN = 30.0
LONG = 120.0


@pytest.fixture
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The only place the harness may make a temporary directory."""
    root = tmp_path / "scratch"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


@pytest.fixture
def record(tmp_path: Path) -> Path:
    path = tmp_path / "record"
    path.mkdir()
    return path


@pytest.fixture
def restored_signals() -> Iterator[None]:
    """The handlers the test process had before the harness, put back whatever it did."""
    before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    yield
    for number, handler in before.items():
        signal.signal(number, handler)


def assert_cleaned_up(record: Path, scratch: Path) -> None:
    assert not still_alive(pids(record)), "the agent's group is not gone"
    assert list(scratch.iterdir()) == [], "the harness left a temporary directory"


def test_an_agent_that_never_answers_ends_at_the_default_deadline_path(
    record: Path, scratch: Path
) -> None:
    began = time.monotonic()
    result = drive(command(record, "silent"), COMMANDS, deadline=DEADLINE)

    assert time.monotonic() - began < ENDS_WITHIN
    assert not result.finished
    assert "did not finish" in result.error
    assert result.observations == ()


def test_a_run_ended_once_the_agent_is_up_leaves_no_process_and_no_directory(
    record: Path, scratch: Path
) -> None:
    """Ended by the caller's own condition, not by a clock the agent's start-up could outrun."""
    result = drive(
        command(record, "silent"),
        COMMANDS,
        deadline=LONG,
        heartbeat=0.05,
        stop_when=lambda progress: started(record),
    )

    assert not result.finished
    assert result.error
    assert_cleaned_up(record, scratch)


def test_each_command_judged_is_named_on_stderr_and_a_stall_is_heartbeaten(
    record: Path, scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fourth = ("git branch -D probe-throwaway", "force-deleting a branch")
    seen: list[int] = []

    def stalled_for_a_heartbeat(progress: Progress) -> bool:
        if progress.judged < 3:
            return False
        seen.append(progress.heartbeats)
        return progress.heartbeats > seen[0]

    result = drive(
        command(record, "judge", "--judge", "3"),
        (*COMMANDS, fourth),
        deadline=LONG,
        heartbeat=0.1,
        stop_when=stalled_for_a_heartbeat,
    )
    err = capsys.readouterr().err

    assert not result.finished
    assert [o.command for o in result.observations] == [c for c, _ in COMMANDS]
    lines = err.splitlines()
    judged = [i for i, line in enumerate(lines) if any(c in line for c, _ in COMMANDS)]
    assert len(judged) == 3
    assert [c for c, _ in COMMANDS] == [
        next(c for c, _ in COMMANDS if c in lines[i]) for i in judged
    ]
    assert any("heartbeat" in line.lower() for line in lines[judged[-1] + 1 :])
    assert_cleaned_up(record, scratch)


@pytest.mark.parametrize("name", ["SIGINT", "SIGTERM"])
def test_a_signal_during_a_run_cleans_up_as_a_deadline_does(
    name: str, record: Path, scratch: Path, restored_signals: None
) -> None:
    before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}

    result = drive(command(record, "judge", "--signal", name), COMMANDS, deadline=30)

    assert not result.finished
    assert result.error
    assert_cleaned_up(record, scratch)
    assert {n: signal.getsignal(n) for n in before} == before


def test_a_signal_gives_the_result_a_deadline_gives(
    tmp_path: Path, scratch: Path, restored_signals: None
) -> None:
    ended = tmp_path / "deadline"
    ended.mkdir()
    interrupted = tmp_path / "interrupted"
    interrupted.mkdir()

    by_deadline = drive(command(ended, "judge", "--judge", "0"), COMMANDS, deadline=DEADLINE)
    by_signal = drive(command(interrupted, "judge", "--signal", "SIGTERM"), COMMANDS, deadline=30)

    assert not by_deadline.finished and not by_signal.finished
    assert by_signal.observations == by_deadline.observations == ()


def test_a_command_the_agent_asks_to_run_is_allowed_and_recorded_but_never_run(
    tmp_path: Path, record: Path, scratch: Path
) -> None:
    marker = tmp_path / "marker"
    asked = f"touch {marker}"

    result = drive(command(record, "judge", "--ask", "touch"), [(asked, "a write")], deadline=30)

    assert result.finished
    assert [d for d in did(record) if d["did"] == "asked"][0]["outcome"] == "allow"
    assert result.requested == (asked,)
    assert not marker.exists(), "the client ran the command"
    assert_cleaned_up(record, scratch)


def test_a_command_refused_without_a_terminal_request_is_refused_and_one_run_is_reached(
    record: Path, scratch: Path
) -> None:
    result = drive(command(record, "judge", "--refuse", "git reset"), COMMANDS, deadline=30)

    assert result.finished
    assert {o.command: o.reached for o in result.observations} == {
        "git commit --no-verify -m probe": True,
        "git reset --hard HEAD": False,
        "git clean -fd": True,
    }
    assert [o.label for o in result.observations] == [label for _, label in COMMANDS]
    assert "git reset --hard HEAD" not in result.requested
    assert_cleaned_up(record, scratch)


def test_a_command_the_agent_wraps_in_a_shell_is_still_observed_as_reached(
    record: Path, scratch: Path
) -> None:
    result = drive(command(record, "judge", "--shell"), COMMANDS, deadline=30)

    assert result.finished
    assert [o.reached for o in result.observations] == [True, True, True]
    assert result.requested == tuple(f"sh -c {line}" for line, _ in COMMANDS)
    assert_cleaned_up(record, scratch)


def test_an_agent_that_cannot_be_started_keeps_the_error_and_is_no_pass(
    tmp_path: Path, scratch: Path
) -> None:
    missing = str(tmp_path / "no-such-agent")

    result = drive([missing, "acp"], COMMANDS, deadline=DEADLINE)

    assert not result.finished
    assert missing in result.error
    assert result.observations == ()
    assert list(scratch.iterdir()) == []


def test_an_agent_that_exits_at_once_keeps_what_it_said_on_stderr(
    tmp_path: Path, scratch: Path
) -> None:
    script = tmp_path / "exits.py"
    script.write_text("import sys\nprint('no gateway running', file=sys.stderr)\nsys.exit(3)\n")

    result = drive([sys.executable, str(script)], COMMANDS, deadline=DEADLINE)

    assert not result.finished
    assert "no gateway running" in result.error
    assert list(scratch.iterdir()) == []
