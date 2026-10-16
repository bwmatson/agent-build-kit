"""The provider library's own billing summary, built by hand, so no account is needed."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from modal.types import WorkspaceBillingSummary

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 11, 1, tzinfo=UTC)


def summary(**overrides: object) -> WorkspaceBillingSummary:
    """The library's own billing summary for October 2026, with `overrides` applied."""
    fields: dict[str, object] = {
        "start": START,
        "end": END,
        "metered_cost": Decimal("173.04285316"),
        "metered_cost_breakdown": {"object-1": Decimal("100"), "object-2": Decimal("73.04285316")},
        "adjustments": {"credit": Decimal("30")},
        "billed_cost": Decimal("142.99"),
    }
    fields.update(overrides)
    return WorkspaceBillingSummary(**fields)  # type: ignore[bad-argument-type]
