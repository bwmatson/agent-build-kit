"""An auto-landed unit is a sample for the rates only when audited or reverted.

A record says it was landed by the pipeline with `auto_landed`; the audit results (`ok` or
`wrong`) of the units a person has read are given beside the records, by unit id.
"""

from __future__ import annotations

from agent_build_kit.pipeline.review_rates import class_rates


def record(outcome: str, *, auto_landed: bool = False) -> dict:
    return {
        "final": True,
        "unit_class": "docs",
        "brief": True,
        "outcome": outcome,
        "evidence_tier": "auto",
        "auto_landed": auto_landed,
    }


def table(*records: dict) -> dict[str, dict]:
    return {"feature/" + str(n): r for n, r in enumerate(records, start=1)}


def test_an_auto_landed_unit_never_audited_or_reverted_is_no_sample() -> None:
    rates = class_rates(table(record("clean", auto_landed=True)))["docs"]

    assert (rates.samples, rates.clean, rates.agreement_samples) == (0, 0, 0)


def test_one_audited_ok_is_one_accepted_sample_whatever_its_outcome() -> None:
    rates = class_rates(table(record("reworked", auto_landed=True)), {"feature/1": "ok"})["docs"]

    assert (rates.samples, rates.clean, rates.agreement_samples, rates.agreement) == (1, 1, 1, 1.0)


def test_one_audited_wrong_is_one_sample_not_accepted_and_not_clean() -> None:
    rates = class_rates(table(record("clean", auto_landed=True)), {"feature/1": "wrong"})["docs"]

    assert (rates.samples, rates.clean, rates.agreement_samples, rates.agreement) == (1, 0, 1, 0.0)


def test_one_reverted_is_one_sample_not_accepted_and_not_clean_beside_an_unread_one() -> None:
    rates = class_rates(
        table(record("reverted", auto_landed=True), record("clean", auto_landed=True))
    )["docs"]

    assert (rates.samples, rates.clean, rates.agreement_samples, rates.agreement) == (1, 0, 1, 0.0)


def test_a_reverted_unit_audited_ok_is_not_accepted_beside_an_unread_one() -> None:
    rates = class_rates(
        table(record("reverted", auto_landed=True), record("clean", auto_landed=True)),
        {"feature/1": "ok"},
    )["docs"]

    assert (rates.samples, rates.clean) == (1, 0)


def test_a_unit_a_person_merged_is_counted_as_before_beside_an_unread_auto_landed_one() -> None:
    rates = class_rates(
        table(record("clean"), record("reworked"), record("clean", auto_landed=True))
    )["docs"]

    assert (rates.samples, rates.clean, rates.agreement_samples) == (2, 1, 2)
