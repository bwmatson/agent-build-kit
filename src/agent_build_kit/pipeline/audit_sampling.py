"""Which landed units are put to a person afterwards."""

from __future__ import annotations


def picked(unit: str, commit: str, rate: float) -> bool:
    """Whether the unit landed as `commit` is picked for audit at `rate` (0 to 1): a number
    derived from a hash of the two is below the rate, so the answer is always the same."""
    raise NotImplementedError
