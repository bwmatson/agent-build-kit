"""A ratio is keyed by the pooled kind: integration-test counts as unit-test; e2e-test is apart."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.unit_size import Kind, calibrations, kind_of
from tests.calibration_support import limits, sample


def test_a_stored_unit_of_either_kind_has_the_same_kind() -> None:
    unit = sample(1.5, at=0, tier="unit-test", flag="ui")
    wider = sample(1.5, at=1, tier="integration-test", flag="ui")

    assert kind_of(wider) == kind_of(unit)
    assert kind_of(wider).tier == "unit-test"
    assert kind_of(sample(1.5, at=2, tier="e2e-test", flag="ui")) != kind_of(wider)


def test_the_calibration_over_both_kinds_is_one_ratio_from_all_samples() -> None:
    limits(calibration_shrink=0, calibration_min=1)
    units = [
        sample(1.2, at=0, tier="unit-test"),
        sample(1.4, at=1, tier="integration-test"),
        sample(1.6, at=2, tier="unit-test"),
        sample(1.8, at=3, tier="integration-test"),
        sample(3.0, at=4, tier="e2e-test"),
    ]

    found = calibrations(units)

    pooled = Kind(repo="app", tier="unit-test")
    assert found[pooled].samples == 4
    assert found[pooled].ratio == pytest.approx(1.5)
    assert found[Kind(repo="app", tier="e2e-test")].samples == 1
    assert len(found) == 2
