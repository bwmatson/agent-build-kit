"""Escalation to a person is kept beside the classification (spec: review-by-tier-is-always-on).

The reviewer's `needs_human` and `escalate` answer whether a person must decide something before
a pull request is worth opening; the classification answers how much review a finished unit
deserves. Neither sets or clears the other. The tests load a file that still sets
`review.enabled: false`, so they also show the old key leaves the escalation as it is.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit import config as config_module
from agent_build_kit.config import load
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.pipeline.verdict_record import VERDICTS, latest_verdict
from agent_build_kit.pipeline.wiring import build_run_review
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh
from tests.runner_fakes import rejecting
from tests.runtimes.stand_in import StandInRuntime

REPOS = {"app": {"path": "/work/app", "slug": "example/app"}}
REASONING = "a list of spellings cannot be complete. The approach needs changing."

ESCALATIONS = [
    pytest.param({"needs_human": True}, Cause.NEEDS_HUMAN, id="needs_human"),
    pytest.param(
        {"escalate": "class", "reasoning": REASONING},
        Cause.REVIEW_ESCALATED_CLASS,
        id="class",
    ),
    pytest.param(
        {"escalate": "disagreement", "reasoning": REASONING},
        Cause.REVIEW_ESCALATED_DISAGREEMENT,
        id="disagreement",
    ),
]


@pytest.fixture(autouse=True)
def key_set_false(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "repos": REPOS, "review": {"enabled": False}}))
    config_module.activate(load(path), tmp_path)


def reply(**fields: object) -> str:
    return json.dumps({"approved": False, "feedback": "a person must decide", **fields})


def test_the_review_prompt_names_both_fields_and_what_each_is_for(tmp_path: Path) -> None:
    runtime = StandInRuntime()
    build_run_review(runtime=runtime)(cwd=tmp_path)

    text = " ".join(runtime.request.prompt.split())

    assert "`needs_human`" in text
    assert "BLOCKED:" in text
    assert '"escalate": "class"' in text
    assert '"escalate": "disagreement"' in text
    assert "a person decides" in text
    assert "classification" in text, "the classification is asked for beside them"


@pytest.mark.parametrize(("fields", "cause"), ESCALATIONS)
def test_a_reply_that_sets_either_holds_the_unit_with_its_cause_before_a_pull_request(
    tmp_path: Path, fields: dict[str, object], cause: Cause
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock leaks"), reply(**fields)]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    stored = recorder.store.get(unit().id)
    assert stored.state == HELD
    assert stored.cause is cause
    assert recorder.prs == {}
    assert "push" not in recorder.events


@pytest.mark.parametrize(("fields", "cause"), ESCALATIONS)
@pytest.mark.parametrize("tier", ["auto", "light"])
def test_a_classification_in_the_same_reply_does_not_clear_the_hold(
    tmp_path: Path, fields: dict[str, object], cause: Cause, tier: str
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock leaks"), reply(classification=tier, **fields)]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "held"
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.cause) == (HELD, cause)
    assert recorder.prs == {}


@pytest.mark.parametrize(("fields", "_cause"), ESCALATIONS)
def test_a_held_unit_has_a_round_recorded_and_no_final_verdict(
    tmp_path: Path, fields: dict[str, object], _cause: Cause
) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("the lock leaks"), reply(classification="auto", **fields)]

    build(tmp_path, recorder)

    recorded = latest_verdict(tmp_path / VERDICTS, unit().id)
    assert recorded is not None, "the round is recorded"
    assert recorded.final is False
