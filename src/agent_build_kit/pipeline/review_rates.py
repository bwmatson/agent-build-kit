"""The rates and the gates of each class, over the verdict records that carried the brief."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.review_outcome import Outcome
from agent_build_kit.pipeline.verdict import ReviewTier


class ClassRates(Frozen):
    """A class's figures: the samples are its brief-carrying records that merged or were
    reverted; `excluded` counts its records without the brief."""

    samples: int
    clean: int
    # Clean over samples; None when there are no samples.
    clean_rate: float | None
    # Samples whose evidence tier was `auto`, and the share of them that are clean.
    agreement_samples: int
    agreement: float | None
    excluded: int


class ClassGate(Frozen):
    """Whether a class clears the gates, and what it lacks when it does not."""

    rates: ClassRates
    clears: bool
    # Samples still needed to reach `min_samples`; zero when it has enough.
    more_samples: int
    # False for a class that `review.classes` does not name.
    nameable: bool


def class_rates(records: Mapping[str, Mapping[str, Any]]) -> dict[str, ClassRates]:
    """The rates of each class in `records` (verdict records by unit id)."""
    counts: dict[str, dict[str, int]] = {}
    for record in records.values():
        c = counts.setdefault(
            record["unit_class"],
            {"samples": 0, "clean": 0, "auto": 0, "auto_clean": 0, "excluded": 0},
        )
        if not record["brief"]:
            c["excluded"] += 1
            continue
        if record["outcome"] not in (Outcome.CLEAN, Outcome.REWORKED, Outcome.REVERTED):
            continue
        clean = record["outcome"] == Outcome.CLEAN
        c["samples"] += 1
        c["clean"] += clean
        if record["evidence_tier"] == ReviewTier.AUTO:
            c["auto"] += 1
            c["auto_clean"] += clean
    return {
        name: ClassRates(
            samples=c["samples"],
            clean=c["clean"],
            clean_rate=c["clean"] / c["samples"] if c["samples"] else None,
            agreement_samples=c["auto"],
            agreement=c["auto_clean"] / c["auto"] if c["auto"] else None,
            excluded=c["excluded"],
        )
        for name, c in counts.items()
    }


def class_gates(
    records: Mapping[str, Mapping[str, Any]],
    policy: AutoLandConfig,
    named: Collection[str],
) -> dict[str, ClassGate]:
    """Each class in `records` with whether it clears `policy`'s gates; `named` are the classes
    `review.classes` names."""
    gates = {}
    for name, rates in class_rates(records).items():
        more = max(0, policy.min_samples - rates.samples)
        clears = more == 0 and (rates.clean_rate or 0) >= policy.min_clean_rate
        gates[name] = ClassGate(
            rates=rates, clears=clears, more_samples=more, nameable=name in named
        )
    return gates
