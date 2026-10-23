"""The basis in force is the kept calibration's: a window without an adopted cost fit, or with
calibration or the cost basis off, is estimated as it was by units alone, and each window is on
its own basis (spec: usage-pause).

Each case shows the units estimate, with a unit-less row adding nothing, and then, once its cause
is removed, the cost estimate of the same ledger, so the case fails until the cost basis exists."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from agent_build_kit.pipeline.usage_allowances import ALLOWANCES_NAME
from agent_build_kit.pipeline.usage_guard import decide_start
from tests.usage_cost_estimate import cost_fit, keep_fits, paused, row
from tests.usage_host import Host, configure

UNITS = "session ~60% estimated (50% read + 10% spent)"
COST = "session ~58% estimated (50% read + 8% spent from $3.00 recorded)"


def ledger(host: Host) -> None:
    """A unit that cost a dollar and a plan call with no unit that cost two."""
    row(host, "implement", 1.00, unit="feature/1")
    row(host, "plan", 2.00)


def keep_nothing(host: Host) -> None:
    return None


def keep_units_entry(host: Host) -> None:
    keep_fits(host, session=cost_fit(2.65, flat=10, basis="units", reason="more_false_allows"))


def keep_too_few(host: Host) -> None:
    keep_fits(host, session=cost_fit(2.65, flat=10, basis="units", reason="too_few_pairs"))


def keep_damaged(host: Host) -> None:
    (host.cache.parent / ALLOWANCES_NAME).write_text('{"version": 2, "windows": {"session":')


def keep_unknown_version(host: Host) -> None:
    fit = cost_fit(2.65, flat=10).model_dump(mode="json")
    body = json.dumps({"version": 9, "windows": {"session": fit}})
    (host.cache.parent / ALLOWANCES_NAME).write_text(body)


def keep_previous_shape(host: Host) -> None:
    flat = cost_fit(2.65, flat=10).model_dump(mode="json")
    body = {key: flat[key] for key in flat if key in _PREVIOUS_FIELDS}
    (host.cache.parent / ALLOWANCES_NAME).write_text(json.dumps({"session": body}))


_PREVIOUS_FIELDS = (
    "quantile_pct_per_unit",
    "quantile",
    "pairs_used",
    "pairs_available",
    "computed_at",
)


def keep_adopted(host: Host) -> None:
    keep_fits(host, session=cost_fit(2.65, flat=10))


CASES: dict[str, tuple[dict[str, Any], Callable[[Host], None]]] = {
    "no entry": ({}, keep_nothing),
    "not adopted": ({}, keep_units_entry),
    "too few pairs with cost": ({}, keep_too_few),
    "damaged file": ({}, keep_damaged),
    "unknown version": ({}, keep_unknown_version),
    "previous shape": ({}, keep_previous_shape),
    "basis units": (
        {"session": {"usage_pause_pct": 80, "usage_estimate_basis": "units"}},
        keep_adopted,
    ),
    "calibration off": ({"calibrate_usage_allowances": False}, keep_adopted),
}


@pytest.mark.parametrize("case", CASES)
def test_a_window_without_an_adopted_cost_fit_keeps_the_units_estimate(
    host: Host, case: str
) -> None:
    limits, keep = CASES[case]
    paused(host, session=50.0)
    configure(
        weekly={"usage_pause_pct": 80},
        usage_climb_floor=2.0,
        **{"session": {"usage_pause_pct": 80}, **limits},
    )
    ledger(host)
    keep(host)

    assert UNITS in decide_start().reason

    configure(
        session={"usage_pause_pct": 80}, weekly={"usage_pause_pct": 80}, usage_climb_floor=2.0
    )
    keep_adopted(host)
    assert COST in decide_start().reason


def test_the_session_may_be_on_the_cost_basis_while_the_weekly_is_on_units(host: Host) -> None:
    paused(host, session=50.0, weekly=40.0)
    ledger(host)
    keep_fits(
        host,
        session=cost_fit(2.65, flat=10),
        weekly=cost_fit(0.4, flat=2, basis="units", reason="more_false_allows"),
    )

    reason = decide_start().reason

    assert COST in reason
    assert "weekly ~42% estimated (40% read + 2% spent)" in reason
