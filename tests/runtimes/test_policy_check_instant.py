"""The static check is instant and keeps no answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import policy_check
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.policy_check import check_policy
from agent_build_kit.runtimes.recommended_policy import patterns
from tests.runtimes.policy_static_support import (
    agent_home,
    first_agent_entry,
    protocol_runtime,
    write_config,
)

HUNDREDS = 600


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return agent_home(tmp_path, monkeypatch)


def test_several_hundred_entries_are_judged_in_one_pass_per_command(
    home: Path, installation: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Speed is stated as work done, not elapsed time, so load cannot change the answer."""
    deny = [*(f"tool-{n} *" for n in range(HUNDREDS)), *patterns()]
    write_config(home, deny)
    asked: list[tuple[str, str]] = []
    real = policy_check.matches

    def counting(pattern: str, command: str) -> bool:
        asked.append((pattern, command))
        return real(pattern, command)

    monkeypatch.setattr(policy_check, "matches", counting)

    report = check_policy(protocol_runtime(), first_agent_entry(), installation)

    assert len(asked) <= len(PROBE_CLASSES) * len(deny)
    assert report.ok


def test_every_run_reads_the_file_again_and_keeps_no_answer(
    home: Path, installation: Installation
) -> None:
    write_config(home, patterns())
    first = check_policy(protocol_runtime(), first_agent_entry(), installation)
    write_config(home, [])

    second = check_policy(protocol_runtime(), first_agent_entry(), installation)

    assert first.ok
    assert not second.ok
    assert not list(installation.state_dir.glob("policy-check*"))
