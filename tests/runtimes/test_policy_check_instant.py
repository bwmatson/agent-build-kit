"""The static check is instant and keeps no answer."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes.policy_check import check_policy
from tests.runtimes.policy_static_support import (
    agent_home,
    first_agent_entry,
    protocol_runtime,
    recommended,
    write_config,
)

HUNDREDS = 600


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return agent_home(tmp_path, monkeypatch)


def test_several_hundred_entries_are_judged_in_under_a_second(
    home: Path, installation: Installation
) -> None:
    write_config(home, [*(f"tool-{n} *" for n in range(HUNDREDS)), *recommended()])

    started = time.perf_counter()
    report = check_policy(protocol_runtime(), first_agent_entry(), installation)

    assert time.perf_counter() - started < 1
    assert report.ok


def test_every_run_reads_the_file_again_and_keeps_no_answer(
    home: Path, installation: Installation
) -> None:
    write_config(home, recommended())
    first = check_policy(protocol_runtime(), first_agent_entry(), installation)
    write_config(home, [])

    second = check_policy(protocol_runtime(), first_agent_entry(), installation)

    assert first.ok
    assert not second.ok
    assert not list(installation.state_dir.glob("policy-check*"))
