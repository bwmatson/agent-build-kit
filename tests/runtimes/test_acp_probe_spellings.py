"""The probe attempts every spelling of the table, in one prompt, and reports
each class and spelling it was refused or not.

The fake agent (`acp_agent.py --probe`) attempts each command the prompt names
in an inline code span, and never really runs one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.command_spellings import probe_rows
from agent_build_kit.runtimes.acp import PROBE_CLASSES, AcpRuntime
from tests.runtimes.acp_agent import requests, use_agent
from tests.spelling_rows import AMEND

SPAN = re.compile(r"`([^`\n]+)`")


def table_rows() -> list[tuple[str, str, str]]:
    """The table's probe rows as (class, spelling, command), in table order."""
    return [(label, spelling.name.value, spelling.command) for label, spelling in probe_rows()]


def prompted(record: Path) -> list[str]:
    [prompt] = requests(record, "session/prompt")
    return SPAN.findall(" ".join(block["text"] for block in prompt["prompt"]))


@pytest.mark.parametrize("attempts", ["terminal", "ask"])
def test_every_spelling_is_attempted_as_written_and_reported_in_table_order(
    tmp_path: Path, planning: Path, attempts: str
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe=attempts)

    report = AcpRuntime().check_policy(planning)

    assert report.ok is True, report
    assert report.unenforced == ()
    assert table_rows()
    sent = [command for command, _label in PROBE_CLASSES]
    if attempts == "ask":
        attempted = [entry["command"] for entry in requests(record, "did/ask")]
    else:
        ran = requests(record, "did/terminal")
        attempted = [" ".join([entry["command"], *entry["args"]]) for entry in ran]
    assert attempted == sent
    assert {command for _l, _s, command in table_rows()} <= set(attempted)

    assert [result.command for result in report.results] == sent
    assert all(result.refused for result in report.results)
    labels = dict(PROBE_CLASSES)
    assert [result.label for result in report.results] == [labels[c] for c in sent]
    in_table = {command: (label, name) for label, name, command in table_rows()}
    shown = [
        (result.label, result.spelling, result.command)
        for result in report.results
        if result.command in in_table
    ]
    assert shown == table_rows()


def test_the_whole_table_is_asked_in_one_prompt_of_one_session(
    tmp_path: Path, planning: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="terminal")

    AcpRuntime().check_policy(planning)

    assert len(requests(record, "session/new")) == 1
    assert table_rows()
    spans = prompted(record)
    assert len(spans) == len(PROBE_CLASSES)
    assert len(spans) > len(table_rows())
    assert {command for _l, _s, command in table_rows()} <= set(spans)


def test_a_spelling_the_agent_runs_unasked_is_named_and_the_class_s_others_are_refused(
    tmp_path: Path, planning: Path
) -> None:
    """The plain amend is flagged by the agent's own list; the one with a
    working directory option is not, so it runs without asking."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="ask", unasked="git -C . commit --amend")

    report = AcpRuntime().check_policy(planning)

    assert report.ok is False
    assert report.unenforced == (f"{AMEND} (as git -C . commit --amend --no-edit)",)
    amend = {r.spelling: r for r in report.results if r.label == AMEND}
    assert amend
    assert {name for name, result in amend.items() if not result.refused} == {"directory"}
    assert amend["directory"].command == "git -C . commit --amend --no-edit"
    assert all(r.refused for r in report.results if r.label != AMEND)


def test_an_agent_that_runs_every_command_unasked_has_every_spelling_reported(
    tmp_path: Path, planning: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="ask", unasked="")

    report = AcpRuntime().check_policy(planning)

    assert report.ok is False
    assert [result.command for result in report.results] == [c for c, _l in PROBE_CLASSES]
    assert not any(result.refused for result in report.results)
    assert table_rows()
    for label, name, command in table_rows():
        if name == "plain":
            assert label in report.unenforced, (label, name)
        else:
            assert any(entry.startswith(label) and command in entry for entry in report.unenforced)
