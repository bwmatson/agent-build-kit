"""The shared tick helper: a process run, its lines timed, the last three remembered, and the
environment summarised without a secret."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from agent_build_kit import redaction
from tests import scratch_tick
from tests.redaction_fakes import known
from tests.scratch_fakes import HandScratch, hand_scratch
from tests.scratch_tick import run_tick, scratch_env_summary, ticks_of

# Plain concatenation: the shebang is the interpreter running the suite.
STAND_IN = (
    "import os\n"
    "import sys\n"
    "\n"
    'print("first", flush=True)\n'
    'print("second on stderr", file=sys.stderr, flush=True)\n'
    'print("third " + os.environ["RUN"], flush=True)\n'
    "sys.exit(3)\n"
)


@pytest.fixture
def stand_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An `abk` that prints three lines, one on stderr, and exits 3."""
    program = tmp_path / "abk-stand-in"
    program.write_text("#!" + sys.executable + "\n" + STAND_IN)
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(scratch_tick, "ABK", program)
    return program


def ticking(path: Path) -> HandScratch:
    scratch = hand_scratch(path)
    scratch.planning.mkdir()
    return scratch


def test_a_tick_holds_its_return_code_and_its_lines_in_arrival_order(
    tmp_path: Path, stand_in: Path
) -> None:
    scratch = ticking(tmp_path)
    scratch.env["RUN"] = "1"

    result = run_tick(scratch)

    assert result.returncode == 3
    assert [text for _, text in result.lines] == ["first", "second on stderr", "third 1"]
    seconds = [at for at, _ in result.lines]
    assert seconds == sorted(seconds)
    assert result.output == "first\nsecond on stderr\nthird 1"
    assert result.started <= seconds[0] and seconds[-1] <= result.ended


def test_the_last_three_ticks_of_a_scratch_are_remembered(tmp_path: Path, stand_in: Path) -> None:
    scratch = ticking(tmp_path / "one")
    other = ticking(tmp_path / "other")
    other.env["RUN"] = "other"

    runs = []
    for number in range(1, 4):
        scratch.env["RUN"] = str(number)
        runs.append(run_tick(scratch))
    run_tick(other)

    assert ticks_of(scratch) == tuple(runs)
    scratch.env["RUN"] = "4"
    fourth = run_tick(scratch)
    assert ticks_of(scratch) == (*runs[1:], fourth)
    assert len(ticks_of(other)) == 1


def test_the_environment_summary_lists_values_except_for_secret_looking_names() -> None:
    env = {
        "ABK_RUNTIME": "claude_code",
        "GH_TOKEN": "ghp_tokenvalue",
        "SERVICE_KEY": "keyvalue",
        "CLIENT_SECRET": "secretvalue",
        "DB_PASSWORD": "passwordvalue",
        "AWS_CREDENTIALS": "credentialvalue",
        "OAUTH_AUTHORIZATION": "authvalue",
    }

    summary = scratch_env_summary(env)

    assert "ABK_RUNTIME=claude_code" in summary
    for name in (
        "GH_TOKEN",
        "SERVICE_KEY",
        "CLIENT_SECRET",
        "DB_PASSWORD",
        "AWS_CREDENTIALS",
        "OAUTH_AUTHORIZATION",
    ):
        assert name in summary
    text = "\n".join(summary)
    for value in ("tokenvalue", "keyvalue", "secretvalue", "passwordvalue", "credentialvalue"):
        assert value not in text
    assert "authvalue" not in text


def test_a_registered_secret_in_a_plain_value_goes_through_the_redactor() -> None:
    with known({"REGISTERED": "registered-secret-value-1"}):
        assert redaction.active().redact("registered-secret-value-1") != (
            "registered-secret-value-1"
        )

        summary = scratch_env_summary({"PLAIN": "prefix-registered-secret-value-1-suffix"})

        assert any(line.startswith("PLAIN=") for line in summary)
        assert "registered-secret-value-1" not in "\n".join(summary)
