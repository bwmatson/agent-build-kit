"""Review by tier is on in every configuration (spec: review-by-tier-is-always-on).

Every test loads a file that still sets `review.enabled: false`, the case that used to switch
review off, so the old key must change nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit import config as config_module
from agent_build_kit.config import ReviewConfig, load
from agent_build_kit.pipeline.planner import PlannerError, build_prompt, parse_graph
from agent_build_kit.pipeline.verdict_record import VERDICTS, latest_verdict
from agent_build_kit.pipeline.wiring import build_run_review
from tests.factories import groups_at, unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import fresh
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime

REPOS = {"app": {"path": "/work/app", "slug": "example/app"}}


@pytest.fixture(autouse=True)
def key_set_false(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "repos": REPOS, "review": {"enabled": False}}))
    config_module.activate(load(path), tmp_path)


def test_no_review_setting_turns_it_off() -> None:
    assert "enabled" not in ReviewConfig.model_fields


def test_the_planner_prompt_asks_for_a_review_tier() -> None:
    prompt = " ".join(build_prompt({}, []).split())

    assert "`review_tier`" in prompt
    assert "ceiling" in prompt


def test_the_planner_holds_a_tier_it_was_given_to_its_floor() -> None:
    reply = json.dumps(
        {
            "units": [
                {
                    "id": "feature/1",
                    "change": "feature",
                    "title": "t",
                    "repo": "app",
                    "tier": "unit-test",
                    "groups": [1],
                    "review_tier": "auto",
                }
            ]
        }
    )
    flagged = [group.model_copy(update={"flag": "contract"}) for group in groups_at(3)]
    text = "# Tasks\n\n## 1. [app] [unit-test] G\n\n- [ ] 1.1 Test: it behaves.\n"

    with pytest.raises(PlannerError, match=r"feature/1.*full"):
        parse_graph(reply, groups=flagged, tasks=text)


def test_the_review_prompt_asks_for_the_classification(tmp_path: Path) -> None:
    runtime = StandInRuntime()
    build_run_review(runtime=runtime)(cwd=tmp_path)

    text = " ".join(runtime.request.prompt.split()).lower()

    assert "classification" in text
    for tier in ("`auto`", "`light`", "`full`"):
        assert tier in text
    assert "drivers" in text


def test_an_approval_records_a_final_verdict(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [approving()]

    build(tmp_path, recorder)

    recorded = latest_verdict(tmp_path / VERDICTS, unit().id)
    assert recorded is not None
    assert recorded.final is True
