"""The rates and the gates of each class, over the verdict records that carried the brief."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any

from agent_build_kit.config import AutoLandConfig
from agent_build_kit.model import Frozen


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
    raise NotImplementedError


def class_gates(
    records: Mapping[str, Mapping[str, Any]],
    policy: AutoLandConfig,
    named: Collection[str],
) -> dict[str, ClassGate]:
    """Each class in `records` with whether it clears `policy`'s gates; `named` are the classes
    `review.classes` names."""
    raise NotImplementedError
