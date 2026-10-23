"""Deriving an outcome counts it, by outcome, tier and class and never by unit; a merged unit that
was `auto` also counts whether a person accepted it as it stood (spec: review-outcomes, outcomes
and agreement are counted)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import telemetry
from agent_build_kit.forges.base import Forge
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.factories import commit, commit_files, init_repo
from tests.forges.stand_in import StandInForge
from tests.otlp import Collector, enabled
from tests.review_sweep_support import land, merged, sweep

OUTCOME = "abk.review.outcome"
AGREEMENT = "abk.review.agreement"
UNIT = "feature/1"


@pytest.fixture
def exported() -> Iterator[Collector]:
    with enabled() as collector:
        assert telemetry.init() is True
        yield collector


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    commit(repo, "base.txt")
    return repo


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge()


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    return tmp_path / "verdicts.json"


def record_for(
    verdicts: Path, *, tier: str = "light", evidence: str = "light", unit_class: str = "docs"
) -> None:
    verdicts.write_text(
        json.dumps(
            {
                UNIT: {
                    "final": True,
                    "brief": True,
                    "tier": tier,
                    "evidence_tier": evidence,
                    "unit_class": unit_class,
                }
            }
        )
    )


def derive(_exported: Collector, unit: StoredUnit, verdicts: Path, forge: Forge, app: Path) -> None:
    """Sweep once and flush, so the points the sweep counted reach the collector."""
    sweep([unit], verdicts, forge, app)
    telemetry.shutdown()


def counted(exported: Collector, name: str) -> list[dict]:
    return [point.attributes for point in exported.metric(name)]


def test_deriving_an_outcome_counts_it_once_with_its_outcome_tier_and_class(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts, tier="light", unit_class="docs")

    derive(exported, merged(UNIT, 1, timedelta(days=1)), verdicts, forge, app)

    (point,) = exported.metric(OUTCOME)
    assert point.value == 1
    assert point.attributes == {"outcome": "clean", "tier": "light", "class": "docs"}


def test_no_count_carries_a_unit_id(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts, evidence="auto")

    derive(exported, merged(UNIT, 1, timedelta(days=1)), verdicts, forge, app)

    for name in (OUTCOME, AGREEMENT):
        points = exported.metric(name)
        assert points, name
        assert not {"unit", "change", "unit_id"} & {k for p in points for k in p.attributes}, name
        assert UNIT not in [v for p in points for v in p.attributes.values()], name


def test_a_later_revert_adds_a_count_and_removes_none(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    sha = land(forge, app, 1)
    record_for(verdicts)
    unit = merged(UNIT, 1, timedelta(days=1))
    sweep([unit], verdicts, forge, app)
    commit_files(app, f"Revert\n\nThis reverts commit {sha}.", {"revert.txt": sha})

    derive(exported, unit, verdicts, forge, app)

    outcomes = sorted(a["outcome"] for a in counted(exported, OUTCOME))
    assert outcomes == ["clean", "reverted"]


def test_deriving_the_same_outcome_again_counts_nothing(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts)
    unit = merged(UNIT, 1, timedelta(days=1))
    sweep([unit], verdicts, forge, app)
    sweep([unit], verdicts, forge, app)

    derive(exported, unit, verdicts, forge, app)

    (point,) = exported.metric(OUTCOME)
    assert point.value == 1


def test_a_merged_auto_unit_that_merged_clean_counts_as_accepted_as_it_stood(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts, evidence="auto", unit_class="docs")

    derive(exported, merged(UNIT, 1, timedelta(days=1)), verdicts, forge, app)

    (point,) = exported.metric(AGREEMENT)
    assert point.value == 1
    assert point.attributes == {"class": "docs", "accepted": "true"}


def test_a_merged_auto_unit_reworked_before_it_merged_counts_as_not_accepted(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts, evidence="auto", unit_class="docs")
    unit = merged(UNIT, 1, timedelta(days=1))
    reworked = unit.model_copy(
        update={"history": ({"state": "running", "at": "t", "cause": "rework"}, *unit.history)}
    )

    derive(exported, reworked, verdicts, forge, app)

    (point,) = exported.metric(AGREEMENT)
    assert point.attributes == {"class": "docs", "accepted": "false"}


def test_a_merged_unit_whose_evidence_tier_was_not_auto_counts_no_agreement(
    exported: Collector, app: Path, forge: StandInForge, verdicts: Path
) -> None:
    land(forge, app, 1)
    record_for(verdicts, evidence="light")

    derive(exported, merged(UNIT, 1, timedelta(days=1)), verdicts, forge, app)

    assert exported.metric(OUTCOME)
    assert exported.metric(AGREEMENT) == []
