"""The verdict counter and the planner-accuracy reading are recorded with each verdict and
listed in the metric catalogue (spec: review-verdict, verdicts are counted)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.verdict import ClassHistory, GateResult, ReviewTier, VerdictFacts
from agent_build_kit.pipeline.verdict_record import record_verdict
from agent_build_kit.serve.metrics import catalogue
from tests.otlp import Collector, enabled

COUNTER = "abk.verdict"
ACCURACY = "abk.planner.accuracy"


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


def verdict(
    tmp_path: Path, estimate: ReviewTier, red_first: GateResult = GateResult.PASSED
) -> None:
    facts = VerdictFacts(
        kind=TestTier.UNIT_TEST,
        red_first=red_first,
        unit_test=GateResult.PASSED,
        e2e_test=GateResult.PASSED,
        planned_estimate=estimate,
        classification=ReviewTier.AUTO,
    )
    record_verdict(
        tmp_path / "verdicts.json",
        unit="add-marker/1",
        change="add-marker",
        round=1,
        unit_class="code",
        repo="app",
        facts=facts,
        history=ClassHistory(samples=100, clean=100),
    )
    telemetry.shutdown()


def test_the_catalogue_lists_the_verdict_counter_with_tier_estimate_and_class_only() -> None:
    listed = {i.name: i for i in catalogue()}

    assert listed[COUNTER].type == "counter"
    assert set(listed[COUNTER].attributes) == {"tier", "estimate", "class"}


def test_the_catalogue_lists_the_planner_accuracy_reading_by_repo_and_class() -> None:
    listed = {i.name: i for i in catalogue()}

    assert listed[ACCURACY].type == "counter"
    assert {"repo", "class", "reading"} <= set(listed[ACCURACY].attributes)
    assert not {"unit", "change"} & set(listed[ACCURACY].attributes)


def test_a_recorded_verdict_counts_one_with_its_tier_estimate_and_class(
    tmp_path: Path, exported: Collector
) -> None:
    verdict(tmp_path, ReviewTier.AUTO)

    (point,) = exported.metric(COUNTER)
    assert point.value == 1
    assert point.attributes == {"tier": "auto", "estimate": "auto", "class": "code"}


def test_an_estimate_below_the_evidence_tier_counts_one_below(
    tmp_path: Path, exported: Collector
) -> None:
    verdict(tmp_path, ReviewTier.AUTO, red_first=GateResult.FAILED)

    (point,) = exported.metric(ACCURACY)
    assert point.value == 1
    assert point.attributes["reading"] == "below"
    assert point.attributes["repo"] == "app"
    assert point.attributes["class"] == "code"


def test_an_estimate_equal_to_the_evidence_tier_counts_one_equal(
    tmp_path: Path, exported: Collector
) -> None:
    verdict(tmp_path, ReviewTier.AUTO)

    (point,) = exported.metric(ACCURACY)
    assert point.attributes["reading"] == "equal"
