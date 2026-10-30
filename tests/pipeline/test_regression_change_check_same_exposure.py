"""The check of the regression agent's change reads the `Same exposure` section of its proposal
(spec: regression-same-exposure).

The section is `## Same exposure` with one line per test —
`- <test id> — <the line that shows the shared cause> — confirmed|possible` — or, for a cause that
is not a pattern, the line `Same exposure: none, the cause is specific to this test`. The check
reads the section's presence and the format of its lines, and does not judge their content. The
agent is a stand-in that writes a canned change; no model runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import FixOutcome
from tests.regression_agent_support import NO_EXPOSURE, TEST, Attempts, run


def section(*lines: str) -> str:
    return "\n## Same exposure\n\n" + "\n".join(lines) + "\n"


def listed(count: int) -> str:
    """A section of `count` tests, the first one `confirmed` and the others `possible`."""
    return section(
        *(
            f"- tests/test_scan_{n}.py::test_walks_the_tree — tests/test_scan_{n}.py:{n + 3} "
            f"walks the directory — {'confirmed' if n == 0 else 'possible'}"
            for n in range(count)
        )
    )


MALFORMED = {
    "no-marker": section("- tests/test_a.py::test_one looks like the same shape"),
    "no-evidence": section("- tests/test_a.py::test_one — confirmed"),
    "unknown-marker": section("- tests/test_a.py::test_one — tests/helpers.py:12 — likely"),
    "one-bad-among-good": section(
        "- tests/test_a.py::test_one — tests/helpers.py:12 calls the helper — confirmed",
        "- tests/test_b.py::test_two",
    ),
    "bare-prose": section("Other tests may share this cause."),
}


def asked_for_the_section(agent: Attempts) -> None:
    """The agent was told to write the section, in its first run."""
    assert "Same exposure" in agent.runtime.requests[0].prompt


@pytest.mark.parametrize("count", [1, 3, 25])
def test_a_section_of_any_number_of_lines_is_accepted(
    installation: Installation, tmp_path: Path, count: int
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": listed(count)})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    asked_for_the_section(agent)


def test_the_none_form_is_accepted(installation: Installation, tmp_path: Path) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": NO_EXPOSURE})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 1
    asked_for_the_section(agent)


def test_a_proposal_without_the_section_is_rewritten_once(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": ""}, {"exposure": listed(2)})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "Same exposure" in agent.runtime.requests[1].prompt


def test_a_proposal_still_without_the_section_is_held_for_a_person(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": ""})

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.change == name
    assert outcome.held
    assert "Same exposure" in outcome.reason


@pytest.mark.parametrize("defect", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_malformed_line_is_rewritten_once(
    installation: Installation, tmp_path: Path, defect: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": defect}, {"exposure": listed(2)})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert "Same exposure" in agent.runtime.requests[1].prompt


@pytest.mark.parametrize("defect", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_line_still_malformed_is_held_for_a_person(
    installation: Installation, tmp_path: Path, defect: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"exposure": defect})

    outcome = run(installation, tmp_path, agent.runtime)

    assert len(agent.runtime.requests) == 2
    assert outcome.held
    assert "Same exposure" in outcome.reason
