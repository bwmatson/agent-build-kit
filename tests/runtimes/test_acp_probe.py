"""`check_policy` under the `acp` adapter: proving, on this machine, that the
agent's forbidden commands are intercepted rather than assuming it.

Which enforcement point applies depends on the agent, so the adapter asks it
to attempt one representative command per forbidden class and watches what
comes back: a class passes when the attempt reaches abk to be refused — as a
terminal request or a permission request — and fails when the agent runs it
without asking. The fake agent (`acp_agent.py --probe`) attempts each command
the prompt names in an inline code span, and never really runs one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes.acp import PROBE_CLASSES, AcpRuntime, probe_branch
from tests.factories import init_repo
from tests.runtimes.acp_agent import requests, use_agent, use_command


@pytest.fixture
def planning(tmp_path: Path) -> Path:
    """Where `doctor` and `init` ask from: the planning checkout, which the
    probe must leave as it found it."""
    root = init_repo(tmp_path / "planning")
    (root / "abk.yaml").write_text("repos: {}\n")
    return root


def _files(root: Path) -> set[Path]:
    return {path for path in root.rglob("*") if ".git" not in path.parts}


@pytest.mark.parametrize("attempts", ["terminal", "ask"])
def test_an_agent_that_honours_refusals_has_every_class_enforced(
    tmp_path: Path, planning: Path, attempts: str
) -> None:
    """Both points count: an agent that defers its commands to the client, and
    one that runs its own but asks about each. Every attempt is refused — a
    rejecting option for an ask, the rule's own reason for a terminal — so the
    pass is the refusal's and not merely an attempt having been made."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe=attempts)
    before = _files(planning)

    report = AcpRuntime().check_policy(planning)

    assert report.ok is True, report
    assert report.unenforced == ()
    assert requests(record, "session/prompt")
    if attempts == "ask":
        asked = requests(record, "did/ask")
        assert [entry["command"] for entry in asked] == [c for c, _ in PROBE_CLASSES]
        for entry in asked:
            assert entry["outcome"] == "selected", entry
            assert entry["optionKind"] in ("reject_once", "reject_always"), entry
        assert requests(record, "did/run") == []
    else:
        ran = requests(record, "did/terminal")
        assert [" ".join([e["command"], *e["args"]]) for e in ran] == [c for c, _ in PROBE_CLASSES]
        for entry in ran:
            line = " ".join([entry["command"], *entry["args"]])
            reason = check_command(line, branch=probe_branch()).reason
            assert entry["error"]["data"]["reason"] == reason, entry
    assert _files(planning) == before


def test_every_probed_command_is_one_the_rules_refuse() -> None:
    """The list cannot drift from `command_policy`: a class the rules would
    allow could never be reported as enforced."""
    for command, label in PROBE_CLASSES:
        verdict = check_command(command, branch=probe_branch())
        assert not verdict.allowed, f"{label}: {command!r} is allowed by the rules"


def test_a_class_the_agent_never_attempted_is_reported(tmp_path: Path, planning: Path) -> None:
    """An attempt at one class proves nothing of the rest."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="terminal", only="git reset")

    report = AcpRuntime().check_policy(planning)

    assert report.ok is False
    assert set(report.unenforced) == {label for _c, label in PROBE_CLASSES} - {"a hard reset"}
    assert report.fix == ""


def test_an_agent_offering_only_permitting_options_is_not_ok(
    tmp_path: Path, planning: Path
) -> None:
    """Nothing was refused: the first class cancels the turn and the rest are
    never tried, so every class is reported."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="ask", offer=["allow_once", "allow_always"])

    report = AcpRuntime().check_policy(planning)

    assert report.ok is False
    assert set(report.unenforced) == {label for _c, label in PROBE_CLASSES}


def test_a_command_sent_as_a_program_and_its_arguments_is_intercepted(
    tmp_path: Path, planning: Path
) -> None:
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="terminal", split=True)

    report = AcpRuntime().check_policy(planning)

    assert report.ok is True, report
    assert all(entry["args"] for entry in requests(record, "did/terminal"))


def test_a_probe_that_could_not_run_is_an_error_not_a_report(planning: Path) -> None:
    """Nothing is known about the classes, so nothing is reported — and so
    nothing is cached."""
    use_command(["abk-no-such-agent"])

    with pytest.raises(RuntimeError, match="abk-no-such-agent"):
        AcpRuntime().check_policy(planning)


def test_an_agent_that_runs_a_forbidden_command_anyway_has_that_class_reported(
    tmp_path: Path, planning: Path
) -> None:
    """The agent's own configuration does not flag merging a pull request, so
    it runs the merge without asking: that class, and only that one, is
    reported unenforced — the rest were still refused."""
    record = tmp_path / "agent.jsonl"
    use_agent(record, probe="ask", unasked="gh pr merge")

    report = AcpRuntime().check_policy(planning)

    ran = [entry["command"] for entry in requests(record, "did/run")]
    assert any(command and command.startswith("gh pr merge") for command in ran), ran
    assert report.ok is False
    assert len(report.unenforced) == 1, report
    assert "pull request" in report.unenforced[0]
