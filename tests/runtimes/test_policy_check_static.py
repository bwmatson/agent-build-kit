"""The static policy check: the agent's real configuration, judged with the kit's matcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import PolicyReport
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.claude_code import NAME as CLAUDE_CODE
from agent_build_kit.runtimes.policy_check import (
    check_policy,
    classes_of,
    describe,
    fix_for,
    unrefused,
)
from agent_build_kit.runtimes.recommended_policy import matches, patterns
from tests.runtimes.policy_static_support import (
    FIRST,
    LABEL,
    UNCOVERED_LABELS,
    agent_home,
    commands_of,
    config_file,
    entry_for,
    first_agent_entry,
    protocol_runtime,
    write_config,
)
from tests.spelling_rows import AMEND

CANNOT = "cannot check: abk has no policy for this agent"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return agent_home(tmp_path, monkeypatch)


def check(installation: Installation) -> PolicyReport:
    return check_policy(protocol_runtime(), first_agent_entry(), installation)


def test_the_recommendation_gives_an_ok_report_with_a_result_per_command(
    home: Path, installation: Installation
) -> None:
    deny = patterns()
    write_config(home, deny)

    report = check(installation)

    assert report.ok
    assert report.source == LABEL
    assert [(r.command, r.label) for r in report.results] == list(PROBE_CLASSES)
    for result in report.results:
        first = next((p for p in deny if matches(p, result.command)), "")
        assert result.by == first
        assert result.refused == bool(first)
        assert result.by_design == (result.label in UNCOVERED_LABELS)
        if result.label in UNCOVERED_LABELS:
            assert not result.refused
    assert {r.label for r in report.results if r.by_design} == UNCOVERED_LABELS


def test_a_configuration_without_the_amend_patterns_fails_naming_only_amend(
    home: Path, installation: Installation
) -> None:
    write_config(home, [p for p in patterns() if "amend" not in p])

    report = check(installation)

    assert not report.ok
    assert commands_of(AMEND)
    assert classes_of(report) == {AMEND}
    assert [r.command for r in unrefused(report)] == commands_of(AMEND)
    assert fix_for("acp", first_agent_entry(), report) == "run `abk policy apply`"


def test_an_empty_deny_list_leaves_every_covered_spelling_unenforced(
    home: Path, installation: Installation
) -> None:
    write_config(home, [])

    report = check(installation)

    covered = [r for r in report.results if not r.by_design]
    assert not report.ok
    assert covered
    assert not any(r.refused for r in covered)
    assert len(report.unenforced) == len(covered)


def test_a_class_not_covered_by_design_never_fails(home: Path, installation: Installation) -> None:
    write_config(home, patterns())

    report = check(installation)

    assert report.ok
    assert not any(label in text for text in report.unenforced for label in UNCOVERED_LABELS)
    assert not any(r.by_design for r in unrefused(report))
    assert not any(label in describe(report) for label in UNCOVERED_LABELS)


def test_a_class_not_covered_by_design_that_a_pattern_refuses_is_reported_so(
    home: Path, installation: Installation
) -> None:
    write_config(home, [*patterns(), "git reset --hard*"])

    report = check(installation)

    reset = next(r for r in report.results if r.command == "git reset --hard HEAD")
    assert reset.refused
    assert reset.by == "git reset --hard*"
    assert reset.by_design
    assert report.ok


def test_an_absent_configuration_cannot_be_checked(home: Path, installation: Installation) -> None:
    assert FIRST.apply is not None

    report = check(installation)

    assert not report.ok
    assert str(config_file(home)) in report.cannot_check
    assert FIRST.apply.home_env in report.cannot_check
    assert report.results == ()


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("approvals: [unclosed", "does not parse"),
        ("approvals:\n  deny: git push\n", "not a list"),
    ],
)
def test_a_configuration_that_cannot_be_read_cannot_be_checked(
    home: Path, installation: Installation, text: str, reason: str
) -> None:
    config_file(home).write_text(text)

    report = check(installation)

    assert not report.ok
    assert str(config_file(home)) in report.cannot_check
    assert reason in report.cannot_check
    assert report.results == ()


@pytest.mark.parametrize("command", [("no-such-agent", "acp"), ("openclaw", "acp"), ()])
def test_an_agent_without_a_policy_cannot_be_checked(
    installation: Installation, command: tuple[str, ...]
) -> None:
    report = check_policy(protocol_runtime(), entry_for(*command), installation)

    assert report.cannot_check == CANNOT
    assert not report.ok
    assert report.results == ()


def test_a_runtime_that_answers_on_its_own_reads_no_configuration(
    home: Path, installation: Installation
) -> None:
    config_file(home).write_text("approvals: [unclosed")
    runtime = runtimes.get(CLAUDE_CODE)

    report = check_policy(runtime, entry_for(), installation)

    assert report == runtime.check_policy(installation.root)
    assert report.ok
    assert report.cannot_check == ""
