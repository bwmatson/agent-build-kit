"""The sandbox registry: the same shape as the forge registry, with a probe to choose by."""

from __future__ import annotations

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.sandboxes import Coverage
from tests.sandboxes.stand_in import StandInBackend

pytestmark = pytest.mark.usefixtures("registry")


def test_a_registered_backend_comes_back_by_name() -> None:
    backend = StandInBackend("stand_in")

    sandboxes.register(backend)

    assert sandboxes.get("stand_in") is backend
    assert "stand_in" in sandboxes.names()


def test_an_unknown_backend_names_the_ones_it_knows() -> None:
    sandboxes.register(StandInBackend("stand_in"))

    with pytest.raises(KeyError) as caught:
        sandboxes.get("nope")

    assert "nope" in str(caught.value)
    for known in sandboxes.names():
        assert known in str(caught.value)


def test_detect_takes_the_first_in_order_whose_platform_matches_and_probe_passes() -> None:
    seatbelt = StandInBackend("seatbelt", "darwin")
    landlock = StandInBackend("landlock", "linux")
    sandboxes.register(seatbelt)
    sandboxes.register(landlock)

    assert sandboxes.detect("linux") is landlock
    assert sandboxes.detect("darwin") is seatbelt


def test_detect_skips_a_backend_whose_probe_fails() -> None:
    sandboxes.register(StandInBackend("landlock", "linux", ok=False))

    assert sandboxes.detect("linux").name == "unavailable"


def test_detect_falls_back_to_unavailable_on_a_platform_with_no_backend() -> None:
    sandboxes.register(StandInBackend("landlock", "linux"))

    assert sandboxes.detect("win32").name == "unavailable"


def test_the_unavailable_backend_reports_no_coverage_with_a_cause_and_a_fix() -> None:
    availability = sandboxes.get("unavailable").availability()

    assert availability.ok is False
    assert availability.coverage is Coverage.NONE
    assert availability.cause
    assert availability.fix
