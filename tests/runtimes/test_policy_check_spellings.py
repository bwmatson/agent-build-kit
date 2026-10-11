"""The spellings' answer is asked once a short while, and an answer stored
before spellings were reported still loads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.runtimes.acp import PROBE_CLASSES, AcpRuntime
from agent_build_kit.runtimes.policy_check import MAX_AGE, checked
from tests.runtimes.acp_agent import requests, use_agent

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def test_an_answer_stored_before_spellings_were_reported_loads_and_is_reused(
    tmp_path: Path, planning: Path
) -> None:
    cache = tmp_path / "policy.json"
    older = {"ok": False, "unenforced": ["merging a pull request"], "fix": ""}
    cache.write_text(json.dumps({"acp": {"checked_at": NOW.isoformat(), "report": older}}))
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="terminal")

    report = checked(AcpRuntime(), planning, cache=cache, now=NOW + MAX_AGE / 2)

    assert report.ok is False
    assert report.unenforced == ("merging a pull request",)
    assert report.results == ()
    assert requests(record, "session/prompt") == []

    renewed = checked(AcpRuntime(), planning, cache=cache, now=NOW + MAX_AGE * 2)

    assert renewed.ok is True
    assert len(renewed.results) == len(PROBE_CLASSES)


def test_a_second_check_in_the_window_sends_no_prompt_and_one_after_it_asks_again(
    tmp_path: Path, planning: Path
) -> None:
    cache = tmp_path / "policy.json"
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="terminal")
    runtime = AcpRuntime()

    first = checked(runtime, planning, cache=cache, now=NOW)
    again = checked(runtime, planning, cache=cache, now=NOW + MAX_AGE / 2)

    assert len(first.results) == len(PROBE_CLASSES)
    assert again == first
    assert len(requests(record, "session/prompt")) == 1

    later = checked(runtime, planning, cache=cache, now=NOW + MAX_AGE * 2)

    assert later == first
    assert len(requests(record, "session/prompt")) == 2
