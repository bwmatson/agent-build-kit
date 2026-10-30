"""The judgement the proposal states is one line, worded once, which the prompt asks for, the
check requires and `abk status` and `abk explain` read (spec: regression-agent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import next_fix_name
from agent_build_kit.pipeline.regression_agent import (
    JUDGEMENT_LABEL,
    JUDGEMENTS,
    FixOutcome,
    judgement_of,
)
from tests.pipeline.test_regression_agent_change import run
from tests.regression_agent_fakes import PROPOSAL, TEST, Attempts

WITHOUT_LINE = PROPOSAL.replace("- Judgement: the implementation is wrong.\n", "")
IN_PROSE = WITHOUT_LINE.replace(
    "## What Changes", "I think the code is at fault.\n\n## What Changes"
)
UNKNOWN = PROPOSAL.replace("the implementation is wrong", "both are fine")


def test_the_prompt_names_every_wording_the_check_reads(
    installation: Installation, tmp_path: Path
) -> None:
    agent = Attempts(installation, next_fix_name(installation, TEST), {})

    run(installation, tmp_path, agent.runtime)

    for each in JUDGEMENTS:
        assert f"`{JUDGEMENT_LABEL} {each}`" in agent.runtime.request.prompt


@pytest.mark.parametrize(
    "proposal", [WITHOUT_LINE, IN_PROSE, UNKNOWN], ids=["none", "prose", "other"]
)
def test_a_proposal_without_the_line_is_refused_and_rewritten_once(
    installation: Installation, tmp_path: Path, proposal: str
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"proposal": proposal}, {})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome == FixOutcome(change=name)
    assert len(agent.runtime.requests) == 2
    assert JUDGEMENT_LABEL in agent.runtime.requests[1].prompt


def test_a_proposal_that_still_has_no_line_is_held_for_a_person(
    installation: Installation, tmp_path: Path
) -> None:
    name = next_fix_name(installation, TEST)
    agent = Attempts(installation, name, {"proposal": WITHOUT_LINE})

    outcome = run(installation, tmp_path, agent.runtime)

    assert outcome.held and JUDGEMENT_LABEL in outcome.reason


@pytest.mark.parametrize("each", JUDGEMENTS)
def test_judgement_of_reads_each_wording_the_prompt_gives(
    installation: Installation, each: str
) -> None:
    root = installation.changes_dir / "fix-test-x"
    root.mkdir(parents=True)
    (root / "proposal.md").write_text(f"## Why\n\n{JUDGEMENT_LABEL} {each}.\n")

    assert judgement_of(installation, "fix-test-x") == each


def test_judgement_of_reads_nothing_from_prose(installation: Installation) -> None:
    root = installation.changes_dir / "fix-test-x"
    root.mkdir(parents=True)
    (root / "proposal.md").write_text(IN_PROSE)

    assert judgement_of(installation, "fix-test-x") == ""
