"""Rates per class count only records whose pull request carried the brief."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.review_rates import class_rates


def record(
    outcome: str, *, brief: bool = True, evidence: str = "light", unit_class: str = "docs"
) -> dict:
    return {
        "final": True,
        "unit_class": unit_class,
        "brief": brief,
        "outcome": outcome,
        "evidence_tier": evidence,
    }


def table(*records: dict) -> dict[str, dict]:
    return {"feature/" + str(n): r for n, r in enumerate(records, start=1)}


def test_brief_carrying_records_make_the_samples_and_the_rest_are_excluded() -> None:
    records = table(
        *[record("clean")] * 4,
        record("reworked"),
        *[record("clean", brief=False)] * 10,
    )
    rates = class_rates(records)["docs"]
    assert (rates.samples, rates.clean, rates.clean_rate, rates.excluded) == (5, 4, 0.8, 10)


def test_a_reverted_record_is_a_sample_and_not_clean() -> None:
    rates = class_rates(table(record("clean"), record("reverted")))["docs"]
    assert (rates.samples, rates.clean, rates.clean_rate) == (2, 1, 0.5)


def test_open_and_closed_records_are_no_sample() -> None:
    rates = class_rates(table(record("clean"), record("open"), record("closed")))["docs"]
    assert (rates.samples, rates.clean) == (1, 1)


def test_agreement_is_clean_over_the_samples_with_evidence_tier_auto() -> None:
    records = table(
        record("clean", evidence="auto"),
        record("clean", evidence="auto"),
        record("reworked", evidence="auto"),
        record("clean", evidence="light"),
        record("reworked", evidence="light"),
    )
    rates = class_rates(records)["docs"]
    assert rates.agreement_samples == 3
    assert rates.agreement == pytest.approx(2 / 3)


def test_a_class_with_no_auto_samples_has_no_agreement() -> None:
    rates = class_rates(table(record("clean"), record("reworked")))["docs"]
    assert rates.agreement is None
    assert rates.agreement_samples == 0


def test_each_class_is_counted_on_its_own() -> None:
    records = table(record("clean"), record("reworked", unit_class="code"))
    rates = class_rates(records)
    assert (rates["docs"].samples, rates["docs"].clean_rate) == (1, 1.0)
    assert (rates["code"].samples, rates["code"].clean_rate) == (1, 0.0)


def test_a_class_with_only_excluded_records_is_kept_with_no_samples() -> None:
    rates = class_rates(table(record("clean", brief=False)))["docs"]
    assert (rates.samples, rates.clean_rate, rates.excluded) == (0, None, 1)
